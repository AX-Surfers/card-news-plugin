#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DRIVE_API = 'https://www.googleapis.com/drive/v3'
UPLOAD_API = 'https://www.googleapis.com/upload/drive/v3/files'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/drive'


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def load_service_account(path: str | None = None) -> dict:
    path = path or os.environ.get('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE', '').strip()
    if not path:
        raise SystemExit('GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE is required')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sign_rs256(message: bytes, key_pem: str) -> bytes:
    key_path = Path('/tmp') / f'gdrive-key-{uuid.uuid4().hex}.pem'
    key_path.write_text(key_pem, encoding='utf-8')
    try:
        proc = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-sign', str(key_path)],
            input=message,
            capture_output=True,
            check=True,
        )
        return proc.stdout
    finally:
        try:
            key_path.unlink()
        except FileNotFoundError:
            pass


def get_access_token(sa: dict) -> tuple[str, int]:
    now = int(time.time())
    header = {'alg': 'RS256', 'typ': 'JWT'}
    claim = {
        'iss': sa['client_email'],
        'scope': SCOPE,
        'aud': sa.get('token_uri', TOKEN_URI),
        'exp': now + 3600,
        'iat': now,
    }
    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(claim, separators=(',', ':')).encode())}".encode()
    signature = sign_rs256(signing_input, sa['private_key'])
    assertion = signing_input.decode() + '.' + b64url(signature)
    data = urllib.parse.urlencode({
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'assertion': assertion,
    }).encode()
    req = urllib.request.Request(sa.get('token_uri', TOKEN_URI), data=data, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    return payload['access_token'], int(payload.get('expires_in', 3600))


def api_request(method: str, url: str, token: str, body: bytes | None = None, content_type: str | None = None) -> dict:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Authorization', f'Bearer {token}')
    if content_type:
        req.add_header('Content-Type', content_type)
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else {}


def upload_file(path: Path, token: str, parent_id: str | None = None) -> dict:
    mime = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    meta = {'name': path.name}
    if parent_id:
        meta['parents'] = [parent_id]
    boundary = '===============%s==' % uuid.uuid4().hex
    parts = []
    parts.append(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.append(path.read_bytes())
    parts.append(f'\r\n--{boundary}--\r\n'.encode())
    body = b''.join(parts)
    url = UPLOAD_API + '?uploadType=multipart&supportsAllDrives=true&fields=id,name,mimeType,webViewLink,webContentLink'
    uploaded = api_request('POST', url, token, body, f'multipart/related; boundary={boundary}')
    file_id = uploaded['id']
    perm_url = f'{DRIVE_API}/files/{file_id}/permissions?supportsAllDrives=true'
    perm_body = json.dumps({'role': 'reader', 'type': 'anyone'}).encode()
    api_request('POST', perm_url, token, perm_body, 'application/json')
    meta_url = f'{DRIVE_API}/files/{file_id}?fields=id,name,webViewLink,webContentLink,thumbnailLink&supportsAllDrives=true'
    meta = api_request('GET', meta_url, token)
    meta['public_direct_url'] = f'https://drive.google.com/uc?id={file_id}'
    meta['public_view_url'] = f'https://drive.google.com/file/d/{file_id}/view?usp=sharing'
    return meta


def upload_many(paths: list[Path], token: str, parent_id: str | None = None) -> list[dict]:
    return [upload_file(p, token, parent_id) for p in paths]


def main() -> None:
    parser = argparse.ArgumentParser(description='Upload files to Google Drive and make them public')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p1 = sub.add_parser('upload-one')
    p1.add_argument('--file', required=True)
    p1.add_argument('--parent-id')

    p2 = sub.add_parser('upload-many')
    p2.add_argument('--files', nargs='+', required=True)
    p2.add_argument('--parent-id')

    p3 = sub.add_parser('upload-from-dir')
    p3.add_argument('--dir', required=True)
    p3.add_argument('--glob', default='*.png')
    p3.add_argument('--parent-id')

    args = parser.parse_args()
    sa = load_service_account()
    token, expires_in = get_access_token(sa)

    if args.cmd == 'upload-one':
        result = upload_file(Path(args.file), token, args.parent_id)
    elif args.cmd == 'upload-many':
        result = upload_many([Path(x) for x in args.files], token, args.parent_id)
    elif args.cmd == 'upload-from-dir':
        files = sorted(Path(args.dir).glob(args.glob))
        result = upload_many(files, token, args.parent_id)
    else:
        raise SystemExit('unknown command')

    print(json.dumps({'expires_in': expires_in, 'result': result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(json.dumps({'error': str(e), 'type': type(e).__name__}, ensure_ascii=False), file=sys.stderr)
        raise
