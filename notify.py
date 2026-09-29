"""텔레그램 포워딩. ~/.claude/telegram.json 의 봇/챗을 그대로 씀."""
import html
import json
import os
import pathlib
import urllib.parse
import urllib.request

CONFIG = pathlib.Path.home() / ".claude" / "telegram.json"


def _cfg():
    """봇 자격증명을 찾는다. 환경변수 우선 → 로컬 파일.

    환경변수를 먼저 보는 이유: 컨테이너/CI 로 옮겨도 코드 수정 없이 돌게.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        return {"bot_token": token, "chat_id": chat}
    if CONFIG.exists():
        with CONFIG.open() as f:
            return json.load(f)
    raise SystemExit(
        "텔레그램 설정이 없다. TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수를 주거나 "
        f"{CONFIG} 를 두세요.")


def send_html(text, disable_preview=False):
    cfg = _cfg()
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_preview else "false",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {res}")
    return res


def _age(seconds):
    m = int(seconds // 60)
    if m < 60:
        return f"{m}분 전"
    h = m // 60
    if h < 24:
        return f"{h}시간 전"
    return f"{h // 24}일 전"


def _meta_line(post, age_seconds):
    import html as _h
    parts = [f"r/{_h.escape(post.get('subreddit',''), quote=False)}",
             f"u/{_h.escape(post.get('author',''), quote=False)}",
             _age(age_seconds)]
    if post.get("score") is not None:
        parts.append(f"⬆{post['score']}")
    if post.get("num_comments") is not None:
        parts.append(f"💬{post['num_comments']}")
    return " · ".join(parts)


def format_post(post, matched, age_seconds):
    e = lambda x: html.escape(x or '', quote=False)
    flag = "🔥" if matched.get("intent") else "🔵"
    body = (post.get("selftext") or "").strip().replace("\n\n", "\n")
    if len(body) > 400:
        body = body[:400].rstrip() + "…"

    lines = [
        f"{flag} <b>non-KYC 카드 관련 글</b>",
        _meta_line(post, age_seconds),
        "",
        f"<b>{e(post.get('title',''))}</b>",
    ]
    if body:
        lines += ["", f"<blockquote>{e(body)}</blockquote>"]
    hits = ", ".join(matched.get("terms", []))
    if hits:
        lines += ["", f"<i>매칭: {e(hits)}</i>"]
    lines += ["", f"https://www.reddit.com{post.get('permalink','')}"]
    return "\n".join(lines)
