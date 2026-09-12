#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
THREADS_BASE = "https://graph.threads.net/v1.0"


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8").strip()


def _read_token_from_env(key: str, file_key: str) -> str:
    direct = os.environ.get(key, "").strip()
    if direct:
        return direct
    file_path = os.environ.get(file_key, "").strip()
    if file_path and Path(file_path).exists():
        return Path(file_path).read_text(encoding="utf-8").strip()
    return ""


def _read_lines(path: str) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")


def _media_kind(url: str) -> str:
    """Classify a carousel item URL as VIDEO or IMAGE by its path extension.

    Query strings are ignored so signed/public URLs like `...0_thumbnail.mp4?x=1`
    still resolve correctly.
    """
    path = urllib.parse.urlparse(url).path.lower()
    return "VIDEO" if path.endswith(VIDEO_EXTS) else "IMAGE"


def _parse_media_item(line: str) -> tuple[str, str]:
    """Parse one urls-file line into (kind, url).

    Extensionless hosts (e.g. Google Drive `uc?id=...`) can't be classified by
    extension, so an explicit prefix wins: `video <url>` / `image <url>`, or
    `video:<url>` / `image:<url>`. Without a prefix, fall back to the extension.
    """
    stripped = line.strip()
    low = stripped.lower()
    for kind in ("video", "image"):
        if low.startswith(f"{kind} ") or low.startswith(f"{kind}:"):
            url = stripped[len(kind):].lstrip(": ").strip()
            return kind.upper(), url
    return _media_kind(stripped), stripped


def _json_request(method: str, url: str, *, data: dict | None = None, headers: dict | None = None) -> dict:
    body = None
    req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        req_headers.update(headers)
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {error_body}") from exc
    return json.loads(raw)


def _graph_get(path: str, token: str, params: dict | None = None) -> dict:
    params = params or {}
    params["access_token"] = token
    url = GRAPH_BASE + path + "?" + urllib.parse.urlencode(params)
    return _json_request("GET", url)


def _graph_post(path: str, token: str, params: dict) -> dict:
    params = params.copy()
    params["access_token"] = token
    return _json_request("POST", GRAPH_BASE + path, data=params)


def _threads_get(path: str, token: str, params: dict | None = None) -> dict:
    params = params or {}
    params["access_token"] = token
    url = THREADS_BASE + path + "?" + urllib.parse.urlencode(params)
    return _json_request("GET", url)


def _threads_post(path: str, token: str, params: dict) -> dict:
    params = params.copy()
    params["access_token"] = token
    return _json_request("POST", THREADS_BASE + path, data=params)


def verify_instagram() -> dict:
    token = _read_token_from_env("INSTAGRAM_GRAPH_TOKEN", "INSTAGRAM_GRAPH_TOKEN_FILE") or _read_token_from_env("META_GRAPH_ACCESS_TOKEN", "META_GRAPH_ACCESS_TOKEN_FILE")
    ig_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not token or not ig_id:
        raise SystemExit("INSTAGRAM_GRAPH_TOKEN(or META_GRAPH_ACCESS_TOKEN) and INSTAGRAM_BUSINESS_ACCOUNT_ID are required")
    profile = _graph_get(f"/{ig_id}", token, {"fields": "id,username,name,profile_picture_url,followers_count,media_count"})
    try:
        limit = _graph_get(f"/{ig_id}/content_publishing_limit", token, {"fields": "quota_usage,config"})
    except Exception as e:
        limit = {"warning": f"content_publishing_limit check failed: {e}"}
    return {"profile": profile, "publishing_limit": limit}


def _poll_instagram_container(container_id: str, token: str, *, timeout: int = 300) -> dict:
    started = time.time()
    while True:
        status = _graph_get(f"/{container_id}", token, {"fields": "id,status_code,status"})
        code = status.get("status_code") or status.get("status")
        if code in {"FINISHED", "PUBLISHED"}:
            return status
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram container {container_id} failed: {status}")
        if time.time() - started > timeout:
            raise TimeoutError(f"Instagram container {container_id} not ready after {timeout}s: {status}")
        time.sleep(5)


def publish_instagram_single(image_url: str, caption: str) -> dict:
    token = _read_token_from_env("INSTAGRAM_GRAPH_TOKEN", "INSTAGRAM_GRAPH_TOKEN_FILE") or _read_token_from_env("META_GRAPH_ACCESS_TOKEN", "META_GRAPH_ACCESS_TOKEN_FILE")
    ig_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not token or not ig_id:
        raise SystemExit("INSTAGRAM_GRAPH_TOKEN(or META_GRAPH_ACCESS_TOKEN) and INSTAGRAM_BUSINESS_ACCOUNT_ID are required")
    creation = _graph_post(f"/{ig_id}/media", token, {"image_url": image_url, "caption": caption})
    creation_id = creation["id"]
    _poll_instagram_container(creation_id, token)
    published = _graph_post(f"/{ig_id}/media_publish", token, {"creation_id": creation_id})
    return {"creation": creation, "published": published}


def publish_instagram_carousel(image_urls: list[str], caption: str) -> dict:
    token = _read_token_from_env("INSTAGRAM_GRAPH_TOKEN", "INSTAGRAM_GRAPH_TOKEN_FILE") or _read_token_from_env("META_GRAPH_ACCESS_TOKEN", "META_GRAPH_ACCESS_TOKEN_FILE")
    ig_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not token or not ig_id:
        raise SystemExit("INSTAGRAM_GRAPH_TOKEN(or META_GRAPH_ACCESS_TOKEN) and INSTAGRAM_BUSINESS_ACCOUNT_ID are required")
    if len(image_urls) < 2:
        raise SystemExit("Instagram carousel requires at least 2 media URLs")
    video_timeout = int(os.environ.get("INSTAGRAM_VIDEO_CONTAINER_TIMEOUT", "600"))
    child_ids = []
    child_results = []
    for line in image_urls:
        kind, media_url = _parse_media_item(line)
        if kind == "VIDEO":
            child = _graph_post(f"/{ig_id}/media", token, {
                "media_type": "VIDEO",
                "video_url": media_url,
                "is_carousel_item": "true",
            })
            child_id = child["id"]
            # 동영상 컨테이너는 트랜스코딩 때문에 이미지보다 오래 걸린다
            _poll_instagram_container(child_id, token, timeout=video_timeout)
        else:
            child = _graph_post(f"/{ig_id}/media", token, {"image_url": media_url, "is_carousel_item": "true"})
            child_id = child["id"]
            _poll_instagram_container(child_id, token)
        child_ids.append(child_id)
        child_results.append(child)
    parent = _graph_post(f"/{ig_id}/media", token, {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
    })
    parent_id = parent["id"]
    _poll_instagram_container(parent_id, token)
    published = _graph_post(f"/{ig_id}/media_publish", token, {"creation_id": parent_id})
    return {"children": child_results, "parent": parent, "published": published}


def comment_instagram_media(media_id: str, message: str) -> dict:
    """Post a top-level comment on an existing IG media (post-publish).

    Note: the Graph API has no pin endpoint — pinning a comment is a manual,
    in-app-only action (long-press → Pin), limited to 3 pins per post.
    """
    token = _read_token_from_env("INSTAGRAM_GRAPH_TOKEN", "INSTAGRAM_GRAPH_TOKEN_FILE") or _read_token_from_env("META_GRAPH_ACCESS_TOKEN", "META_GRAPH_ACCESS_TOKEN_FILE")
    if not token:
        raise SystemExit("INSTAGRAM_GRAPH_TOKEN(or META_GRAPH_ACCESS_TOKEN) is required")
    return _graph_post(f"/{media_id}/comments", token, {"message": message})


def verify_threads() -> dict:
    token = _read_token_from_env("THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN_FILE")
    if not token:
        raise SystemExit("THREADS_ACCESS_TOKEN or THREADS_ACCESS_TOKEN_FILE is required")
    me = _threads_get("/me", token, {"fields": "id,username,name"})
    try:
        limit = _threads_get("/me/threads_publishing_limit", token, {"fields": "quota_usage,config"})
    except Exception as e:
        limit = {"warning": f"threads_publishing_limit check failed: {e}"}
    return {"me": me, "publishing_limit": limit}


def _threads_publish_with_wait(user_id: str, token: str, creation_id: str, *, wait_seconds: int = 30) -> dict:
    time.sleep(wait_seconds)
    return _threads_post(f"/{user_id}/threads_publish", token, {"creation_id": creation_id})


def _wait_for_threads_children_ready(wait_seconds: int = 30) -> None:
    if wait_seconds > 0:
        time.sleep(wait_seconds)


def _poll_threads_container(container_id: str, token: str, *, timeout: int = 600) -> dict:
    """Poll a Threads media container until it finishes processing.

    Needed for video children, which transcode asynchronously; a fixed sleep is
    not reliable. Images usually report FINISHED almost immediately.
    """
    started = time.time()
    while True:
        status = _threads_get(f"/{container_id}", token, {"fields": "id,status,error_message"})
        code = status.get("status")
        if code in {"FINISHED", "PUBLISHED"}:
            return status
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Threads container {container_id} failed: {status}")
        if time.time() - started > timeout:
            raise TimeoutError(f"Threads container {container_id} not ready after {timeout}s: {status}")
        time.sleep(5)


def publish_threads_text(text: str) -> dict:
    token = _read_token_from_env("THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN_FILE")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise SystemExit("THREADS_ACCESS_TOKEN(or file) and THREADS_USER_ID are required")
    creation = _threads_post(f"/{user_id}/threads", token, {"media_type": "TEXT", "text": text})
    creation_id = creation["id"]
    published = _threads_publish_with_wait(user_id, token, creation_id)
    return {"creation": creation, "published": published}


def publish_threads_image(text: str, image_url: str) -> dict:
    token = _read_token_from_env("THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN_FILE")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise SystemExit("THREADS_ACCESS_TOKEN(or file) and THREADS_USER_ID are required")
    creation = _threads_post(f"/{user_id}/threads", token, {"media_type": "IMAGE", "text": text, "image_url": image_url})
    creation_id = creation["id"]
    published = _threads_publish_with_wait(user_id, token, creation_id)
    return {"creation": creation, "published": published}


def publish_threads_carousel(text: str, image_urls: list[str]) -> dict:
    token = _read_token_from_env("THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN_FILE")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise SystemExit("THREADS_ACCESS_TOKEN(or file) and THREADS_USER_ID are required")
    if len(image_urls) < 2:
        raise SystemExit("Threads carousel requires at least 2 media URLs")
    if len(image_urls) > 20:
        raise SystemExit("Threads carousel supports at most 20 media URLs")

    video_timeout = int(os.environ.get("THREADS_VIDEO_CONTAINER_TIMEOUT", "600"))
    child_results = []
    child_ids = []
    has_video = False
    for line in image_urls:
        kind, media_url = _parse_media_item(line)
        if kind == "VIDEO":
            has_video = True
            child = _threads_post(f"/{user_id}/threads", token, {
                "media_type": "VIDEO",
                "video_url": media_url,
                "is_carousel_item": "true",
            })
        else:
            child = _threads_post(f"/{user_id}/threads", token, {
                "media_type": "IMAGE",
                "image_url": media_url,
                "is_carousel_item": "true",
            })
        child_results.append(child)
        child_ids.append(child["id"])

    if has_video:
        # 동영상 자식은 트랜스코딩이 끝나야 부모에 묶을 수 있다 → 상태 폴링
        for child_id in child_ids:
            _poll_threads_container(child_id, token, timeout=video_timeout)
    else:
        _wait_for_threads_children_ready(int(os.environ.get("THREADS_CAROUSEL_CHILD_READY_WAIT", "30")))

    parent = _threads_post(f"/{user_id}/threads", token, {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "text": text,
    })
    published = _threads_publish_with_wait(user_id, token, parent["id"])
    return {"children": child_results, "parent": parent, "published": published}


def main() -> None:
    parser = argparse.ArgumentParser(description="Instagram/Threads publishing helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("verify-instagram")
    sub.add_parser("verify-threads")

    p1 = sub.add_parser("publish-instagram-single")
    p1.add_argument("--image-url", required=True)
    p1.add_argument("--caption-file")
    p1.add_argument("--caption")

    p2 = sub.add_parser("publish-instagram-carousel")
    p2.add_argument("--image-urls-file", required=True, help="newline-delimited public media URLs (image or video; .mp4/.mov/.m4v/.webm → video item)")
    p2.add_argument("--caption-file")
    p2.add_argument("--caption")

    p1b = sub.add_parser("comment-instagram")
    p1b.add_argument("--media-id", required=True)
    p1b.add_argument("--message-file")
    p1b.add_argument("--message")

    p3 = sub.add_parser("publish-threads-text")
    p3.add_argument("--text-file")
    p3.add_argument("--text")

    p4 = sub.add_parser("publish-threads-image")
    p4.add_argument("--image-url", required=True)
    p4.add_argument("--text-file")
    p4.add_argument("--text")

    p5 = sub.add_parser("publish-threads-carousel")
    p5.add_argument("--image-urls-file", required=True, help="newline-delimited public media URLs (image or video; .mp4/.mov/.m4v/.webm → video item)")
    p5.add_argument("--text-file")
    p5.add_argument("--text")

    args = parser.parse_args()
    if args.cmd == "verify-instagram":
        result = verify_instagram()
    elif args.cmd == "verify-threads":
        result = verify_threads()
    elif args.cmd == "publish-instagram-single":
        caption = args.caption or _read_text(args.caption_file)
        result = publish_instagram_single(args.image_url, caption)
    elif args.cmd == "publish-instagram-carousel":
        caption = args.caption or _read_text(args.caption_file)
        result = publish_instagram_carousel(_read_lines(args.image_urls_file), caption)
    elif args.cmd == "comment-instagram":
        message = args.message or _read_text(args.message_file)
        result = comment_instagram_media(args.media_id, message)
    elif args.cmd == "publish-threads-text":
        text = args.text or _read_text(args.text_file)
        result = publish_threads_text(text)
    elif args.cmd == "publish-threads-image":
        text = args.text or _read_text(args.text_file)
        result = publish_threads_image(text, args.image_url)
    elif args.cmd == "publish-threads-carousel":
        text = args.text or _read_text(args.text_file)
        result = publish_threads_carousel(text, _read_lines(args.image_urls_file))
    else:
        raise SystemExit(f"Unknown command: {args.cmd}")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False), file=sys.stderr)
        raise
