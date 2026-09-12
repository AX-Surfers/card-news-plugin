#!/usr/bin/env bash
# Local card-news publish wrapper.
# Loads ~/.local/share/cardnews/.env into the environment, then runs the
# publish pipeline locally (no hermes, no docker). Tokens stay in .env / .secrets
# and are never printed.
set -euo pipefail

ROOT="${CARDNEWS_DATA_ROOT:-$HOME/.local/share/cardnews}"
ENV_FILE="$ROOT/.env"
SCRIPTS="$ROOT/scripts"

[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE (copy .env.example and fill values)" >&2; exit 1; }

# load .env (KEY=VALUE lines) without echoing values
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
export CARDNEWS_DATA_ROOT="$ROOT"

cmd="${1:-help}"; shift || true
case "$cmd" in
  verify)          # verify [instagram|threads|both(default)]
    target="${1:-both}"
    if [ "$target" = "both" ] || [ "$target" = "instagram" ]; then
      python3 "$SCRIPTS/meta_social_publish.py" verify-instagram
    fi
    if [ "$target" = "both" ] || [ "$target" = "threads" ]; then
      python3 "$SCRIPTS/meta_social_publish.py" verify-threads
    fi
    ;;
  upload-public)   # --dir DIR  -> prints public URLs JSON
    # SA has 0 personal Drive quota -> must upload into a Shared Drive. Auto-inject
    # --parent-id from GOOGLE_DRIVE_PARENT_ID unless the caller already passed one.
    extra=()
    if [ -n "${GOOGLE_DRIVE_PARENT_ID:-}" ] && [[ " $* " != *" --parent-id "* ]]; then
      extra=(--parent-id "$GOOGLE_DRIVE_PARENT_ID")
    fi
    python3 "$SCRIPTS/google_drive_public_upload.py" upload-from-dir "$@" "${extra[@]}"
    ;;
  publish)         # passes through to post_card_news_social.py (approval-gated)
                   # add --platform instagram|threads|both(default) to post to one or both
    python3 "$SCRIPTS/post_card_news_social.py" "$@"
    ;;
  raw)             # run any bundled script by name: raw meta_social_publish.py ...
    s="$1"; shift; python3 "$SCRIPTS/$s" "$@"
    ;;
  *)
    cat >&2 <<EOF
usage: run_publish.sh {verify [instagram|threads|both] | upload-public --dir DIR | publish <post_card_news_social args> | raw SCRIPT ...}
  verify         : check IG and/or Threads credentials (no posting)
  upload-public  : upload PNGs to public Google Drive URLs
  publish        : approval-gated IG + Threads carousel publish (--platform instagram|threads|both)
EOF
    exit 2;;
esac
