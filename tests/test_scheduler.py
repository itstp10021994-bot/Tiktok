from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from tiktok_scheduler.config import ConfigError, parse_time
from tiktok_scheduler.scheduler import next_slot, upcoming_slots

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def test_times_sorted_and_days_parsed(cfg):
    assert cfg.schedule.times == [time(8, 0), time(19, 30)]
    assert cfg.schedule.days == [0, 2, 4]


def test_next_slot_same_day(cfg):
    # 2026-10-05 là thứ Hai
    assert next_slot(datetime(2026, 10, 5, 9, 0, tzinfo=VN), cfg.schedule) == datetime(2026, 10, 5, 19, 30, tzinfo=VN)


def test_next_slot_is_strictly_after(cfg):
    at = datetime(2026, 10, 5, 8, 0, tzinfo=VN)
    assert next_slot(at, cfg.schedule) == datetime(2026, 10, 5, 19, 30, tzinfo=VN)


def test_next_slot_skips_disabled_days(cfg):
    # Sau 19:30 thứ Hai → 08:00 thứ Tư
    assert next_slot(datetime(2026, 10, 5, 20, 0, tzinfo=VN), cfg.schedule) == datetime(2026, 10, 7, 8, 0, tzinfo=VN)


def test_next_slot_converts_timezone(cfg):
    utc = datetime(2026, 10, 5, 1, 30, tzinfo=ZoneInfo("UTC"))  # = 08:30 giờ VN
    assert next_slot(utc, cfg.schedule) == datetime(2026, 10, 5, 19, 30, tzinfo=VN)


def test_upcoming_slots(cfg):
    slots = upcoming_slots(datetime(2026, 10, 9, 20, 0, tzinfo=VN), cfg.schedule, 3)  # thứ Sáu tối
    assert [s.strftime("%a %H:%M") for s in slots] == ["Mon 08:00", "Mon 19:30", "Wed 08:00"]


@pytest.mark.parametrize("bad", ["25:00", "8h", ""])
def test_parse_time_invalid(bad):
    with pytest.raises(ConfigError):
        parse_time(bad)
