"""실시간 모의매매. 업비트 웹소켓으로 실제 체결·호가를 받아 가상으로 사고판다.
주문 API 는 호출하지 않으므로 API 키가 필요 없고 돈이 나가지 않습니다.

사용:
  python paper.py --market KRW-BTC               # Ctrl+C 로 종료
  python paper.py --market KRW-BTC --minutes 60  # 60분만 실행

- 시세는 REST 반복조회가 아니라 웹소켓 구독 1회로 받습니다(밴 원인 제거).
- 끊기면 지수 백오프로 재접속합니다.
- 체결 기록은 logs/ 에 CSV 로 남습니다.
- 텔레그램 알림: 환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 를 설정하면 손실 한도 도달 시 전송.
"""
import argparse
import asyncio
import csv
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
import websockets

from strategy import Engine, FlowStrategy, Params, print_summary, summarize

WS_URL = "wss://api.upbit.com/websocket/v1"
KST = timezone(timedelta(hours=9))


def kst(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).strftime("%m-%d %H:%M:%S")


def make_notifier():
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")

    def notify(msg):
        print(f"\n🔔 {msg}\n", flush=True)
        if token and chat:
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              data={"chat_id": chat, "text": msg}, timeout=5)
            except requests.RequestException as e:
                print(f"[알림 전송 실패] {e!r}")
    return notify


async def run(market: str, p: Params, minutes: float | None):
    strat = FlowStrategy(p)
    notify = make_notifier()
    eng = Engine(p, strat, notify=notify)

    os.makedirs("logs", exist_ok=True)
    log_path = f"logs/paper_{market}_{datetime.now(KST):%Y%m%d_%H%M%S}.csv"
    logf = open(log_path, "w", newline="")
    log = csv.writer(logf)
    log.writerow(["entry_kst", "exit_kst", "entry_price", "exit_price", "qty", "pnl_krw", "fees_krw", "reason"])

    def on_closed(t):
        log.writerow([kst(t.entry_ts), kst(t.exit_ts), t.entry_price, t.exit_price,
                      f"{t.qty:.8f}", f"{t.pnl:.2f}", f"{t.fees_krw:.2f}", t.reason])
        logf.flush()
        total = sum(x.pnl for x in eng.trades)
        print(f"[{kst(t.exit_ts)}] 매도({t.reason}) {t.exit_price:,.0f}  손익 {t.pnl:+,.1f}원  "
              f"누적 {total:+,.1f}원 ({len(eng.trades)}회)", flush=True)

    eng.on_trade_closed = on_closed

    bid = ask = None
    started = time.time()
    last_status = 0.0
    backoff = 1
    had_pos = False
    print(f"모의매매 시작: {market}, 1회 {p.order_krw:,.0f}원, 익절 {p.take_profit_pct}% / 손절 {p.stop_loss_pct}%, "
          f"일손실한도 {p.max_daily_loss_krw:,.0f}원")
    print(f"지표 준비(워밍업) {p.ema_slow_sec:.0f}초 후부터 판단합니다. 로그: {log_path}\n", flush=True)

    try:
        while True:
            try:
                async with websockets.connect(WS_URL, ping_interval=30, max_size=2**22) as ws:
                    await ws.send(json.dumps([
                        {"ticket": str(uuid.uuid4())},
                        {"type": "trade", "codes": [market]},
                        {"type": "orderbook", "codes": [market]},
                    ]))
                    backoff = 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        ts = msg.get("timestamp") or int(time.time() * 1000)
                        if msg["type"] == "orderbook":
                            u = msg["orderbook_units"][0]
                            bid, ask = float(u["bid_price"]), float(u["ask_price"])
                        elif msg["type"] == "trade":
                            strat.on_trade(msg["trade_timestamp"], float(msg["trade_price"]),
                                           float(msg["trade_volume"]), msg["ask_bid"] == "BID")
                        if bid is None:
                            continue
                        eng.step(ts, bid, ask)

                        if eng.pos and not had_pos:
                            print(f"[{kst(ts)}] 매수 {eng.pos.entry_price:,.0f}  "
                                  f"(flow {strat.flow:+.2f})", flush=True)
                        had_pos = eng.pos is not None

                        now = time.time()
                        if now - last_status >= 30:
                            last_status = now
                            state = "보유중 " + f"{eng.net_pnl_pct(bid):+.3f}%" if eng.pos else "대기"
                            if eng.stopped or eng.halted_day is not None:
                                state = "중단(손실한도)"
                            warm = "" if strat.warmed_up else " [워밍업]"
                            print(f"  · {kst(ts)} 가격 {bid:,.0f}/{ask:,.0f}  flow {strat.flow:+.2f}  "
                                  f"추세 {'↑' if strat.uptrend else '↓'}  {state}{warm}", flush=True)
                        if minutes and now - started >= minutes * 60:
                            return
            except (websockets.ConnectionClosed, OSError) as e:
                print(f"[ws] 연결 끊김 {e!r} → {backoff}s 후 재접속", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(60, backoff * 2)
    finally:
        if eng.pos and bid:
            eng.force_close(int(time.time() * 1000), bid)
        logf.close()
        hours = (time.time() - started) / 3600
        print_summary(summarize(eng.trades, p, hours), f"{market} 모의매매 결과")
        print(f"체결 로그: {log_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--minutes", type=float)
    ap.add_argument("--order-krw", type=float)
    ap.add_argument("--take-profit", type=float)
    ap.add_argument("--stop-loss", type=float)
    ap.add_argument("--max-daily-loss", type=float)
    args = ap.parse_args()

    p = Params(resume_next_day=False)
    if args.order_krw:
        p.order_krw = args.order_krw
    if args.take_profit is not None:
        p.take_profit_pct = args.take_profit
    if args.stop_loss is not None:
        p.stop_loss_pct = args.stop_loss
    if args.max_daily_loss is not None:
        p.max_daily_loss_krw = args.max_daily_loss
    try:
        asyncio.run(run(args.market, p, args.minutes))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
