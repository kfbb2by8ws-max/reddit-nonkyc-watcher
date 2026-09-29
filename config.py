"""탐지 대상 정의. 여기만 고치면 됨."""
import os

# 검색 피드 사용 여부. 데이터센터 IP(GitHub Actions, Railway 등)에서는
# Reddit 이 search.rss 를 429 로 막으므로 켜두면 백오프로 시간만 태운다.
# 주거용 회선 = 1(기본), CI = 0.
ENABLE_SEARCH = os.getenv("ENABLE_SEARCH", "1") not in ("0", "false", "False", "")

# ── 폴링 대상: 멀티레딧 그룹 ────────────────────────────────
# 멀티레딧(r/a+b+c)은 요청 1회로 여러 서브를 가져온다. 엔트리는 25칸 고정이고
# 서브들이 나눠 갖는다. 한 그룹의 25칸이 POLL_INTERVAL 보다 긴 시간을
# 커버해야 그 사이 올라온 글을 놓치지 않는다.
#
# 실측 (2026-09-29, 단독 실행, 60초 간격):
#   단일 CryptoCurrency → 25건 / 2897분 (48시간)
#   멀티 3개            → 25건 / 1042분 (17시간)
#   멀티 8개            → 25건 /  598분 (10시간)
#   멀티 17개(전체)      → 25건 /   95분  ← 최악의 경우도 폴링주기의 6배
#
# 17개를 한 요청에 다 넣어도 95분을 커버해서 15분 주기엔 충분하지만,
# 한 서브가 갑자기 활발해지면 칸을 독식한다 (위 17개 측정에서 r/UAE 가 10칸).
# 그래서 2그룹으로 나눠 여유를 둔다. 요청 2회면 비용도 미미하다.
SUBREDDIT_GROUPS = [
    # 크립토 코어 (고~중볼륨)
    ["CryptoCurrency", "CryptoCurrencies", "CryptoMarkets", "Bitcoin",
     "BitcoinBeginners", "btc", "CryptoTechnology", "defi", "ethereum"],
    # 프라이버시 + 카드 + 로컬
    ["Monero", "privacy", "privacytoolsIO", "CryptoCards",
     "cryptocurrencycards", "dubai", "UAE", "expats"],
    # 검색 피드가 막히는 환경(CI)을 보완하기 위한 확장.
    # 실측에서 매칭 3건이 전부 목록 밖에서 나왔고, 그 중 r/CryptoReferrals 가
    # 실제 히트였다. 존재하지 않는 서브가 섞여도 멀티피드는 200 을 주고
    # 유효한 것만 반환하므로(실측 확인) 미검증 후보를 넣어도 무해하다.
    ["CryptoReferrals", "digitalnomad", "digitalnomads", "freelance",
     "Fintech", "ethtrader", "Crypto_com", "binance", "kraken"],
]

# 하위 호환 / 참고용 평면 목록
SUBREDDITS = [s for g in SUBREDDIT_GROUPS for s in g]

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

POLL_INTERVAL_SECONDS = 900   # 15분 (레이트리밋 때문에 5분은 무리)
POSTS_PER_SUBREDDIT = 25
MAX_AGE_HOURS = 48            # 검색 색인 지연 감안해서 넉넉히
