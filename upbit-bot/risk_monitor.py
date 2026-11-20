"""실시간 호가 위험 모니터 — 과거 데이터로는 볼 수 없는 '호가창' 신호를 실시간으로 감지한다.

감지 항목
  - 스프레드 확대    : 스프레드가 최근 10분 중앙값의 3배 이상 → 마켓메이커 봇이 호가를 뺌(급변 전조)
  - 유동성 이탈      : 15호가 누적 금액이 최근 10분 중앙값의 40% 미만으로 감소
  - 호가 불균형      : (매수잔량 − 매도잔량)/합계 가 ±0.7 이상
  - 대형벽 / 스푸핑 의심 : 평소 호가의 10배 이상 큰 주문(벽)이 생겼다가,
                        그 가격에 체결되지 않았는데 60초 안에 사라지면 '스푸핑 의심'
                        → 30초 뒤 가격이 벽 반대방향으로 갔는지 기록
  - 거래소 공식 경고 : 업비트 유의/주의 플래그(가격급등락, 거래량급등, 입금급등, 글로벌 시세차, 소수계정 집중)

--record 를 주면 호가·체결을 data/live_*.jsonl.gz 로 저장해 나중에 호가 기반 백테스트에 쓸 수 있습니다.

사용: python risk_monitor.py --market KRW-BTC --minutes 30 [--record]
"""
import argparse
import asyncio
import gzip
import json
import os
import statistics
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

import websockets

from upbit_api import UpbitPublic

WS_URL = "wss://api.upbit.com/websocket/v1"
KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST).strftime("%H:%M:%S")


class Monitor:
    def __init__(self, market, record=False):
        self.market = market
        self.spreads = deque(maxlen=600)   # 1초 1개 샘플, 10분
        self.depths = deque(maxlen=600)
        self.level_sizes = deque(maxlen=600)
        self.last_sample = 0
        self.walls = {}                    # (side, price) -> {krw, since, traded}
        self.pending_spoof = []            # 30초 후 가격 확인
        self.spoofs = []
        self.alert_last = {}
        self.counts = {}
        self.mid = None
        self.lo_since_wall = {}
        self.rec = gzip.open(f"data/live_{market}_{datetime.now(KST):%Y%m%d_%H%M%S}.jsonl.gz", "wt") if record else None
        self.events = None

    def alert(self, kind, msg, cooldown=60):
        t = time.time()
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if t - self.alert_last.get(kind, 0) >= cooldown:
            self.alert_last[kind] = t
            print(f"[{now_kst()}] ⚠️ {kind}: {msg}", flush=True)

    def on_trade(self, m):
        p = float(m["trade_price"])
        for key, w in self.walls.items():
            side, wp = key
            if (side == "bid" and p <= wp) or (side == "ask" and p >= wp):
                w["traded"] = True

    def on_orderbook(self, m):
        units = m["orderbook_units"]
        bid, ask = units[0]["bid_price"], units[0]["ask_price"]
        self.mid = (bid + ask) / 2
        spread_bp = (ask - bid) / self.mid * 1e4
        bid_krw = sum(u["bid_price"] * u["bid_size"] for u in units)
        ask_krw = sum(u["ask_price"] * u["ask_size"] for u in units)
        depth = bid_krw + ask_krw
        imb = (bid_krw - ask_krw) / depth if depth else 0
        sizes = [u["bid_price"] * u["bid_size"] for u in units] + [u["ask_price"] * u["ask_size"] for u in units]

        t = time.time()
        if t - self.last_sample >= 1:
            self.last_sample = t
            self.spreads.append(spread_bp)
            self.depths.append(depth)
            self.level_sizes.append(statistics.median(sizes))

        if len(self.spreads) >= 60:
            med_sp = statistics.median(self.spreads)
            med_dp = statistics.median(self.depths)
            if spread_bp > max(3 * med_sp, 2.0):
                self.alert("스프레드 확대", f"{spread_bp:.1f}bp (평소 {med_sp:.1f}bp) → 마켓메이커 이탈, 급변 주의")
            if depth < 0.4 * med_dp:
                self.alert("유동성 이탈", f"15호가 {depth / 1e8:.2f}억 (평소 {med_dp / 1e8:.2f}억)")
            if abs(imb) >= 0.7:
                self.alert("호가 불균형", f"{imb:+.2f} ({'매수' if imb > 0 else '매도'}잔량 쏠림)", cooldown=120)

            # 대형벽 추적
            med_lv = statistics.median(self.level_sizes)
            present = {}
            for u in units:
                for side in ("bid", "ask"):
                    px, sz = u[f"{side}_price"], u[f"{side}_size"]
                    krw = px * sz
                    if krw >= 10 * med_lv and krw >= 50_000_000:
                        present[(side, px)] = krw
            for key, krw in present.items():
                if key not in self.walls:
                    self.walls[key] = {"krw": krw, "since": t, "traded": False}
                    self.alert("대형벽 등장", f"{'매수' if key[0] == 'bid' else '매도'}벽 {key[1]:,.0f}원에 "
                                          f"{krw / 1e8:.2f}억 (평소 호가의 {krw / med_lv:.0f}배)", cooldown=20)
            # 사라진 벽 판정: 가격 범위 안인데 안 보이면 취소된 것
            lo_px = units[-1]["bid_price"]
            hi_px = units[-1]["ask_price"]
            for key in list(self.walls):
                if key in present:
                    continue
                w = self.walls.pop(key)
                side, px = key
                in_range = lo_px <= px <= hi_px
                age = t - w["since"]
                if in_range and not w["traded"] and age <= 60:
                    self.alert("스푸핑 의심", f"{'매수' if side == 'bid' else '매도'}벽 {px:,.0f}원 "
                                          f"{w['krw'] / 1e8:.2f}억이 체결 없이 {age:.0f}초 만에 취소", cooldown=0)
                    self.pending_spoof.append({"t": t, "side": side, "mid": self.mid})

        for ev in list(self.pending_spoof):
            if t - ev["t"] >= 30:
                self.pending_spoof.remove(ev)
                move = (self.mid / ev["mid"] - 1) * 1e4
                # 매수벽 스푸핑 → 가격 하락 예상(벽으로 사람들 유인 후 팔고 빠짐)
                expected = -1 if ev["side"] == "bid" else 1
                self.spoofs.append(move * expected)
                print(f"   ↳ 스푸핑 30초 후: 가격 {move:+.1f}bp ({'예상대로' if move * expected > 0 else '반대로'})", flush=True)

    async def poll_market_event(self, api):
        prev = None
        while True:
            try:
                mk = next(x for x in await asyncio.to_thread(api._get, "/v1/market/all", {"isDetails": "true"})
                          if x["market"] == self.market)
                ev = mk.get("market_event", {})
                flags = [k for k, v in ev.get("caution", {}).items() if v]
                if ev.get("warning"):
                    flags.insert(0, "투자유의")
                if flags != prev:
                    if flags:
                        self.alert("거래소 경고", ", ".join(flags), cooldown=0)
                    elif prev is not None:
                        print(f"[{now_kst()}] 거래소 경고 해제", flush=True)
                    else:
                        print(f"[{now_kst()}] 거래소 공식 경고 없음", flush=True)
                    prev = flags
            except Exception as e:  # 조회 실패해도 모니터는 계속
                print(f"[market_event 조회 실패] {e!r}")
            await asyncio.sleep(60)

    async def run(self, minutes):
        api = UpbitPublic(rate_per_sec=2)
        poller = asyncio.create_task(self.poll_market_event(api))
        start = time.time()
        backoff = 1
        last_status = 0
        try:
            while True:
                try:
                    async with websockets.connect(WS_URL, ping_interval=30, max_size=2**22) as ws:
                        await ws.send(json.dumps([{"ticket": str(uuid.uuid4())},
                                                  {"type": "trade", "codes": [self.market]},
                                                  {"type": "orderbook", "codes": [self.market]}]))
                        backoff = 1
                        async for raw in ws:
                            m = json.loads(raw)
                            if self.rec:
                                self.rec.write(raw.decode() if isinstance(raw, bytes) else raw)
                                self.rec.write("\n")
                            if m["type"] == "trade":
                                self.on_trade(m)
                            else:
                                self.on_orderbook(m)
                            if time.time() - last_status >= 60 and self.spreads:
                                last_status = time.time()
                                print(f"  · {now_kst()} 중간가 {self.mid:,.0f}  스프레드 {self.spreads[-1]:.1f}bp  "
                                      f"15호가 {self.depths[-1] / 1e8:.2f}억  "
                                      f"{'[학습중]' if len(self.spreads) < 60 else ''}", flush=True)
                            if minutes and time.time() - start >= minutes * 60:
                                return
                except (websockets.ConnectionClosed, OSError) as e:
                    print(f"[ws] 끊김 {e!r} → {backoff}s 후 재접속")
                    await asyncio.sleep(backoff)
                    backoff = min(60, backoff * 2)
        finally:
            poller.cancel()
            if self.rec:
                self.rec.close()
            print("\n===== 모니터 요약 =====")
            print(f"실행 {(time.time() - start) / 60:.1f}분, 신호 발생: " +
                  (", ".join(f"{k} {v}회" for k, v in self.counts.items()) or "없음"))
            if self.spoofs:
                ok = sum(1 for x in self.spoofs if x > 0)
                print(f"스푸핑 의심 {len(self.spoofs)}건 중 30초 뒤 예상 방향: {ok}건, "
                      f"평균 {statistics.mean(self.spoofs):+.1f}bp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--minutes", type=float)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args()
    os.makedirs("data", exist_ok=True)
    try:
        asyncio.run(Monitor(args.market, args.record).run(args.minutes))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
