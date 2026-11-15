"""Execute the APK's real guardian script against isolated power-supply fixtures."""
import os
from pathlib import Path
import subprocess
import time
import pytest

SOURCE=Path(__file__).resolve().parents[2]/'android/app/src/main/res/raw/charge_guardian.sh'

@pytest.fixture
def guardian(tmp_path):
    node=tmp_path/'current_cmd';node.write_text('1 0\n')
    capacity=tmp_path/'capacity';capacity.write_text('80\n')
    parent=tmp_path/'parent';parent.write_bytes(b'com.fay.smsrelay\0'+b'\0'*65536)
    base=tmp_path/'root-private'
    script=SOURCE.read_text().replace('__APP_PID__',str(os.getpid())).replace('/proc/mtk_battery_cmd/current_cmd',str(node)).replace('/sys/class/power_supply/battery/capacity',str(capacity)).replace('/proc/$APP_PID/cmdline',str(parent)).replace('/data/adb/fay-sms-relay',str(base)).replace('[ "$(id -u)" = 0 ]','true')
    path=tmp_path/'guardian.sh';path.write_text(script)
    child=subprocess.Popen(['bash',str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    def check(level=None):
        if level is not None:capacity.write_text(str(level)+'\n')
        child.stdin.write('CHECK\n');child.stdin.flush()
    def expect(flags):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if node.read_text().strip()==flags:return
            time.sleep(.02)
        assert node.read_text().strip()==flags
    yield child,node,parent,capacity,check,expect,base
    if child.poll() is None:
        child.stdin.write('STOP\n');child.stdin.flush()
    child.communicate(timeout=3)


def test_real_guardian_hysteresis_and_stop_restore(guardian):
    child,node,parent,capacity,check,expect,base=guardian
    expect('1 1')
    check(70);time.sleep(.1);expect('1 1')
    check(60);expect('1 0')
    check(79);time.sleep(.1);expect('1 0')
    check(80);expect('1 1')
    child.stdin.write('STOP\n');child.stdin.flush();child.wait(timeout=3)
    expect('1 0')
    assert not (base/'charge.lock').exists()


def test_parent_exit_restores_normal_charging(guardian):
    child,node,parent,capacity,check,expect,base=guardian
    expect('1 1')
    parent.write_bytes(b'not-the-relay\0');check()
    child.wait(timeout=3);expect('1 0')


def test_invalid_battery_read_restores_normal_charging(guardian):
    child,node,parent,capacity,check,expect,base=guardian
    expect('1 1')
    capacity.write_text('invalid\n');check()
    child.wait(timeout=3);expect('1 0')


def test_cycle_survives_app_restart_between_thresholds(guardian):
    child,node,parent,capacity,check,expect,base=guardian
    expect('1 1')
    parent.write_bytes(b'not-the-relay\0');check()
    child.wait(timeout=3);expect('1 0')
    assert (base/'cycle').read_text().strip()=='1'
    parent.write_bytes(b'com.fay.smsrelay\0');capacity.write_text('70\n')
    restarted=subprocess.Popen(child.args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        expect('1 1')
        restarted.stdin.write('STOP\n');restarted.stdin.flush();restarted.wait(timeout=3)
        expect('1 0')
        assert not (base/'cycle').exists()
    finally:
        if restarted.poll() is None:restarted.stdin.write('STOP\n');restarted.stdin.flush()
        restarted.communicate(timeout=3)
