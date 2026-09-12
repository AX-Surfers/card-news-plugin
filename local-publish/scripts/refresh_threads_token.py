#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

THREADS_BASE = 'https://graph.threads.net/v1.0'


def read_token() -> tuple[str, Path]:
    direct = os.environ.get('THREADS_ACCESS_TOKEN', '').strip()
    if direct:
        return direct, Path('')
    file_path = os.environ.get('THREADS_ACCESS_TOKEN_FILE', '').strip()
    if not file_path:
        raise SystemExit('THREADS_ACCESS_TOKEN_FILE or THREADS_ACCESS_TOKEN is required')
    path = Path(file_path)
    if not path.exists():
        raise SystemExit(f'token file not found: {path}')
    return path.read_text(encoding='utf-8').strip(), path


def refresh(token: str) -> dict:
    url = THREADS_BASE + '/refresh_access_token?' + urllib.parse.urlencode({
        'grant_type': 'th_refresh_token',
        'access_token': token,
    })
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    token, token_path = read_token()
    payload = refresh(token)
    new_token = payload.get('access_token')
    if new_token and token_path:
        token_path.write_text(new_token, encoding='utf-8')
    meta = {
        'refreshed_at': int(time.time()),
        'expires_in': payload.get('expires_in'),
        'token_updated': bool(new_token and token_path),
    }
    meta_path = Path('/opt/data/.secrets/threads_access_token_meta.json')
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, **meta}, ensure_ascii=False))


if __name__ == '__main__':
    main()
