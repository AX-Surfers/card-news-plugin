#!/usr/bin/env python3
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

FB_GRAPH_VERSION = os.environ.get('META_GRAPH_VERSION', 'v23.0')
FB_GRAPH = f'https://graph.facebook.com/{FB_GRAPH_VERSION}'


def read_text(path: str) -> str:
    return Path(path).read_text(encoding='utf-8').strip()


def main() -> None:
    token_file = os.environ.get('INSTAGRAM_GRAPH_TOKEN_FILE', '').strip()
    app_id = os.environ.get('META_APP_ID', '').strip()
    secret_file = os.environ.get('META_APP_SECRET_FILE', '').strip()
    warn_days = int(os.environ.get('INSTAGRAM_TOKEN_WARN_DAYS', '14'))
    if not token_file or not app_id or not secret_file:
        raise SystemExit('INSTAGRAM_GRAPH_TOKEN_FILE, META_APP_ID, META_APP_SECRET_FILE are required')
    input_token = read_text(token_file)
    app_secret = read_text(secret_file)
    app_token = f'{app_id}|{app_secret}'
    url = FB_GRAPH + '/debug_token?' + urllib.parse.urlencode({'input_token': input_token, 'access_token': app_token})
    with urllib.request.urlopen(url, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    data = payload['data']
    expires_at = data.get('data_access_expires_at') or 0
    now = int(time.time())
    days_left = (expires_at - now) / 86400 if expires_at else None
    meta = {
        'checked_at': now,
        'data_access_expires_at': expires_at,
        'days_left': days_left,
        'is_valid': data.get('is_valid'),
        'type': data.get('type'),
        'profile_id': data.get('profile_id'),
        'user_id': data.get('user_id'),
    }
    Path('/opt/data/.secrets/instagram_token_health.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    if days_left is not None and days_left <= warn_days:
        print(json.dumps({'warning': 'Instagram/Page token data access expiry approaching', **meta}, ensure_ascii=False))


if __name__ == '__main__':
    main()
