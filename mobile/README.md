# Android APK

The app reads `EXPO_PUBLIC_API_URL` at build time. For a deployed backend, set
it to the HTTPS URL assigned by Render; do not put the Twelve Data API key or
MetaTrader credentials in the mobile app.

From PowerShell:

```powershell
Set-Location 'C:\path\to\ai-trading-bot\mobile'
npx eas-cli login
npx eas-cli init
$env:EXPO_PUBLIC_API_URL = 'https://<your-render-service>.onrender.com'
npx eas-cli build -p android --profile preview
```

EAS must be authenticated and initialized with an Expo project before the
cloud APK build. EAS uploads the mobile project to Expo to build it. The
preview profile produces an installable APK. If `EXPO_PUBLIC_API_URL` is
unset, the app defaults to a local development address.

The app supports live Twelve Data market display and paper orders only. MT5
order submission is disabled.
