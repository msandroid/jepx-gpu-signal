"""Windows タスクトレイ常駐 GPU電力シグナル アプリケーション。"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Optional

import pystray
from pystray import MenuItem as Item

from jepx_data import AREA_NAMES, JepxRepository
from popup_ui import SignalPopupWindow
from signal_engine import SignalSnapshot, evaluate_snapshot
from tray_icons import create_tray_icon

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "data"

TOOLTIP_LABELS = {
    "green": "緑・お得",
    "yellow": "黄・標準",
    "red": "赤・高騰",
    None: "不明",
}


class GpuSignalTrayApp:
    """トレイアイコンとバックグラウンド更新・UIを統合管理するメインクラス。"""

    def __init__(self) -> None:
        self.area: str = self._load_config()
        self.repo = JepxRepository(cache_dir=CACHE_DIR, refresh_interval_sec=1800)
        self.snapshot: Optional[SignalSnapshot] = None
        self._records = []
        self._source = "統計推定"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self.root = tk.Tk()
        self.root.withdraw()

        self.popup = SignalPopupWindow(
            root=self.root,
            on_area_change=self.change_area,
            on_refresh=lambda: self.trigger_refresh(force=True),
        )

        self.icon = pystray.Icon(
            name="jepx_gpu_signal",
            icon=create_tray_icon(None),
            title="GPU電力シグナル: 読み込み中",
            menu=self._build_menu(),
        )

    def _load_config(self) -> str:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                area = data.get("area", "北海道")
                if area in AREA_NAMES:
                    return area
            except Exception:
                pass
        return "北海道"

    def _save_config(self) -> None:
        try:
            CONFIG_PATH.write_text(
                json.dumps({"area": self.area}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _build_menu(self) -> pystray.Menu:
        area_items = [
            Item(
                area_name,
                self._make_area_handler(area_name),
                checked=self._make_area_checker(area_name),
                radio=True,
            )
            for area_name in AREA_NAMES
        ]
        return pystray.Menu(
            Item("詳細パネルを開く", self._on_open_popup, default=True),
            Item("エリア選択", pystray.Menu(*area_items)),
            Item("今すぐデータを更新", self._on_manual_refresh),
            pystray.Menu.SEPARATOR,
            Item("終了", self._on_exit),
        )

    def _make_area_handler(self, area_name: str):
        def handler(_icon, _item) -> None:
            self.root.after(0, lambda: self.change_area(area_name))
        return handler

    def _make_area_checker(self, area_name: str):
        def checker(_item) -> bool:
            return self.area == area_name
        return checker

    def _on_open_popup(self, _icon=None, _item=None) -> None:
        self.root.after(0, lambda: self.popup.toggle(self.snapshot))

    def _on_manual_refresh(self, _icon=None, _item=None) -> None:
        self.trigger_refresh(force=True)

    def _on_exit(self, _icon=None, _item=None) -> None:
        self._stop_event.set()
        self.icon.stop()
        self.root.after(0, self.root.quit)

    def change_area(self, new_area: str) -> None:
        if new_area not in AREA_NAMES or new_area == self.area:
            return
        self.area = new_area
        self._save_config()
        self._recompute_snapshot()
        self.icon.update_menu()

    def trigger_refresh(self, force: bool = False) -> None:
        threading.Thread(
            target=self._fetch_and_update,
            args=(force,),
            daemon=True,
        ).start()

    def _fetch_and_update(self, force: bool) -> None:
        records, source = self.repo.load_records(now_dt=datetime.now(), force_refresh=force)
        with self._lock:
            self._records = records
            self._source = source
        self.root.after(0, self._recompute_snapshot)

    def _recompute_snapshot(self) -> None:
        with self._lock:
            records = list(self._records)
            source = self._source
        if not records:
            return

        snap = evaluate_snapshot(
            records=records,
            area=self.area,
            now_dt=datetime.now(),
            source=source,
        )
        self.snapshot = snap
        self._update_tray_visuals(snap)
        if self.popup.is_visible():
            self.popup.update_snapshot(snap)

    def _update_tray_visuals(self, snap: SignalSnapshot) -> None:
        cur = snap.current_slot
        level = cur.level if cur else None
        self.icon.icon = create_tray_icon(level)

        label = TOOLTIP_LABELS[level]
        if cur:
            title = f"GPU電力シグナル [{label}] {snap.area} {cur.price:.2f}円/kWh (下位{cur.percentile:.0f}%)"
        else:
            title = f"GPU電力シグナル [{label}] {snap.area}"
        # Windows タスクトレイ tooltip 上限(127文字)以内に収める
        self.icon.title = title[:120]

    def _periodic_tick(self) -> None:
        if self._stop_event.is_set():
            return
        self._recompute_snapshot()
        # 60秒ごとに現在コマ・カウントダウンを再計算
        self.root.after(60_000, self._periodic_tick)

    def _periodic_fetch(self) -> None:
        if self._stop_event.is_set():
            return
        self.trigger_refresh(force=False)
        # 15分ごとにキャッシュ鮮度チェック＆必要時更新
        self.root.after(900_000, self._periodic_fetch)

    def run(self) -> None:
        self.icon.run_detached()
        self.trigger_refresh(force=False)
        self.root.after(60_000, self._periodic_tick)
        self.root.after(900_000, self._periodic_fetch)
        self.root.mainloop()


def main() -> None:
    app = GpuSignalTrayApp()
    app.run()


if __name__ == "__main__":
    main()
