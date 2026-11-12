Whale50 V4 | 2026-11-12

기능: 유명 운용사 50곳 SEC 13F 추정 매수금액 TOP 20에 대해,
바이낸스가 실제로 제공하는 미국 주식 연계 무기한 선물의 공개 캔들로
15m/30m/1h/4h/1d/1w/1M 일목균형표 및 롱/숏 방향 점수를 분석합니다.

미국 주식 직접 매매와 다릅니다: 주식 무기한 선물은 주식을 소유하지 않으며
펀딩비, 청산 및 주식시장 폐장 중 가격 괴리 위험이 있습니다.
롱/숏 퍼센트는 검증된 확률이 아닌 상대 지표 점수입니다.
주봉 및 월봉은 상장 이력이 짧아 '자료 부족'이라고 표시될 수 있습니다.
지역별 Binance 기능 제한 및 API 접속 제한이 있을 수 있습니다.

안전: 계정, API 키, 실거래 주문 기능 없음. 공개 조회(GET)만 수행합니다.
구글·마이크로소프트 등 주식 연계 선물의 실제 존재 여부는 실행시
Binance exchangeInfo에서 status=TRADING으로 확인한 후에만 조회합니다.

GitHub 저장소 기존 파일의 백업(특히 data/)을 먼저 만들어 놓고
새 패키지의 .github/workflows/whale50-cloud.yml 파일과
cloud_run.py, whale50.py, whale50_signals.py, whale50_validation.py,
whale50_binance.py, dashboard.html 등을 최상위에 업데이트하세요.
GitHub Pages는 site/ 폴더 내용을 Actions가 다시 생성하므로
site/index.html을 수동으로 건드릴 필요가 없습니다.
기존 data/whale50.sqlite3는 반드시 보존하세요.
실행 전/후 Actions 로그에서 시세 조회 오류 여부를 검증하세요.
기존 Yahoo 데이터와 예측은 지우지 않고 별도 BINEQ: 키로 저장합니다.
13F 매수 순위는 분기말 수량 차이의 추정 가치이며 당일 매수내역이 아닙니다.

스케줄: 매일 15분 간격 시도. GitHub Actions 예약 작업은 지연/누락 가능.
직접 주식과 다른 24/7 선물 시세는 미국 주식장이 닫힌 동안 괴리가 발생할 수 있음.
