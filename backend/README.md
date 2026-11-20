# Backend operation

The backend defaults to simulated candles and paper execution. To use the
Twelve Data feed, set the API key locally and select the feed before starting
the server:

```powershell
$secure = Read-Host 'Twelve Data API key' -AsSecureString
$env:TWELVE_DATA_API_KEY = (New-Object System.Net.NetworkCredential('', $secure)).Password
$env:MARKET_DATA_MODE = 'twelvedata'
python server.py
```

The account database and MT5 terminal remain on this computer. The optional
`GET /api/broker/status` endpoint checks MT5 connectivity read-only; it does not
send orders. The server reports live order submission as disabled and provides
only manually confirmed paper orders in assisted mode. AI and SMC analysis do
not submit orders.

Do not expose the backend port to the public internet. It binds to
`127.0.0.1` by default. `BOT_BIND_HOST` can be set for a trusted local network
when a mobile device must connect; keep that network private.

`backtesting.py` is an approximate historical simulation using the portfolio's
simplified P&L model. It is not broker-accurate and does not send orders.

## Render deployment

The repository-root `render.yaml` configures a free web service to require
Twelve Data rather than fall back to simulated candles. Add
`TWELVE_DATA_API_KEY` as a secret in Render before the first successful start.
The free plan can sleep and has ephemeral storage, so account registrations and
local SQLite state can be lost after a restart or deploy.

Render's Python service runs on Linux and cannot connect to the MetaTrader
terminal on a Windows desktop. The MT5 status endpoint is for a locally hosted
Windows backend only. Live broker order submission remains disabled.

For an APK pointed at the deployed service, set
`EXPO_PUBLIC_API_URL=https://<your-render-service>.onrender.com` during the
Expo/EAS build. The mobile app falls back to localhost when this variable is
unset.
