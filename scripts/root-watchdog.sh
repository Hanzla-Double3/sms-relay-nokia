#!/system/bin/sh
# Optional /data/adb/service.d/sms-relay.sh. Requires an explicit local opt-in file.
# Never modifies the OS, packages, SELinux, modem or SMS database.
(
  while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 15; done
  while true; do
    if [ -f /data/adb/sms-relay-watchdog.enabled ]; then
      if ! dumpsys activity services com.fay.smsrelay 2>/dev/null | grep -q 'isForeground=true'; then
        am start-foreground-service -n com.fay.smsrelay/.RelayService >/dev/null 2>&1
      fi
    fi
    sleep 60
  done
) &
