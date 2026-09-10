# -*- coding: utf-8 -*-
"""
네이버 모바일 증권의 시가총액 순위 JSON API를 이용해
코스피/코스닥 종목 코드+이름+시가총액을 가져오고,
지정한 시가총액 이상인 종목만 걸러서 tickers_full.txt 로 저장.

실제 응답 구조(직접 확인 완료, 2026-09-09 기준):
{
  "result": {
    "totCnt": 2483,
    "itemList": [
      {"cd": "005930", "nm": "삼성전자", "mks": 15945725,
       "kospi": true, "kosdaq": false, "etn": false, "etf": false, ...},
      ...
    ]
  }
}
- mks: 억원 단위 시가총액 (예: 15,945,725억원 = 약 1,594조원)
- etn/etf 플래그가 이미 내려오므로 이름 패턴 없이도 정확히 걸러낼 수 있음

실행 예시:
  python naver_export_tickers.py                    # 시총 필터 없이 전종목
  python naver_export_tickers.py --min-cap 3000      # 시총 3,000억 이상만
결과: 같은 폴더에 tickers_full.txt 생성 (ETN/ETF/스팩/우선주 제외)
"""

import argparse
import re
import time
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def is_excluded_by_name(name: str) -> bool:
    """스팩, 우선주(우/우B/1우/2우B 등) - API에 플래그가 없는 것들만 이름으로 필터링."""
    if "스팩" in name:
        return True
    if re.search(r"\d*우(B)?$", name):
        return True
    return False


def fetch_market(sosok: int, market_name: str, min_cap_eok: float,
                  page_size: int = 100, sleep_sec: float = 0.2, max_pages: int = 60):
    """sosok: 0=KOSPI, 1=KOSDAQ. min_cap_eok: 억원 단위 최소 시가총액 (None이면 필터 없음)."""
    results = []
    total_cnt = None
    page = 1

    while page <= max_pages:
        url = (f"https://m.stock.naver.com/api/json/sise/siseListJson.nhn"
               f"?menu=market_sum&sosok={sosok}&pageSize={page_size}&page={page}")
        resp = None
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            data = resp.json()
        except Exception as e:
            print(f"  {market_name} {page}페이지 요청/파싱 실패: {e}")
            if resp is not None:
                print(f"  응답 일부: {resp.text[:500]}")
            break

        result = data.get("result", {}) if isinstance(data, dict) else {}
        if total_cnt is None:
            total_cnt = result.get("totCnt")
            if total_cnt:
                print(f"  {market_name} 전체 {total_cnt}개 종목 확인됨")

        items = result.get("itemList", [])
        if not items:
            print(f"  {market_name} {page}페이지: 데이터 없음 -> 종료")
            break

        for item in items:
            code = item.get("cd")
            name = item.get("nm")
            market_cap = item.get("mks")  # 억원 단위

            if not code or not name:
                continue
            if item.get("etn") or item.get("etf"):
                continue
            if is_excluded_by_name(name):
                continue
            if min_cap_eok is not None and market_cap is not None and market_cap < min_cap_eok:
                continue

            results.append((code, name.strip(), market_cap))

        if total_cnt and page * page_size >= total_cnt:
            break

        page += 1
        time.sleep(sleep_sec)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-cap", type=float, default=None,
                         help="최소 시가총액(억원 단위). 예: 3000 = 3,000억원 이상만")
    parser.add_argument("--out", default="tickers_full.txt")
    args = parser.parse_args()

    print("[1/2] KOSPI 종목 수집 중...")
    kospi = fetch_market(sosok=0, market_name="KOSPI", min_cap_eok=args.min_cap)
    print(f"  -> {len(kospi)}개 (필터 적용 후)")

    print("[2/2] KOSDAQ 종목 수집 중...")
    kosdaq = fetch_market(sosok=1, market_name="KOSDAQ", min_cap_eok=args.min_cap)
    print(f"  -> {len(kosdaq)}개 (필터 적용 후)")

    all_tickers = kospi + kosdaq

    with open(args.out, "w", encoding="utf-8") as f:
        cap_note = f"(시총 {args.min_cap:.0f}억 이상)" if args.min_cap else "(시총 필터 없음)"
        f.write(f"# 네이버 증권에서 자동 생성된 종목 리스트 {cap_note}, ETN/ETF/스팩/우선주 제외\n")
        for code, name, mcap in all_tickers:
            f.write(f"{code},{name}\n")

    print(f"\n총 {len(all_tickers)}개 종목 -> {args.out} 저장 완료")
