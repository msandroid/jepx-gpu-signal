"""エリア非依存の直近30日パーセンタイル判定・カウントダウン計算エンジン。"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Literal, Optional, Tuple

from jepx_data import SpotRecord

SignalLevel = Literal["green", "yellow", "red"]

GREEN_PERCENTILE_MAX = 30.0
RED_PERCENTILE_MIN = 70.0


@dataclass(frozen=True)
class SlotEvaluation:
    """1コマ（30分）の評価結果。"""

    delivery_date: date
    slot_code: int
    start_dt: datetime
    end_dt: datetime
    price: float
    percentile: float  # 0.0 .. 100.0 (低いほどお得)
    level: SignalLevel
    intensity: int  # 0..4 (0=最安緑, 1=緑, 2=黄, 3=赤, 4=最高赤)

    @property
    def time_range_label(self) -> str:
        return f"{self.start_dt.strftime('%H:%M')}〜{self.end_dt.strftime('%H:%M')}"


@dataclass(frozen=True)
class SignalSnapshot:
    """UI・トレイ表示用の総合スナップショット。"""

    area: str
    source: str  # "JEPX実績" or "統計推定"
    updated_at: datetime
    current_slot: Optional[SlotEvaluation]
    p30_price: float
    p70_price: float
    heatmap_days: List[Tuple[date, List[Optional[SlotEvaluation]]]]
    next_green_dt: Optional[datetime]
    next_red_dt: Optional[datetime]
    current_green_end_dt: Optional[datetime]


def slot_to_datetimes(delivery_date: date, slot_code: int) -> Tuple[datetime, datetime]:
    """日付と時刻コード(1..48)から開始・終了日時を返す。"""
    minutes_from_midnight = (slot_code - 1) * 30
    start_dt = datetime.combine(delivery_date, datetime.min.time()) + timedelta(minutes=minutes_from_midnight)
    end_dt = start_dt + timedelta(minutes=30)
    return start_dt, end_dt


def current_slot_code(now_dt: datetime) -> int:
    """現在時刻に対応する時刻コード(1..48)を返す。"""
    return now_dt.hour * 2 + (1 if now_dt.minute < 30 else 2)


def classify_percentile(percentile: float) -> Tuple[SignalLevel, int]:
    """パーセンタイル値(0..100)から信号レベルと5段階強度(0..4)を返す。"""
    if percentile <= 15.0:
        return "green", 0
    if percentile <= GREEN_PERCENTILE_MAX:
        return "green", 1
    if percentile < RED_PERCENTILE_MIN:
        return "yellow", 2
    if percentile < 85.0:
        return "red", 3
    return "red", 4


def compute_percentile_rank(sorted_values: List[float], value: float) -> float:
    """ソート済み基準分布における value のパーセンタイル順位(0..100)を返す。"""
    if not sorted_values:
        return 50.0
    idx = bisect_right(sorted_values, value)
    return round((idx / len(sorted_values)) * 100.0, 1)


def quantile_value(sorted_values: List[float], q: float) -> float:
    """ソート済みリストの分位値(q: 0.0..1.0)を返す。"""
    if not sorted_values:
        return 0.0
    pos = min(max(int(round((len(sorted_values) - 1) * q)), 0), len(sorted_values) - 1)
    return sorted_values[pos]


def evaluate_snapshot(
    records: List[SpotRecord],
    area: str,
    now_dt: Optional[datetime] = None,
    source: str = "JEPX実績",
    history_days: int = 13,
) -> SignalSnapshot:
    """指定エリアの直近30日分布を基準に現在状態・ヒートマップ・カウントダウンを計算する。"""
    now_dt = now_dt or datetime.now()
    today = now_dt.date()
    tomorrow = today + timedelta(days=1)

    # (date, slot) -> price のインデックスを構築
    price_map: Dict[Tuple[date, int], float] = {}
    for rec in records:
        if area in rec.prices:
            price_map[(rec.delivery_date, rec.slot_code)] = rec.prices[area]

    # 直近30日 (today - 29日 .. today) の価格分布を収集
    dist_start = today - timedelta(days=29)
    baseline_prices = sorted(
        p for (d, _), p in price_map.items() if dist_start <= d <= today
    )
    # もし直近30日にデータが無ければ全利用可能データにフォールバック
    if not baseline_prices:
        baseline_prices = sorted(price_map.values())

    p30_price = quantile_value(baseline_prices, 0.30)
    p70_price = quantile_value(baseline_prices, 0.70)

    def eval_cell(d: date, slot: int) -> Optional[SlotEvaluation]:
        price = price_map.get((d, slot))
        if price is None:
            return None
        pct = compute_percentile_rank(baseline_prices, price)
        level, intensity = classify_percentile(pct)
        start_dt, end_dt = slot_to_datetimes(d, slot)
        return SlotEvaluation(
            delivery_date=d,
            slot_code=slot,
            start_dt=start_dt,
            end_dt=end_dt,
            price=price,
            percentile=pct,
            level=level,
            intensity=intensity,
        )

    cur_slot = current_slot_code(now_dt)
    current_eval = eval_cell(today, cur_slot)

    # ヒートマップ用の日付行 (直近 history_days 日 .. 今日 [+ 明日があれば明日])
    has_tomorrow = any((tomorrow, s) in price_map for s in range(1, 49))
    end_day = tomorrow if has_tomorrow else today
    start_day = today - timedelta(days=history_days)

    heatmap_days: List[Tuple[date, List[Optional[SlotEvaluation]]]] = []
    cur_d = start_day
    while cur_d <= end_day:
        row_slots = [eval_cell(cur_d, s) for s in range(1, 49)]
        heatmap_days.append((cur_d, row_slots))
        cur_d += timedelta(days=1)

    # 今後のスロットを時系列で走査し、次の緑・次の赤・緑終了時刻を算出
    next_green_dt: Optional[datetime] = None
    next_red_dt: Optional[datetime] = None
    current_green_end_dt: Optional[datetime] = None

    future_slots: List[SlotEvaluation] = []
    for d in (today, tomorrow):
        for s in range(1, 49):
            if d == today and s <= cur_slot:
                continue
            ev = eval_cell(d, s)
            if ev is not None:
                future_slots.append(ev)

    if current_eval and current_eval.level == "green":
        end_dt = current_eval.end_dt
        for ev in future_slots:
            if ev.level == "green":
                end_dt = ev.end_dt
            else:
                break
        current_green_end_dt = end_dt

    for ev in future_slots:
        if next_green_dt is None and ev.level == "green":
            next_green_dt = ev.start_dt
        if next_red_dt is None and ev.level == "red":
            next_red_dt = ev.start_dt
        if next_green_dt is not None and next_red_dt is not None:
            break

    return SignalSnapshot(
        area=area,
        source=source,
        updated_at=now_dt,
        current_slot=current_eval,
        p30_price=p30_price,
        p70_price=p70_price,
        heatmap_days=heatmap_days,
        next_green_dt=next_green_dt,
        next_red_dt=next_red_dt,
        current_green_end_dt=current_green_end_dt,
    )


def format_countdown(target_dt: Optional[datetime], now_dt: datetime) -> str:
    """目標時刻までの残り時間を日本語でフォーマットする。"""
    if target_dt is None:
        return "予定データ範囲内に該当なし"
    diff_sec = max(0, int((target_dt - now_dt).total_seconds()))
    hours = diff_sec // 3600
    minutes = (diff_sec % 3600) // 60
    time_str = target_dt.strftime("%H:%M")
    day_prefix = "明日 " if target_dt.date() > now_dt.date() else ""
    if hours > 0:
        return f"あと {hours}時間{minutes}分 ({day_prefix}{time_str}〜)"
    return f"あと {minutes}分 ({day_prefix}{time_str}〜)"
