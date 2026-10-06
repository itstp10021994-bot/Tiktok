"""Giao diện dòng lệnh: python -m tiktok_scheduler <lệnh>."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from .api import TikTokAPIError, TikTokClient
from .auth import AuthError, TokenProvider, TokenStore, login
from .config import WEEKDAYS, Config, ConfigError, load_config
from .poster import post_next
from .scheduler import next_slot, upcoming_slots
from .video_queue import State, list_queue, load_caption

log = logging.getLogger("tiktok_scheduler")

MISSED_GRACE = timedelta(minutes=30)  # máy ngủ / bận quá lâu thì bỏ qua slot đó
MAX_SLEEP = 30


def setup_logging(cfg: Config, verbose: bool) -> None:
    cfg.folders.data.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = RotatingFileHandler(cfg.folders.data / "tiktok_scheduler.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    root.handlers[:] = [console, file]
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def make_client(cfg: Config) -> TikTokClient:
    return TikTokClient(TokenProvider(cfg).get)


def cmd_auth(cfg: Config, args) -> int:
    token = login(cfg, open_browser=not args.no_browser)
    print(f"\n✔ Đăng nhập thành công (open_id={token.get('open_id')}, scope={token.get('scope')})")
    print(f"  Token lưu tại {TokenStore(cfg.folders.data).path}")
    return 0


def cmd_check(cfg: Config, args) -> int:
    info = make_client(cfg).creator_info()
    print(f"✔ Kết nối OK. Tài khoản: @{info.get('creator_username')} ({info.get('creator_nickname')})")
    print(f"  Quyền riêng tư cho phép: {info.get('privacy_level_options')}")
    print(f"  Thời lượng video tối đa: {info.get('max_video_post_duration_sec')} giây")
    if cfg.post.privacy_level not in (info.get("privacy_level_options") or [cfg.post.privacy_level]):
        print(f"⚠ privacy_level={cfg.post.privacy_level} không được phép với tài khoản/app này!")
        return 1
    return 0


def cmd_queue(cfg: Config, args) -> int:
    queue = list_queue(cfg)
    now = datetime.now(cfg.schedule.timezone)
    slots = upcoming_slots(now, cfg.schedule, max(1, -(-len(queue) // cfg.schedule.posts_per_slot)) if queue else 5)
    days = ", ".join(WEEKDAYS[d] for d in cfg.schedule.days)
    print(f"Thư mục: {cfg.folders.watch}")
    print(f"Khung giờ: {', '.join(t.strftime('%H:%M') for t in cfg.schedule.times)} ({days}), "
          f"{cfg.schedule.posts_per_slot} video/slot, múi giờ {cfg.schedule.timezone.key}\n")
    if not queue:
        print("Hàng chờ trống. Các slot sắp tới:")
        for s in slots:
            print("  " + s.strftime("%a %d/%m/%Y %H:%M"))
        return 0
    print(f"{len(queue)} video chờ đăng:")
    for i, video in enumerate(queue):
        slot = slots[i // cfg.schedule.posts_per_slot]
        caption = load_caption(cfg, video).replace("\n", " ")
        print(f"  {slot.strftime('%a %d/%m %H:%M')}  {video.name}  |  {caption[:60] or '(không caption)'}")
    return 0


def cmd_post_now(cfg: Config, args) -> int:
    results = post_next(cfg, make_client(cfg), State(cfg.folders.data), args.count)
    return 0 if results and all(r.ok for r in results) else 1


def cmd_run(cfg: Config, args) -> int:
    state = State(cfg.folders.data)
    client = make_client(cfg)
    TokenProvider(cfg).get()  # báo lỗi ngay nếu chưa đăng nhập
    tz = cfg.schedule.timezone
    log.info("Bắt đầu chạy. Thư mục: %s | %d video trong hàng chờ", cfg.folders.watch, len(list_queue(cfg)))

    slot = next_slot(datetime.now(tz), cfg.schedule)
    while True:
        log.info("Slot tiếp theo: %s", slot.strftime("%a %d/%m/%Y %H:%M"))
        while (now := datetime.now(tz)) < slot:
            time.sleep(min(MAX_SLEEP, (slot - now).total_seconds()))

        if now - slot > MISSED_GRACE:
            log.warning("Bỏ qua slot %s vì đã trễ %s (máy ngủ/tắt?)", slot.strftime("%H:%M"), now - slot)
        elif state.data.get("last_slot") == slot.isoformat():
            log.info("Slot %s đã chạy trước đó, bỏ qua.", slot.isoformat())
        else:
            state.data["last_slot"] = slot.isoformat()
            state.save()
            try:
                post_next(cfg, client, state, cfg.schedule.posts_per_slot)
            except AuthError as exc:
                log.error("Lỗi đăng nhập: %s", exc)
            except Exception:  # không để một lỗi bất ngờ làm dừng cả lịch
                log.exception("Lỗi không mong muốn khi đăng")
        slot = next_slot(max(slot, datetime.now(tz) - MISSED_GRACE), cfg.schedule)


COMMANDS = {
    "auth": (cmd_auth, "Đăng nhập TikTok và lưu token"),
    "check": (cmd_check, "Kiểm tra token và thông tin tài khoản"),
    "queue": (cmd_queue, "Xem hàng chờ video và giờ dự kiến đăng"),
    "post-now": (cmd_post_now, "Đăng ngay video tiếp theo (dùng cho Task Scheduler/cron)"),
    "run": (cmd_run, "Chạy liên tục, tự đăng theo khung giờ cố định"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tiktok_scheduler", description="Tự động đăng video lên TikTok theo khung giờ.")
    parser.add_argument("-c", "--config", default="config.toml", help="Đường dẫn file cấu hình (mặc định config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        if name == "auth":
            p.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
        if name == "post-now":
            p.add_argument("-n", "--count", type=int, default=1, help="Số video đăng (mặc định 1)")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        setup_logging(cfg, args.verbose)
        return COMMANDS[args.command][0](cfg, args)
    except (ConfigError, AuthError, TikTokAPIError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        return 130
