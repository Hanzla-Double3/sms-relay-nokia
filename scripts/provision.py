#!/usr/bin/env python3
"""Generate private local credentials. Raw tokens are never printed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument("--output", default=".local")
parser.add_argument("--recipient", action="append", default=[], help="Authorized E.164 test recipient; repeat for allowlist")
parser.add_argument("--production", action="store_true", help="Require TLS (default is loopback development)")
args = parser.parse_args()
import re
if any(not re.fullmatch(r"\+[1-9][0-9]{7,14}", n) for n in args.recipient):
    parser.error("Recipients must use E.164")
output = Path(args.output)
output.mkdir(mode=0o700,parents=True,exist_ok=True)
if (output/"credentials.json").exists() or (output/"gateway.env").exists():
    parser.error("Output already has credentials; choose a new directory for rotation")
tokens = {name: secrets.token_urlsafe(32) for name in ("server-b","operator","nokia-01")}
def hashed(name): return hashlib.sha256(tokens[name].encode()).hexdigest()
callers={"server-b":{"token_sha256":hashed("server-b"),"devices":["nokia-01"],"admin":False},"operator":{"token_sha256":hashed("operator"),"devices":["nokia-01"],"admin":True}}
values={"RELAY_DATABASE":str(output/"relay.sqlite3"),"RELAY_CALLERS_JSON":json.dumps(callers),"RELAY_DEVICES_JSON":json.dumps({"nokia-01":hashed("nokia-01")}),"RELAY_ALLOW_INSECURE_LOCAL":str(not args.production).lower(),"RELAY_RECIPIENT_ALLOWLIST":json.dumps(args.recipient)}
for filename, contents in [("credentials.json",json.dumps(tokens,indent=2)+"\n"),("gateway.env","".join(f"{k}='{v}'\n" for k,v in values.items()))]:
    fd=os.open(output/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f: f.write(contents)
print(f"Private credentials saved in {output}/credentials.json; gateway config in {output}/gateway.env")
print("Do not commit these files. Set a recipient allowlist before real SMS testing.")
