# AI Trading Bot

The backend provides market data and analysis; the mobile app connects to it.
Twelve Data is supported for live market quotes. Trading in this project is
paper-only: real MetaTrader order submission is disabled.

## Deploy the backend to Render

Create a GitHub repository and push this project, then create a Render
Blueprint from its `render.yaml`. Set `TWELVE_DATA_API_KEY` as a secret in
Render before the service starts. The free service may sleep and uses
ephemeral local storage, so it is not an always-on or durable account service.
Render cannot connect to a MetaTrader terminal running on a Windows desktop.

See [backend/README.md](backend/README.md) for backend operation details.

## Build the Android APK

After Render assigns the service an HTTPS URL, set
`EXPO_PUBLIC_API_URL` to that URL and follow [mobile/README.md](mobile/README.md)
to initialize Expo Application Services and build the APK. Never put API keys
or broker credentials in the mobile app or source repository.
