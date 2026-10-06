"""Tính khung giờ đăng tiếp theo."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import ScheduleConfig


def next_slot(after: datetime, schedule: ScheduleConfig) -> datetime:
    """Khung giờ đầu tiên > `after` (theo múi giờ cấu hình)."""
    local = after.astimezone(schedule.timezone)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in schedule.days:
            continue
        for t in schedule.times:
            candidate = datetime.combine(day, t, tzinfo=schedule.timezone)
            if candidate > local:
                return candidate
    raise RuntimeError("Không tìm được khung giờ nào - kiểm tra lại schedule.days / schedule.times")


def upcoming_slots(after: datetime, schedule: ScheduleConfig, count: int) -> list[datetime]:
    slots, cur = [], after
    for _ in range(count):
        cur = next_slot(cur, schedule)
        slots.append(cur)
    return slots
