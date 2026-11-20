"""과거 체결 데이터로 전략을 돌려본다(백테스트).

사용:
  python backtest.py --market KRW-BTC --hours 24            # 데이터 없으면 자동으로 받음
  python backtest.py --market KRW-BTC --hours 24 --grid     # 파라미터 여러 조합 + 과최적화 점검

체결 가정(보수적):
- 매수는 매도호가(ask), 매도는 매수호가(bid)에 시장가 체결
- 과거 틱에는 호가가 없으므로 '현재 호가의 스프레드'를 기준으로 bid/ask 를 추정
- 판단 후 latency_ms(기본 200ms) 뒤의 가격으로 체결
- 수수료 0.05% x 2
"""
import argparse
import csv
import itertools
import os
import time

from fetch_ticks import fetch
from strategy import Engine, FlowStrategy, Params, print_summary, summarize
from upbit_api import UpbitPublic, spread_pct


def load_ticks(path):
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        return [(int(a), float(b), float(c), d == "1") for a, b, c, d in r]


def run(ticks, p: Params, half_spread: float, fee_rate: float):
    s = FlowStrategy(p)
    e = Engine(p, s, notify=lambda msg: None, fee_rate=fee_rate)
    for ts, price, vol, is_buy in ticks:
        s.on_trade(ts, price, vol, is_buy)
        e.step(ts, price * (1 - half_spread), price * (1 + half_spread))
    last_ts, last_price = ticks[-1][0], ticks[-1][1]
    e.force_close(last_ts, last_price * (1 - half_spread))
    hours = (ticks[-1][0] - ticks[0][0]) / 3.6e6
    out = summarize(e.trades, p, hours)
    out["blocked"] = e.blocked
    out["halts"] = sum(1 for v in e.daily_pnl.values() if v <= -p.max_daily_loss_krw)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--file", help="직접 지정한 틱 CSV")
    ap.add_argument("--half-spread-pct", type=float, help="스프레드 절반(%). 생략 시 현재 호가로 추정")
    ap.add_argument("--fee-pct", type=float, default=0.05)
    ap.add_argument("--take-profit", type=float)
    ap.add_argument("--stop-loss", type=float)
    ap.add_argument("--entry-flow", type=float)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--no-flow-exit", action="store_true", help="흐름전환 청산 끄기(익절/손절만)")
    ap.add_argument("--max-daily-loss", type=float)
    ap.add_argument("--risk-filter", action="store_true", help="고변동성·정각 구간 진입 금지")
    args = ap.parse_args()

    api = UpbitPublic()
    path = args.file or f"data/ticks_{args.market}_{args.hours:g}h.csv"
    if not os.path.exists(path):
        print(f"{path} 없음 → 업비트에서 {args.hours:g}시간치 체결 데이터를 받습니다")
        rows = fetch(api, args.market, args.hours)
        os.makedirs("data", exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "price", "volume", "is_buy"])
            w.writerows(rows)
    ticks = load_ticks(path)
    print(f"틱 {len(ticks):,}건 로드 ({path})")

    if args.half_spread_pct is None:
        samples = []
        for _ in range(9):  # 순간값에 휘둘리지 않게 여러 번 찍어서 중앙값
            samples.append(spread_pct(api.orderbooks([args.market])[0])[2])
            time.sleep(0.5)
        sp = sorted(samples)[len(samples) // 2]
        half = sp / 2 / 100
        print(f"현재 스프레드(중앙값) {sp:.4f}% → 체결 가정: 한쪽당 {sp / 2:.4f}% 불리하게")
    else:
        half = args.half_spread_pct / 100
    fee = args.fee_pct / 100

    p = Params()
    if args.take_profit is not None:
        p.take_profit_pct = args.take_profit
    if args.stop_loss is not None:
        p.stop_loss_pct = args.stop_loss
    if args.entry_flow is not None:
        p.entry_flow = args.entry_flow
    if args.no_flow_exit:
        p.exit_on_flow = False
    if args.max_daily_loss is not None:
        p.max_daily_loss_krw = args.max_daily_loss
    if args.risk_filter:
        p.vol_filter = p.avoid_minute_open = True

    if not args.grid:
        res = run(ticks, p, half, fee)
        print_summary(res, f"{args.market} 백테스트 (수수료 {args.fee_pct}%)")
        if res["blocked"]:
            print("위험 필터가 막은 진입: " + ", ".join(f"{k} {v}회" for k, v in res["blocked"].items()))
        zero = run(ticks, p, 0.0, 0.0)
        print(f"\n[비교] 수수료·스프레드 0 이었다면 순손익: {zero['net_pnl']:+,.1f}원 "
              f"→ 비용이 결과를 얼마나 바꾸는지 보세요")
        return

    # ---- 파라미터 조합 탐색 + 앞/뒤 절반 검증 ----
    mid = len(ticks) // 2
    first, second = ticks[:mid], ticks[mid:]
    grid = {
        "take_profit_pct": [0.2, 0.3, 0.5, 0.8],
        "stop_loss_pct": [0.2, 0.4, 0.8],
        "entry_flow": [0.2, 0.4, 0.6],
    }
    results = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        q = Params(**{**p.__dict__, **dict(zip(keys, combo))})
        a = run(first, q, half, fee)
        b = run(second, q, half, fee)
        results.append((combo, a, b))
    results.sort(key=lambda x: x[1]["net_pnl"], reverse=True)

    print(f"\n조합 {len(results)}개.  [앞 절반에서의 성적] → [뒤 절반에서 같은 설정의 성적]")
    print(f"{'익절%':>6}{'손절%':>6}{'진입flow':>9} | {'거래':>5}{'승률':>7}{'순손익':>10} | {'거래':>5}{'승률':>7}{'순손익':>10}")
    for i, (combo, a, b) in enumerate(results[:10] + results[-3:]):
        if i == 10:
            print("   ... (하위 3개)")
        print(f"{combo[0]:>6}{combo[1]:>6}{combo[2]:>9} | {a['trades']:>5}{a['win_rate']:>6.0f}%{a['net_pnl']:>+10,.0f} |"
              f" {b['trades']:>5}{b['win_rate']:>6.0f}%{b['net_pnl']:>+10,.0f}")
    pos_a = sum(1 for _, a, _ in results if a["net_pnl"] > 0)
    pos_b = sum(1 for _, _, b in results if b["net_pnl"] > 0)
    best = results[0]
    print(f"\n앞 절반 수익 조합: {pos_a}/{len(results)},  뒤 절반 수익 조합: {pos_b}/{len(results)}")
    print(f"앞 절반 1등 조합의 뒤 절반 성적: {best[2]['net_pnl']:+,.0f}원")
    print("→ 앞에서 좋았던 설정이 뒤에서도 좋아야 '진짜 엣지'일 가능성이 있습니다. 뒤에서 무너지면 과최적화입니다.")


if __name__ == "__main__":
    main()
