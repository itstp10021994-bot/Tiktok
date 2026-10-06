"""Đăng nhập TikTok (OAuth 2.0) và lưu / tự làm mới access token."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .config import Config

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"
REFRESH_MARGIN_SEC = 300

log = logging.getLogger(__name__)


class AuthError(Exception):
    pass


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    # Lưu ý: Login Kit for Desktop của TikTok yêu cầu code_challenge là SHA256 dạng HEX
    # (khác chuẩn base64url của RFC 7636).
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    return verifier, challenge


class TokenStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "tokens.json"

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, token: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        token = dict(token)
        token.setdefault("obtained_at", now)
        if "expires_in" in token:
            token["expires_at"] = now + int(token["expires_in"])
        if "refresh_expires_in" in token:
            token["refresh_expires_at"] = now + int(token["refresh_expires_in"])
        self.path.write_text(json.dumps(token, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _token_request(data: dict, session: requests.Session | None = None) -> dict:
    s = session or requests
    resp = s.post(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        timeout=30,
    )
    try:
        body = resp.json()
    except ValueError as exc:
        raise AuthError(f"Phản hồi token không hợp lệ (HTTP {resp.status_code}): {resp.text[:300]}") from exc
    if "access_token" not in body:
        raise AuthError(f"Lấy token thất bại: {body.get('error')} - {body.get('error_description')}")
    return body


def build_authorize_url(cfg: Config, state: str, challenge: str | None) -> str:
    params = {
        "client_key": cfg.tiktok.client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": cfg.tiktok.redirect_uri,
        "state": state,
    }
    if challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return AUTHORIZE_URL + "?" + urlencode(params)


def _wait_for_callback(redirect_uri: str, timeout: int = 300) -> dict:
    """Mở một web server nhỏ trên localhost để nhận ?code=... từ TikTok."""
    parsed = urlparse(redirect_uri)
    result: dict = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if "code" not in qs and "error" not in qs:
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in qs.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Đăng nhập thành công! Bạn có thể đóng tab này." if "code" in qs else "Đăng nhập thất bại."
            self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())
            done.set()

        def log_message(self, *args):
            pass

    server = HTTPServer((parsed.hostname or "127.0.0.1", parsed.port or 80), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not done.wait(timeout):
            raise AuthError("Hết thời gian chờ đăng nhập.")
    finally:
        server.shutdown()
        server.server_close()
    return result


def login(cfg: Config, open_browser: bool = True) -> dict:
    if not cfg.tiktok.client_key or not cfg.tiktok.client_secret:
        raise AuthError("Chưa điền tiktok.client_key / client_secret trong config.toml")

    state = secrets.token_urlsafe(16)
    verifier, challenge = _pkce_pair() if cfg.tiktok.app_type == "desktop" else (None, None)
    url = build_authorize_url(cfg, state, challenge)

    print("\nMở link sau để đăng nhập TikTok và cấp quyền:\n")
    print(url + "\n")
    if open_browser:
        webbrowser.open(url)

    host = urlparse(cfg.tiktok.redirect_uri).hostname
    if host in ("localhost", "127.0.0.1"):
        print("Đang chờ TikTok chuyển hướng về máy... (tối đa 5 phút)")
        params = _wait_for_callback(cfg.tiktok.redirect_uri)
    else:
        pasted = input("Sau khi đăng nhập, dán toàn bộ URL trên thanh địa chỉ trình duyệt vào đây:\n> ").strip()
        params = {k: v[0] for k, v in parse_qs(urlparse(pasted).query).items()}

    if "error" in params:
        raise AuthError(f"TikTok trả về lỗi: {params.get('error')} - {params.get('error_description')}")
    if params.get("state") != state:
        raise AuthError("State không khớp, hãy thử đăng nhập lại.")

    data = {
        "client_key": cfg.tiktok.client_key,
        "client_secret": cfg.tiktok.client_secret,
        "code": params["code"],
        "grant_type": "authorization_code",
        "redirect_uri": cfg.tiktok.redirect_uri,
    }
    if verifier:
        data["code_verifier"] = verifier
    token = _token_request(data)
    TokenStore(cfg.folders.data).save(token)
    return token


class TokenProvider:
    """Trả về access token còn hạn, tự refresh khi sắp hết hạn (token sống 24h)."""

    def __init__(self, cfg: Config, session: requests.Session | None = None):
        self.cfg = cfg
        self.store = TokenStore(cfg.folders.data)
        self.session = session

    def get(self) -> str:
        token = self.store.load()
        if not token:
            raise AuthError("Chưa đăng nhập. Chạy: python -m tiktok_scheduler auth")
        now = time.time()
        if token.get("expires_at", 0) - REFRESH_MARGIN_SEC > now:
            return token["access_token"]
        if token.get("refresh_expires_at", 0) <= now:
            raise AuthError("Refresh token đã hết hạn. Chạy lại: python -m tiktok_scheduler auth")
        log.info("Access token sắp hết hạn, đang làm mới...")
        new = _token_request(
            {
                "client_key": self.cfg.tiktok.client_key,
                "client_secret": self.cfg.tiktok.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
            self.session,
        )
        self.store.save(new)
        return new["access_token"]
