"""システムトレイ用のステータスアイコン生成モジュール。"""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw

from signal_engine import SignalLevel

ICON_COLORS = {
    "green": "#2ea043",
    "yellow": "#d29922",
    "red": "#f85149",
    None: "#6e7681",
}

INNER_HIGHLIGHT = {
    "green": "#3fb950",
    "yellow": "#e3b341",
    "red": "#ff7b72",
    None: "#8b949e",
}


def create_tray_icon(level: Optional[SignalLevel], size: int = 64) -> Image.Image:
    """緑・黄・赤の視認性の高い丸型トレイアイコン画像を生成する。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 4
    # 外枠（暗いタスクバーでも明るいタスクバーでも輪郭がはっきりする濃色リング）
    draw.ellipse(
        (margin, margin, size - margin, size - margin),
        fill="#0d1117",
        outline="#30363d",
        width=2,
    )

    inner_margin = 9
    fill_color = ICON_COLORS.get(level, ICON_COLORS[None])
    draw.ellipse(
        (inner_margin, inner_margin, size - inner_margin, size - inner_margin),
        fill=fill_color,
    )

    # 左上に控えめなハイライト
    hl_color = INNER_HIGHLIGHT.get(level, INNER_HIGHLIGHT[None])
    draw.ellipse((16, 15, 28, 27), fill=hl_color)
    return img
