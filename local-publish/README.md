# cardnews — local publish runtime

> This directory is the **versioned copy** of the scripts for backup/history.
> They actually run from `~/.local/share/cardnews` (`$CARDNEWS_DATA_ROOT`) —
> see `skills/cardnews-autopublish`. That runtime dir also holds `.env`,
> `.secrets/`, and `work/`, which are intentionally **not** in this repo.
> To pick up changes made here, copy the updated files back into the runtime dir.

Card-news IG/Threads publish scripts, pulled off the hermes server so they run
**locally**. Layout mirrors the old `/opt/data` (root overridable via
`CARDNEWS_DATA_ROOT`).

```
~/.local/share/cardnews/
├── .env                 # secrets (perms 600, gitignored, NEVER commit)  ← you create
├── .env.example         # template (keys only, no values)
├── .secrets/            # token/service-account files (perms 700)         ← you create
├── scripts/             # publish scripts from hermes (patched for local paths)
├── work/                # scratch: rendered PNGs, url lists, results
├── run_publish.sh       # loads .env → runs the pipeline locally
└── README.md
```

## Setup
1. `cp .env.example .env` and fill values (or drop token files into `.secrets/`
   and point the `*_FILE` vars at them). `chmod 600 .env`.
2. Google Drive service-account JSON → `.secrets/google_drive_sa.json`, and set
   `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` to it (needed for public carousel URLs).

## Use
```bash
# 1. check credentials (no posting)
bash run_publish.sh verify

# 2. make rendered cards public
bash run_publish.sh upload-public --dir /path/to/card-news-out/<id>
#    -> collect the public_direct_url values into ig_urls.txt / threads_urls.txt

# 3. write approval manifest (only after the team approves), then publish
cat > work/<id>/approval.json <<'JSON'
{ "approved": true, "approval_source": "<approver>", "approved_at": "2026-07-07T19:30:00+09:00" }
JSON
bash run_publish.sh publish \
  --instagram-caption-file work/<id>/ig_caption.txt \
  --instagram-image-urls-file work/<id>/ig_urls.txt \
  --threads-text-file work/<id>/threads_text.txt \
  --threads-image-urls-file work/<id>/threads_urls.txt \
  --approval-manifest work/<id>/approval.json \
  --result-json work/<id>/publish_result.json
```

## Security
- Secrets live only in `.env` / `.secrets/` (600/700), outside any git repo.
- Scripts read tokens themselves; values are never printed to logs or transcripts.
- Publishing is irreversible + approval-gated: no post unless the approval manifest
  asserts `approved: true` (local sign-off, no Notion).

## Bundled scripts (patched)
`post_card_news_social.py` (approval gate + orchestrates both carousels),
`meta_social_publish.py` (IG/Threads Graph API, env-driven),
`google_drive_public_upload.py` (public URL hosting),
`meta_token_refresh.py`, `check_instagram_token_expiry.py`,
`refresh_threads_token.py`, `watch_card_news_publish.py`.
Only `post_card_news_social.py` needed local path patches; the rest are env-driven.
