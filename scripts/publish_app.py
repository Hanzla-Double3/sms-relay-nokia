#!/usr/bin/env python3
"""Create a signed, fixed-path release bundle; private keys never enter the archive."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

p=argparse.ArgumentParser()
p.add_argument('--apk',required=True,type=Path)
p.add_argument('--key',required=True,type=Path)
p.add_argument('--code',required=True,type=int)
p.add_argument('--version',required=True)
p.add_argument('--out',required=True,type=Path)
a=p.parse_args()
if not 1<=a.apk.stat().st_size<=20_000_000: raise SystemExit('Invalid APK size')
payload=json.dumps(dict(package='com.fay.smsrelay',version_code=a.code,version_name=a.version,sha256=hashlib.sha256(a.apk.read_bytes()).hexdigest(),size=a.apk.stat().st_size),sort_keys=True,separators=(',',':')).encode()
with tempfile.TemporaryDirectory() as directory:
    raw=Path(directory)/'manifest'; raw.write_bytes(payload)
    signature=subprocess.check_output(['openssl','dgst','-sha256','-sign',str(a.key),str(raw)])
a.out.mkdir(parents=True,exist_ok=True)
shutil.copyfile(a.apk,a.out/'relay.apk')
(a.out/'manifest.json').write_text(json.dumps(dict(payload=base64.b64encode(payload).decode(),signature=base64.b64encode(signature).decode())))
