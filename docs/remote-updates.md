The rooted Nokia can install updates remotely after an initial USB installation of **0.6.0 (code 8)**. Older versions do not contain the updater and cannot bootstrap themselves. Install over the existing app; do not uninstall or clear data.

On the admin page, **App updates → Request update** queues an update request for that device, including when offline. The running relay checks its configured HTTPS server every 15 minutes; **More info → Check update** checks sooner. Downloads run on a separate worker. The phone verifies the pinned RSA release signature, SHA-256 and bounded size, package ID, version code, and exact installed APK signing identity. Redirects, downgrades, same-version reinstalls, arbitrary URLs, and server-supplied shell commands are rejected.

Installation waits until there are no queued local submissions, modem submissions awaiting callbacks, or unacknowledged SMS statuses. The phone announces `ready=false` and pauses new submissions, then runs a fixed root installer with a 30-second install timeout. `pm install -r` preserves the encrypted configuration, SMS duplicate guards, logs, battery history and preferences. The package replacement receiver and installer restart the relay and dashboard. The server clears the request once the phone reports the published version code. Failures keep the existing app; retry checks occur after 15 minutes. SMS jobs remain durably queued on the server during replacement, and the existing ambiguity guards prevent blind resends.

An administrator chooses when to install each release. This is a rooted-device updater, so grant the relay Magisk root access. Root installation/restart must still be verified on the physical Nokia when it reconnects; local checks validate signing rules and compile the installer. Offline devices need Internet access to download; the app does not bypass TLS, auth, or carrier delivery limits.

Publishing is part of the private repository's `main` workflow:

1. Gateway tests and Android tests/lint/build must pass.
2. CI restores the phone's stable APK signing key from `SMS_ANDROID_KEYSTORE` (base64 keystore, existing Android debug alias/password), signs the APK, and signs the release manifest with `SMS_UPDATE_SIGNING_KEY` (RSA PKCS#8 PEM).
3. Only source, APK and signed manifest enter the bounded deploy archive. Private keys stay in GitHub secrets and temporary CI files. The APK and manifest are served from the isolated relay container with device bearer authentication. Caller API tokens cannot download updates or impersonate a device.
4. Admin sees the published version and can request installation. Merely publishing does not automatically install it.

The manifest signing key and matching original phone keystore are backed up privately in `.local/ota/` (not committed). Keep them safe: changing the APK signing identity prevents in-place installs; rotating the pinned manifest key requires publishing a bridge version signed by the existing key. Every new release must increase `versionCode` and `versionName` in `android/app/build.gradle.kts`. The deployed APK uses the current application's signing identity to preserve upgrade compatibility; the existing unsigned release build is not used for OTA. If migrating away from the existing debug signing identity, plan that separately rather than silently replacing the app or its data.

For local packaging:

```sh
python scripts/publish_app.py --apk android/app/build/outputs/apk/debug/app-debug.apk \
  --key .local/ota/signing.pem --code 8 --version 0.6.0 --out .local/ota/release
```

There are no new public upload routes and no root commands accepted over WebSocket. Existing `.env` credentials, caller scopes, recipient policy, and other sites on the VPS are preserved.
