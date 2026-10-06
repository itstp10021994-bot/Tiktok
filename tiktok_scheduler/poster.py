"""Đăng một video: upload lên TikTok, theo dõi trạng thái, di chuyển file."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .api import MB, TikTokAPIError, TikTokClient, plan_chunks
from .auth import AuthError
from .config import Config
from .video_queue import State, list_queue, load_caption, move_with_caption

log = logging.getLogger(__name__)

POLL_INTERVAL = 5
POLL_TIMEOUT = 15 * 60
SUCCESS_STATUSES = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}


@dataclass
class PostResult:
    video: str
    ok: bool
    status: str
    publish_id: str = ""
    detail: str = ""


def _build_post_info(cfg: Config, caption: str, creator: dict) -> dict:
    options = creator.get("privacy_level_options") or []
    privacy = cfg.post.privacy_level
    if options and privacy not in options:
        raise TikTokAPIError(
            "privacy_not_allowed",
            f"Tài khoản chỉ cho phép {options}, nhưng config đang để {privacy}. "
            "App chưa được TikTok duyệt (audit) chỉ đăng được SELF_ONLY.",
        )
    return {
        "title": caption,
        "privacy_level": privacy,
        "disable_comment": cfg.post.disable_comment or bool(creator.get("comment_disabled")),
        "disable_duet": cfg.post.disable_duet or bool(creator.get("duet_disabled")),
        "disable_stitch": cfg.post.disable_stitch or bool(creator.get("stitch_disabled")),
        "is_aigc": cfg.post.is_aigc,
        "video_cover_timestamp_ms": 1000,
    }


def wait_for_publish(client: TikTokClient, publish_id: str, sleep=time.sleep) -> tuple[str, dict]:
    deadline = time.monotonic() + POLL_TIMEOUT
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.fetch_status(publish_id)
        status = last.get("status", "")
        if status in SUCCESS_STATUSES or status == "FAILED":
            return status, last
        sleep(POLL_INTERVAL)
    return "TIMEOUT", last


def post_video(cfg: Config, client: TikTokClient, video: Path, sleep=time.sleep) -> PostResult:
    caption = load_caption(cfg, video)
    size = video.stat().st_size
    chunk_size, total = plan_chunks(size, cfg.post.chunk_size_mb * MB)
    log.info("Đăng %s (%.1f MB, %d chunk, chế độ %s)", video.name, size / MB, total, cfg.post.mode)

    if cfg.post.mode == "direct":
        creator = client.creator_info()
        max_dur = creator.get("max_video_post_duration_sec")
        if max_dur:
            log.info("  tài khoản @%s, video tối đa %ss", creator.get("creator_username", "?"), max_dur)
        init = client.init_direct_post(_build_post_info(cfg, caption, creator), size, chunk_size, total)
    else:
        init = client.init_inbox_upload(size, chunk_size, total)

    publish_id = init["publish_id"]
    client.upload_file(init["upload_url"], video, chunk_size, total)
    status, info = wait_for_publish(client, publish_id, sleep)

    if status == "FAILED":
        return PostResult(video.name, False, status, publish_id, info.get("fail_reason", ""))
    if status == "TIMEOUT":
        # Video đã upload xong; coi như thành công để tránh đăng trùng, kiểm tra lại trên app.
        log.warning("  Hết thời gian chờ TikTok xử lý %s - hãy kiểm tra trên app.", video.name)
    return PostResult(video.name, True, status, publish_id)


def post_next(cfg: Config, client: TikTokClient, state: State, count: int = 1, sleep=time.sleep) -> list[PostResult]:
    """Đăng `count` video tiếp theo trong hàng chờ. Video lỗi sẽ được thử lại ở slot sau."""
    results: list[PostResult] = []
    queue = list_queue(cfg)
    if not queue:
        log.warning("Thư mục %s không còn video nào để đăng.", cfg.folders.watch)
        return results

    for video in queue[:count]:
        try:
            result = post_video(cfg, client, video, sleep)
        except AuthError:
            raise
        except (TikTokAPIError, OSError, ValueError, KeyError) as exc:
            result = PostResult(video.name, False, "ERROR", detail=str(exc))

        if result.ok:
            dest = move_with_caption(video, cfg.folders.posted)
            state.clear_attempts(video.name)
            log.info("✔ Đã đăng %s (%s) → %s", video.name, result.status, dest.parent)
        else:
            n = state.add_attempt(video.name)
            log.error("✘ Lỗi đăng %s (lần %d/%d): %s", video.name, n, cfg.post.max_attempts, result.detail)
            if n >= cfg.post.max_attempts:
                dest = move_with_caption(video, cfg.folders.failed)
                state.clear_attempts(video.name)
                log.error("  Đã chuyển %s sang thư mục lỗi %s", video.name, dest.parent)

        state.add_history(
            video=result.video, ok=result.ok, status=result.status, publish_id=result.publish_id, detail=result.detail
        )
        state.save()
        results.append(result)
    return results
