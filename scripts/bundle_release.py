#!/usr/bin/env python3
"""Combine tracked source and the signed APK without including CI credentials."""
import io
import subprocess
import tarfile
from pathlib import Path
import sys
source=subprocess.check_output(['git','archive','--format=tar','HEAD'])
with tarfile.open(fileobj=io.BytesIO(source),mode='r:') as original,tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as output:
    for member in original:
        output.addfile(member,original.extractfile(member) if member.isfile() else None)
    for name in ('manifest.json','relay.apk'):
        output.add(Path('ota-release')/name,arcname='gateway/relay/updates/'+name,recursive=False)
