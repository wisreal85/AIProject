# 업비트 흐름 단타 – 조회 / 백테스트 / 모의매매

**실제 주문 기능은 없습니다.** 시세 조회와 가상 매매만 하므로 API 키가 필요 없고 돈이 나가지 않습니다.

## 설치
```bash
cd upbit-bot
pip install -r requirements.txt
```

## 1. 종목 스캔 – 어떤 종목이 단타에 유리한가
```bash
python scan.py --top 15
```
거래대금 상위 종목의 **스프레드 + 왕복 수수료(0.10%)** 를 보여줍니다.
익절 목표는 이 '왕복비용%'보다 충분히 커야 합니다. 보통 BTC가 가장 유리합니다.

## 2. 백테스트 – 과거 체결 데이터로 돌려보기
```bash
python backtest.py --market KRW-BTC --hours 24          # 최근 24시간 (최대 7일 = 168)
python backtest.py --market KRW-BTC --hours 72 --grid   # 파라미터 조합 + 과최적화 점검
python backtest.py --take-profit 0.6 --stop-loss 0.6 --no-flow-exit --max-daily-loss 1e9
```
- 처음 실행하면 체결 데이터를 받아 `data/` 에 저장합니다(24시간에 약 1~2분).
- 체결 가정: 매수는 매도호가, 매도는 매수호가, 판단 후 200ms 지연, 수수료 0.05%×2.
- 마지막에 **"수수료·스프레드가 0이었다면"** 의 결과를 같이 보여줘서, 비용이 결과를 얼마나 바꾸는지 비교할 수 있습니다.
- `--grid` 는 앞 절반에서 가장 좋았던 설정이 뒤 절반에서도 통하는지 봅니다. 뒤에서 무너지면 과최적화입니다.

## 3. 실시간 모의매매 – 지금 시장에서 가상으로
```bash
python paper.py --market KRW-BTC               # Ctrl+C 로 종료하면 결과 요약
python paper.py --market KRW-BTC --minutes 60 --order-krw 10000 --max-daily-loss 2000
```
- 웹소켓 구독 1회로 체결·호가를 받습니다. REST 를 반복 호출하지 않으므로 예전처럼 밴을 먹지 않습니다.
- 매매 내역은 `logs/paper_*.csv` 에 남습니다.
- 일일 손실 한도에 닿으면 알림을 띄우고 거래를 멈춥니다.
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 환경변수를 넣으면 텔레그램으로도 알림을 보냅니다.

## 4. 다른 봇의 흔적 분석 + 위험 신호 검증
```bash
python bot_footprint.py --file data/ticks_KRW-BTC_72h.csv
python backtest.py --hours 72 --risk-filter   # 위험 신호 구간 진입 금지 적용
```
| 분석 | 무엇을 보나 |
|---|---|
| 주문 크기 지문 | 같은 수량·딱 떨어지는 원화금액 반복 → 고정금액 봇, 분할매매 봇 |
| 시간 지문 | 매분 0초 등 특정 시각 몰림 → 적립식/스케줄 봇 |
| 스윕·버스트 | 여러 호가를 한 번에 쓸어가는 주문, 체결 폭주 → 그 뒤 가격이 이어지나 되돌리나 |
| 흐름 과열 이후 | 매수세가 강할 때 들어가면 실제로 수수료(10bp) 이상 오르나 |
| 위험 신호 Lift | 각 신호가 '향후 60초 급변동' 확률을 평소의 몇 배로 올리나 |

## 5. 저빈도(스윙) 전략 – 5분봉 1년, walk-forward
```bash
python swing_backtest.py --market KRW-BTC --days 365
```
돌파 / 평균회귀 / 추세 3계열 270개 설정. 매달 '직전 2개월 최고 설정'을 다음 달에 적용해 실전에 가깝게 검증합니다.

## 6. 봇 따라타기 검증
```bash
python ride_bots.py --file data/ticks_KRW-BTC_72h.csv
```
정각 적립봇 선행매수 / 분할매매 봇 따라타기 / 대형 스윕 따라타기 / 급등락 역추세 — 보유기간별 평균수익을 왕복비용(12bp)과 비교.

## 7. 실시간 호가 위험 모니터
```bash
python risk_monitor.py --market KRW-BTC --minutes 30 --record
```
스프레드 확대, 유동성 이탈, 호가 불균형, 대형벽 등장·스푸핑 의심(체결 없이 취소된 벽), 업비트 공식 유의/주의 플래그.
`--record` 로 호가·체결을 저장해 두면 나중에 호가 기반 백테스트가 가능합니다.

## 전략 규칙 (`strategy.py` 의 `Params`)
| 항목 | 기본값 | 의미 |
|---|---|---|
| flow_window_sec | 60 | 흐름 계산 구간. flow = (매수체결금액 − 매도체결금액) / 전체 |
| entry_flow | 0.30 | 매수세가 이 이상이고 30초 EMA > 180초 EMA 이면 진입 |
| take_profit_pct | 0.30 | 수수료 차감 후 순수익 %에서 익절 |
| stop_loss_pct | 0.30 | 수수료 차감 후 순손실 %에서 손절 |
| exit_on_flow | True | 흐름이 꺾이면(flow ≤ −0.2 또는 EMA 역전) 즉시 청산 |
| cooldown_sec | 30 | 청산 후 재진입 대기 |
| max_spread_pct | 0.10 | 스프레드가 넓으면 진입 안 함 |
| max_daily_loss_krw | 2000 | 하루(KST) 손실 한도 → 알림 후 중단 |
| order_krw | 10000 | 1회 매수 금액 |
| vol_filter | False | 최근 60초 변동폭이 최근 30분 중 상위 10%면 진입 금지 |
| avoid_minute_open | False | 매분 58~02초(적립식 봇 몰림) 진입 금지 |

## API 호출 제한 대응 (`upbit_api.py`)
- 초당 8회 토큰 버킷 (업비트 시세 API 제한은 그룹별 초당 10회)
- 응답 헤더 `Remaining-Req` 의 남은 횟수가 1 이하이면 1초 쉬기
- 429 응답은 지수 백오프로 재시도, 418(일시 차단)은 즉시 중단

## 실전으로 가기 전 체크리스트
1. 여러 날(최대 7일) 백테스트에서 **수수료 포함 순손익이 플러스**인가?
2. `--grid` 에서 **앞 절반 1등 설정이 뒤 절반에서도 플러스**인가?
3. 실시간 모의매매를 며칠 돌렸을 때 백테스트와 결과가 비슷한가?

셋 다 통과하지 못하면 실전 주문 기능은 붙이지 않는 것을 권합니다.
