# CI, deployment and independent signing

Pull requests and ordinary main pushes run backend tests and Android build/unit/lint checks without production secrets. APK build artifacts contain no provisioned device token. A default debug keystore is for development only; release builds are unsigned until explicitly signed.

## Optional production automation

Leave `SMS_PRODUCTION_ENABLED` unset for build/test only. To enable production on your own repository, configure these repository variables:

- `SMS_PRODUCTION_ENABLED`: `true`.
- `SMS_HEALTH_URL`: your own HTTPS `/health` URL.

Configure these GitHub Actions secrets (Settings → Secrets and variables → Actions):

- `SMS_DEPLOY_KEY`: dedicated restricted SSH private key, not your general root key.
- `SMS_DEPLOY_HOST`: deployment host.
- `SMS_DEPLOY_KNOWN_HOSTS`: independently verified SSH host-key entry.
- `SMS_ANDROID_KEYSTORE`: base64 of your private stable APK keystore (the current workflow expects the Android debug alias/password). This is the existing appliance workflow; independent production operators should adapt signing configuration to their privately managed release alias/password before enrolling phones.
- `SMS_UPDATE_SIGNING_KEY`: private RSA PKCS#8 PEM matching the public key pinned in your app.

Set up the isolated host deployment described in [production operations](production.md) before enabling the flag: the workflow does not provision the VPS, DNS, firewall, forced SSH command, directories, proxy or runtime `.env`. Never expose the deployment key to pull-request workflows. Retain environment protection as appropriate.

Main releases package only tracked source and signed OTA assets. Runtime credentials and SQLite remain outside releases. The deployment updates only the relay gateway, backs up SQLite, and checks health with rollback. It does not edit other sites or their proxy blocks. The standalone root Compose file starts its own Caddy on 80/443; use the existing-proxy deployment on a shared server instead of starting a second listener.

## Independent OTA trust

The committed manifest public key is intentionally public and belongs to the original installation. You do not have its private key. Generate your own before installing your independently maintained app:

```sh
mkdir -p .local/ota
chmod 700 .local/ota
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out .local/ota/signing.pem
openssl pkey -in .local/ota/signing.pem -pubout -outform DER | openssl base64 -A
```

Replace `UpdateRules.PUBLIC_KEY` with the final command's public output, rebuild, and install your own APK. Preserve its APK signing identity for every upgrade. Never replace an enrolled app's trust key without a bridge release signed by its currently trusted keys. Never uninstall/clear a live relay to bypass a signing mismatch.

For each OTA release increase versionCode/versionName, use the stable APK signer, and run `scripts/publish_app.py` with your manifest key. See [remote update behavior](remote-updates.md). The rooted install path remains hardware-dependent; successful builds are not evidence of a real OTA installation. Keep both signing keys and private backups out of Git/artifacts.
