from tiktok_scheduler.api import MB, TikTokAPIError, TikTokClient

import pytest


class Resp:
    def __init__(self, status=206, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, post_body=None):
        self.puts = []
        self.post_body = post_body

    def put(self, url, data, headers, timeout):
        self.puts.append((headers["Content-Range"], len(data), headers["Content-Type"]))
        return Resp(206)

    def post(self, url, json, headers, timeout):
        return Resp(200, self.post_body)


def test_upload_content_ranges(tmp_path):
    f = tmp_path / "v.mov"
    f.write_bytes(b"x" * (12 * MB + 7))
    s = FakeSession()
    TikTokClient(lambda: "t", s).upload_file("u", f, 5 * MB, 2)
    total = 12 * MB + 7
    assert s.puts == [
        (f"bytes 0-{5 * MB - 1}/{total}", 5 * MB, "video/quicktime"),
        (f"bytes {5 * MB}-{total - 1}/{total}", total - 5 * MB, "video/quicktime"),
    ]


def test_api_error_raised():
    s = FakeSession({"error": {"code": "access_token_invalid", "message": "bad", "log_id": "L"}})
    with pytest.raises(TikTokAPIError, match="access_token_invalid"):
        TikTokClient(lambda: "t", s).creator_info()


def test_api_ok_returns_data():
    s = FakeSession({"data": {"creator_username": "me"}, "error": {"code": "ok"}})
    assert TikTokClient(lambda: "t", s).creator_info() == {"creator_username": "me"}
