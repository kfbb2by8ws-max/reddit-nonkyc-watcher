"""탐지 대상 정의. 여기만 고치면 됨."""
import os

# 검색 피드 사용 여부. 데이터센터 IP(GitHub Actions, Railway 등)에서는
# Reddit 이 search.rss 를 429 로 막으므로 켜두면 백오프로 시간만 태운다.
# 주거용 회선 = 1(기본), CI = 0.
ENABLE_SEARCH = os.getenv("ENABLE_SEARCH", "1") not in ("0", "false", "False", "")

# ── 폴링 대상 ──────────────────────────────────────────────
# 멀티레딧(r/a+b+c)은 요청 1회로 여러 서브를 가져오지만 엔트리 25칸을
# 서브들이 나눠 갖는다. 즉 묶을수록 커버 시간이 짧아진다.
#
# 실측 (2026-09-29):
#   단일 r/CryptoCurrency → 25건 / 2897분 (48시간)
#   단일 r/Bitcoin        → 25건 / 1524분 (25시간)
#   멀티 3개              → 25건 / 1042분 (17시간)
#   멀티 8개              → 25건 /  598분 (10시간)
#   멀티 17개             → 25건 /   95분
#
# 따라서 묶음 크기는 폴링 주기에 맞춰야 한다. 커버 < 주기면 글을 놓치고,
# 그 경우 로그에 경고가 찍힌다.
#
#   맥 데몬 (15분 주기, 무료)  → GROUP_SIZE=9  : 3요청 ≈ 2분, 커버 10시간+
#   GitHub Actions (1일 1회)   → GROUP_SIZE=1  : 26요청 ≈ 18분, 커버 24시간+
SUBREDDIT_LIST = [
    # 크립토 코어
    "CryptoCurrency", "CryptoCurrencies", "CryptoMarkets", "Bitcoin",
    "BitcoinBeginners", "btc", "CryptoTechnology", "defi", "ethereum",
    # 프라이버시 + 카드 + 로컬
    "Monero", "privacy", "privacytoolsIO", "CryptoCards",
    "cryptocurrencycards", "dubai", "UAE", "expats",
    # 검색이 막히는 CI 를 보완하는 확장.
    # 실측 매칭 3건이 전부 목록 밖에서 나왔고 r/CryptoReferrals 가 실제 히트였다.
    # 존재하지 않는 서브가 섞여도 200 을 주고 유효한 것만 반환한다(실측 확인).
    "CryptoReferrals", "digitalnomad", "digitalnomads", "freelance",
    "Fintech", "ethtrader", "Crypto_com", "binance", "kraken",
]

GROUP_SIZE = max(1, int(os.getenv("GROUP_SIZE", "9")))
SUBREDDIT_GROUPS = [SUBREDDIT_LIST[i:i + GROUP_SIZE]
                    for i in range(0, len(SUBREDDIT_LIST), GROUP_SIZE)]
SUBREDDITS = list(SUBREDDIT_LIST)

# ── 전체 Reddit 검색 (느리지만 동작함) ──
SEARCH_QUERIES = [
    # search.rss 는 막힌 게 아니라 레이트리밋이 훨씬 빡세다 (SPACING_SEARCH=180s).
    # 실측: 180초 간격이면 200. 위 서브 목록 밖을 잡는 유일한 수단이다
    # (테스트에서 r/CryptoReferrals 등 목록에 없는 서브가 잡혔다).
    # 다만 Reddit 검색 relevance 가 헐거워서 무관한 결과가 섞인다 → 로컬 필터가 거른다.
    '("no kyc" OR "non-kyc") ("crypto card" OR "debit card" OR "virtual card")',
]

# ── 로컬 필터: (카드 용어) AND (non-KYC 용어) 둘 다 있어야 매칭 ──
CARD_TERMS = [
    "crypto card", "debit card", "virtual card", "prepaid card",
    "credit card", "visa card", "mastercard", "crypto visa",
    "카드",
]

NOKYC_TERMS = [
    "no kyc", "non kyc", "non-kyc", "nonkyc", "without kyc",
    "kyc free", "kyc-free", "no verification", "without verification",
    "no id", "no identity", "anonymous card", "unverified",
    "논케이와이씨", "kyc 없",
]

# 있으면 "구하는 글"일 확률이 높음. 없어도 매칭은 되지만 우선순위 표시가 붙음.
INTENT_TERMS = [
    "looking for", "recommend", "any card", "anyone know", "does anyone",
    "where can i", "suggestion", "need a", "best card", "which card",
    "is there a", "how do i get", "help me find",
]

# 매칭돼도 버릴 것 (광고/스팸 글)
EXCLUDE_TERMS = [
    "dm me", "pm me", "telegram @", "whatsapp +", "referral code",
    "use my link", "sign up with", "promo code",
]

# 데몬 루프 간격이자 커버리지 자가점검의 기준값.
# 맥 데몬 = 900(15분), CI = 86400(1일, 워크플로에서 주입).
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))
POSTS_PER_SUBREDDIT = 25
MAX_AGE_HOURS = 48            # 검색 색인 지연 감안해서 넉넉히
