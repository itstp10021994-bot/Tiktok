"""Client tối giản cho TikTok Content Posting API (v2)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import requests

API_BASE = "https://open.tiktokapis.com"
MB = 1024 * 1024
MIN_CHUNK = 5 * MB
MAX_CHUNK = 64 * MB

MIME_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}

log = logging.getLogger(__name__)


class TikTokAPIError(Exception):
    def __init__(self, code: str, message: str, log_id: str = ""):
        super().__init__(f"{code}: {message}" + (f" (log_id={log_id})" if log_id else ""))
        self.code = code


def plan_chunks(video_size: int, chunk_size: int = 10 * MB) -> tuple[int, int]:
    """Tính (chunk_size, total_chunk_count) theo quy tắc của TikTok.

    - File nhỏ hơn hoặc bằng chunk_size: upload một lần.
    - Còn lại: chunk 5–64MB, số chunk = làm tròn xuống, phần dư gộp vào chunk cuối.
    """
    if video_size <= 0:
        raise ValueError("File video rỗng")
    chunk_size = min(max(chunk_size, MIN_CHUNK), MAX_CHUNK)
    if video_size <= chunk_size:
        return video_size, 1
    return chunk_size, video_size // chunk_size


class TikTokClient:
    def __init__(self, token_getter: Callable[[], str], session: requests.Session | None = None):
        self.token_getter = token_getter
        self.session = session or requests.Session()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.session.post(
            API_BASE + path,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.token_getter()}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=60,
        )
        try:
            body = resp.json()
        except ValueError:
            raise TikTokAPIError(f"http_{resp.status_code}", resp.text[:300])
        err = body.get("error") or {}
        if err.get("code", "ok") != "ok" or resp.status_code >= 400:
            raise TikTokAPIError(err.get("code", f"http_{resp.status_code}"), err.get("message", ""), err.get("log_id", ""))
        return body.get("data") or {}

    def creator_info(self) -> dict:
        return self._post("/v2/post/publish/creator_info/query/", {})

    def init_direct_post(self, post_info: dict, video_size: int, chunk_size: int, total_chunks: int) -> dict:
        return self._post(
            "/v2/post/publish/video/init/",
            {
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                },
            },
        )

    def init_inbox_upload(self, video_size: int, chunk_size: int, total_chunks: int) -> dict:
        return self._post(
            "/v2/post/publish/inbox/video/init/",
            {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                }
            },
        )

    def upload_file(self, upload_url: str, path: Path, chunk_size: int, total_chunks: int) -> None:
        size = path.stat().st_size
        mime = MIME_TYPES.get(path.suffix.lower(), "video/mp4")
        with path.open("rb") as f:
            for i in range(total_chunks):
                start = i * chunk_size
                end = size - 1 if i == total_chunks - 1 else start + chunk_size - 1
                f.seek(start)
                data = f.read(end - start + 1)
                for attempt in range(3):
                    try:
                        resp = self.session.put(
                            upload_url,
                            data=data,
                            headers={
                                "Content-Type": mime,
                                "Content-Length": str(len(data)),
                                "Content-Range": f"bytes {start}-{end}/{size}",
                            },
                            timeout=300,
                        )
                    except requests.RequestException as exc:
                        if attempt == 2:
                            raise TikTokAPIError("upload_network_error", str(exc))
                        time.sleep(2 ** attempt)
                        continue
                    if resp.status_code in (200, 201, 206):
                        break
                    if attempt == 2 or resp.status_code < 500:
                        raise TikTokAPIError(f"upload_http_{resp.status_code}", resp.text[:300])
                    time.sleep(2 ** attempt)
                log.info("  đã upload chunk %d/%d", i + 1, total_chunks)

    def fetch_status(self, publish_id: str) -> dict:
        return self._post("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
