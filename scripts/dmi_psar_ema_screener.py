# -*- coding: utf-8 -*-
"""
DMI + PSAR + EMA 골든크로스 초입 스크리너
==========================================

플래드낵님 매매법 재현 스크립트:
  1) DI 상승 전환   : +DI가 -DI를 상향 돌파 (혹은 +DI 저점 반등)
  2) PSAR 하단점 전환 : PSAR 점이 캔들 위 -> 아래로 전환 (하락추세 종료)
  3) EMA 정배열 초입  : 단기 EMA가 중기 EMA를 막 상향 돌파

세 조건이 최근 N영업일(기본 5일) 이내에 함께(각각 순서 무관) 발생한
종목을 KOSPI/KOSDAQ 전체에서 스크리닝해서 엑셀로 저장합니다.

필요 라이브러리 (Charles님 환경엔 이미 설치돼 있음)
  pip install pandas numpy FinanceDataReader pykrx openpyxl --break-system-packages

사용법
  python dmi_psar_ema_screener.py                # 코스피+코스닥 전체 스캔
  python dmi_psar_ema_screener.py --market KOSPI  # 코스피만
  python dmi_psar_ema_screener.py --tickers 005930,000660  # 특정 종목만 테스트
"""

import argparse
import os
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# 1. 지표 계산 함수 (외부 TA 라이브러리 없이 직접 구현 -> 계산식 눈으로 확인 가능)
# ----------------------------------------------------------------------

def calc_ema(df: pd.DataFrame, span: int, col: str = "Close") -> pd.Series:
    """지수이동평균"""
    return df[col].ewm(span=span, adjust=False).mean()


def calc_sma(df: pd.DataFrame, window: int, col: str = "Close") -> pd.Series:
    """단순이동평균 (국내 HTS 기본 이동평균선 방식)"""
    return df[col].rolling(window=window).mean()


def calc_dmi(df: pd.DataFrame, period: int = 14):
    """+DI, -DI, ADX 계산 (Wilder 방식)"""
    high, low, close = df["High"], df["Low"], df["Close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder 스무딩 = alpha=1/period 지수이동평균과 동일
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return plus_di, minus_di, adx


def calc_psar(df: pd.DataFrame, af_step: float = 0.02, af_max: float = 0.2):
    """
    Parabolic SAR 계산.
    반환: psar 값 시리즈, is_bull(그 날 추세가 상승이면 True) 불리언 시리즈
    """
    high = df["High"].values
    low = df["Low"].values
    n = len(df)

    psar = np.zeros(n)
    is_bull = np.zeros(n, dtype=bool)

    bull = True
    af = af_step
    ep = low[0]
    psar[0] = high[0]
    is_bull[0] = bull

    for i in range(1, n):
        prev_psar = psar[i - 1]

        if bull:
            psar[i] = prev_psar + af * (ep - prev_psar)
            # 상승 추세에서 SAR은 직전 1~2봉의 저점을 넘을 수 없음
            lookback_low = min(low[i - 1], low[i - 2]) if i >= 2 else low[i - 1]
            psar[i] = min(psar[i], lookback_low)

            if low[i] < psar[i]:  # 추세 반전 -> 하락
                bull = False
                psar[i] = ep
                af = af_step
                ep = low[i]
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            psar[i] = prev_psar + af * (ep - prev_psar)
            lookback_high = max(high[i - 1], high[i - 2]) if i >= 2 else high[i - 1]
            psar[i] = max(psar[i], lookback_high)

            if high[i] > psar[i]:  # 추세 반전 -> 상승
                bull = True
                psar[i] = ep
                af = af_step
                ep = high[i]
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)

        is_bull[i] = bull

    return pd.Series(psar, index=df.index), pd.Series(is_bull, index=df.index)


# ----------------------------------------------------------------------
# 2. 신호 탐지
# ----------------------------------------------------------------------

def find_signals(df: pd.DataFrame, lookback_days: int = 5,
                  ma_short: int = 5, ma_mid: int = 20,
                  ma_type: str = "sma",
                  dmi_period: int = 14):
    """
    최근 lookback_days 영업일 안에 아래 세 이벤트가 각각(순서 무관) 발생했는지 체크.
    ma_type: 'sma'(국내 HTS 기본 이동평균선, 기본값) 또는 'ema'
    반환: dict(di_cross_date, psar_flip_date, ma_cross_date) or None
    """
    if len(df) < max(ma_mid, dmi_period) + lookback_days + 5:
        return None  # 데이터 부족

    df = df.copy()
    ma_func = calc_sma if ma_type == "sma" else calc_ema
    df["MA_short"] = ma_func(df, ma_short)
    df["MA_mid"] = ma_func(df, ma_mid)
    plus_di, minus_di, adx = calc_dmi(df, dmi_period)
    psar, is_bull = calc_psar(df)

    recent = df.index[-lookback_days:]

    # 1) DI 골든크로스: +DI가 -DI를 상향 돌파한 날
    di_cross = (plus_di.shift(1) <= minus_di.shift(1)) & (plus_di > minus_di)
    di_cross_dates = df.index[di_cross.reindex(df.index, fill_value=False)]
    di_cross_dates = [d for d in di_cross_dates if d in recent]

    # 2) PSAR 하단점 전환: 하락(False) -> 상승(True) 로 바뀐 날
    psar_flip = (~is_bull.shift(1).fillna(False)) & is_bull
    psar_flip_dates = df.index[psar_flip]
    psar_flip_dates = [d for d in psar_flip_dates if d in recent]

    # 3) 이동평균 정배열 초입: 단기선이 중기선을 상향 돌파한 날 (SMA/EMA는 ma_type으로 결정)
    ma_cross = (df["MA_short"].shift(1) <= df["MA_mid"].shift(1)) & (df["MA_short"] > df["MA_mid"])
    ma_cross_dates = df.index[ma_cross]
    ma_cross_dates = [d for d in ma_cross_dates if d in recent]

    if di_cross_dates and psar_flip_dates and ma_cross_dates:
        # ---- 버그 수정: '전환이 있었다'는 사실만 보지 말고, '지금도 그 상태가
        # 유지되고 있는지'까지 확인한다. 크로스 이후 휩쏘로 이미 되돌아간 경우
        # (예: 골든크로스 후 다시 데드크로스) 를 신호에서 제외하기 위함. ----
        still_di_bullish = plus_di.iloc[-1] > minus_di.iloc[-1]
        still_psar_bullish = bool(is_bull.iloc[-1])
        still_ma_aligned = df["MA_short"].iloc[-1] > df["MA_mid"].iloc[-1]

        if not (still_di_bullish and still_psar_bullish and still_ma_aligned):
            return None

        return {
            "di_cross_date": max(di_cross_dates).strftime("%Y-%m-%d"),
            "psar_flip_date": max(psar_flip_dates).strftime("%Y-%m-%d"),
            "ma_cross_date": max(ma_cross_dates).strftime("%Y-%m-%d"),
            "adx_now": round(float(adx.iloc[-1]), 1) if not np.isnan(adx.iloc[-1]) else None,
            "close_now": int(df["Close"].iloc[-1]),
        }
    return None


# ----------------------------------------------------------------------
# 3. 유니버스 가져오기 + 스캔 실행 (실서비스용, 네트워크 필요)
# ----------------------------------------------------------------------

def get_universe(market: str):
    """
    market: 'KOSPI', 'KOSDAQ', 'ALL' -> [(ticker, name), ...]

    pykrx.stock.get_nearest_business_day_in_a_week()는 내부적으로 지수(index)
    데이터 엔드포인트를 거치는데, 이게 로그인 요구/포맷 변경 등으로 자주 깨집니다.
    그래서 그 함수는 아예 안 쓰고, 최근 며칠(최대 10일)을 하나씩 직접 시도해서
    실제로 종목 리스트가 내려오는 날짜를 찾는 방식으로 바꿨습니다.
    """
    from pykrx import stock

    markets = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]
    tickers = []

    for m in markets:
        codes = None
        for delta in range(10):  # 오늘부터 최대 10일 전까지 하나씩 시도
            d = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
            try:
                candidate = stock.get_market_ticker_list(d, market=m)
            except Exception:
                candidate = []
            if candidate:
                codes = candidate
                print(f"  {m} 종목 리스트 기준일: {d} ({len(candidate)}개)")
                break

        if not codes:
            raise RuntimeError(
                f"{m} 종목 리스트를 최근 10일치 모두 시도했지만 가져오지 못했습니다. "
                "pykrx 버전이 오래됐거나 KRX 쪽 API 변경일 수 있어요 "
                "(pip install --upgrade pykrx 로 업데이트 후 재시도 해보세요)."
            )

        for code in codes:
            try:
                name = stock.get_market_ticker_name(code)
            except Exception:
                name = code
            tickers.append((code, name))

    return tickers


def run_screen(market: str = "ALL", tickers_override=None,
               lookback_days: int = 5, days_of_history: int = 250,
               ma_type: str = "sma", sleep_sec: float = 0.05):
    import FinanceDataReader as fdr

    if tickers_override:
        # 문자열 리스트(코드만) 또는 (코드,이름) 튜플 리스트 둘 다 허용
        universe = [(t if isinstance(t, str) else t[0],
                     t if isinstance(t, str) else t[1]) for t in tickers_override]
    else:
        print(f"[1/2] {market} 종목 리스트 불러오는 중...")
        universe = get_universe(market)
        print(f"  -> 총 {len(universe)}개 종목")

    start = (datetime.now() - timedelta(days=int(days_of_history * 1.6))).strftime("%Y-%m-%d")

    results = []
    print("[2/2] 종목별 신호 스캔 중... (수천 종목이면 수십 분 걸릴 수 있습니다)")
    for i, (code, name) in enumerate(universe):
        try:
            df = fdr.DataReader(code, start)
            if df.empty:
                continue
            sig = find_signals(df, lookback_days=lookback_days, ma_type=ma_type)
            if sig:
                sig["code"] = code
                sig["name"] = name
                results.append(sig)
                print(f"  [신호 발견] {name}({code})")
        except Exception as e:
            print(f"  {name}({code}) 처리 중 오류: {e}")
        time.sleep(sleep_sec)  # 과도한 요청 방지

    return pd.DataFrame(results)


# ----------------------------------------------------------------------
# 4. 메인
# ----------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="ALL", choices=["ALL", "KOSPI", "KOSDAQ"])
    parser.add_argument("--tickers", default=None, help="콤마로 구분된 종목코드, 예: 005930,000660")
    parser.add_argument("--tickers-file", default=None,
                         help="종목코드가 한 줄에 하나씩(또는 '코드,이름' 형태로) 들어있는 텍스트/CSV 파일 경로. "
                              "예: HeroM 조건검색 결과를 저장한 파일. --tickers보다 우선 적용됨.")
    parser.add_argument("--lookback", type=int, default=5, help="신호 탐지 기간(영업일)")
    parser.add_argument("--ma-type", default="sma", choices=["sma", "ema"],
                         help="이동평균 계산 방식. 국내 HTS 기본값과 맞추려면 sma(기본값), "
                              "지수이동평균을 쓰려면 ema")
    parser.add_argument("--out", default="results/latest_signals.csv",
                         help="결과 저장 경로. 확장자가 .csv면 CSV로, 아니면 엑셀로 저장")
    args = parser.parse_args()

    if args.tickers_file:
        tickers_override = []
        with open(args.tickers_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # '005930' 또는 '005930,삼성전자' 형태 모두 허용
                parts = [p.strip() for p in line.split(",")]
                code = parts[0]
                # 엑셀에서 저장하면 앞자리 0이 날아갈 수 있으니 6자리로 보정
                code = code.zfill(6) if code.isdigit() else code
                name = parts[1] if len(parts) > 1 else code
                tickers_override.append((code, name))
        print(f"파일에서 {len(tickers_override)}개 종목코드를 읽었습니다: {args.tickers_file}")
    elif args.tickers:
        tickers_override = args.tickers.split(",")
    else:
        tickers_override = None

    df_result = run_screen(market=args.market, tickers_override=tickers_override,
                            lookback_days=args.lookback, ma_type=args.ma_type)

    ma_label = "SMA(단순)정배열초입일" if args.ma_type == "sma" else "EMA(지수)정배열초입일"
    scan_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    if df_result.empty:
        print("조건에 맞는 종목이 없습니다.")
        # 빈 결과여도 파일은 남겨서, 결과를 읽는 쪽(Streamlit 등)이 항상 최신 스캔 시각을
        # 확인할 수 있게 함
        df_result = pd.DataFrame(columns=["종목코드", "종목명", "현재가", "ADX",
                                           "PSAR전환일", "DI골든크로스일", ma_label, "스캔일시"])
    else:
        cols = ["code", "name", "close_now", "adx_now",
                "psar_flip_date", "di_cross_date", "ma_cross_date"]
        df_result = df_result[cols].rename(columns={
            "code": "종목코드", "name": "종목명", "close_now": "현재가",
            "adx_now": "ADX", "psar_flip_date": "PSAR전환일",
            "di_cross_date": "DI골든크로스일", "ma_cross_date": ma_label,
        })
        df_result["스캔일시"] = scan_date

    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if out_path.lower().endswith(".csv"):
        df_result.to_csv(out_path, index=False, encoding="utf-8-sig")
    else:
        df_result.to_excel(out_path, index=False)
    print(f"\n총 {len(df_result)}개 종목 발견 ({args.ma_type.upper()} 기준) -> {out_path} 저장 완료")
