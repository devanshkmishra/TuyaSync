# TuyaSync for Android

Controls the Wipro DS22000 batten (and other Tuya Wi-Fi lights) directly over the home Wi-Fi with the Tuya local
protocol, so the Smart Life app is not needed. No cloud account, no Bluetooth.

## Install

Every push builds an APK in GitHub Actions: open the latest **Android app** run, download the `TuyaSync-android`
artifact, unzip it and install `app-debug.apk` on the phone (allow installs from your browser or file manager when
asked). Builds share one signing key, so a newer APK installs over the old one.

## Set up the light

The app needs the light's Local Key once:

1. **From the desktop app:** in TuyaSync on your computer, open **Light → Share to phone** and scan the QR code.
   Or run `python -m screensync.phone_share` to print the code in a terminal.
2. **From a file:** open an exported `.tuyasync-profile.json`.
3. **By hand:** tap **Find lights on this Wi-Fi** to fill in the Device ID and address, then type the Local Key.

The key is stored encrypted with Android Keystore. Uninstalling Smart Life is safe, but don't remove the light from
the Smart Life account: that gives it a new Local Key.

## Layout

- `tuya-core/`: plain Kotlin library with the protocol (3.3, 3.4 and 3.5 framing, session handshake, LAN
  discovery), the DS22000 data points and the scene encoder. Tests check it byte-for-byte against TinyTuya
  (`tools/make_vectors.py` regenerates `vectors.json`) and run a fake 3.5 light over loopback.
- `app/`: the Jetpack Compose app.

```sh
./gradlew :tuya-core:test              # protocol tests, no Android SDK needed: add -PcoreOnly
./gradlew :app:assembleDebug           # APK in app/build/outputs/apk/debug/
```
