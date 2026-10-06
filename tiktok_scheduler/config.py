"""Đọc và kiểm tra file cấu hình config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

VALID_PRIVACY = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_EXTENSIONS = [".mp4", ".mov", ".webm"]


class ConfigError(Exception):
    pass


@dataclass
class TikTokConfig:
    client_key: str
    client_secret: str
    redirect_uri: str
    app_type: str = "desktop"  # desktop | web


@dataclass
class FolderConfig:
    watch: Path
    posted: Path
    failed: Path
    data: Path
    order: str = "name"  # name | mtime
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))


@dataclass
class ScheduleConfig:
    timezone: ZoneInfo
    times: list[time]
    days: list[int]  # 0 = thứ Hai ... 6 = Chủ nhật
    posts_per_slot: int = 1


@dataclass
class PostConfig:
    mode: str = "direct"  # direct | inbox
    privacy_level: str = "SELF_ONLY"
    default_caption: str = ""
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    is_aigc: bool = False
    max_attempts: int = 3
    chunk_size_mb: int = 10


@dataclass
class Config:
    path: Path
    tiktok: TikTokConfig
    folders: FolderConfig
    schedule: ScheduleConfig
    post: PostConfig


def parse_time(value: str) -> time:
    try:
        hour, minute = value.strip().split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"Giờ không hợp lệ: {value!r} (định dạng HH:MM, ví dụ 19:30)") from exc


def _resolve(base: Path, value: str | None, default: Path) -> Path:
    if not value:
        return default
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise ConfigError(
            f"Không tìm thấy file cấu hình {path}. Hãy copy config.example.toml thành config.toml rồi sửa."
        )
    with path.open("rb") as f:
        raw = tomllib.load(f)
    base = path.parent

    t = raw.get("tiktok", {})
    tiktok = TikTokConfig(
        client_key=str(t.get("client_key", "")).strip(),
        client_secret=str(t.get("client_secret", "")).strip(),
        redirect_uri=str(t.get("redirect_uri", "http://127.0.0.1:8765/callback/")).strip(),
        app_type=str(t.get("app_type", "desktop")).strip().lower(),
    )
    if tiktok.app_type not in ("desktop", "web"):
        raise ConfigError("tiktok.app_type phải là 'desktop' hoặc 'web'")

    fo = raw.get("folders", {})
    if not fo.get("watch"):
        raise ConfigError("Thiếu folders.watch (thư mục chứa video chờ đăng)")
    watch = _resolve(base, fo["watch"], base)
    exts = [e.lower() if e.startswith(".") else "." + e.lower() for e in fo.get("extensions", DEFAULT_EXTENSIONS)]
    folders = FolderConfig(
        watch=watch,
        posted=_resolve(base, fo.get("posted"), watch / "posted"),
        failed=_resolve(base, fo.get("failed"), watch / "failed"),
        data=_resolve(base, fo.get("data"), base / ".tiktok_data"),
        order=str(fo.get("order", "name")).lower(),
        extensions=exts,
    )
    if folders.order not in ("name", "mtime"):
        raise ConfigError("folders.order phải là 'name' hoặc 'mtime'")

    s = raw.get("schedule", {})
    try:
        tz = ZoneInfo(s.get("timezone", "Asia/Ho_Chi_Minh"))
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError
        raise ConfigError(f"Múi giờ không hợp lệ: {s.get('timezone')!r} (trên Windows cần `pip install tzdata`)") from exc
    times = sorted({parse_time(v) for v in s.get("times", [])})
    if not times:
        raise ConfigError("schedule.times phải có ít nhất một khung giờ, ví dụ [\"08:00\", \"19:30\"]")
    day_names = [d.strip().lower()[:3] for d in s.get("days", [])] or WEEKDAYS
    bad = [d for d in day_names if d not in WEEKDAYS]
    if bad:
        raise ConfigError(f"schedule.days có giá trị không hợp lệ: {bad}. Dùng: {WEEKDAYS}")
    schedule = ScheduleConfig(
        timezone=tz,
        times=times,
        days=sorted({WEEKDAYS.index(d) for d in day_names}),
        posts_per_slot=max(1, int(s.get("posts_per_slot", 1))),
    )

    p = raw.get("post", {})
    post = PostConfig(
        mode=str(p.get("mode", "direct")).lower(),
        privacy_level=str(p.get("privacy_level", "SELF_ONLY")).upper(),
        default_caption=str(p.get("default_caption", "")),
        disable_comment=bool(p.get("disable_comment", False)),
        disable_duet=bool(p.get("disable_duet", False)),
        disable_stitch=bool(p.get("disable_stitch", False)),
        is_aigc=bool(p.get("is_aigc", False)),
        max_attempts=max(1, int(p.get("max_attempts", 3))),
        chunk_size_mb=int(p.get("chunk_size_mb", 10)),
    )
    if post.mode not in ("direct", "inbox"):
        raise ConfigError("post.mode phải là 'direct' (đăng thẳng) hoặc 'inbox' (gửi bản nháp vào app TikTok)")
    if post.privacy_level not in VALID_PRIVACY:
        raise ConfigError(f"post.privacy_level phải là một trong {sorted(VALID_PRIVACY)}")

    return Config(path=path, tiktok=tiktok, folders=folders, schedule=schedule, post=post)
