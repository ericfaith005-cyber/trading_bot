import MetaTrader5 as mt5


print("=" * 60)
print("EXNESS MT5 CONNECTION TEST")
print("=" * 60)


# Connect to the MT5 terminal that is already open
if not mt5.initialize():
    print("❌ MT5 connection failed")
    print("Error:", mt5.last_error())
    raise SystemExit(1)


print("✅ MT5 connected successfully")


# Account information
account = mt5.account_info()

if account is None:
    print("❌ Could not read account information")
    print("Error:", mt5.last_error())
    mt5.shutdown()
    raise SystemExit(1)


print("\nACCOUNT")
print("-" * 60)
print("Login:", account.login)
print("Server:", account.server)
print("Currency:", account.currency)
print("Balance:", account.balance)
print("Equity:", account.equity)
print("Free margin:", account.margin_free)
print("Leverage:", account.leverage)


# Trading permissions
print("\nTRADING STATUS")
print("-" * 60)
print("Trade allowed:", account.trade_allowed)
print("Expert trading allowed:", account.trade_expert)


# Forex symbols
pairs = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "GBPJPY",
]


print("\nFOREX MARKET DATA")
print("-" * 60)


for symbol in pairs:

    info = mt5.symbol_info(symbol)

    if info is None:
        print(f"\n❌ {symbol}: symbol not found")
        continue

    # Make sure the symbol is visible in Market Watch
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)

    tick = mt5.symbol_info_tick(symbol)

    print(f"\n{symbol}")

    if tick is None:
        print("  ❌ No live tick available")
        continue

    print("  Bid:", tick.bid)
    print("  Ask:", tick.ask)
    print("  Spread:", tick.ask - tick.bid)

    print("  Digits:", info.digits)
    print("  Point:", info.point)
    print("  Minimum volume:", info.volume_min)
    print("  Volume step:", info.volume_step)
    print("  Maximum volume:", info.volume_max)


print("\n" + "=" * 60)
print("TEST COMPLETE — NO TRADE WAS PLACED")
print("=" * 60)


mt5.shutdown()