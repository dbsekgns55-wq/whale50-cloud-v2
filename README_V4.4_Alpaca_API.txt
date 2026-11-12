Whale50 V4.4 Alpaca FREE IEX 시세 연결
===================================
이번 버전은 Alpaca가 공식 제공하는 미국 주식 과거 봉 API(v2/stocks/{symbol}/bars)를 이용합니다.
기존 Whale50 투자 거물 TOP20 / TradingView 차트 / 기존 데이터는 유지합니다.

[핵심 구분]
* 무료 Alpaca Basic은 IEX 거래소 시세로 제한됩니다. 미국 전체 시장의 실시간 거래량이 아닙니다.
* 미국 주식의 완전한 24/7 거래 또는 24/5 야간 데이터가 보장되지 않습니다.
* 연장 거래시간 중 IEX에 체결이 없으면 봉이 비어 있을 수 있습니다.
* API 키는 공시/시세 조회용입니다. Whale50에 주문 기능은 없습니다.
* 예측 점수는 실제 상승/하락 확률이나 검증된 수익률이 아닙니다.

[GitHub 클라우드 업데이트]
1. GitHub 저장소 최상위에 whale50.py, whale50_alpaca.py, dashboard.html을 업로드/덮어쓰기.
2. 기존 site/index.html도 바꾸려면 site/ 하위에 업로드할 수 있습니다. 업데이트 뒤 Actions 실행 시 자동 생성됩니다.
3. Settings > Secrets and variables > Actions > New repository secret 에 각각 등록:
   WHALE50_ALPACA_KEY_ID       = Alpaca API Key ID
   WHALE50_ALPACA_SECRET_KEY   = Alpaca Secret Key
   (기존 WHALE50_SEC_EMAIL은 보존)
4. .github/workflows/whale50-cloud.yml 을 브라우저의 연필 편집에서 열고
   GitHub_워크플로_수정_v4.4.txt 내용으로 바꾼 뒤 Commit changes.
5. Actions > Whale50 Cloud Collector and Website > Run workflow. collect-publish 성공 확인.
6. 기존 주소 https://dbsekgns55-wq.github.io/whale50-cloud/ 에서 Ctrl+F5.
7. 화면의 `Alpaca IEX ...` 출처를 확인. 401/403 오류가 나면 API 키 권한 확인.

[Windows 설치형]
1. 기존 Whale50 폴더에 whale50.py, whale50_alpaca.py, dashboard.html,
   alpaca_setup.py, Alpaca_API_설정.cmd 파일을 덮어쓰기/복사.
2. Alpaca_API_설정.cmd 실행 -> Alpaca Key ID / Secret Key 입력.
3. 실행_Whale50.cmd 실행 -> TOP 20 롱숏 탭에서 새로고침.
4. 로컬 data/alpaca_private.json 파일은 절대로 GitHub에 업로드하지 말 것.

[데이터 분리]
ALPACA_IEX:TICKER / ALPACA_SIP:TICKER / STOCK:TICKER / BINEQ:TICKER
각 데이터는 독립적으로 쌓이고 이전 데이터도 삭제하지 않습니다.
Alpaca API 키 없이 auto 모드라면 Yahoo 주식 시세를 그대로 사용합니다.
미국 주식 4시간봉은 Alpaca API의 4Hour 봉입니다. 바이낸스 4시간봉과 정확히 같은 구간이 아닙니다.

[실행 전]
실제 키를 갖고 있는 계정으로 Alpaca API 접근, GitHub Secrets, GitHub Actions 실행까지는 사용자가 설정하고 확인해야 합니다.
