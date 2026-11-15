"""Device-authenticated, fixed-path signed release distribution. No remote shell input."""
import hmac
import json
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from .config import digest

RELEASE_DIR = Path(__file__).with_name('updates')

def release_info():
    try:
        envelope=json.loads((RELEASE_DIR/'manifest.json').read_text())
        payload=json.loads(__import__('base64').b64decode(envelope['payload'],validate=True))
        if not (RELEASE_DIR/'relay.apk').is_file(): return None
        return {k:payload[k] for k in ('version_code','version_name','sha256','size')}
    except (OSError,ValueError,KeyError,TypeError): return None

def register_device_updates(app,settings,store):
    def authenticated(request,device):
        auth=request.headers.get('authorization','')
        expected=settings.devices.get(device)
        if not expected or not auth.startswith('Bearer ') or len(auth)>300 or not hmac.compare_digest(digest(auth[7:]),expected):
            raise HTTPException(401,'UNAUTHORIZED')

    @app.get('/v1/device/update')
    async def check(request: Request,device: str,version_code: int):
        authenticated(request,device)
        release=release_info()
        if not release: return Response(status_code=204)
        if version_code>=release['version_code']:
            store.db.execute('DELETE FROM update_requests WHERE device=?',(device,))
            return Response(status_code=204)
        if not store.db.execute('SELECT 1 FROM update_requests WHERE device=?',(device,)).fetchone(): return Response(status_code=204)
        return JSONResponse(json.loads((RELEASE_DIR/'manifest.json').read_text()),headers={'Cache-Control':'no-store'})

    @app.get('/v1/device/update/apk')
    async def apk(request: Request,device: str):
        authenticated(request,device)
        if not release_info(): raise HTTPException(404,'NO_RELEASE_AVAILABLE')
        return FileResponse(RELEASE_DIR/'relay.apk',media_type='application/vnd.android.package-archive',headers={'Cache-Control':'no-store'})
