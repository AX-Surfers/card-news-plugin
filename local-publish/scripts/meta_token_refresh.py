#!/usr/bin/env python3
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

FB_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")
FB_GRAPH = f"https://graph.facebook.com/{FB_GRAPH_VERSION}"
THREADS_GRAPH = "https://graph.threads.net/v1.0"
THREADS_OAUTH_BASE = "https://graph.threads.net"


def _read_token(key: str, file_key: str) -> str:
    direct = os.environ.get(key, "").strip()
    if direct:
        return direct
    p = os.environ.get(file_key, "").strip()
    if p and Path(p).exists():
        return Path(p).read_text(encoding="utf-8").strip()
    return ""


def _json_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode())


def refresh_threads_long_lived() -> dict:
    token = _read_token("THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN_FILE")
    token_file = os.environ.get("THREADS_ACCESS_TOKEN_FILE", "").strip()
    if not token:
        raise SystemExit("THREADS_ACCESS_TOKEN or THREADS_ACCESS_TOKEN_FILE is required")
    url = THREADS_OAUTH_BASE + '/refresh_access_token?' + urllib.parse.urlencode({
        'grant_type': 'th_refresh_token',
        'access_token': token,
    })
    payload = _json_get(url)
    new_token = payload.get('access_token')
    if new_token and token_file:
        Path(token_file).write_text(new_token, encoding='utf-8')
    return {**payload, 'token_saved_to_file': bool(new_token and token_file)}


def _read_plain_or_file_env(key: str, file_key: str) -> str:
    value = os.environ.get(key, '').strip()
    if value:
        return value
    file_path = os.environ.get(file_key, '').strip()
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding='utf-8').strip()
    return ''


def exchange_threads_long_lived() -> dict:
    token = _read_token('THREADS_ACCESS_TOKEN', 'THREADS_ACCESS_TOKEN_FILE')
    app_secret = _read_plain_or_file_env('META_APP_SECRET', 'META_APP_SECRET_FILE')
    token_file = os.environ.get('THREADS_ACCESS_TOKEN_FILE', '').strip()
    if not token or not app_secret:
        raise SystemExit('THREADS_ACCESS_TOKEN(or file) and META_APP_SECRET(or file) are required')
    url = THREADS_OAUTH_BASE + '/access_token?' + urllib.parse.urlencode({
        'grant_type': 'th_exchange_token',
        'client_secret': app_secret,
        'access_token': token,
    })
    payload = _json_get(url)
    new_token = payload.get('access_token')
    if new_token and token_file:
        Path(token_file).write_text(new_token, encoding='utf-8')
    return {**payload, 'token_saved_to_file': bool(new_token and token_file)}


def exchange_fb_long_lived() -> dict:
    app_id = os.environ.get('META_APP_ID', '').strip()
    app_secret = _read_plain_or_file_env('META_APP_SECRET', 'META_APP_SECRET_FILE')
    short_token = _read_token('FACEBOOK_SHORT_LIVED_USER_TOKEN', 'FACEBOOK_SHORT_LIVED_USER_TOKEN_FILE')
    if not app_id or not app_secret or not short_token:
        raise SystemExit('META_APP_ID, META_APP_SECRET, and FACEBOOK_SHORT_LIVED_USER_TOKEN(or file) are required')
    url = FB_GRAPH + '/oauth/access_token?' + urllib.parse.urlencode({
        'grant_type': 'fb_exchange_token',
        'client_id': app_id,
        'client_secret': app_secret,
        'fb_exchange_token': short_token,
    })
    return _json_get(url)


def explain_page_token_refresh() -> dict:
    return {
        'note': 'A page token cannot be independently refreshed with only the page token itself.',
        'required_for_automation': [
            'META_APP_ID',
            'META_APP_SECRET',
            'A renewable Facebook user token flow (short-lived -> long-lived), or a working non-expiring system-user setup'
        ],
        'recommended': 'Use a renewable long-lived Facebook user token to derive page/IG publishing access, or switch to a working system-user token if Meta permits the needed endpoints.'
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Meta token refresh helpers')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('refresh-threads')
    sub.add_parser('exchange-threads-long-lived-token')
    sub.add_parser('exchange-facebook-long-lived-user-token')
    sub.add_parser('explain-instagram-page-token-refresh')
    args = parser.parse_args()

    if args.cmd == 'refresh-threads':
        result = refresh_threads_long_lived()
    elif args.cmd == 'exchange-threads-long-lived-token':
        result = exchange_threads_long_lived()
    elif args.cmd == 'exchange-facebook-long-lived-user-token':
        result = exchange_fb_long_lived()
    elif args.cmd == 'explain-instagram-page-token-refresh':
        result = explain_page_token_refresh()
    else:
        raise SystemExit('unknown command')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error': str(e), 'type': type(e).__name__}, ensure_ascii=False), file=sys.stderr)
        raise
