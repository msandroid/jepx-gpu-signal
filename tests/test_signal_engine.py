"""信号判定エンジン・JEPXデータパーサーのユニットテスト。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from jepx_data import build_statistical_fallback, fiscal_year_for, parse_spot_csv
from signal_engine import (
    classify_percentile,
    current_slot_code,
    evaluate_snapshot,
    format_countdown,
)


def test_fiscal_year_for() -> None:
    assert fiscal_year_for(date(2026, 4, 1)) == 2026
    assert fiscal_year_for(date(2026, 11, 24)) == 2026
    assert fiscal_year_for(date(2027, 3, 31)) == 2026
    assert fiscal_year_for(date(2026, 1, 15)) == 2025


def test_current_slot_code() -> None:
    assert current_slot_code(datetime(2026, 11, 24, 0, 0)) == 1
    assert current_slot_code(datetime(2026, 11, 24, 0, 29)) == 1
    assert current_slot_code(datetime(2026, 11, 24, 0, 30)) == 2
    assert current_slot_code(datetime(2026, 11, 24, 11, 35)) == 24
    assert current_slot_code(datetime(2026, 11, 24, 23, 59)) == 48


def test_classify_percentile() -> None:
    assert classify_percentile(10.0) == ("green", 0)
    assert classify_percentile(30.0) == ("green", 1)
    assert classify_percentile(50.0) == ("yellow", 2)
    assert classify_percentile(70.0) == ("red", 3)
    assert classify_percentile(95.0) == ("red", 4)


def test_relative_evaluation_across_areas() -> None:
    # 九州はベースが低く東京は高いが、各エリアの30日分布で相対評価されるため
    # どちらのエリアでも昼間はお得(green)、夕方は高騰(red)と判定されること
    now_day = datetime(2026, 11, 24, 11, 30)
    now_eve = datetime(2026, 11, 24, 18, 30)
    records = build_statistical_fallback(now_day.date(), days_back=30)

    for area in ("北海道", "東京", "九州"):
        snap_day = evaluate_snapshot(records, area=area, now_dt=now_day, source="統計推定")
        snap_eve = evaluate_snapshot(records, area=area, now_dt=now_eve, source="統計推定")
        assert snap_day.current_slot is not None
        assert snap_eve.current_slot is not None
        assert snap_day.current_slot.level == "green"
        assert snap_eve.current_slot.level == "red"
        assert snap_day.next_red_dt is not None
        assert snap_eve.next_green_dt is not None


def test_countdown_formatting() -> None:
    now_dt = datetime(2026, 11, 24, 22, 0)
    target_tomorrow = datetime(2026, 11, 25, 1, 30)
    text = format_countdown(target_tomorrow, now_dt)
    assert "3時間30分" in text
    assert "明日 01:30" in text


def test_parse_spot_csv(tmp_path: Path) -> None:
    csv_file = tmp_path / "sample.csv"
    header = (
        "受渡日,時刻コード,売り入札量(kWh),買い入札量(kWh),約定総量(kWh),"
        "システムプライス(円/kWh),エリアプライス北海道(円/kWh),エリアプライス東北(円/kWh),"
        "エリアプライス東京(円/kWh),エリアプライス中部(円/kWh),エリアプライス北陸(円/kWh),"
        "エリアプライス関西(円/kWh),エリアプライス中国(円/kWh),エリアプライス四国(円/kWh),"
        "エリアプライス九州(円/kWh)\n"
    )
    row = "2026/11/24,24,1000,1000,1000,10.50,8.20,9.10,12.30,11.00,9.50,9.50,9.50,9.50,8.00\n"
    csv_file.write_bytes((header + row).encode("cp932"))

    records = parse_spot_csv(csv_file)
    assert len(records) == 1
    assert records[0].delivery_date == date(2026, 11, 24)
    assert records[0].slot_code == 24
    assert records[0].prices["北海道"] == 8.20
    assert records[0].prices["東京"] == 12.30
