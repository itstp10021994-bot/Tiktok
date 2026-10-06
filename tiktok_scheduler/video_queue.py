"""Hàng chờ video trong thư mục, caption và lịch sử đăng."""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import Config

STABLE_SECONDS = 15  # bỏ qua file vừa sửa (có thể đang copy dở)
MAX_CAPTION_UTF16 = 2200


def list_queue(cfg: Config, now: float | None = None) -> list[Path]:
    watch = cfg.folders.watch
    if not watch.is_dir():
        return []
    now = now if now is not None else time.time()
    files = [
        p
        for p in watch.iterdir()
        if p.is_file()
        and p.suffix.lower() in cfg.folders.extensions
        and not p.name.startswith(".")
        and now - p.stat().st_mtime >= STABLE_SECONDS
    ]
    if cfg.folders.order == "mtime":
        files.sort(key=lambda p: (p.stat().st_mtime, p.name.lower()))
    else:
        files.sort(key=lambda p: p.name.lower())
    return files


def caption_file(video: Path) -> Path:
    return video.with_suffix(".txt")


def _truncate_utf16(text: str, limit: int) -> str:
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text
    out, units = [], 0
    for ch in text:
        u = len(ch.encode("utf-16-le")) // 2
        if units + u > limit:
            break
        out.append(ch)
        units += u
    return "".join(out)


def load_caption(cfg: Config, video: Path) -> str:
    """Caption lấy từ file .txt cùng tên với video, nếu không có thì dùng default_caption.

    Trong default_caption có thể dùng {name} để chèn tên file (không có đuôi).
    """
    txt = caption_file(video)
    if txt.exists():
        text = txt.read_text(encoding="utf-8-sig").strip()
    else:
        text = cfg.post.default_caption.replace("{name}", video.stem).strip()
    return _truncate_utf16(text, MAX_CAPTION_UTF16)


def _unique_dest(folder: Path, name: str) -> Path:
    dest = folder / name
    if not dest.exists():
        return dest
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return folder / f"{Path(name).stem}_{stamp}{Path(name).suffix}"


def move_with_caption(video: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(folder, video.name)
    txt = caption_file(video)
    shutil.move(str(video), dest)
    if txt.exists():
        shutil.move(str(txt), dest.with_suffix(".txt"))
    return dest


class State:
    """Lưu số lần thử của từng file, slot đã chạy gần nhất và lịch sử đăng."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "state.json"
        self.data = {"attempts": {}, "last_slot": None, "history": []}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def attempts(self, name: str) -> int:
        return self.data["attempts"].get(name, 0)

    def add_attempt(self, name: str) -> int:
        n = self.attempts(name) + 1
        self.data["attempts"][name] = n
        return n

    def clear_attempts(self, name: str) -> None:
        self.data["attempts"].pop(name, None)

    def add_history(self, **entry) -> None:
        entry.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        self.data["history"].append(entry)
        self.data["history"] = self.data["history"][-500:]
