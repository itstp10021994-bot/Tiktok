import os
import time
from pathlib import Path

import pytest

from tiktok_scheduler.config import load_config


@pytest.fixture
def cfg(tmp_path: Path):
    (tmp_path / "videos").mkdir()
    (tmp_path / "config.toml").write_text(
        """
[tiktok]
client_key = "k"
client_secret = "s"

[folders]
watch = "videos"

[schedule]
timezone = "Asia/Ho_Chi_Minh"
times = ["19:30", "08:00"]
days = ["mon", "wed", "fri"]

[post]
default_caption = "{name} #fyp"
max_attempts = 2
""",
        encoding="utf-8",
    )
    return load_config(tmp_path / "config.toml")


def make_video(folder: Path, name: str, size: int = 1000, age: float = 60) -> Path:
    p = folder / name
    p.write_bytes(b"\0" * size)
    t = time.time() - age
    os.utime(p, (t, t))
    return p
