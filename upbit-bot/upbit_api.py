"""업비트 공개(Quotation) API 클라이언트.

예전에 밴을 먹었던 원인(쿨타임 없는 반복 호출)을 막기 위해
- 초당 호출 수를 토큰 버킷으로 제한하고
- 응답 헤더 Remaining-Req 의 남은 횟수를 보고 스스로 쉬고
- 429(요청 과다)는 지수 백오프로 재시도, 418(차단)은 즉시 중단합니다.
"""
from __future__ import annotations

import re
import threading
import time

import requests

BASE_URL = "https://api.upbit.com"


class RateLimiter:
    """간단한 토큰 버킷. rate_per_sec 개를 넘지 않게 호출 간격을 맞춘다."""

    def __init__(self, rate_per_sec: float = 8.0):
        self.capacity = rate_per_sec
        self.tokens = rate_per_sec
        self.rate = rate_per_sec
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                need = (1 - self.tokens) / self.rate
            time.sleep(need)


class UpbitBanned(RuntimeError):
    pass


class UpbitPublic:
    def __init__(self, rate_per_sec: float = 8.0, verbose: bool = False):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.limiter = RateLimiter(rate_per_sec)
        self.verbose = verbose

    def _get(self, path: str, params: dict | None = None):
        for attempt in range(7):
            self.limiter.wait()
            try:
                r = self.session.get(BASE_URL + path, params=params, timeout=10)
            except requests.RequestException as e:
                wait = min(30, 0.5 * 2 ** attempt)
                print(f"[api] 네트워크 오류 {e!r}, {wait:.1f}s 후 재시도")
                time.sleep(wait)
                continue

            if r.status_code == 418:
                raise UpbitBanned(
                    "업비트가 418을 반환했습니다(일시 IP 차단). 호출 빈도를 낮추고 한참 뒤에 다시 시도하세요."
                )
            if r.status_code == 429:
                wait = min(30, 0.5 * 2 ** attempt)
                print(f"[api] 429 요청 과다 → {wait:.1f}s 대기 후 재시도")
                time.sleep(wait)
                continue
            r.raise_for_status()

            # Remaining-Req: group=crix-trades; min=600; sec=9
            rem = r.headers.get("Remaining-Req", "")
            m = re.search(r"sec=(\d+)", rem)
            if m and int(m.group(1)) <= 1:
                time.sleep(1.0)
            return r.json()
        raise RuntimeError(f"요청 실패(재시도 초과): {path} {params}")

    # ---- 시세 조회 ----
    def markets(self):
        return self._get("/v1/market/all", {"isDetails": "false"})

    def tickers(self, markets: list[str]):
        out = []
        for i in range(0, len(markets), 100):
            out += self._get("/v1/ticker", {"markets": ",".join(markets[i:i + 100])})
        return out

    def orderbooks(self, markets: list[str]):
        out = []
        for i in range(0, len(markets), 50):
            out += self._get("/v1/orderbook", {"markets": ",".join(markets[i:i + 50])})
        return out

    def ticks(self, market: str, count: int = 500, cursor: str | None = None, days_ago: int = 0):
        params = {"market": market, "count": count}
        if cursor:
            params["cursor"] = cursor
        if days_ago:
            params["days_ago"] = days_ago
        return self._get("/v1/trades/ticks", params)


def spread_pct(orderbook: dict) -> tuple[float, float, float]:
    """(best_bid, best_ask, 스프레드%) 반환"""
    u = orderbook["orderbook_units"][0]
    bid, ask = float(u["bid_price"]), float(u["ask_price"])
    mid = (bid + ask) / 2
    return bid, ask, (ask - bid) / mid * 100
