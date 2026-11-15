#!/system/bin/sh
# Nokia 2.2 / mt6761 only. No remote input, boot module, current or voltage changes.
APP_PID=__APP_PID__
NODE=/proc/mtk_battery_cmd/current_cmd
CAPACITY=/sys/class/power_supply/battery/capacity
PARENT_NAME=/proc/$APP_PID/cmdline
BASE=/data/adb/fay-sms-relay
POLL=15
[ "$(id -u)" = 0 ] || { echo ROOT_REQUIRED; exit 1; }
[ -e "$NODE" ] || { echo UNSUPPORTED; exit 1; }
[ ! -L "$BASE" ] || { echo CONTROL_ERROR; exit 1; }
mkdir -p "$BASE" && chmod 700 "$BASE" || { echo CONTROL_ERROR; exit 1; }
LOCK=$BASE/charge.lock
# An old guardian releases its lock when the old app PID disappears.
tries=0
while ! mkdir "$LOCK" 2>/dev/null; do
    tries=$((tries+1))
    [ "$tries" -le 25 ] || { echo CONTROL_BUSY; exit 1; }
    sleep 1
    owner=$(cat "$LOCK/pid" 2>/dev/null)
    case "$owner" in '') [ "$tries" -lt 3 ] || rmdir "$LOCK" 2>/dev/null; continue;; *[!0-9]*) continue;; esac
    if ! kill -0 "$owner" 2>/dev/null; then rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null; fi
done
printf '%s\n' "$$" > "$LOCK/pid"
cleanup() {
    trap - EXIT HUP INT TERM
    flags=$(cat "$NODE" 2>/dev/null)
    case "$flags" in '0 1'|'1 1') printf '%s 0\n' "${flags% *}" > "$NODE";; esac
    rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null
    echo OFF
}
trap cleanup EXIT
trap 'exit' HUP INT TERM
previous=''
cycle=$(cat "$BASE/cycle" 2>/dev/null)
case "$cycle" in 0|1) ;; *) cycle='';; esac
while kill -0 "$APP_PID" 2>/dev/null && [ "$(head -c 128 "$PARENT_NAME" 2>/dev/null | tr '\000' '\n' | head -n 1)" = com.fay.smsrelay ]; do
    flags=$(cat "$NODE" 2>/dev/null)
    case "$flags" in '0 0'|'0 1'|'1 0'|'1 1') ;; *) echo CONTROL_ERROR; exit 1;; esac
    usb=${flags% *}; paused=${flags#* }
    level=$(cat "$CAPACITY" 2>/dev/null)
    case "$level" in ''|*[!0-9]*) echo CONTROL_ERROR; exit 1;; esac
    [ "$level" -le 100 ] || { echo CONTROL_ERROR; exit 1; }
    desired=${cycle:-$paused}
    [ "$level" -ge 80 ] && desired=1
    [ "$level" -le 60 ] && desired=0
    if [ "$desired" != "$cycle" ]; then
        printf '%s\n' "$desired" > "$BASE/cycle.tmp" && chmod 600 "$BASE/cycle.tmp" && mv -f "$BASE/cycle.tmp" "$BASE/cycle" || { echo CONTROL_ERROR; exit 1; }
        cycle=$desired
    fi
    if [ "$desired" != "$paused" ]; then
        printf '%s %s\n' "$usb" "$desired" > "$NODE" || { echo CONTROL_ERROR; exit 1; }
        [ "$(cat "$NODE")" = "$usb $desired" ] || { echo CONTROL_ERROR; exit 1; }
    fi
    state=CHARGING_LIMITED
    [ "$desired" = 1 ] && state=PAUSED_TO_60
    if [ "$state" != "$previous" ]; then echo "$state"; previous=$state; fi
    # STOP interrupts the wait. Parent death is checked at most 15 seconds later.
    instruction=''
    read -r -t "$POLL" instruction
    if [ "$instruction" = STOP ]; then rm -f "$BASE/cycle"; break; fi
done
