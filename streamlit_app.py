# -*- coding: utf-8 -*-
"""
DMI + PSAR + SMA 신호 스크리너 결과를 보여주는 Streamlit 대시보드.

이 앱은 스캔을 직접 돌리지 않습니다 — GitHub Actions가 매일 자동으로 돌려서
results/latest_signals.csv 에 저장해둔 결과를 읽어서 보여주기만 합니다.
(무거운 전종목 스캔을 브라우저 세션에서 직접 돌리면 느리고 타임아웃 나기 쉬워서
 분리했습니다.)

로컬 실행: streamlit run streamlit_app.py
배포: share.streamlit.io 에서 이 저장소 연결하면 자동 배포
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

RESULTS_PATH = "results/latest_signals.csv"

st.set_page_config(page_title="DMI+PSAR+SMA 스크리너", layout="wide")

st.title("📈 DMI + PSAR + SMA 신호 스크리너")
st.caption("DI 골든크로스 · PSAR 하단점 전환 · 이동평균 정배열 초입 — 세 조건이 함께 나타난 종목")

if not os.path.exists(RESULTS_PATH):
    st.warning(
        "아직 스캔 결과 파일이 없습니다. GitHub Actions의 'Daily DMI+PSAR+SMA Scan' "
        "워크플로우가 최소 한 번 실행된 뒤에 결과가 나타납니다. "
        "Actions 탭에서 수동으로(workflow_dispatch) 한 번 실행해보세요."
    )
    st.stop()

df = pd.read_csv(RESULTS_PATH)

# ---- 상단 요약 ----
scan_time = df["스캔일시"].iloc[0] if (not df.empty and "스캔일시" in df.columns) else None
mtime = datetime.fromtimestamp(os.path.getmtime(RESULTS_PATH)).strftime("%Y-%m-%d %H:%M")

col1, col2, col3 = st.columns(3)
col1.metric("신호 발생 종목 수", len(df))
col2.metric("스캔 실행 시각", scan_time or "-")
col3.metric("파일 갱신 시각", mtime)

st.divider()

if df.empty:
    st.info("현재 조건을 만족하는 종목이 없습니다. 조건이 너무 엄격하면 스크립트의 "
            "`--lookback` 값을 늘리거나 `--min-cap` 값을 낮춰보세요.")
    st.stop()

# ---- 필터 ----
with st.sidebar:
    st.header("필터")
    name_filter = st.text_input("종목명 검색", "")
    min_adx = st.slider("최소 ADX (추세 강도)", 0, 60, 0,
                         help="ADX가 낮으면 추세가 약한(횡보) 상태에서 나온 신호일 수 있습니다.")

filtered = df.copy()
if name_filter:
    filtered = filtered[filtered["종목명"].astype(str).str.contains(name_filter, case=False, na=False)]
if "ADX" in filtered.columns:
    filtered = filtered[filtered["ADX"].fillna(0) >= min_adx]

st.subheader(f"신호 종목 목록 ({len(filtered)}개)")
st.dataframe(filtered, use_container_width=True, hide_index=True)

# ---- 차트: ADX 분포 (추세 강도가 센 순으로) ----
if "ADX" in filtered.columns and not filtered.empty:
    st.subheader("종목별 ADX (추세 강도)")
    chart_df = filtered[["종목명", "ADX"]].dropna().sort_values("ADX", ascending=False).set_index("종목명")
    st.bar_chart(chart_df)

with st.expander("지표 설명 (DMI / PSAR / SMA 정배열이 뭔가요?)"):
    st.markdown(
        """
- **DI 골든크로스**: +DI(매수 압력)가 -DI(매도 압력)를 상향 돌파한 날
- **PSAR 전환**: 추세추종 지표인 Parabolic SAR의 점이 캔들 위(하락)에서 아래(상승)로 옮겨온 날
- **SMA 정배열 초입**: 단기 이동평균(5일)이 중기 이동평균(20일)을 상향 돌파한 날
- 세 조건 모두 **최근 며칠(lookback) 안에 발생 + 현재도 그 상태가 유지 중**이어야 신호로 잡힙니다.
- **ADX**는 방향과 무관하게 추세의 강도만 나타내는 지표로, 20 이하면 횡보, 25 이상이면 뚜렷한 추세로 봅니다.
        """
    )
