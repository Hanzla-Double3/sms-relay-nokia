#!/usr/bin/env python3
"""Reversible optional-app cleanup. No root, uninstalls, data deletion or core changes."""
import argparse
import json
from pathlib import Path
import re
import subprocess

OPTIONAL = {
    "com.google.android.googlequicksearchbox": "Google Search/voice assistant",
    "com.google.android.apps.googleassistant": "Google Assistant",
    "com.google.android.youtube": "YouTube",
    "com.google.android.gm": "Gmail",
    "com.google.android.calendar": "Google Calendar",
    "com.google.android.apps.maps": "Google Maps",
    "com.google.android.apps.photos": "Google Photos",
    "com.google.android.apps.docs": "Google Drive",
    "com.google.android.keep": "Google Keep",
    "com.google.android.apps.subscriptions.red": "Google One",
    "com.google.android.projection.gearhead": "Android Auto",
    "com.google.android.apps.wellbeing": "Digital Wellbeing",
    "com.android.printspooler": "Print spooler",
    "com.android.bips": "Built-in print service",
    "com.google.android.printservice.recommendation": "Print recommendation service",
    "com.hmdglobal.app.fmradio": "FM Radio",
    "com.hmdglobal.support": "Nokia support app",
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--snapshot", default=".local/phone-cleanup.json")
parser.add_argument("--restore", action="store_true")
args = parser.parse_args()
if args.apply and args.restore:
    parser.error("Choose apply or restore")
if not args.serial:
    found = [line.split()[0] for line in subprocess.check_output(["adb","devices"],text=True).splitlines()[1:] if len(line.split())>=2 and line.split()[1]=="device"]
    if len(found) != 1: parser.error("Connect exactly one authorized handset or supply --serial")
    args.serial = found[0]
base = ["adb","-s",args.serial]
def adb(*cmd): return subprocess.check_output(base+list(cmd),text=True,stderr=subprocess.STDOUT)
path = Path(args.snapshot)
if args.restore:
    data = json.loads(path.read_text())
    if data["serial"] != args.serial: parser.error("Snapshot belongs to a different handset")
    for pkg, state in data["changed"].items():
        if pkg not in OPTIONAL or state not in (0,1): parser.error("Invalid cleanup snapshot")
        print(adb("shell","pm","default-state" if state==0 else "enable","--user","0",pkg).strip())
    print("Original package enabled states restored; no app data was changed.")
else:
    installed=set(line.removeprefix("package:") for line in adb("shell","pm","list","packages","--user","0").splitlines())
    disabled=set(line.removeprefix("package:") for line in adb("shell","pm","list","packages","-d","--user","0").splitlines())
    selected={}
    for pkg,label in OPTIONAL.items():
        if pkg not in installed or pkg in disabled: continue
        details=adb("shell","dumpsys","package",pkg)
        match=re.search(r"User 0:.*?enabled=(\d+)",details)
        if not match or int(match[1]) not in (0,1): continue
        selected[pkg]=int(match[1])
        print(f"{'Disable' if args.apply else 'Would disable'}: {label} ({pkg})")
    if args.apply:
        if path.exists(): parser.error("Snapshot already exists; preserve it and choose a new snapshot path")
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        # Persist full original states before the first change, so interrupted runs can be restored.
        with path.open("x") as f: json.dump({"serial":args.serial,"changed":selected},f,indent=2)
        path.chmod(0o600)
        for pkg in selected:
            result=adb("shell","pm","disable-user","--user","0",pkg)
            if "disabled-user" not in result: raise RuntimeError(f"Disable failed for {pkg}; restore using the snapshot")
        print(f"Disabled {len(selected)} optional packages; restore snapshot: {path}")
    else:
        print(f"Dry run: {len(selected)} optional packages. Use --apply to disable with a restore snapshot.")
