"""과거 체결(틱) 데이터를 내려받아 CSV 로 저장한다. (업비트는 최근 7일까지 제공)

사용: python fetch_ticks.py --market KRW-BTC --hours 24
저장: data/ticks_KRW-BTC_24h.csv  (timestamp,price,volume,is_buy)
"""
import argparse
import csv
import os
import time

from upbit_api import UpbitPublic


def fetch(api: UpbitPublic, market: str, hours: float) -> list[tuple]:
    start_ts = int((time.time() - hours * 3600) * 1000)
    rows: dict[int, tuple] = {}
    calls = 0
    for days_ago in range(0, 8):
        cursor = None
        while True:
            data = api.ticks(market, 500, cursor, days_ago)
            calls += 1
            if not data:
                break
            for d in data:
                rows[d["sequential_id"]] = (
                    d["timestamp"], d["trade_price"], d["trade_volume"], 1 if d["ask_bid"] == "BID" else 0
                )
            oldest = data[-1]["timestamp"]
            cursor = data[-1]["sequential_id"]
            if calls % 20 == 0:
                done = (time.time() * 1000 - oldest) / (hours * 3600 * 1000) * 100
                print(f"  ...{len(rows):,}건 수집 ({min(done, 100):.0f}%)", flush=True)
            if oldest < start_ts:
                break
        if rows and min(r[0] for r in rows.values()) < start_ts:
            break
    out = sorted((r for r in rows.values() if r[0] >= start_ts), key=lambda r: r[0])
    print(f"API 호출 {calls}회, 체결 {len(out):,}건")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="KRW-BTC")
    ap.add_argument("--hours", type=float, default=24)
    args = ap.parse_args()

    rows = fetch(UpbitPublic(), args.market, args.hours)
    os.makedirs("data", exist_ok=True)
    path = f"data/ticks_{args.market}_{args.hours:g}h.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "price", "volume", "is_buy"])
        w.writerows(rows)
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
