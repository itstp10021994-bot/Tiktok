from tiktok_scheduler.api import MB, plan_chunks
from tiktok_scheduler.poster import post_next
from tiktok_scheduler.video_queue import State, list_queue, load_caption

from .conftest import make_video


def test_plan_chunks():
    assert plan_chunks(1000) == (1000, 1)
    assert plan_chunks(8 * MB, 10 * MB) == (8 * MB, 1)
    assert plan_chunks(25 * MB, 10 * MB) == (10 * MB, 2)  # chunk cuối 15MB
    assert plan_chunks(200 * MB, 1 * MB) == (5 * MB, 40)  # tối thiểu 5MB


def test_queue_order_and_filters(cfg):
    w = cfg.folders.watch
    make_video(w, "b.mp4")
    make_video(w, "a.MOV")
    make_video(w, "notes.txt")
    make_video(w, "copying.mp4", age=0)  # đang copy, chưa ổn định
    assert [p.name for p in list_queue(cfg)] == ["a.MOV", "b.mp4"]


def test_caption_sidecar_and_default(cfg):
    w = cfg.folders.watch
    v1 = make_video(w, "clip1.mp4")
    v2 = make_video(w, "clip2.mp4")
    (w / "clip1.txt").write_text("Xin chào 👋 #test\n", encoding="utf-8")
    assert load_caption(cfg, v1) == "Xin chào 👋 #test"
    assert load_caption(cfg, v2) == "clip2 #fyp"


class FakeClient:
    def __init__(self, final_status="PUBLISH_COMPLETE", privacy=("SELF_ONLY",)):
        self.final_status = final_status
        self.privacy = list(privacy)
        self.calls = []

    def creator_info(self):
        return {"privacy_level_options": self.privacy, "creator_username": "me"}

    def init_direct_post(self, post_info, size, chunk, total):
        self.calls.append(("init", post_info["title"], post_info["privacy_level"], size, total))
        return {"publish_id": "p1", "upload_url": "https://upload"}

    def upload_file(self, url, path, chunk, total):
        self.calls.append(("upload", path.name))

    def fetch_status(self, publish_id):
        return {"status": self.final_status, "fail_reason": "boom"}


def test_post_success_moves_file(cfg):
    w = cfg.folders.watch
    make_video(w, "a.mp4")
    (w / "a.txt").write_text("cap", encoding="utf-8")
    make_video(w, "b.mp4")
    client = FakeClient()
    results = post_next(cfg, client, State(cfg.folders.data), sleep=lambda s: None)
    assert [r.ok for r in results] == [True]
    assert client.calls[0] == ("init", "cap", "SELF_ONLY", 1000, 1)
    assert (cfg.folders.posted / "a.mp4").exists() and (cfg.folders.posted / "a.txt").exists()
    assert [p.name for p in list_queue(cfg)] == ["b.mp4"]
    assert State(cfg.folders.data).data["history"][-1]["video"] == "a.mp4"


def test_post_failure_retries_then_moves_to_failed(cfg):
    make_video(cfg.folders.watch, "a.mp4")
    client = FakeClient(final_status="FAILED")
    state = State(cfg.folders.data)
    post_next(cfg, client, state, sleep=lambda s: None)
    assert (cfg.folders.watch / "a.mp4").exists()  # còn thử lại
    post_next(cfg, client, state, sleep=lambda s: None)
    assert (cfg.folders.failed / "a.mp4").exists()  # max_attempts = 2


def test_privacy_not_allowed_is_reported(cfg):
    make_video(cfg.folders.watch, "a.mp4")
    cfg.post.privacy_level = "PUBLIC_TO_EVERYONE"
    results = post_next(cfg, FakeClient(), State(cfg.folders.data), sleep=lambda s: None)
    assert not results[0].ok and "privacy_not_allowed" in results[0].detail
