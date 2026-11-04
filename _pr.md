## What

Reverse-engineering writeup + working collector for OZON's `abt` anti-bot challenge and the two JSON page APIs behind it. 18 new files under `workspace/ozon/`, no changes to existing code.

## TL;DR of the findings

| Layer | Result |
|---|---|
| `POST /abt/result`, pure HTTP / curl replay | **Impossible** — `{"ok":false}`, 12 bytes, no error grad
...[Truncated]...
ifacts.
- [ ] `python tools/abt_batch.py /category/aksessuary-7697/` → stage 1, exports `abt_cookies_latest.json`
- [ ] `python tools/ozon_curl.py --repeat 2` → stage 2, expect 6/6 HTTP 200

## Notes

Cookies / tokens / `fp` blobs / raw captures are excluded via `workspace/ozon/.gitignore`; a regex scan for real secret *values* (not field names) came back clean before committing.
