#!/bin/sh
# Build the Android APK (debug-signed, for internal sideloading) into translate/dist/.
# Needs JDK 17, Gradle 8.9+ and the Android SDK (ANDROID_HOME or native/android/local.properties).
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE/native/android"
if [ ! -f local.properties ] && [ -n "${ANDROID_HOME:-}" ]; then echo "sdk.dir=$ANDROID_HOME" > local.properties; fi
GRADLE=${GRADLE:-gradle}
"$GRADLE" assembleDebug --no-daemon
mkdir -p "$HERE/dist"
cp app/build/outputs/apk/debug/app-debug.apk "$HERE/dist/QueryBookTranslate-android-debug.apk"
echo "APK: $HERE/dist/QueryBookTranslate-android-debug.apk"
