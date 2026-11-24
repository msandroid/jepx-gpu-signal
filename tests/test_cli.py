"""CLI モジュールのユニットテスト。"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import cli
from jepx_data import build_statistical_fallback


def test_cli_json_output(capsys) -> None:
    now_dt = datetime(2026, 11, 24, 11, 30)
    records = build_statistical_fallback(now_dt.date(), days_back=30)

    with patch("cli.JepxRepository.load_records", return_value=(records, "統計推定")):
        with patch("cli.datetime") as mock_dt:
            mock_dt.now.return_value = now_dt
            code = cli.main(["--area", "東京", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["area"] == "東京"
    assert payload["level"] == "green"
    assert payload["source"] == "統計推定"


def test_cli_check_exit_codes(capsys) -> None:
    now_day = datetime(2026, 11, 24, 11, 30)
    now_eve = datetime(2026, 11, 24, 18, 30)
    records = build_statistical_fallback(now_day.date(), days_back=30)

    with patch("cli.JepxRepository.load_records", return_value=(records, "統計推定")):
        with patch("cli.datetime") as mock_dt:
            mock_dt.now.return_value = now_day
            assert cli.main(["--area", "北海道", "--check", "--no-color"]) == 0

        with patch("cli.datetime") as mock_dt:
            mock_dt.now.return_value = now_eve
            assert cli.main(["--area", "北海道", "--check", "--no-color"]) == 2


def test_cli_all_areas_and_heatmap(capsys) -> None:
    now_dt = datetime(2026, 11, 24, 11, 30)
    records = build_statistical_fallback(now_dt.date(), days_back=30)

    with patch("cli.JepxRepository.load_records", return_value=(records, "統計推定")):
        with patch("cli.datetime") as mock_dt:
            mock_dt.now.return_value = now_dt
            assert cli.main(["--all", "--no-color"]) == 0
            out_all = capsys.readouterr().out
            assert "北海道" in out_all
            assert "九州" in out_all

            assert cli.main(["--area", "関西", "--heatmap", "--no-color"]) == 0
            out_hm = capsys.readouterr().out
            assert "時間帯ヒートマップ" in out_hm
