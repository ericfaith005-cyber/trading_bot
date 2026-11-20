from mt5_risk import MT5RiskManager

risk = MT5RiskManager(
    max_risk_pct=0.01,
    max_spread_points=50,
)

risk.connect()

pairs = [
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "GBP/JPY",
]

for pair in pairs:
    print()
    print("=" * 50)
    print(pair)
    print("=" * 50)

    result = risk.get_trade_readiness(
        pair,
        "BUY",
    )

    print(result)