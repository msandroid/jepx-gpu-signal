"""JEPX スポット市場価格データの取得・キャッシュ・統計フォールバックモジュール。"""

from __future__ import annotations

import csv
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

JEPX_DOWNLOAD_URL = "https://www.jepx.jp/_download.php"
JEPX_REFERER = "https://www.jepx.jp/electricpower/market-data/spot/"

AREAS: List[Tuple[str, str]] = [
    ("北海道", "エリアプライス北海道(円/kWh)"),
    ("東北", "エリアプライス東北(円/kWh)"),
    ("東京", "エリアプライス東京(円/kWh)"),
    ("中部", "エリアプライス中部(円/kWh)"),
    ("北陸", "エリアプライス北陸(円/kWh)"),
    ("関西", "エリアプライス関西(円/kWh)"),
    ("中国", "エリアプライス中国(円/kWh)"),
    ("四国", "エリアプライス四国(円/kWh)"),
    ("九州", "エリアプライス九州(円/kWh)"),
    ("システム", "システムプライス(円/kWh)"),
]

AREA_NAMES: List[str] = [name for name, _ in AREAS]
AREA_COLUMN_MAP: Dict[str, str] = dict(AREAS)


@dataclass(frozen=True)
class SpotRecord:
    """30分コマごとのスポット価格レコード。"""

    delivery_date: date
    slot_code: int  # 1..48
    prices: Dict[str, float]  # area_name -> yen/kWh


def fiscal_year_for(d: date) -> int:
    """日本の会計年度（4月始まり）を返す。"""
    return d.year if d.month >= 4 else d.year - 1


def _download_fiscal_csv(fiscal_year: int, dest_path: Path, timeout: int = 15) -> bool:
    """JEPX公式エンドポイントから指定年度の spot_summary CSV を取得して保存する。"""
    filename = f"spot_summary_{fiscal_year}.csv"
    payload = urllib.parse.urlencode({"dir": "spot_summary", "file": filename}).encode("utf-8")
    req = urllib.request.Request(
        JEPX_DOWNLOAD_URL,
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": JEPX_REFERER,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if not raw or b"\x8e\x9e\x8d\x8f" not in raw and b"," not in raw:
            return False
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_suffix(".tmp")
        tmp_path.write_bytes(raw)
        tmp_path.replace(dest_path)
        return True
    except Exception:
        return False


def parse_spot_csv(csv_path: Path) -> List[SpotRecord]:
    """spot_summary CSV ファイルをパースして SpotRecord のリストを返す。"""
    records: List[SpotRecord] = []
    if not csv_path.exists():
        return records

    text = csv_path.read_bytes().decode("cp932", errors="replace")
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        date_str = (row.get("受渡日") or "").strip()
        slot_str = (row.get("時刻コード") or "").strip()
        if not date_str or not slot_str:
            continue
        try:
            d = datetime.strptime(date_str, "%Y/%m/%d").date()
            slot = int(slot_str)
        except ValueError:
            continue

        prices: Dict[str, float] = {}
        for area_name, col_name in AREAS:
            val_str = (row.get(col_name) or "").strip()
            if val_str:
                try:
                    prices[area_name] = float(val_str)
                except ValueError:
                    pass
        if prices:
            records.append(SpotRecord(delivery_date=d, slot_code=slot, prices=prices))
    return records


def build_statistical_fallback(ref_date: date, days_back: int = 35) -> List[SpotRecord]:
    """オフライン時に利用する統計傾向ベースのフォールバック価格データを生成する。

    JEPXスポット市場の日内変動（昼間09:30〜13:30最安、夕方16:30〜20:30高騰、
    土日昼間のさらなる低下、12月の深夜シフト傾向）を反映した相対基準値。
    """
    records: List[SpotRecord] = []
    area_base = {
        "北海道": 12.0,
        "東北": 11.0,
        "東京": 12.5,
        "中部": 11.5,
        "北陸": 10.5,
        "関西": 10.5,
        "中国": 10.8,
        "四国": 10.2,
        "九州": 9.5,
        "システム": 11.0,
    }

    start = ref_date - timedelta(days=days_back)
    end = ref_date + timedelta(days=1)
    cur = start
    while cur <= end:
        is_weekend = cur.weekday() >= 5
        is_december = cur.month == 12
        for slot in range(1, 49):
            hour = (slot - 1) * 0.5
            # 基準の日内カーブ: 昼間 (9.5..13.5) に大きく下がり、夕方 (16.5..20.5) に高騰
            daytime_dip = -5.5 * math.exp(-((hour - 11.5) ** 2) / 5.0)
            evening_peak = 7.5 * math.exp(-((hour - 18.25) ** 2) / 4.5)
            night_dip = -2.2 * math.exp(-((hour - 3.0) ** 2) / 6.0)

            if is_december:
                # 12月は深夜帯が相対的に安くなり、昼間の低下が弱まる傾向
                daytime_dip *= 0.55
                night_dip *= 1.8

            weekend_adj = -1.8 if is_weekend and 8.0 <= hour <= 16.0 else (-0.6 if is_weekend else 0.0)
            factor = max(0.25, 1.0 + (daytime_dip + evening_peak + night_dip + weekend_adj) / 12.0)

            prices = {area: round(base * factor, 2) for area, base in area_base.items()}
            records.append(SpotRecord(delivery_date=cur, slot_code=slot, prices=prices))
        cur += timedelta(days=1)
    return records


class JepxRepository:
    """JEPXデータの取得・キャッシュ管理を行うリポジトリ。"""

    def __init__(self, cache_dir: Path, refresh_interval_sec: int = 1800) -> None:
        self.cache_dir = cache_dir
        self.refresh_interval_sec = refresh_interval_sec

    def _is_cache_fresh(self, csv_path: Path, now_dt: datetime) -> bool:
        if not csv_path.exists():
            return False
        mtime = datetime.fromtimestamp(csv_path.stat().st_mtime)
        age = (now_dt - mtime).total_seconds()
        if age > self.refresh_interval_sec:
            return False
        # 10:30以降は翌日データ公開タイミングのため、10:30前のキャッシュなら更新を促す
        cutoff = now_dt.replace(hour=10, minute=35, second=0, microsecond=0)
        if now_dt >= cutoff and mtime < cutoff:
            return False
        return True

    def load_records(self, now_dt: Optional[datetime] = None, force_refresh: bool = False) -> Tuple[List[SpotRecord], str]:
        """スポット価格レコードとデータソース種別 ('JEPX実績' or '統計推定') を返す。"""
        now_dt = now_dt or datetime.now()
        today = now_dt.date()
        fy = fiscal_year_for(today)
        prev_fy = fy - 1

        # 4月〜5月初旬は直近30日分を確保するため前年度CSVも対象にする
        need_prev = (today - date(fy, 4, 1)).days < 35
        target_fys = [prev_fy, fy] if need_prev else [fy]

        all_records: List[SpotRecord] = []
        used_live_or_cache = False

        for target_fy in target_fys:
            csv_path = self.cache_dir / f"spot_summary_{target_fy}.csv"
            should_fetch = force_refresh or (
                target_fy == fy and not self._is_cache_fresh(csv_path, now_dt)
            ) or (not csv_path.exists())

            if should_fetch:
                _download_fiscal_csv(target_fy, csv_path)

            if csv_path.exists():
                parsed = parse_spot_csv(csv_path)
                if parsed:
                    all_records.extend(parsed)
                    used_live_or_cache = True

        if used_live_or_cache and all_records:
            return all_records, "JEPX実績"

        return build_statistical_fallback(today), "統計推定"
