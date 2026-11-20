"""'다른 봇의 매매를 예측해서 올라타기'가 수수료를 넘는지 검증한다.

체결 데이터에서 예측 가능한 봇 행동 4가지를 찾고, 그걸 미리/같이 탔을 때의 수익을 본다.
  1. 정각 적립봇 선행매수  : 매분 57초에 사서 0초(적립봇 매수 직후)에 판다
  2. 분할매매 봇 따라타기  : 같은 '특이한' 수량이 같은 방향으로 2분 안에 4번 이상 → 큰 주문을 쪼개는 중
                              → 그 방향으로 따라 들어가 1~30분 보유
  3. 대형 스윕 따라타기    : 상위 1% 크기로 호가를 쓸어간 주문 방향으로 진입
  4. 급등락 역추세        : 10초 안에 15bp 이상 튄 뒤 반대로 진입 (모멘텀 점화 후 되돌림 노림)

각 신호의 보유기간별 평균 수익(bp)을 왕복 비용(수수료 10bp + 스프레드·슬리피지 약 2bp)과 비교한다.

사용: python ride_bots.py --file data/ticks_KRW-BTC_72h.csv
"""
import argparse
from collections import defaultdict, deque

import numpy as np

from backtest import load_ticks
from bot_footprint import group_orders, per_second

COST_BP = 12.0
HORIZONS = (1, 3, 10, 30, 60, 300, 900, 1800)


def fwd(close, idx, k, direction):
    idx = idx[idx + k < len(close)]
    d = direction if np.isscalar(direction) else direction[: len(idx)]
    return (close[idx + k] / close[idx] - 1) * 1e4 * d


def report(name, close, idx, direction, horizons=HORIZONS):
    idx = np.asarray(idx, dtype=int)
    if np.ndim(direction):
        direction = np.asarray(direction, dtype=float)
    print(f"\n■ {name}  (신호 {len(idx):,}회)")
    best = -1e9
    row = []
    for k in horizons:
        r = fwd(close, idx, k, direction)
        if len(r) == 0:
            continue
        m = r.mean()
        best = max(best, m)
        lab = f"{k}s" if k < 60 else f"{k // 60}m"
        row.append(f"{lab}:{m:+.1f}bp({(r > 0).mean() * 100:.0f}%)")
    print("  보유기간별 평균수익(적중률): " + "  ".join(row))
    verdict = "수수료 넘음 ✅" if best > COST_BP else "수수료 못 넘음 ❌"
    print(f"  최고 {best:+.1f}bp vs 왕복비용 {COST_BP:.0f}bp → {verdict}  (순익 {best - COST_BP:+.1f}bp/회)")
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/ticks_KRW-BTC_72h.csv")
    args = ap.parse_args()

    t = np.array(load_ticks(args.file), dtype=float)
    ts, price, vol, side = t[:, 0].astype(np.int64), t[:, 1], t[:, 2], t[:, 3]
    s0, cnt, buy, sell, close, hi, lo = per_second(ts, price, vol, side)
    secs = np.arange(len(close)) + s0
    print(f"{len(ts):,}건 / {len(close) / 3600:.0f}시간.  모든 수익은 신호 방향 기준, 1bp=0.01%")

    # 1. 정각 적립봇 선행매수
    i57 = np.flatnonzero(secs % 60 == 57)
    report("정각 적립봇 선행매수 (57초 매수)", close, i57, 1, horizons=(1, 2, 3, 4, 5, 10, 30))

    # 2. 분할매매 봇
    o_ts, o_side, o_krw, o_vol, levels, _, _ = group_orders(ts, price, vol, side)
    rounded = np.round(o_vol, 8)
    roundish = (np.abs(o_vol * 1e4 - np.round(o_vol * 1e4)) < 1e-6)  # 0.0001 단위로 딱 떨어지는 '흔한' 수량 제외
    recent: dict[tuple, deque] = defaultdict(deque)
    sig_t, sig_d = [], []
    last_fire: dict[tuple, int] = {}
    for tt, sd, q, rd in zip(o_ts, o_side, rounded, roundish):
        if rd or q * price[0] < 50_000:
            continue
        key = (q, sd)
        dq = recent[key]
        dq.append(tt)
        while dq and dq[0] < tt - 120_000:
            dq.popleft()
        if len(dq) >= 4 and tt - last_fire.get(key, -10**15) > 600_000:
            last_fire[key] = tt
            sig_t.append(tt)
            sig_d.append(1 if sd == 1 else -1)
    idx = (np.array(sig_t) // 1000 - s0).astype(int)
    report("분할매매 봇 따라타기 (특이수량 2분 내 4회+)", close, idx, np.array(sig_d))

    # 3. 대형 스윕
    big = (levels >= 3) & (o_krw > np.percentile(o_krw, 99))
    idx = (o_ts[big] // 1000 - s0).astype(int)
    report("대형 스윕 따라타기 (상위 1%)", close, idx, np.where(o_side[big] == 1, 1, -1))

    # 4. 급등락 역추세
    move10 = np.zeros(len(close))
    move10[10:] = (close[10:] / close[:-10] - 1) * 1e4
    cand = np.flatnonzero(np.abs(move10) >= 15)
    keep, last = [], -10**9
    for i in cand:
        if i - last > 60:
            keep.append(i)
            last = i
    keep = np.array(keep, dtype=int)
    report("급등락 역추세 (10초 15bp+ 튄 뒤 반대로)", close, keep, -np.sign(move10[keep]))
    report("(비교) 급등락 추세추종 (같은 방향)", close, keep, np.sign(move10[keep]))

    print("\n해석:")
    print("  - 평균이 +12bp 를 넘는 칸이 있어야 '타고 먹고 빠지기'가 성립합니다.")
    print("  - 업비트는 지정가(메이커)도 수수료가 같아서, 지정가로 바꿔도 10bp 는 그대로 듭니다.")


if __name__ == "__main__":
    main()
