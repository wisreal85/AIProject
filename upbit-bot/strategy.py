"""'거래 흐름' 기반 단타 전략 + 모의 체결 엔진.

백테스트(과거 체결 데이터)와 실시간 모의매매(웹소켓)가 **같은 코드**를 쓰도록
전략(FlowStrategy)과 체결/리스크 엔진(Engine)을 분리했습니다.

전략 규칙 (기본값)
- 흐름(flow): 최근 60초 동안 (매수체결 금액 - 매도체결 금액) / 전체 체결 금액.  -1 ~ +1
- 추세: 30초 EMA 가 180초 EMA 위에 있으면 상승
- 진입: flow >= 0.3 이고 상승 추세, 스프레드가 너무 넓지 않고, 쿨타임이 지났을 때 소액 매수
- 청산: 수수료 포함 순손익 >= +0.30% 이면 익절
        순손익 <= -0.30% 이면 손절
        흐름이 꺾이면(flow <= -0.2 또는 EMA 역전) 즉시 청산
- 리스크: 하루(KST) 누적 손실이 한도를 넘으면 알림 후 거래 중단
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, asdict

FEE_RATE = 0.0005  # 업비트 원화마켓 0.05% (매수/매도 각각)
KST = 9 * 3600


@dataclass
class Params:
    order_krw: float = 10_000          # 1회 매수 금액 (업비트 최소 5,000원)
    flow_window_sec: float = 60
    ema_fast_sec: float = 30
    ema_slow_sec: float = 180
    entry_flow: float = 0.30
    exit_flow: float = -0.20
    take_profit_pct: float = 0.30      # 수수료 차감 후 순수익 %
    stop_loss_pct: float = 0.30        # 수수료 차감 후 순손실 %
    min_hold_sec: float = 5            # 진입 직후 흐름 청산 금지 시간(노이즈 방지)
    cooldown_sec: float = 30           # 청산 후 재진입 대기
    eval_interval_sec: float = 1.0     # 판단 주기
    min_trades_in_window: int = 20     # 거래가 너무 한산하면 진입 안 함
    max_spread_pct: float = 0.10       # 스프레드가 이보다 넓으면 진입 안 함
    latency_ms: float = 200            # 판단 → 체결까지 지연(실제 API 왕복 가정)
    max_daily_loss_krw: float = 2_000  # 하루 누적 손실 한도
    resume_next_day: bool = True       # False 면 한도 도달 시 완전 정지
    exit_on_flow: bool = True          # 흐름 꺾이면 즉시 청산할지
    # --- 위험 신호 필터 (bot_footprint.py 분석 결과) ---
    vol_filter: bool = False           # 최근 60초 변동폭이 최근 30분 중 상위 10%면 진입 금지 (위험확률 3.3배)
    vol_filter_pct: float = 90
    avoid_minute_open: bool = False    # 매분 58~02초(적립식 봇 몰림, 직후 되돌림) 진입 금지


class FlowStrategy:
    def __init__(self, p: Params):
        self.p = p
        self.window: deque[tuple[int, float]] = deque()  # (ts_ms, signed_krw)
        self.buy_krw = 0.0
        self.total_krw = 0.0
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.last_ts: int | None = None
        self.first_ts: int | None = None
        self.prices: deque[tuple[int, float]] = deque()   # 최근 60초 (ts, price)
        self.vol_hist: deque[float] = deque(maxlen=1800)  # 초당 1개, 최근 30분의 60초 변동폭
        self._last_sec = None
        self._vol_thr = None
        self._thr_age = 0

    def on_trade(self, ts: int, price: float, volume: float, is_buy: bool) -> None:
        krw = price * volume
        self.window.append((ts, krw if is_buy else -krw))
        self.total_krw += krw
        if is_buy:
            self.buy_krw += krw
        cutoff = ts - self.p.flow_window_sec * 1000
        while self.window and self.window[0][0] < cutoff:
            _, v = self.window.popleft()
            self.total_krw -= abs(v)
            if v > 0:
                self.buy_krw -= v

        self.prices.append((ts, price))
        while self.prices[0][0] < ts - 60_000:
            self.prices.popleft()
        sec = ts // 1000
        if sec != self._last_sec:
            self._last_sec = sec
            self.vol_hist.append(self.range_bp())
            self._thr_age += 1

        if self.ema_fast is None:
            self.ema_fast = self.ema_slow = price
            self.first_ts = ts
        else:
            dt = max(0.0, (ts - self.last_ts) / 1000)
            af = 1 - math.exp(-dt / self.p.ema_fast_sec)
            as_ = 1 - math.exp(-dt / self.p.ema_slow_sec)
            self.ema_fast += af * (price - self.ema_fast)
            self.ema_slow += as_ * (price - self.ema_slow)
        self.last_ts = ts

    @property
    def warmed_up(self) -> bool:
        return self.first_ts is not None and self.last_ts - self.first_ts >= self.p.ema_slow_sec * 1000

    @property
    def flow(self) -> float:
        if self.total_krw <= 0:
            return 0.0
        sell = self.total_krw - self.buy_krw
        return (self.buy_krw - sell) / self.total_krw

    @property
    def uptrend(self) -> bool:
        return self.ema_fast is not None and self.ema_fast > self.ema_slow

    def entry_signal(self) -> bool:
        return (
            self.warmed_up
            and len(self.window) >= self.p.min_trades_in_window
            and self.flow >= self.p.entry_flow
            and self.uptrend
        )

    def range_bp(self) -> float:
        ps = [p for _, p in self.prices]
        return (max(ps) - min(ps)) / ps[-1] * 1e4 if ps else 0.0

    def risk_reason(self, ts: int) -> str | None:
        """진입을 막아야 할 위험 신호가 있으면 사유를 돌려준다"""
        if self.p.avoid_minute_open and (ts // 1000) % 60 in (58, 59, 0, 1, 2):
            return "정각 적립봇 구간"
        if self.p.vol_filter and len(self.vol_hist) >= 300:
            if self._vol_thr is None or self._thr_age >= 30:
                hist = sorted(self.vol_hist)
                self._vol_thr = hist[int(len(hist) * self.p.vol_filter_pct / 100) - 1]
                self._thr_age = 0
            if self.range_bp() > self._vol_thr:
                return "고변동성"
        return None

    def flow_broken(self) -> bool:
        return self.flow <= self.p.exit_flow or not self.uptrend


@dataclass
class Trade:
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    qty: float
    cost_krw: float      # 매수 총액(수수료 포함)
    proceeds_krw: float  # 매도 수령액(수수료 차감)
    fees_krw: float
    reason: str

    @property
    def pnl(self) -> float:
        return self.proceeds_krw - self.cost_krw

    @property
    def gross_pnl(self) -> float:
        """수수료가 없었다면의 손익(스프레드/슬리피지는 포함)"""
        return (self.exit_price - self.entry_price) * self.qty


@dataclass
class Position:
    entry_ts: int
    entry_price: float
    qty: float
    cost_krw: float
    buy_fee: float


class Engine:
    """모의 체결 + 리스크 관리. 실제 주문은 하지 않습니다."""

    def __init__(self, p: Params, strat: FlowStrategy, notify=print, fee_rate: float = FEE_RATE):
        self.p = p
        self.s = strat
        self.notify = notify
        self.fee = fee_rate
        self.pos: Position | None = None
        self.pending: tuple[str, int, str] | None = None  # (side, due_ts, reason)
        self.trades: list[Trade] = []
        self.last_exit_ts = -10**15
        self.last_eval_ts = -10**15
        self.halted_day: int | None = None
        self.stopped = False
        self.daily_pnl: dict[int, float] = {}
        self.on_trade_closed = None  # 콜백(선택)
        self.blocked: dict[str, int] = {}  # 위험 필터로 막은 진입 횟수

    @staticmethod
    def kst_day(ts: int) -> int:
        return int((ts / 1000 + KST) // 86400)

    def _fill(self, side: str, ts: int, bid: float, ask: float, reason: str) -> None:
        if side == "buy":
            # order_krw 를 수수료 포함해서 쓴다
            qty = self.p.order_krw / (ask * (1 + self.fee))
            notional = ask * qty
            fee = notional * self.fee
            self.pos = Position(ts, ask, qty, notional + fee, fee)
        else:
            pos = self.pos
            notional = bid * pos.qty
            fee = notional * self.fee
            t = Trade(pos.entry_ts, ts, pos.entry_price, bid, pos.qty,
                      pos.cost_krw, notional - fee, pos.buy_fee + fee, reason)
            self.trades.append(t)
            self.pos = None
            self.last_exit_ts = ts
            day = self.kst_day(ts)
            self.daily_pnl[day] = self.daily_pnl.get(day, 0.0) + t.pnl
            if self.on_trade_closed:
                self.on_trade_closed(t)
            if self.daily_pnl[day] <= -self.p.max_daily_loss_krw:
                self.halted_day = day
                if not self.p.resume_next_day:
                    self.stopped = True
                self.notify(
                    f"⚠️ 일일 손실 한도 도달: {self.daily_pnl[day]:,.0f}원 "
                    f"(한도 -{self.p.max_daily_loss_krw:,.0f}원) → "
                    + ("거래 완전 중단" if self.stopped else "오늘(KST)은 거래 중단")
                )

    def net_pnl_pct(self, bid: float) -> float:
        proceeds = bid * self.pos.qty * (1 - self.fee)
        return (proceeds - self.pos.cost_krw) / self.pos.cost_krw * 100

    def step(self, ts: int, bid: float, ask: float) -> None:
        # 1) 지연 후 체결 대기 중인 주문 처리
        if self.pending and ts >= self.pending[1]:
            side, _, reason = self.pending
            self.pending = None
            self._fill(side, ts, bid, ask, reason)
            return
        if self.pending or self.stopped:
            return
        if ts - self.last_eval_ts < self.p.eval_interval_sec * 1000:
            return
        self.last_eval_ts = ts

        if self.pos is None:
            if self.halted_day is not None:
                if self.kst_day(ts) == self.halted_day or not self.p.resume_next_day:
                    return
                self.halted_day = None
            if ts - self.last_exit_ts < self.p.cooldown_sec * 1000:
                return
            mid = (bid + ask) / 2
            if (ask - bid) / mid * 100 > self.p.max_spread_pct:
                return
            if self.s.entry_signal():
                why = self.s.risk_reason(ts)
                if why:
                    self.blocked[why] = self.blocked.get(why, 0) + 1
                    return
                self.pending = ("buy", ts + int(self.p.latency_ms), "entry")
        else:
            pnl = self.net_pnl_pct(bid)
            held = (ts - self.pos.entry_ts) / 1000
            reason = None
            if pnl >= self.p.take_profit_pct:
                reason = "익절"
            elif pnl <= -self.p.stop_loss_pct:
                reason = "손절"
            elif self.p.exit_on_flow and held >= self.p.min_hold_sec and self.s.flow_broken():
                reason = "흐름전환"
            if reason:
                self.pending = ("sell", ts + int(self.p.latency_ms), reason)

    def force_close(self, ts: int, bid: float) -> None:
        if self.pos:
            self._fill("sell", ts, bid, bid, "종료청산")


def summarize(trades: list[Trade], p: Params, duration_hours: float | None = None) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    net = sum(t.pnl for t in trades)
    fees = sum(t.fees_krw for t in trades)
    gross = sum(t.gross_pnl for t in trades)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t.pnl
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {
        "trades": n,
        "win_rate": len(wins) / n * 100 if n else 0.0,
        "avg_win": sum(t.pnl for t in wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(t.pnl for t in losses) / len(losses) if losses else 0.0,
        "net_pnl": net,
        "gross_pnl_no_fee": gross,
        "fees": fees,
        "max_drawdown": mdd,
        "net_pct_of_order": net / p.order_krw * 100,
        "avg_hold_sec": sum((t.exit_ts - t.entry_ts) for t in trades) / n / 1000 if n else 0.0,
        "reasons": reasons,
        "hours": duration_hours,
    }


def print_summary(s: dict, title: str = "결과") -> None:
    print(f"\n===== {title} =====")
    if s.get("hours"):
        print(f"기간            : {s['hours']:.1f}시간")
    print(f"거래 횟수       : {s['trades']}회")
    if not s["trades"]:
        print("(진입 조건을 만족한 구간이 없었습니다)")
        return
    print(f"승률            : {s['win_rate']:.1f}%")
    print(f"평균 이익/손실  : +{s['avg_win']:,.1f}원 / {s['avg_loss']:,.1f}원")
    print(f"수수료 전 손익  : {s['gross_pnl_no_fee']:+,.1f}원  (스프레드·지연 손실은 이미 반영)")
    print(f"낸 수수료       : -{s['fees']:,.1f}원")
    print(f"최종 순손익     : {s['net_pnl']:+,.1f}원  (1회 주문금액 대비 {s['net_pct_of_order']:+.2f}%)")
    print(f"최대 낙폭(MDD)  : {s['max_drawdown']:,.1f}원")
    print(f"평균 보유시간   : {s['avg_hold_sec']:.0f}초")
    print("청산 사유       : " + ", ".join(f"{k} {v}" for k, v in s["reasons"].items()))
    if s.get("hours"):
        per_day = s["net_pnl"] / s["hours"] * 24
        print(f"하루 환산 순손익: {per_day:+,.0f}원")


def params_dict(p: Params) -> dict:
    return asdict(p)
