"""
Reddit 공개 Atom 피드에서 글을 읽어온다. 인증 불필요, 외부 의존성 없음.

Data API 대신 쓰는 경로. 레이트리밋이 빡세서 요청 간격을 넉넉히 두고,
ETag/Last-Modified 조건부 요청으로 불필요한 트래픽을 줄인다.
"""
import html
import json
import logging
import pathlib
import re
import time
import urllib.error
import urllib.parse
import os
import urllib.request
import xml.etree.ElementTree as ET
from calendar import timegm

NS = {"a": "http://www.w3.org/2005/Atom"}
HERE = pathlib.Path(__file__).resolve().parent
CACHE_PATH = pathlib.Path(os.getenv("DATA_DIR", HERE)) / "feed_cache.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 엔드포인트 종류별 최소 간격(초).
# 실측: 서브레딧 피드는 30~40초면 안정적으로 200.
#       search.rss 는 훨씬 빡세서 누적 4분쯤 벌려야 통과했다.
SPACING_FEED = 60.0       # /r/<sub>/new/.rss  (40초는 3번째 그룹이 매 사이클 429, 2026-10-01)
SPACING_SEARCH = 180.0    # /search.rss 끼리
# 검색은 직전 피드 요청과도 벌려야 한다. 피드 40초 뒤에 치면 매번 429,
# 90초 백오프 후 재시도(피드로부터 ~220초)에서야 200이 났다 (2026-09-30 로그).
SPACING_SEARCH_AFTER_ANY = 240.0
MAX_RETRIES = 3

log = logging.getLogger("rss")
_TAG_RE = re.compile(r"<[^>]+>")
_last_any = [0.0]         # 모든 요청 공통 (같은 버킷을 쓰므로)
_last_search = [0.0]      # 검색 요청끼리의 추가 간격


# ── 조건부 요청 캐시 (ETag / Last-Modified) ─────────────────
# CI 처럼 매 실행이 새 컨테이너인 환경에서는 ETag 캐시가 의미 없고,
# 잘못 남아 있으면 304 로 글을 건너뛴다. 스위치로 끌 수 있게 한다.
USE_CACHE = os.getenv("USE_FEED_CACHE", "1") not in ("0", "false", "False", "")


def _load_cache():
    if USE_CACHE and CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache):
    if not USE_CACHE:
        return
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(CACHE_PATH)


_cache = _load_cache()


# ── HTTP ────────────────────────────────────────────────────
def _throttle(is_search=False):
    now = time.time()
    wait = SPACING_FEED - (now - _last_any[0])
    if is_search:
        wait = max(SPACING_SEARCH_AFTER_ANY - (now - _last_any[0]),
                   SPACING_SEARCH - (now - _last_search[0]))
    if wait > 0:
        log.debug("스로틀 %.0f초 대기", wait)
        time.sleep(wait)
    _last_any[0] = time.time()
    if is_search:
        _last_search[0] = _last_any[0]


def _fetch(url, is_search=False):
    """피드 본문을 반환. 변경 없으면(304) None."""
    entry = _cache.get(url, {})
    for attempt in range(MAX_RETRIES):
        _throttle(is_search)
        headers = {"User-Agent": UA, "Accept": "application/atom+xml, application/xml"}
        if USE_CACHE and entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        if USE_CACHE and entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                new = {}
                if r.headers.get("ETag"):
                    new["etag"] = r.headers["ETag"]
                if r.headers.get("Last-Modified"):
                    new["last_modified"] = r.headers["Last-Modified"]
                if new:
                    _cache[url] = new
                    _save_cache(_cache)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None
            if e.code == 429:
                backoff = (90 if is_search else 20) * (attempt + 1)
                log.warning("429 레이트리밋 — %d초 대기 (%s)", backoff, url)
                time.sleep(backoff)
                continue
            if 500 <= e.code < 600:
                time.sleep(5 * (attempt + 1))
                continue
            log.warning("HTTP %d — %s", e.code, url)
            return None
        except Exception as e:
            log.warning("요청 실패 (%s): %s", type(e).__name__, url)
            time.sleep(3 * (attempt + 1))
    log.warning("재시도 소진 — %s", url)
    return None


# ── 파싱 ────────────────────────────────────────────────────
def _strip_html(raw):
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    # RSS 가 본문 뒤에 붙이는 보일러플레이트 제거
    text = re.sub(r"\s*submitted by\s+/u/\S+.*$", "", text, flags=re.S | re.I)
    text = re.sub(r"\s*\[link\]\s*\[comments\]\s*$", "", text, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _to_epoch(iso):
    if not iso:
        return time.time()
    try:
        # 2026-09-29T18:05:55+00:00
        base = iso[:19]
        return timegm(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return time.time()


def _parse(body, fallback_sub=""):
    posts = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        log.warning("XML 파싱 실패: %s", e)
        return posts

    for e in root.findall("a:entry", NS):
        def txt(tag):
            el = e.find(f"a:{tag}", NS)
            return (el.text or "").strip() if el is not None and el.text else ""

        raw_id = txt("id")                       # "t3_1wtheta"
        pid = raw_id.split("_", 1)[-1] if raw_id else ""
        if not pid:
            continue

        link_el = e.find("a:link", NS)
        url = link_el.get("href", "") if link_el is not None else ""
        permalink = urllib.parse.urlparse(url).path

        cat = e.find("a:category", NS)
        sub = cat.get("term", "") if cat is not None else fallback_sub

        author_el = e.find("a:author/a:name", NS)
        author = (author_el.text or "").strip() if author_el is not None else ""
        author = author[3:] if author.startswith("/u/") else author

        content_el = e.find("a:content", NS)
        body_text = _strip_html(content_el.text if content_el is not None else "")

        if not sub or not permalink.startswith("/r/"):
            continue        # 글이 아닌 항목 (검색 결과에 섞이는 서브레딧 자체 등)

        posts.append({
            "id": pid,
            "subreddit": sub,
            "author": author,
            "title": txt("title"),
            "selftext": body_text,
            "created_utc": _to_epoch(txt("published") or txt("updated")),
            "permalink": permalink,
            "score": None,          # RSS에는 없음
            "num_comments": None,   # RSS에는 없음
        })
    return posts


# ── 공개 API (reddit_client.RedditClient 와 같은 모양) ───────
class RssSource:
    def new_posts(self, subreddit, limit=25):
        """단일 서브레딧. 여러 개면 new_posts_multi 를 쓸 것."""
        url = f"https://www.reddit.com/r/{subreddit}/new/.rss"
        body = _fetch(url)
        if body is None:
            return []
        return _parse(body, fallback_sub=subreddit)[:limit]

    def new_posts_group(self, group):
        """볼륨별 그룹 하나를 요청 1회로 가져온다. r/a+b+c 멀티레딧 문법."""
        url = f"https://www.reddit.com/r/{'+'.join(group)}/new/.rss"
        body = _fetch(url)
        if body is None:
            return []
        got = _parse(body)
        if got:
            span = (max(p["created_utc"] for p in got)
                    - min(p["created_utc"] for p in got)) / 60
            log.info("그룹 %s → %d건, %.0f분 커버", "+".join(group), len(got), span)
            if span < config_poll_minutes():
                log.warning("커버(%.0f분) < 폴링주기 — 글을 놓칠 수 있음: %s",
                            span, "+".join(group))
        return got


    def search(self, query, limit=25, time_filter="week"):
        """Reddit 전체 검색. 서브 목록 밖의 글을 잡는 유일한 수단.
        레이트리밋이 피드보다 훨씬 빡세다 (SPACING_SEARCH)."""
        url = ("https://www.reddit.com/search.rss?"
               + urllib.parse.urlencode({"q": query, "sort": "new", "t": time_filter}))
        body = _fetch(url, is_search=True)
        if body is None:
            return []
        got = _parse(body)
        log.info("검색 [%s] → %d건", query[:45], len(got))
        return got[:limit]


def config_poll_minutes():
    try:
        import config
        return config.POLL_INTERVAL_SECONDS / 60
    except Exception:
        return 0


def from_env():
    return RssSource()
