#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Local-run support: base dir that mirrors the old /opt/data layout.
# Override with CARDNEWS_DATA_ROOT; defaults to ~/.local/share/cardnews.
DATA_ROOT = Path(os.environ.get("CARDNEWS_DATA_ROOT", os.path.expanduser("~/.local/share/cardnews")))
SCRIPTS_DIR = Path(__file__).resolve().parent


def run(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {cmd}")
    return json.loads(proc.stdout)


def read_lines(path: str) -> list[str]:
    return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json_file(path: str) -> dict:
    payload_path = Path(path)
    if not payload_path.exists():
        raise SystemExit(f"file not found: {payload_path}")
    return json.loads(payload_path.read_text(encoding="utf-8"))


def load_approval(args: argparse.Namespace) -> dict:
    # Approval gate is a local JSON manifest (no Notion). It must assert an
    # explicit human/team sign-off before anything is posted.
    if not args.approval_manifest:
        raise SystemExit("--approval-manifest is required (publish is approval-gated)")
    payload = load_json_file(args.approval_manifest)
    if not payload.get("approved"):
        raise SystemExit("approval manifest exists but approved=false")
    if not payload.get("approval_source"):
        raise SystemExit("approval manifest must include approval_source (who approved)")
    if not payload.get("approved_at"):
        raise SystemExit("approval manifest must include approved_at (ISO timestamp)")
    return {"source": "manifest", **payload}


def main() -> None:
    p = argparse.ArgumentParser(description="Post one card-news bundle to Instagram and/or Threads after explicit approval")
    p.add_argument("--platform", choices=["both", "instagram", "threads"], default="both",
                    help="which platform(s) to publish to (default: both)")
    p.add_argument("--instagram-caption-file")
    p.add_argument("--instagram-image-urls-file", help="newline-delimited public URLs for carousel upload")
    p.add_argument("--threads-text-file")
    p.add_argument("--threads-image-urls-file", help="newline-delimited public URLs for Threads carousel upload")
    p.add_argument("--approval-manifest", required=True, help="JSON approval file: {approved:true, approval_source, approved_at}")
    p.add_argument("--result-json", help="optional path to store publish result JSON")
    args = p.parse_args()

    want_instagram = args.platform in ("both", "instagram")
    want_threads = args.platform in ("both", "threads")

    if want_instagram and not (args.instagram_caption_file and args.instagram_image_urls_file):
        raise SystemExit("--instagram-caption-file and --instagram-image-urls-file are required for Instagram")
    if want_threads and not (args.threads_text_file and args.threads_image_urls_file):
        raise SystemExit("--threads-text-file and --threads-image-urls-file are required for Threads")

    approval = load_approval(args)

    result = {"approval": approval, "platform_post_shape": {}, "image_counts": {}}

    if want_instagram:
        instagram_urls = read_lines(args.instagram_image_urls_file)
        if len(instagram_urls) < 2:
            raise SystemExit("Instagram card-news posting requires at least 2 images")
        result["instagram"] = run([
            "python3", str(SCRIPTS_DIR / "meta_social_publish.py"),
            "publish-instagram-carousel",
            "--image-urls-file", args.instagram_image_urls_file,
            "--caption-file", args.instagram_caption_file,
        ])
        result["platform_post_shape"]["instagram"] = "carousel"
        result["image_counts"]["instagram"] = len(instagram_urls)

    if want_threads:
        threads_urls = read_lines(args.threads_image_urls_file)
        if len(threads_urls) < 2:
            raise SystemExit("Threads card-news posting requires at least 2 images")
        result["threads"] = run([
            "python3", str(SCRIPTS_DIR / "meta_social_publish.py"),
            "publish-threads-carousel",
            "--image-urls-file", args.threads_image_urls_file,
            "--text-file", args.threads_text_file,
        ])
        result["platform_post_shape"]["threads"] = "carousel"
        result["image_counts"]["threads"] = len(threads_urls)

    if args.result_json:
        Path(args.result_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False), file=sys.stderr)
        raise
