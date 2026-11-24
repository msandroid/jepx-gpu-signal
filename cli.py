"""JEPX GPU電力シグナル コマンドラインツール (CLI)。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jepx_data import AREA_NAMES, JepxRepository
from signal_engine import SignalLevel, SignalSnapshot, evaluate_snapshot, format_countdown

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "data"

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_COLORS = {
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    None: "\033[90m",
}

LEVEL_TEXT = {
    "green": "緑・お得",
    "yellow": "標準",
    "red": "赤・高騰",
    None: "不明",
}

HEATMAP_ANSI = {
    0: "\033[92m",  # 最安緑
    1: "\033[32m",  # 緑
    2: "\033[90m",  # 無色(グレー)
    3: "\033[31m",  # 赤
    4: "\033[91m",  # 高騰赤
    None: "\033[90m",
}


def _supports_color(no_color: bool) -> bool:
    if no_color or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _colorize(text: str, ansi: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{ansi}{text}{ANSI_RESET}"


def _load_default_area() -> str:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            area = data.get("area", "北海道")
            if area in AREA_NAMES:
                return area
        except Exception:
            pass
    return "北海道"


def snapshot_to_dict(snap: SignalSnapshot) -> Dict[str, Any]:
    cur = snap.current_slot
    return {
        "area": snap.area,
        "source": snap.source,
        "updated_at": snap.updated_at.isoformat(timespec="seconds"),
        "level": cur.level if cur else None,
        "level_label": LEVEL_TEXT[cur.level if cur else None],
        "price_yen_per_kwh": cur.price if cur else None,
        "percentile": cur.percentile if cur else None,
        "slot_time_range": cur.time_range_label if cur else None,
        "p30_price": snap.p30_price,
        "p70_price": snap.p70_price,
        "next_green_at": snap.next_green_dt.isoformat(timespec="minutes") if snap.next_green_dt else None,
        "next_red_at": snap.next_red_dt.isoformat(timespec="minutes") if snap.next_red_dt else None,
        "current_green_end_at": snap.current_green_end_dt.isoformat(timespec="minutes")
        if snap.current_green_end_dt
        else None,
    }


def render_single(snap: SignalSnapshot, use_color: bool, show_heatmap: bool) -> str:
    cur = snap.current_slot
    level: Optional[SignalLevel] = cur.level if cur else None
    badge = _colorize(f"[{LEVEL_TEXT[level]}]", ANSI_COLORS[level] + ANSI_BOLD, use_color)

    lines: List[str] = []
    if cur:
        lines.append(
            f"{badge} {snap.area}  {cur.price:.2f} 円/kWh  "
            f"(安い方から {cur.percentile:.1f}% / {cur.time_range_label})"
        )
    else:
        lines.append(f"{badge} {snap.area}  現在時刻のデータなし")

    now_dt = snap.updated_at
    if level == "green":
        lines.append(
            f"  お得終了まで: {format_countdown(snap.current_green_end_dt, now_dt)}  |  "
            f"次の高騰まで: {format_countdown(snap.next_red_dt, now_dt)}"
        )
    else:
        lines.append(f"  次のお得まで: {format_countdown(snap.next_green_dt, now_dt)}")

    lines.append(
        f"  直近30日基準: 緑 <= {snap.p30_price:.2f} 円/kWh / 赤 >= {snap.p70_price:.2f} 円/kWh  "
        f"[データ元: {snap.source}]"
    )

    if show_heatmap:
        lines.append("")
        lines.append("  時間帯ヒートマップ (00時〜23時 / 30分48コマ):")
        lines.append("         00    03    06    09    12    15    18    21")
        today = snap.updated_at.date()
        cur_slot = cur.slot_code if cur else -1
        for d, slots in snap.heatmap_days[-7:]:
            day_lbl = "今日 " if d == today else ("明日 " if (d - today).days == 1 else d.strftime("%m/%d"))
            cells: List[str] = []
            for idx, ev in enumerate(slots):
                is_now = d == today and (idx + 1) == cur_slot
                intensity = ev.intensity if ev is not None else None
                ch = "@" if is_now else ("#" if intensity is not None else ".")
                cells.append(_colorize(ch, HEATMAP_ANSI[intensity], use_color))
            lines.append(f"  {day_lbl}  {''.join(cells)}")

    return "\n".join(lines)


def render_all_areas(snapshots: List[SignalSnapshot], use_color: bool) -> str:
    lines = ["エリア別 GPU電力シグナル一覧:"]
    for snap in snapshots:
        cur = snap.current_slot
        level = cur.level if cur else None
        badge = _colorize(f"[{LEVEL_TEXT[level]:<4}]", ANSI_COLORS[level] + ANSI_BOLD, use_color)
        if cur:
            lines.append(
                f"  {snap.area:<5} {badge} {cur.price:6.2f} 円/kWh  "
                f"(下位 {cur.percentile:5.1f}%  |  緑<= {snap.p30_price:5.2f} / 赤>= {snap.p70_price:5.2f})"
            )
        else:
            lines.append(f"  {snap.area:<5} {badge} データなし")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jepx-gpu-signal",
        description="JEPX スポット価格を直近30日パーセンタイルで相対判定する CLI",
    )
    parser.add_argument(
        "-a",
        "--area",
        choices=AREA_NAMES,
        default=None,
        help="対象エリア名（未指定時は config.json または 北海道）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="全エリアの現在ステータスを一覧表示する",
    )
    parser.add_argument(
        "-g",
        "--heatmap",
        action="store_true",
        help="直近7日〜明日の48コマ・ヒートマップをターミナルに表示する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="JSON 形式で出力する",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="判定結果を終了コードで返す（緑=0, 標準=1, 赤=2, 不明=3）",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="キャッシュを無視して JEPX から最新データを再取得する",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="ANSI カラー出力を無効化する",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if os.name == "nt":
        # Windows ターミナルで ANSI カラーを有効化
        os.system("")

    now_dt = datetime.now()
    repo = JepxRepository(cache_dir=CACHE_DIR, refresh_interval_sec=1800)
    records, source = repo.load_records(now_dt=now_dt, force_refresh=args.refresh)
    use_color = _supports_color(args.no_color)

    if args.all:
        snaps = [evaluate_snapshot(records, area=a, now_dt=now_dt, source=source) for a in AREA_NAMES]
        if args.as_json:
            print(json.dumps([snapshot_to_dict(s) for s in snaps], ensure_ascii=False, indent=2))
        else:
            print(render_all_areas(snaps, use_color=use_color))
        return 0

    area = args.area or _load_default_area()
    snap = evaluate_snapshot(records, area=area, now_dt=now_dt, source=source)

    if args.as_json:
        print(json.dumps(snapshot_to_dict(snap), ensure_ascii=False, indent=2))
    else:
        print(render_single(snap, use_color=use_color, show_heatmap=args.heatmap))

    if args.check:
        level = snap.current_slot.level if snap.current_slot else None
        return {"green": 0, "yellow": 1, "red": 2}.get(level, 3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
