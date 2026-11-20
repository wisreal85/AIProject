"""저빈도(스윙) 전략 백테스트 — 한 번에 0.5~4% 를 노리고 거래 횟수를 줄인다.

틱 단타는 수수료(왕복 10bp)에 비해 움직임이 1bp 단위라 불리했다.
여기서는 5분봉 1년치로 세 가지 전략 계열을 '걸어가며 검증(walk-forward)' 한다.

  breakout  : 최근 L봉 최고가 돌파 + 거래량 증가 → 매수
  meanrev   : 볼린저 하단 이탈(과매도) → 매수, 중심선 복귀 시 매도
  trend     : 빠른 EMA 가 느린 EMA 를 상향 돌파 → 매수, 하향 돌파 시 매도
  공통 청산  : 익절 TP%, 손절 SL%, 최대 보유 봉 수

Walk-forward:
  매달, '직전 2개월'에서 가장 좋았던 설정을 골라 '다음 1개월'에 그대로 적용.
  → 미래 데이터를 보고 고른 설정이 아니므로 실전에 가까운 성적.

비용(보수적): 수수료 0.05% x2 + 슬리피지 0.02% x2,  봉 안에서 TP·SL 둘 다 닿으면 손절로 처리.

사용: python swing_backtest.py --market KRW-BTC --days 365
"""
import argparse
import csv
import itertools
import os
import time
from datetime import datetime, timezone

import numpy as np

from upbit_api import UpbitPublic

FEE = 0.0005
SLIP = 0.0002


# ---------------- 데이터 ----------------
def fetch_candles(api, market, unit, days):
    path = f"data/candles_{market}_{unit}m_{days}d.csv"
    if os.path.exists(path):
        a = np.loadtxt(path, delimiter=",", skiprows=1)
        return a
    need = days * 24 * 60 // unit
    rows, to = {}, None
    while len(rows) < need:
        data = api.candles(market, unit, 200, to)
        if not data:
            break
        for d in data:
            ts = int(datetime.strptime(d["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S")
                     .replace(tzinfo=timezone.utc).timestamp())
            rows[ts] = (ts, d["opening_price"], d["high_price"], d["low_price"], d["trade_price"],
                        d["candle_acc_trade_price"])
        to = data[-1]["candle_date_time_utc"] + "Z"
        if len(rows) % 10000 < 200:
            print(f"  ...{len(rows):,}/{need:,}봉", flush=True)
    a = np.array(sorted(rows.values()))
    os.makedirs("data", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "krw"])
        w.writerows(a.tolist())
    return a


# ---------------- 지표 ----------------
def ema(x, n):
    a = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = out[i - 1] + a * (x[i] - out[i - 1])
    return out


def rolling(x, n, fn):
    from numpy.lib.stride_tricks import sliding_window_view as swv
    out = np.full(len(x), np.nan)
    out[n - 1:] = fn(swv(x, n), axis=1)
    return out


# ---------------- 시뮬레이션 ----------------
def simulate(o, h, l, c, entry, exit_sig, tp, sl, max_hold):
    """entry[i] 가 True 면 i+1 봉 시가에 매수. 반환: (진입idx, 순수익률) 목록"""
    trades = []
    n = len(c)
    i = 0
    while i < n - 2:
        if not entry[i]:
            i += 1
            continue
        j = i + 1
        buy = o[j] * (1 + SLIP)
        tp_px, sl_px = buy * (1 + tp), buy * (1 - sl)
        sell = None
        k = j
        while k < n:
            if l[k] <= sl_px:
                sell = min(sl_px, o[k]) * (1 - SLIP)   # 갭 하락이면 시가로
                break
            if h[k] >= tp_px:
                sell = max(tp_px, o[k]) * (1 - SLIP) if k > j else tp_px * (1 - SLIP)
                break
            if k - j >= max_hold or (exit_sig is not None and exit_sig[k]):
                sell = c[k] * (1 - SLIP)
                break
            k += 1
        if sell is None:
            sell = c[-1] * (1 - SLIP)
            k = n - 1
        ret = sell * (1 - FEE) / (buy * (1 + FEE)) - 1
        trades.append((i, ret))
        i = k + 1
    return trades


def strategy_grid(o, h, l, c, v):
    """(이름, 설정, 진입신호, 청산신호, tp, sl, hold) 생성"""
    for L, vk, tp, sl, hold in itertools.product([12, 48, 144], [1.0, 2.0], [0.005, 0.01, 0.02],
                                                 [0.005, 0.01], [12, 48, 144]):
        hh = rolling(h, L, np.max)
        hh = np.r_[np.nan, hh[:-1]]               # 직전 L봉 최고가(현재봉 제외)
        vavg = np.r_[np.nan, rolling(v, L, np.mean)[:-1]]
        ent = (c > hh) & (v > vavg * vk)
        yield "breakout", f"L{L} vol{vk} tp{tp * 100:g} sl{sl * 100:g} hold{hold}", ent, None, tp, sl, hold

    for n_, k_, tp, sl, hold in itertools.product([20, 60], [2.0, 2.5, 3.0], [0.005, 0.01, 0.02],
                                                  [0.005, 0.01, 0.02], [12, 48]):
        ma = rolling(c, n_, np.mean)
        sd = rolling(c, n_, np.std)
        ent = c < ma - k_ * sd
        ex = c > ma
        yield "meanrev", f"n{n_} k{k_} tp{tp * 100:g} sl{sl * 100:g} hold{hold}", ent, ex, tp, sl, hold

    for (f, s), tp, sl, hold in itertools.product([(12, 48), (24, 96), (48, 288)], [0.01, 0.02, 0.04],
                                                  [0.005, 0.01, 0.02], [48, 288]):
        ef, es = ema(c, f), ema(c, s)
        up = ef > es
        ent = up & ~np.r_[True, up[:-1]]
        ex = ~up
        yield "trend", f"ema{f}/{s} tp{tp * 100:g} sl{sl * 100:g} hold{hold}", ent, ex, tp, sl, hold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--unit", type=int, default=5)
    ap.add_argument("--train-months", type=int, default=2)
    args = ap.parse_args()

    a = fetch_candles(UpbitPublic(), args.market, args.unit, args.days)
    ts, o, h, l, c, v = a.T
    print(f"{args.market} {args.unit}분봉 {len(c):,}개 "
          f"({datetime.fromtimestamp(ts[0], timezone.utc):%Y-%m-%d} ~ {datetime.fromtimestamp(ts[-1], timezone.utc):%Y-%m-%d})")
    print(f"비용: 수수료 {FEE * 100}%×2 + 슬리피지 {SLIP * 100}%×2 = 왕복 {(FEE + SLIP) * 200:.2f}%\n")

    t0 = time.time()
    combos = []
    for fam, name, ent, ex, tp, sl, hold in strategy_grid(o, h, l, c, v):
        ent = np.nan_to_num(ent.astype(float)).astype(bool)
        tr = simulate(o, h, l, c, ent, ex, tp, sl, hold)
        idx = np.array([t[0] for t in tr], dtype=int)
        ret = np.array([t[1] for t in tr])
        combos.append((fam, name, idx, ret))
    print(f"설정 {len(combos)}개 시뮬레이션 완료 ({time.time() - t0:.0f}s)")

    # 월 단위 구간
    month = np.array([datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m") for t in ts])
    months = sorted(set(month))
    m_of_bar = {m: i for i, m in enumerate(months)}
    bar_m = np.array([m_of_bar[m] for m in month])

    def pnl_in(idx, ret, mset):
        mask = np.isin(bar_m[idx], list(mset)) if len(idx) else np.array([], bool)
        return ret[mask].sum(), int(mask.sum()), (ret[mask] > 0).mean() if mask.any() else 0

    # ---- 전체기간 성적 (참고용: 미래를 본 결과) ----
    print("\n[참고] 전체 기간 최고 설정 (사후적으로 고른 것이라 과대평가됨)")
    for fam in ("breakout", "meanrev", "trend"):
        best = max((x for x in combos if x[0] == fam), key=lambda x: x[3].sum())
        print(f"  {fam:<9}{best[1]:<34} 거래 {len(best[3]):>4}회  누적 {best[3].sum() * 100:+7.1f}%")
    pos = sum(1 for x in combos if x[3].sum() > 0)
    print(f"  전체 {len(combos)}개 설정 중 수익 {pos}개")

    # ---- Walk-forward ----
    T = args.train_months
    print(f"\n[Walk-forward] 직전 {T}개월 최고 설정 → 다음 달 적용")
    print(f"  {'달':<8}{'선택 설정':<44}{'학습':>8}{'실전':>8}{'거래':>5}{'BTC보유':>9}")
    wf_total, wf_trades, bh_total = 0.0, 0, 0.0
    fam_totals = {f: 0.0 for f in ("breakout", "meanrev", "trend")}
    for mi in range(T, len(months)):
        train = set(range(mi - T, mi))
        scored = [(pnl_in(x[2], x[3], train)[0], x) for x in combos]
        for fam in fam_totals:
            best_f = max((s for s in scored if s[1][0] == fam), key=lambda s: s[0])[1]
            fam_totals[fam] += pnl_in(best_f[2], best_f[3], {mi})[0]
        tr_score, best = max(scored, key=lambda s: s[0])
        te, n, _ = pnl_in(best[2], best[3], {mi})
        bars = np.flatnonzero(bar_m == mi)
        bh = c[bars[-1]] / o[bars[0]] - 1
        wf_total += te
        wf_trades += n
        bh_total += bh
        print(f"  {months[mi]:<8}{best[0] + ' ' + best[1]:<44}{tr_score * 100:>+7.1f}%{te * 100:>+7.1f}%{n:>5}{bh * 100:>+8.1f}%")
    print(f"\n  Walk-forward 누적: {wf_total * 100:+.1f}% ({wf_trades}회)   같은 기간 BTC 그냥 보유(월별 합): {bh_total * 100:+.1f}%")
    print("  계열별 walk-forward 누적: " + ", ".join(f"{k} {v * 100:+.1f}%" for k, v in fam_totals.items()))
    print("  → '학습'은 좋은데 '실전'이 무너지면 과최적화. 실전 누적이 플러스이고 보유보다 나아야 의미가 있습니다.")


if __name__ == "__main__":
    main()
