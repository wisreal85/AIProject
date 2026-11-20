"""원화마켓 종목을 거래대금 순으로 보고, 스프레드 + 수수료 대비 단타 적합도를 확인한다.

사용: python scan.py [--top 15]
"""
import argparse

from strategy import FEE_RATE
from upbit_api import UpbitPublic, spread_pct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    api = UpbitPublic()
    markets = api.markets()
    names = {m["market"]: m["korean_name"] for m in markets}
    krw = [m["market"] for m in markets if m["market"].startswith("KRW-")]
    tickers = sorted(api.tickers(krw), key=lambda t: t["acc_trade_price_24h"], reverse=True)[: args.top]
    obs = {o["market"]: o for o in api.orderbooks([t["market"] for t in tickers])}

    rt_fee = FEE_RATE * 2 * 100
    print(f"왕복 수수료 = {rt_fee:.2f}%  (매수 0.05% + 매도 0.05%)\n")
    print(f"{'종목':<12}{'이름':<10}{'24h거래대금':>12}{'현재가':>16}{'스프레드%':>10}{'왕복비용%':>10}{'24h변동%':>9}")
    for t in tickers:
        m = t["market"]
        _, _, sp = spread_pct(obs[m])
        cost = rt_fee + sp
        price = f"{t['trade_price']:,.4f}".rstrip("0").rstrip(".")
        print(
            f"{m:<12}{names[m][:8]:<10}{t['acc_trade_price_24h'] / 1e8:>10,.0f}억"
            f"{price:>16}{sp:>10.3f}{cost:>10.3f}{t['signed_change_rate'] * 100:>+9.2f}"
        )
    print(
        "\n왕복비용% = 수수료 + 스프레드(시장가로 사고 바로 팔 때 즉시 잃는 비율)."
        "\n익절 목표는 최소 이 값보다 충분히 커야 합니다. 스프레드가 작고 거래대금이 큰 종목이 유리합니다."
    )


if __name__ == "__main__":
    main()
