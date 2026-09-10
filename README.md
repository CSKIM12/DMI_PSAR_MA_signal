# DMI + PSAR + SMA 신호 스크리너

DI 골든크로스 + PSAR 하단점 전환 + 이동평균(SMA) 정배열 초입, 세 조건이
함께 나타난 종목을 코스피/코스닥 전체에서 찾아주는 스크리너입니다.

- `scripts/naver_export_tickers.py` — 네이버 증권에서 종목 리스트(+시가총액) 수집
- `scripts/dmi_psar_ema_screener.py` — 실제 신호 탐지 및 결과 저장
- `.github/workflows/daily_scan.yml` — 매일 자동 실행 + 결과 커밋
- `streamlit_app.py` — 결과를 표/차트로 보여주는 대시보드

## 설정 방법 (최초 1회)

### 1. 이 폴더를 GitHub 저장소로 올리기

```bash
cd (이 폴더)
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<본인계정>/<저장소이름>.git
git push -u origin main
```

(GitHub 웹사이트에서 먼저 빈 저장소를 하나 만들어두세요. Public/Private 아무거나 상관없습니다.)

### 2. GitHub Actions 자동 실행 확인

- 저장소의 **Actions** 탭 → `Daily DMI+PSAR+SMA Scan` 워크플로우 확인
- 평일 한국시간 16:30에 자동 실행되지만, 바로 확인해보고 싶으면
  Actions 탭 → 해당 워크플로우 → **Run workflow** 버튼으로 즉시 실행 가능
- 처음 실행은 전종목(약 2,500개 중 시총 3,000억 이상) 스캔이라 **몇십 분 걸릴 수 있습니다**
- 끝나면 `results/latest_signals.csv` 파일이 자동으로 커밋됩니다

### 3. Streamlit 대시보드 배포

1. https://share.streamlit.io 접속 후 GitHub 계정으로 로그인
2. "New app" → 방금 만든 저장소 선택
3. Main file path: `streamlit_app.py` 입력 후 배포
4. 몇 분 후 `https://<앱이름>.streamlit.app` 같은 주소가 생성됨 — 이 링크를 북마크해두면 언제든 브라우저로 결과 확인 가능

배포 후에는 GitHub Actions가 매일 결과를 갱신할 때마다 Streamlit 앱도
자동으로 최신 데이터를 반영합니다 (별도 재배포 불필요).

## 파라미터 조정

`.github/workflows/daily_scan.yml` 안의 명령어에서 값을 바꿀 수 있습니다:

- `--min-cap 3000` : 최소 시가총액(억원). 낮추면 더 많은 종목 스캔 (시간 ↑)
- `--lookback 5` (스크리너 실행 명령에 추가 가능) : 신호 탐지 기간(영업일)
- `--ma-type sma` : 이동평균 종류 (`sma` 국내 HTS 기본값 / `ema` 지수이동평균)

## 로컬에서 직접 테스트하고 싶을 때

```bash
pip install -r requirements.txt
python scripts/naver_export_tickers.py --min-cap 3000 --out tickers_full.txt
python scripts/dmi_psar_ema_screener.py --tickers-file tickers_full.txt
streamlit run streamlit_app.py
```
