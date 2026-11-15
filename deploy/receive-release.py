#!/usr/bin/env python3
"""Extract a bounded Git archive; reject path traversal, links and special files."""
import io
from pathlib import Path
import sys
import tarfile

root=Path(sys.argv[1]).resolve()
raw=sys.stdin.buffer.read(20*1024*1024+1)
if len(raw)>20*1024*1024: raise SystemExit('Release archive too large')
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    members=archive.getmembers()
    if len(members)>2000 or sum(m.size for m in members)>50*1024*1024: raise SystemExit('Release contents too large')
    for m in members:
        p=Path(m.name)
        if p.is_absolute() or '..' in p.parts or not (m.isfile() or m.isdir()): raise SystemExit('Unsafe archive member')
        target=(root/p).resolve()
        if not target.is_relative_to(root): raise SystemExit('Unsafe archive path')
    for m in members:
        target=root/m.name
        if m.isdir(): target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(m) as source,target.open('xb') as dest: dest.write(source.read())
            target.chmod(0o755 if m.mode & 0o111 else 0o644)
if not (root/'gateway/Dockerfile').is_file(): raise SystemExit('Missing gateway')
