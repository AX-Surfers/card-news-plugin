#!/usr/bin/env bash
set -euo pipefail
set -a
source /opt/data/.env
set +a

out=$(python3 /opt/data/scripts/meta_token_refresh.py refresh-threads 2>&1) || {
  echo "$out"
  exit 1
}
# stay silent on success; metadata is written to /opt/data/.secrets/threads_access_token_meta.json
exit 0
