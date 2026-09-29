"""Reddit OAuth (app-only) 클라이언트. 외부 의존성 없음."""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"


class RedditClient:
    def __init__(self, client_id, client_secret, user_agent,
                 username=None, password=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.username = username
        self.password = password
        self._token = None
        self._token_expiry = 0

    # ── 인증 ────────────────────────────────────────────────
    def _fetch_token(self):
        if self.username and self.password:
            data = {"grant_type": "password",
                    "username": self.username,
                    "password": self.password}
        else:
            data = {"grant_type": "client_credentials"}

        body = urllib.parse.urlencode(data).encode()
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
            "Authorization": f"Basic {basic}",
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
        if "access_token" not in payload:
            raise RuntimeError(f"토큰 발급 실패: {payload}")
        self._token = payload["access_token"]
        self._token_expiry = time.time() + payload.get("expires_in", 3600) - 60

    def _auth_header(self):
        if not self._token or time.time() >= self._token_expiry:
            self._fetch_token()
        return {"Authorization": f"bearer {self._token}",
                "User-Agent": self.user_agent}

    # ── 요청 ────────────────────────────────────────────────
    def _get(self, path, params=None, retries=3):
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=self._auth_header())
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 401:          # 토큰 만료 → 강제 갱신
                    self._token = None
                elif e.code == 429:        # 레이트리밋
                    time.sleep(10 * (attempt + 1))
                elif 500 <= e.code < 600:
                    time.sleep(3 * (attempt + 1))
                else:
                    raise
            except Exception as e:
                last = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"Reddit GET 실패 {path}: {last}")

    # ── 엔드포인트 ──────────────────────────────────────────
    def new_posts(self, subreddit, limit=25):
        d = self._get(f"/r/{subreddit}/new",
                      {"limit": limit, "raw_json": 1})
        return [c["data"] for c in d.get("data", {}).get("children", [])]

    def search(self, query, limit=25, time_filter="day"):
        d = self._get("/search", {"q": query, "sort": "new", "limit": limit,
                                  "t": time_filter, "type": "link", "raw_json": 1})
        return [c["data"] for c in d.get("data", {}).get("children", [])]


def from_env():
    cid = os.getenv("REDDIT_CLIENT_ID")
    secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 가 없어. .env 를 채워줘.\n"
            "발급: https://www.reddit.com/prefs/apps → create app → type: script")
    ua = os.getenv("REDDIT_USER_AGENT",
                   "macos:nonkyc-card-watcher:v1.0 (by /u/unknown)")
    return RedditClient(cid, secret, ua,
                        os.getenv("REDDIT_USERNAME"),
                        os.getenv("REDDIT_PASSWORD"))
