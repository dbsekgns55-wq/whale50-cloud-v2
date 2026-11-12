Whale50 V4.3 TradingView 공식 차트 탭 추가
============================================

변경된 파일: dashboard.html, site/index.html
기존 Whale50 V4.1 기반 · Python, SEC/시장수집, SQLite, 백테스트 데이터는 변경하지 않습니다.

[PC 설치형]
1. Whale50 프로그램을 종료합니다.
2. 업데이트 ZIP의 dashboard.html 파일만 기존 Whale50 프로그램 폴더에 덮어씁니다.
3. 실행_Whale50.cmd를 다시 실행합니다.
4. 상단의 'TOP 20 트레이딩뷰 차트' 탭을 엽니다.

[GitHub 클라우드]
1. GitHub whale50-cloud 저장소 최상위의 dashboard.html 파일을 새 파일로 교체합니다.
2. site/index.html도 새 파일로 교체하면 즉시 차트 코드가 게시 대상에 포함됩니다.
   (site/index.html 업로드가 어렵다면 dashboard.html만 교체하고 Actions를 새로 실행해도 됩니다.)
3. 이미 설정한 .github/workflows/whale50-cloud.yml 은 변경하지 마세요.
4. Actions > Whale50 Cloud Collector and Website > Run workflow로 새 작업을 실행합니다.
5. Deploy website까지 성공한 후 기존 주소에서 Ctrl+F5로 새로고침합니다.
   https://dbsekgns55-wq.github.io/whale50-cloud/

[차트 기능]
- 매수 규모 TOP20 기업 목록(ETF 제외)에서 종목 선택
- 15분, 30분, 1시간, 4시간, 일봉, 주봉, 월봉 선택
- 트레이딩뷰 공식 Advanced Chart 위젯
- 위젯에 기본 일목균형표 및 RSI 표시 요청 (TradingView의 정책/기능에 따라 표시 안 될 수 있음)
- TradingView에서 크게 보기 외부 링크
- 매수 TOP 순위 행의 '차트' 버튼으로 바로 이동

[중요 사항]
- 트레이딩뷰 위젯은 차트 표시 전용이고 Whale50 롱/숏 점수 계산 및 백테스트용 API가 아닙니다.
- 위젯 로딩은 TradingView 서버 접속 여부와 브라우저 설정에 따라 달라집니다.
- 차트 시세 지연 여부, 야간·장외 거래 지원 여부는 거래소/상품/계정에 따라 다릅니다.
- 미국 주식의 주말 24/7 거래는 보장되지 않습니다.
- API 지역 제한 HTTP 451을 우회하는 기능은 없습니다.
- 이 업데이트는 데이터베이스(data/whale50.sqlite3), SEC 수집 기능, 예측 기록을 수정하지 않습니다.
