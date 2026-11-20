#!/usr/bin/env bash
set -e

echo "=========================================="
echo "      AI TRADING BOT - APK BUILDER        "
echo "=========================================="

echo "Choose your build method:"
echo "1) Cloud Build via Expo EAS (No Android Studio/SDK needed, builds directly to APK)"
echo "2) Local Build via Android Gradle (Requires JDK 17 & Android SDK)"
echo "=========================================="

read -p "Enter choice [1 or 2]: " choice

if [ "$choice" = "1" ]; then
    echo "Starting Expo EAS APK Build..."
    cd mobile
    if ! command -v eas &> /dev/null; then
        echo "Installing EAS CLI..."
        npm install -g eas-cli
    fi
    echo "Logging into EAS and compiling APK..."
    eas build -p android --profile preview
elif [ "$choice" = "2" ]; then
    echo "Starting Local Gradle APK Build..."
    cd mobile/android
    chmod +x gradlew || true
    ./gradlew assembleRelease
    echo "Build Complete! APK located at: mobile/android/app/build/outputs/apk/release/app-release.apk"
else
    echo "Invalid option. Exiting."
    exit 1
fi