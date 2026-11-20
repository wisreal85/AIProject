"""다른 자동매매 봇의 '흔적'을 체결 데이터에서 찾고, 위험 신호가 실제로 예측력이 있는지 검증한다.

개별 계좌는 볼 수 없으므로 '누가'가 아니라 '어떤 패턴'인지를 본다.
  1. 주문 크기 지문  - 같은 수량/딱 떨어지는 원화금액 반복 → 고정금액 봇, 분할매매(TWAP/아이스버그)
  2. 시간 지문      - 매분 0초 등 특정 시각에 몰림 → 스케줄(크론) 봇, 적립식 봇
  3. 스윕          - 한 주문이 여러 호가를 한 번에 쓸고 감 → 공격적 시장가(청산/모멘텀 봇)
  4. 버스트        - 1초 체결 수가 평소의 수 배 → 봇들이 동시에 반응하는 구간
  5. 흐름 과열 이후 - 우리 전략의 진입 신호(매수세 강함) 뒤에 실제로 오르는가
  6. 위험 신호 Lift - 각 신호가 '향후 60초 급변동' 확률을 평소보다 몇 배 높이는가

사용: python bot_footprint.py --file data/ticks_KRW-BTC_72h.csv
"""
import argparse
from collections import Counter

import numpy as np

from backtest import load_ticks


def group_orders(ts, price, vol, side):
    """같은 ms·같은 방향 체결 = 한 테이커 주문으로 근사"""
    key_change = np.r_[True, (ts[1:] != ts[:-1]) | (side[1:] != side[:-1])]
    gid = np.cumsum(key_change) - 1
    n = gid[-1] + 1
    krw = np.bincount(gid, price * vol, n)
    first = np.flatnonzero(key_change)
    o_ts, o_side = ts[first], side[first]
    o_pmin = np.minimum.reduceat(price, first)
    o_pmax = np.maximum.reduceat(price, first)
    levels = np.array([len(set(price[a:b])) for a, b in zip(first, np.r_[first[1:], len(ts)])])
    o_vol = np.add.reduceat(vol, first)
    return o_ts, o_side, krw, o_vol, levels, o_pmin, o_pmax


def per_second(ts, price, vol, side):
    sec = (ts // 1000).astype(np.int64)
    s0 = sec[0]
    idx = sec - s0
    n = idx[-1] + 1
    cnt = np.bincount(idx, minlength=n)
    krw = price * vol
    buy = np.bincount(idx, krw * side, n)
    sell = np.bincount(idx, krw * (1 - side), n)
    close = np.full(n, np.nan)
    close[idx] = price  # 같은 초의 마지막 값이 남는다
    hi = np.full(n, -np.inf)
    lo = np.full(n, np.inf)
    np.maximum.at(hi, idx, price)
    np.minimum.at(lo, idx, price)
    # 체결 없는 초는 직전 가격으로 채움
    mask = np.isnan(close)
    last = np.maximum.accumulate(np.where(~mask, np.arange(n), 0))
    close = close[last]
    hi = np.where(np.isinf(hi), close, hi)
    lo = np.where(np.isinf(lo), close, lo)
    return s0, cnt, buy, sell, close, hi, lo


def rolling_sum(x, w):
    c = np.r_[0, np.cumsum(x)]
    out = np.zeros_like(x, dtype=float)
    out[w - 1:] = c[w:] - c[:-w]
    out[:w - 1] = c[1:w]
    return out


def fwd_return(close, k):
    r = np.full(len(close), np.nan)
    r[:-k] = close[k:] / close[:-k] - 1
    return r


def fwd_range(hi, lo, close, k):
    from numpy.lib.stride_tricks import sliding_window_view as swv
    r = np.full(len(close), np.nan)
    mx = swv(hi[1:], k).max(axis=1)
    mn = swv(lo[1:], k).min(axis=1)
    m = len(mx)
    r[:m] = (mx - mn) / close[:m]
    return r


def bps(x):
    return f"{np.nanmean(x) * 1e4:+.2f}bp"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/ticks_KRW-BTC_72h.csv")
    ap.add_argument("--horizon", type=int, default=60, help="예측 구간(초)")
    args = ap.parse_args()
    H = args.horizon

    t = np.array(load_ticks(args.file), dtype=float)
    ts, price, vol, side = t[:, 0].astype(np.int64), t[:, 1], t[:, 2], t[:, 3]
    hours = (ts[-1] - ts[0]) / 3.6e6
    print(f"체결 {len(ts):,}건, {hours:.1f}시간\n  (1bp = 0.01%, 왕복 수수료 0.10% = 10bp)")

    # ---------- 1. 주문 크기 지문 ----------
    o_ts, o_side, o_krw, o_vol, levels, pmin, pmax = group_orders(ts, price, vol, side)
    print(f"\n[1] 주문 크기 지문  (테이커 주문 추정 {len(o_ts):,}건)")
    common = Counter(np.round(o_vol, 8)).most_common(8)
    print("  가장 자주 반복된 수량:")
    for v, c in common:
        print(f"    {v:.8f} BTC  ≈ {v * np.median(price):>10,.0f}원  × {c:,}회")
    rounds = [5_000, 10_000, 20_000, 30_000, 50_000, 100_000, 200_000, 500_000, 1_000_000]
    hit = np.zeros(len(o_krw), bool)
    for r in rounds:
        hit |= np.abs(o_krw - r) / r < 0.002
    print(f"  딱 떨어지는 원화금액(5천·1만·5만·10만원 등 ±0.2%) 주문: {hit.mean() * 100:.1f}%"
          f"  → 고정금액으로 사는 봇/앱 적립식의 흔적")
    small = (o_krw < 20_000).mean() * 100
    print(f"  2만원 미만 소액 주문 비율: {small:.1f}%")

    # ---------- 2. 시간 지문 ----------
    sec_of_min = (o_ts // 1000) % 60
    hist = np.bincount(sec_of_min, minlength=60)
    print("\n[2] 시간 지문  (주문이 몰리는 '초')")
    top = np.argsort(hist)[::-1][:5]
    print("  " + ", ".join(f"{s}초: 평균의 {hist[s] / hist.mean():.2f}배" for s in top))
    min_of_hour = ((o_ts // 60000) % 60)
    mh = np.bincount(min_of_hour, minlength=60)
    print(f"  매시 정각(00분) 주문량: 평균의 {mh[0] / mh.mean():.2f}배,  30분: {mh[30] / mh.mean():.2f}배"
          "  → 1배보다 크면 스케줄 봇이 존재")

    # ---------- 초 단위 시계열 ----------
    s0, cnt, buy, sell, close, hi, lo = per_second(ts, price, vol, side)
    n = len(cnt)
    fr = fwd_return(close, H)
    rng = fwd_range(hi, lo, close, H)

    # ---------- 3. 스윕 ----------
    print(f"\n[3] 스윕  (한 주문이 3개 이상 호가를 쓸어감)")
    sw = levels >= 3
    print(f"  발생: {sw.sum():,}회 ({sw.sum() / hours:.1f}회/시간)")
    sw_idx = (o_ts[sw] // 1000 - s0).astype(int)
    sw_dir = np.where(o_side[sw] == 1, 1, -1)
    for k in (5, 30, H):
        r = fwd_return(close, k)[sw_idx] * sw_dir
        r = r[~np.isnan(r)]
        print(f"  스윕 방향 기준 {k:>3}초 뒤 평균 수익: {bps(r)}  (같은 방향으로 계속 간 비율 {np.mean(r > 0) * 100:.0f}%)")
    big = sw & (o_krw > np.percentile(o_krw, 99))
    print(f"  상위 1% 대형 스윕(>{np.percentile(o_krw, 99):,.0f}원): {big.sum()}회")

    # ---------- 4. 버스트 ----------
    base = rolling_sum(cnt, 300) / 300
    base = np.r_[base[:1], base[:-1]]  # 직전 5분 평균 (현재 초 제외)
    burst = (cnt >= 5) & (cnt > base * 6)
    flow1 = np.where(buy + sell > 0, (buy - sell) / np.maximum(buy + sell, 1), 0)
    bdir = np.sign(flow1[burst])
    print(f"\n[4] 버스트  (1초 체결 수가 직전 5분 평균의 6배 이상)")
    print(f"  발생: {burst.sum():,}초 ({burst.sum() / hours:.1f}회/시간)")
    r = fr[burst] * bdir
    print(f"  버스트 방향 기준 {H}초 뒤 평균 수익: {bps(r)}  (계속 간 비율 {np.nanmean(r > 0) * 100:.0f}%)")
    print(f"  버스트 직후 {H}초 변동폭: {np.nanmean(rng[burst]) * 1e4:.1f}bp  vs 평소 {np.nanmean(rng) * 1e4:.1f}bp")

    # ---------- 5. 흐름 과열 이후 (우리 진입 신호) ----------
    b60, s60 = rolling_sum(buy, 60), rolling_sum(sell, 60)
    flow60 = np.where(b60 + s60 > 0, (b60 - s60) / np.maximum(b60 + s60, 1), 0)
    print(f"\n[5] 매수세 과열 이후 실제로 올랐나  (60초 flow 기준, {H}초 뒤)")
    for lo_, hi_ in ((-1, -0.6), (-0.6, -0.3), (-0.3, 0.3), (0.3, 0.6), (0.6, 1.01)):
        m = (flow60 >= lo_) & (flow60 < hi_)
        print(f"  flow {lo_:+.1f}~{min(hi_, 1):+.1f}: 표본 {m.sum():>7,}초  {H}초 뒤 평균 {bps(fr[m])}")
    print("  → 진입 구간(+0.3 이상) 평균이 +10bp(수수료)에 못 미치면, 흐름을 보고 들어가는 시점엔 이미 늦은 것")

    # ---------- 6. 위험 신호 Lift ----------
    thr = np.nanpercentile(rng, 95)
    risk = rng > thr
    base_p = np.nanmean(risk)
    vol60 = rolling_sum((hi - lo) / close, 60)
    sweep_recent = np.zeros(n, bool)
    np.add.at(sweep_recent.view(np.int8), sw_idx, 1)
    sweep_recent = rolling_sum(sweep_recent.astype(float), 10) > 0
    burst_recent = rolling_sum(burst.astype(float), 10) > 0
    act = rolling_sum(cnt, 60)
    act_base = rolling_sum(cnt, 1800) / 30
    features = {
        "최근 10초 내 버스트": burst_recent,
        "최근 10초 내 스윕": sweep_recent,
        "최근 60초 변동성 상위 10%": vol60 > np.nanpercentile(vol60, 90),
        "체결 속도 평소의 3배 이상": act > act_base * 3,
        "flow 극단(|flow|≥0.8)": np.abs(flow60) >= 0.8,
        "버스트 + 고변동성 동시": burst_recent & (vol60 > np.nanpercentile(vol60, 90)),
    }
    print(f"\n[6] 위험 신호 예측력  (위험 = 향후 {H}초 변동폭 상위 5%, ≥{thr * 1e4:.0f}bp. 평소 확률 {base_p * 100:.1f}%)")
    print(f"  {'신호':<26}{'발생비율':>8}{'위험확률':>9}{'Lift':>7}")
    for name, f in features.items():
        valid = f & ~np.isnan(rng)
        if valid.sum() == 0:
            continue
        p = risk[valid].mean()
        print(f"  {name:<24}{f.mean() * 100:>8.1f}%{p * 100:>8.1f}%{p / base_p:>7.1f}x")
    print("  Lift = 신호가 떴을 때 위험확률 / 평소 위험확률.  2배 이상이면 '진입 금지 필터'로 쓸 가치가 있음")


if __name__ == "__main__":
    main()
