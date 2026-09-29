#!/usr/bin/env python3
"""
배포 환경의 IP 에서 Reddit 공개 피드가 접근 가능한지 확인한다.

Railway 등에 올린 뒤 start command 를 이걸로 한 번 돌려서 로그를 확인할 것.
200 + entries 가 나오면 watcher 로 바꿔도 된다.
403 이면 그 IP 대역이 Reddit 에 막힌 것이므로 배포를 포기하고 집에서 돌려야 한다.
"""
import json
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TARGETS = [
    ("서브레딧 피드", "https://www.reddit.com/r/CryptoCurrency/new/.rss"),
    ("검색 피드", "https://www.reddit.com/search.rss?q=%22no+kyc%22+crypto+card&sort=new&t=week"),
]


def outbound_ip():
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("ip", "?")
    except Exception as e:
        return f"확인 실패 ({type(e).__name__})"


def main():
    print("=" * 56)
    print(f"이 환경의 외부 IP: {outbound_ip()}")
    print("=" * 56)

    # "ok" / "ratelimited" / "blocked" / "error" 로 구분한다.
    # 429 와 403 은 의미가 완전히 다르다:
    #   429 = 이 IP 가 최근 너무 많이 요청함 (간격을 벌리면 통과. 차단 아님)
    #   403 = 이 IP 대역 자체가 거부됨 (기다려도 안 됨)
    results = {}
    for label, url in TARGETS:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/atom+xml, application/xml"})
            with urllib.request.urlopen(req, timeout=25) as r:
                body = r.read()
            n = body.count(b"<entry")
            if r.status == 200 and n > 0:
                print(f"{label:<12} HTTP 200  entries={n}  ✅ 통과")
                results[label] = "ok"
            else:
                print(f"{label:<12} HTTP {r.status}  entries={n}  ⚠️ 응답은 왔지만 피드가 비었음")
                results[label] = "error"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"{label:<12} HTTP 429  ⏳ 레이트리밋 (차단 아님)")
                results[label] = "ratelimited"
            elif e.code in (403, 451):
                print(f"{label:<12} HTTP {e.code}  ❌ IP 차단")
                results[label] = "blocked"
            else:
                print(f"{label:<12} HTTP {e.code} {e.reason}  ❌")
                results[label] = "error"
        except Exception as e:
            print(f"{label:<12} ERR {type(e).__name__}: {e}  ❌")
            results[label] = "error"

    print("=" * 56)
    vals = list(results.values())
    if "blocked" in vals:
        print("판정: 이 IP 대역이 Reddit 에 거부됐다 (403). 기다려도 안 풀린다.")
        print("      배포 불가 — 주거용 회선(집 맥 / 라즈베리파이)에서 돌려야 한다.")
    elif all(v == "ok" for v in vals):
        print("판정: 통과. start command 를 'python watcher.py --loop' 로 바꿔도 된다.")
    elif "ratelimited" in vals and "error" not in vals:
        print("판정: 차단은 아니다 (403 없음). 429 는 이 IP 가 최근 요청을 많이 썼다는 뜻.")
        print("      같은 IP 에서 워처가 이미 돌고 있으면 자기 자신 때문에 걸린다.")
        print("      → 로컬에서 테스트할 땐 ./stop.sh 로 워처를 먼저 끄고 재실행할 것.")
        print("      → 배포 환경(새 IP)에서 429 가 나오면 2~3분 뒤 다시 돌려볼 것.")
    else:
        print("판정: 불명확. 위 항목별 결과를 보고 판단할 것.")
    print("=" * 56)


if __name__ == "__main__":
    main()
