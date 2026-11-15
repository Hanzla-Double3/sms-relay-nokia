# Reversible Nokia appliance cleanup

For the dedicated SMS appliance, optional consumer apps can be disabled for Android user 0. This suppresses their activities/services/jobs without uninstalling APKs, deleting data, flashing or changing the OS. Keep the stock system and modem intact.

The fixed allowlist in `scripts/phone_cleanup.py` covers Google Search/Assistant, YouTube, Gmail, Calendar, Maps, Photos, Drive, Keep, Google One, Android Auto, Digital Wellbeing, printing services, FM Radio and Nokia support. It skips absent/already-disabled packages and records original states before changing anything.

```sh
python scripts/phone_cleanup.py                   # dry run
python scripts/phone_cleanup.py --apply           # saved restore snapshot, then disable
python scripts/phone_cleanup.py --restore         # return original states from that snapshot
```

Use `--serial` if multiple devices are attached and `--snapshot` to choose a private snapshot path. The default `.local/phone-cleanup.json` is gitignored and includes the handset serial and exact states changed. Restore uses `pm default-state` for previously default-enabled packages, or `pm enable` for explicitly enabled packages. A partial/interrupted apply is still recoverable using its snapshot.

This deliberately preserves Android/MediaTek telephony and IMS, default Messages and Dialer, SMS provider, SIM/carrier configuration, emergency alerts, Wi-Fi/mobile networking, captive portal, DNS/TLS components, Google Play Services/security components, Play Store, WebView, permission controller, Settings, launcher, SystemUI, keyboard, Keystore and Magisk. Individual internal Play Services/MediaTek services are not stripped because their dependencies aren't established here. Android Auto and Search are examples of optional apps with actual active background services on this phone; disabling them stops those services. Disabling idle optional apps prevents later scheduled background work but is not a measured battery/memory savings claim.

The relay does not require Google Play Services, but disabling that shared system dependency is a broader change with effects on updates/account/security behavior. This cleanup keeps it intact. Do not disable every package whose name includes `service` or `telephony`; many are essential to SMS/network recovery.

On 1 October 2026, cleanup disabled 15 enabled optional packages on the attached Nokia: Search, YouTube, Gmail, Calendar, Maps, Photos, Drive, Keep, Google One, Android Auto, Digital Wellbeing, three print packages and FM Radio. Assistant and Nokia support were already disabled and were left as found. The original-state snapshot is `.local/phone-cleanup.json`; run the restore command above to undo these 15 changes.
