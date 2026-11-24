"""GitHub コントリビューショングラフ風のダークモード・ポップアップUI。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from typing import Callable, Dict, Optional, Tuple

from jepx_data import AREA_NAMES
from signal_engine import SignalLevel, SignalSnapshot, SlotEvaluation, format_countdown

# GitHub Dark Dimmed / Default Dark パレット
BG_OUTER = "#0d1117"
BG_CARD = "#161b22"
BORDER_CARD = "#30363d"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED = "#8b949e"
PILL_ACTIVE_BG = "#1f6feb"
PILL_HOVER_BG = "#21262d"
BTN_BG = "#21262d"
BTN_HOVER_BG = "#30363d"

# 5段階ヒートマップ色 (0=最安緑, 1=緑, 2=黄, 3=赤, 4=最高赤)
CELL_COLORS = {
    0: "#39d353",
    1: "#26a641",
    2: "#2d333b",
    3: "#b62324",
    4: "#f85149",
    None: "#1c2128",
}

STATUS_BADGE_COLORS = {
    "green": "#2ea043",
    "yellow": "#d29922",
    "red": "#f85149",
    None: "#6e7681",
}

STATUS_HEADLINES = {
    "green": "今はGPU稼働がお得です（緑）",
    "yellow": "標準的な電力価格帯です（黄）",
    "red": "電力価格が高騰しています（赤）",
    None: "現在時刻の価格データを取得できません",
}

LEVEL_LABELS = {
    "green": "お得・緑",
    "yellow": "標準・黄",
    "red": "高騰・赤",
}

WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


def _draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs,
) -> int:
    """Canvas上に角丸矩形を描画する。"""
    r = min(radius, (x2 - x1) / 2.0, (y2 - y1) / 2.0)
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=12, **kwargs)


class SignalPopupWindow:
    """トレイクリック時に表示するミニポップアップウィンドウ。"""

    def __init__(
        self,
        root: tk.Tk,
        on_area_change: Callable[[str], None],
        on_refresh: Callable[[], None],
    ) -> None:
        self.root = root
        self.on_area_change = on_area_change
        self.on_refresh = on_refresh
        self.window: Optional[tk.Toplevel] = None
        self.snapshot: Optional[SignalSnapshot] = None

        self._cell_eval_map: Dict[int, Optional[SlotEvaluation]] = {}
        self._area_buttons: Dict[str, tk.Label] = {}

        # UIウィジェット参照
        self._status_dot_canvas: Optional[tk.Canvas] = None
        self._headline_var = tk.StringVar(value="読み込み中...")
        self._subinfo_var = tk.StringVar(value="")
        self._countdown_var = tk.StringVar(value="")
        self._threshold_var = tk.StringVar(value="")
        self._hover_var = tk.StringVar(value="マスにカーソルを合わせると時間帯・価格を表示")
        self._footer_var = tk.StringVar(value="")
        self._grid_canvas: Optional[tk.Canvas] = None

    def is_visible(self) -> bool:
        return self.window is not None and self.window.winfo_exists() and self.window.state() == "normal"

    def toggle(self, snapshot: Optional[SignalSnapshot] = None) -> None:
        if snapshot is not None:
            self.snapshot = snapshot
        if self.is_visible():
            self.hide()
        else:
            self.show()

    def hide(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.withdraw()

    def show(self) -> None:
        if self.window is None or not self.window.winfo_exists():
            self._build_window()
        if self.snapshot is not None:
            self.update_snapshot(self.snapshot)
        self._position_near_tray()
        assert self.window is not None
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _position_near_tray(self) -> None:
        assert self.window is not None
        self.window.update_idletasks()
        w = self.window.winfo_reqwidth()
        h = self.window.winfo_reqheight()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        x = max(12, sw - w - 20)
        y = max(12, sh - h - 64)
        self.window.geometry(f"+{x}+{y}")

    def _build_window(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("GPU電力シグナル")
        win.configure(bg=BG_OUTER)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", self.hide)
        win.bind("<Escape>", lambda _e: self.hide())
        self.window = win

        outer = tk.Frame(win, bg=BG_OUTER, padx=16, pady=14)
        outer.pack(fill="both", expand=True)

        # --- ヘッダー行 (GitHubの "2,460 contributions..." 行に相当) ---
        header = tk.Frame(outer, bg=BG_OUTER)
        header.pack(fill="x", pady=(0, 8))

        left_hdr = tk.Frame(header, bg=BG_OUTER)
        left_hdr.pack(side="left", fill="x", expand=True)

        dot_canvas = tk.Canvas(left_hdr, width=16, height=16, bg=BG_OUTER, highlightthickness=0)
        dot_canvas.pack(side="left", padx=(0, 8))
        self._status_dot_canvas = dot_canvas

        tk.Label(
            left_hdr,
            textvariable=self._headline_var,
            bg=BG_OUTER,
            fg=TEXT_PRIMARY,
            font=("Yu Gothic UI", 12, "bold"),
        ).pack(side="left")

        tk.Label(
            header,
            textvariable=self._subinfo_var,
            bg=BG_OUTER,
            fg=TEXT_MUTED,
            font=("Yu Gothic UI", 9),
        ).pack(side="right", padx=(12, 0))

        # --- 中央部: 左にヒートマップカード、右にエリア選択ピル ---
        body = tk.Frame(outer, bg=BG_OUTER)
        body.pack(fill="both", expand=True)

        # ヒートマップカード外枠
        card_border = tk.Frame(body, bg=BORDER_CARD, padx=1, pady=1)
        card_border.pack(side="left", fill="both", expand=True)

        card = tk.Frame(card_border, bg=BG_CARD, padx=12, pady=10)
        card.pack(fill="both", expand=True)

        # 48列 x 最大15日分のグリッドCanvas
        self._grid_canvas = tk.Canvas(
            card,
            width=660,
            height=225,
            bg=BG_CARD,
            highlightthickness=0,
        )
        self._grid_canvas.pack()
        self._grid_canvas.bind("<Motion>", self._on_grid_hover)
        self._grid_canvas.bind("<Leave>", self._on_grid_leave)

        # カード内下部: 左にホバー詳細、右に凡例 (お得 [][][][][] 高騰)
        card_bottom = tk.Frame(card, bg=BG_CARD)
        card_bottom.pack(fill="x", pady=(6, 0))

        tk.Label(
            card_bottom,
            textvariable=self._hover_var,
            bg=BG_CARD,
            fg=TEXT_MUTED,
            font=("Yu Gothic UI", 8),
        ).pack(side="left")

        legend = tk.Frame(card_bottom, bg=BG_CARD)
        legend.pack(side="right")

        tk.Label(legend, text="お得", bg=BG_CARD, fg=TEXT_MUTED, font=("Yu Gothic UI", 8)).pack(
            side="left", padx=(0, 4)
        )
        legend_canvas = tk.Canvas(legend, width=68, height=12, bg=BG_CARD, highlightthickness=0)
        legend_canvas.pack(side="left")
        for idx in range(5):
            x = idx * 14
            _draw_rounded_rect(legend_canvas, x, 1, x + 10, 11, 2, fill=CELL_COLORS[idx], outline="")
        tk.Label(legend, text="高騰", bg=BG_CARD, fg=TEXT_MUTED, font=("Yu Gothic UI", 8)).pack(
            side="left", padx=(4, 0)
        )

        # 右側: エリア選択ピル (GitHubの 2026 / 2025 / 2024 ピルに相当)
        sidebar = tk.Frame(body, bg=BG_OUTER, padx=10)
        sidebar.pack(side="left", fill="y")

        self._area_buttons.clear()
        for area_name in AREA_NAMES:
            lbl = tk.Label(
                sidebar,
                text=area_name,
                bg=BG_OUTER,
                fg=TEXT_MUTED,
                font=("Yu Gothic UI", 9),
                width=9,
                anchor="w",
                padx=10,
                pady=2,
                cursor="hand2",
            )
            lbl.pack(fill="x", pady=1)
            lbl.bind("<Button-1>", lambda _e, a=area_name: self.on_area_change(a))
            lbl.bind("<Enter>", lambda _e, a=area_name: self._on_pill_enter(a))
            lbl.bind("<Leave>", lambda _e, a=area_name: self._on_pill_leave(a))
            self._area_buttons[area_name] = lbl

        # --- 下部情報バー: カウントダウン & 更新/閉じるボタン ---
        info_row = tk.Frame(outer, bg=BG_OUTER)
        info_row.pack(fill="x", pady=(10, 0))

        left_info = tk.Frame(info_row, bg=BG_OUTER)
        left_info.pack(side="left", fill="x", expand=True)

        tk.Label(
            left_info,
            textvariable=self._countdown_var,
            bg=BG_OUTER,
            fg=TEXT_PRIMARY,
            font=("Yu Gothic UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            left_info,
            textvariable=self._threshold_var,
            bg=BG_OUTER,
            fg=TEXT_MUTED,
            font=("Yu Gothic UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        right_actions = tk.Frame(info_row, bg=BG_OUTER)
        right_actions.pack(side="right", anchor="s")

        tk.Label(
            right_actions,
            textvariable=self._footer_var,
            bg=BG_OUTER,
            fg=TEXT_MUTED,
            font=("Yu Gothic UI", 8),
        ).pack(side="left", padx=(0, 10))

        self._make_button(right_actions, "更新", self.on_refresh).pack(side="left", padx=(0, 6))
        self._make_button(right_actions, "閉じる", self.hide).pack(side="left")

    def _make_button(self, parent: tk.Widget, text: str, command: Callable[[], None]) -> tk.Label:
        btn = tk.Label(
            parent,
            text=text,
            bg=BTN_BG,
            fg=TEXT_PRIMARY,
            font=("Yu Gothic UI", 8),
            padx=10,
            pady=4,
            cursor="hand2",
            relief="flat",
        )
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(bg=BTN_HOVER_BG))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=BTN_BG))
        return btn

    def _on_pill_enter(self, area: str) -> None:
        if self.snapshot and self.snapshot.area == area:
            return
        btn = self._area_buttons.get(area)
        if btn:
            btn.configure(bg=PILL_HOVER_BG, fg=TEXT_PRIMARY)

    def _on_pill_leave(self, area: str) -> None:
        if self.snapshot and self.snapshot.area == area:
            return
        btn = self._area_buttons.get(area)
        if btn:
            btn.configure(bg=BG_OUTER, fg=TEXT_MUTED)

    def _on_grid_hover(self, event: tk.Event) -> None:
        if not self._grid_canvas:
            return
        items = self._grid_canvas.find_overlapping(event.x, event.y, event.x, event.y)
        for item_id in items:
            if item_id in self._cell_eval_map:
                ev = self._cell_eval_map[item_id]
                if ev is None:
                    self._hover_var.set("該当コマのデータなし")
                else:
                    wd = WEEKDAY_JA[ev.delivery_date.weekday()]
                    lvl = LEVEL_LABELS[ev.level]
                    self._hover_var.set(
                        f"{ev.delivery_date.strftime('%m/%d')}({wd}) {ev.time_range_label}"
                        f"  |  {ev.price:.2f} 円/kWh  |  下位 {ev.percentile:.0f}%（{lvl}）"
                    )
                return
        self._hover_var.set("マスにカーソルを合わせると時間帯・価格を表示")

    def _on_grid_leave(self, _event: tk.Event) -> None:
        self._hover_var.set("マスにカーソルを合わせると時間帯・価格を表示")

    def update_snapshot(self, snapshot: SignalSnapshot) -> None:
        self.snapshot = snapshot
        if self.window is None or not self.window.winfo_exists():
            return

        cur = snapshot.current_slot
        level: Optional[SignalLevel] = cur.level if cur else None

        # ステータスドット更新
        if self._status_dot_canvas:
            self._status_dot_canvas.delete("all")
            dot_color = STATUS_BADGE_COLORS[level]
            self._status_dot_canvas.create_oval(2, 2, 14, 14, fill=dot_color, outline="")

        headline = STATUS_HEADLINES[level]
        if cur:
            self._headline_var.set(f"{snapshot.area}: {headline}")
            self._subinfo_var.set(
                f"{cur.price:.2f} 円/kWh  (安い方から {cur.percentile:.0f}%)"
            )
        else:
            self._headline_var.set(f"{snapshot.area}: {headline}")
            self._subinfo_var.set("")

        # カウントダウン文言
        now_dt = snapshot.updated_at
        if level == "green":
            next_red_str = format_countdown(snapshot.next_red_dt, now_dt)
            green_end_str = format_countdown(snapshot.current_green_end_dt, now_dt)
            self._countdown_var.set(
                f"お得（緑）終了まで: {green_end_str}    |    次の高騰（赤）まで: {next_red_str}"
            )
        else:
            next_green_str = format_countdown(snapshot.next_green_dt, now_dt)
            self._countdown_var.set(f"次のお得（緑）時間帯まで: {next_green_str}")

        self._threshold_var.set(
            f"直近30日基準 ({snapshot.area}):  緑 <= {snapshot.p30_price:.2f} 円/kWh  /  赤 >= {snapshot.p70_price:.2f} 円/kWh"
        )
        self._footer_var.set(
            f"データ元: {snapshot.source}  |  更新: {snapshot.updated_at.strftime('%H:%M')}"
        )

        # エリアピル更新
        for area_name, btn in self._area_buttons.items():
            if area_name == snapshot.area:
                btn.configure(bg=PILL_ACTIVE_BG, fg="#ffffff", font=("Yu Gothic UI", 9, "bold"))
            else:
                btn.configure(bg=BG_OUTER, fg=TEXT_MUTED, font=("Yu Gothic UI", 9))

        self._render_heatmap(snapshot)

    def _render_heatmap(self, snapshot: SignalSnapshot) -> None:
        canvas = self._grid_canvas
        if not canvas:
            return
        canvas.delete("all")
        self._cell_eval_map.clear()

        left_pad = 46
        top_pad = 18
        cell_size = 10
        gap = 2
        step = cell_size + gap

        rows = snapshot.heatmap_days
        total_w = left_pad + 48 * step + 4
        total_h = top_pad + len(rows) * step + 4
        canvas.configure(width=total_w, height=total_h)

        # X軸ラベル (3時間ごと: 00, 03, 06, 09, 12, 15, 18, 21)
        for hour in range(0, 24, 3):
            col = hour * 2
            x = left_pad + col * step
            canvas.create_text(
                x,
                8,
                text=f"{hour:02d}時",
                fill=TEXT_MUTED,
                font=("Yu Gothic UI", 8),
                anchor="w",
            )

        today = snapshot.updated_at.date()
        cur_slot = snapshot.current_slot.slot_code if snapshot.current_slot else -1

        for row_idx, (d, slots) in enumerate(rows):
            y = top_pad + row_idx * step
            # Y軸ラベル: 今日・明日は常に表示、過去日は2行おきに表示
            if d == today:
                y_label = "今日"
                y_color = TEXT_PRIMARY
            elif (d - today).days == 1:
                y_label = "明日"
                y_color = TEXT_PRIMARY
            elif row_idx % 3 == 0:
                y_label = d.strftime("%m/%d")
                y_color = TEXT_MUTED
            else:
                y_label = ""
                y_color = TEXT_MUTED

            if y_label:
                canvas.create_text(
                    left_pad - 6,
                    y + cell_size / 2,
                    text=y_label,
                    fill=y_color,
                    font=("Yu Gothic UI", 8, "bold" if d >= today else "normal"),
                    anchor="e",
                )

            for col_idx, ev in enumerate(slots):
                x = left_pad + col_idx * step
                intensity = ev.intensity if ev is not None else None
                fill = CELL_COLORS[intensity]
                is_now = (d == today and (col_idx + 1) == cur_slot)

                item_id = _draw_rounded_rect(
                    canvas,
                    x,
                    y,
                    x + cell_size,
                    y + cell_size,
                    2,
                    fill=fill,
                    outline="#ffffff" if is_now else "",
                    width=1.5 if is_now else 0,
                )
                self._cell_eval_map[item_id] = ev
