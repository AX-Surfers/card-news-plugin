#!/usr/bin/env python3
import fcntl
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WORKDIR = Path("/opt/data/work/card-news-output/2026-06-17-ai-literacy-workflow-v2")
MANIFEST = WORKDIR / "workflow_manifest.json"
LOCKFILE = WORKDIR / ".publish_watch.lock"
PUBLISH_MARKER = WORKDIR / ".publish_completed.json"
REACTION_MARKER = WORKDIR / ".check_reaction_done"
APPROVAL_MARKER = WORKDIR / ".slack_approval.json"
RESULT_JSON = WORKDIR / "publish_result.json"
NOTION_VERSION = "2022-06-28"
SLACK_REACTION = "white_check_mark"
APPROVAL_PATTERNS = [
    re.compile(r"(^|\s)승인(\s|$)"),
    re.compile(r"(^|\s)배포(\s|$)"),
    re.compile(r"(^|\s)approve(d)?(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)publish(\s|$)", re.IGNORECASE),
]


def load_env(path: str = "/opt/data/.env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def notion_token() -> str:
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")
    if not token:
        raise SystemExit("NOTION_API_KEY or NOTION_API_TOKEN is required")
    return token


def slack_token() -> str:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise SystemExit("SLACK_BOT_TOKEN is required")
    return token


def notion_page_id(ref: str) -> str:
    m = re.search(r"([0-9a-fA-F]{32})", ref)
    if not m:
        raise SystemExit(f"could not parse notion page id from {ref}")
    return m.group(1)


def notion_request(method: str, url: str, body: dict | None = None) -> dict:
    token = notion_token()
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def slack_api(method: str, payload: dict) -> dict:
    token = slack_token()
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    if not data.get("ok") and data.get("error") != "already_reacted":
        raise RuntimeError(f"Slack API {method} failed: {data}")
    return data


def get_page(page_ref: str) -> dict:
    page_id = notion_page_id(page_ref)
    return notion_request("GET", f"https://api.notion.com/v1/pages/{page_id}")


def update_status(page_ref: str, status: str) -> None:
    page_id = notion_page_id(page_ref)
    notion_request(
        "PATCH",
        f"https://api.notion.com/v1/pages/{page_id}",
        {"properties": {"검수 상태": {"select": {"name": status}}}},
    )


def current_status(page: dict) -> str:
    prop = page.get("properties", {}).get("검수 상태")
    if not prop:
        raise SystemExit("Notion page missing 검수 상태 property")
    if prop.get("type") == "select":
        return (prop.get("select") or {}).get("name", "")
    if prop.get("type") == "status":
        return (prop.get("status") or {}).get("name", "")
    raise SystemExit(f"unsupported 검수 상태 type: {prop.get('type')}")


def get_page_url() -> str:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    notion = manifest.get("notion") or {}
    page_url = notion.get("page_url")
    if not page_url:
        page_url = manifest.get("review", {}).get("page_url")
    if not page_url:
        raise SystemExit("workflow_manifest.json must include notion.page_url")
    return page_url


def get_review_message() -> tuple[str, str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    review = manifest.get("review") or {}
    channel = review.get("channel") or ""
    message_id = review.get("message_id") or ""
    if channel.startswith("slack:"):
        channel = channel.split(":", 1)[1]
    if not channel:
        raise SystemExit("workflow_manifest.json must include review.channel")
    if not message_id:
        raise SystemExit("workflow_manifest.json must include review.message_id")
    return channel, message_id


def add_check_reaction() -> dict:
    channel, message_id = get_review_message()
    try:
        return slack_api("reactions.add", {"channel": channel, "timestamp": message_id, "name": SLACK_REACTION})
    except RuntimeError as exc:
        if "missing_scope" not in str(exc):
            raise
        root = get_thread_replies()[0]
        text = root.get("text") or ""
        if "✅ 게시 완료" not in text:
            text = text.rstrip() + "\n\n✅ 게시 완료"
        return slack_api("chat.update", {"channel": channel, "ts": message_id, "text": text})


def normalize_reply_text(text: str) -> str:
    return re.sub(r"<@[^>]+>", " ", text or "").strip()


def approval_user_allowlist() -> set[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    review = manifest.get("review") or {}
    raw_ids = review.get("approver_user_ids") or os.environ.get("SLACK_CARDNEWS_APPROVER_USER_IDS", "")
    if isinstance(raw_ids, list):
        return {str(x).strip() for x in raw_ids if str(x).strip()}
    return {x.strip() for x in str(raw_ids).split(",") if x.strip()}


def get_thread_replies() -> list[dict]:
    channel, message_id = get_review_message()
    data = slack_api("conversations.replies", {"channel": channel, "ts": message_id, "limit": 200})
    return data.get("messages") or []


def find_slack_approval() -> dict | None:
    allowlist = approval_user_allowlist()
    channel, message_id = get_review_message()
    for reply in get_thread_replies()[1:]:
        if reply.get("subtype") == "bot_message" or reply.get("bot_id"):
            continue
        user = reply.get("user") or ""
        if allowlist and user not in allowlist:
            continue
        text = normalize_reply_text(reply.get("text") or "")
        if not text:
            continue
        if any(pattern.search(text) for pattern in APPROVAL_PATTERNS):
            return {
                "approved": True,
                "approval_source": "slack_thread_reply",
                "channel": channel,
                "thread_ts": message_id,
                "reply_ts": reply.get("ts"),
                "approved_by": user,
                "approved_text": text,
                "approved_at": reply.get("ts"),
            }
    return None


def run_publish(page_url: str, approval: dict | None = None) -> dict:
    caption = WORKDIR / "instagram_caption.txt"
    image_urls = WORKDIR / "instagram_image_urls.txt"
    threads_text = WORKDIR / "threads_text.txt"
    threads_urls = WORKDIR / "threads_image_urls.txt"

    cmd = [
        "python3",
        "/opt/data/scripts/post_card_news_social.py",
        "--instagram-caption-file", str(caption),
        "--instagram-image-urls-file", str(image_urls),
        "--threads-text-file", str(threads_text),
        "--threads-image-urls-file", str(threads_urls),
        "--result-json", str(RESULT_JSON),
    ]
    if approval:
        APPROVAL_MARKER.write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd.extend(["--approval-manifest", str(APPROVAL_MARKER)])
    else:
        cmd.extend(["--notion-page", page_url])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "publish failed")
    return json.loads(proc.stdout)


def publish_marker_exists() -> bool:
    return PUBLISH_MARKER.exists() or RESULT_JSON.exists()


def reaction_marker_exists() -> bool:
    return REACTION_MARKER.exists()


def write_publish_marker(result: dict) -> None:
    PUBLISH_MARKER.write_text(json.dumps({"published": True, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_publish_result() -> dict | None:
    if RESULT_JSON.exists():
        return json.loads(RESULT_JSON.read_text(encoding="utf-8"))
    if PUBLISH_MARKER.exists():
        marker = json.loads(PUBLISH_MARKER.read_text(encoding="utf-8"))
        return marker.get("result")
    return None


def write_reaction_marker(result: dict) -> None:
    REACTION_MARKER.write_text(json.dumps({"reaction": SLACK_REACTION, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_published_and_reacted(page_url: str, status: str) -> None:
    slack_approval = find_slack_approval()

    if status == "Published" and reaction_marker_exists():
        return

    if status == "Published" and not reaction_marker_exists():
        reaction_result = add_check_reaction()
        write_reaction_marker(reaction_result)
        return

    if status != "Approved" and not slack_approval:
        return

    if publish_marker_exists():
        existing_result = load_existing_publish_result()
        if existing_result and not PUBLISH_MARKER.exists():
            write_publish_marker(existing_result)
        update_status(page_url, "Published")
        reaction_result = add_check_reaction()
        write_reaction_marker(reaction_result)
        return

    if slack_approval and status != "Approved":
        update_status(page_url, "Approved")

    publish_result = run_publish(page_url, slack_approval)
    write_publish_marker(publish_result)
    update_status(page_url, "Published")
    reaction_result = add_check_reaction()
    write_reaction_marker(reaction_result)


def main() -> int:
    load_env()
    if not MANIFEST.exists():
        return 0

    page_url = get_page_url()
    with open(LOCKFILE, "a+") as lock_fp:
        fcntl.flock(lock_fp, fcntl.LOCK_EX)
        page = get_page(page_url)
        status = current_status(page)
        ensure_published_and_reacted(page_url, status)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        print(json.dumps({"error": body or exc.reason, "http_status": exc.code}, ensure_ascii=False), file=sys.stderr)
        raise
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        raise
