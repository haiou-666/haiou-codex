# Ozon ABT Collector — Technical Report (2026-11-05)

End-to-end reverse engineering of OZON's `abt` anti-bot challenge and the two
JSON page APIs behind it, plus a working high-throughput collector.

**TL;DR**

| Layer | Result |
|---|---|
| `/abt/result` challenge, pure HTTP/curl replay | **Impossible** — `{"ok":false}` (12 bytes), no error gradient |
| Real Chromium passes challenge | ~7 s, `POST /abt/result` 200, `abt_data` 624–633 chars |
| `composer-api.bx` via browser `ctx.request` | **200**, 1.0–1.4 s per URL |
| `composer-api.bx` via `curl_cffi` (Chrome TLS fingerprint) | **200**, 0.3–1.5 s per URL |
| `composer-api.bx` via system `curl.exe` | **307 redirect loop** (`&__rr=1` → `__rr=2` → …) |
| `entrypoint-api.bx` via `curl_cffi`, warm cookie | **200** (headers irrelevant) |
| Product page (real id) | **200** on both endpoints |

Two-stage pipeline: `abt_batch.py` (browser, once, ~25–40 s) → `ozon_curl.py`
(`curl_cffi`, 0.3–1.5 s/URL, no browser).

---

## 1. The challenge

`GET https://www.ozon.ru/` behind a residential-ish proxy returns

```
403 8397 bytes
<title>Antibot Challenge Page</title>
#challenge  ≈ 4699–4727 chars   (new value on every GET)
cookies: __Secure-ETC (32), abt_data (453)   ← still *unactivated*
```

Client-side script (obfuscated VM, archived as `browser_capture/script_v47_3.js`,
112,368 bytes) computes `fp` and POSTs to `/abt/result`:

```json
{"token":"sc:<...>:<...>","fp":"<26864 chars>","info":"{\"cookie_enabled\":\"true\"}","error":"","timings":{...}}
```

On success the server issues `abt_att=1` (pass marker) plus a fresh `abt_data`.

### 1.1 Direct replay against `/abt/result` — all three attempts failed

| Attempt | Body | Response | Follow-up API |
|---|---|---|---|
| empty `fp` | real token + `fp:""` | `403 {"ok":false}` (12 B) | 403 `fab_chlg_*` |
| fake `fp` | real token + `fp:"QUJDREVGRw=="` | `403 {"ok":false}` (12 B) | 403 `fab_chlg_*` |
| whole-payload replay | real token (3509) + real `fp` (26864) captured from a *successful* browser run | `403 {"ok":false}` (12 B) | 403 `fab_chlg_*` |

All three responses are **byte-identical**. No error code, no field, no length
difference — there is no signal to steer a search. The challenge string rotates
on every request, so the token is a one-time nonce and replay is structurally
dead. `fp` must be produced by the real VM (real canvas / WebGL / font metrics).

**Conclusion: do not attack the challenge. Run it in a real browser.**

### 1.2 The activation trap (most important operational lesson)

Taking cookies the instant `/abt/result` returns 200 yields an `abt_data` that
is **not yet activated** — every subsequent API call is `403 fab_*`.

Required sequence:

```
goto(start) → wait networkidle → sleep 3s → reload → wait networkidle → sleep 3s → read cookies
```

Only after this settle does the jar actually work. Implemented as
`AbtBatch._settle()` / `pass_challenge()` in `abt_batch.py`.

### 1.3 What actually gates access

Deterministic A/B inside a single browser session, same URL, same second:

```
browser ctx.request.get(category API)  -> 200 / 148254
requests.get(same URL, same 9 cookies) -> 403 / 1161 {"incidentId":"fab_..."}
```

So the gate is **not** the cookie alone and **not** a path whitelist. Evidence
against the path model: after activating on `/category/aksessuary-7697/`,
`url=%2F` → 403, the *just-activated* category → 403, while a never-visited
`/category/sumki-7698/` → 200.

The discriminator is the **request context**: Chromium TLS/JA3 + HTTP/2 frame
ordering + browser headers. Cookies exported from a session that the browser has
**already used successfully at least once** are "warm" and work from a
fingerprint-correct client (`curl_cffi`); cookies from a cold session do not.

---

## 2. Client selection: three-way test

Same 9-cookie jar (incl. `abt_data`, 633 chars), same proxy, three clients,
three composer-api URLs:

| Client | `%2F` | `category/aksessuary-7697` | `category/sumki-7698` |
|---|---|---|---|
| `curl_cffi` `impersonate="chrome"` | **200 / 83,095** | **200 / 148,271** | **200 / 65,660** |
| system `curl.exe` (Schannel, no HTTP/2) | 307 / 164 | 307 / 164 | 307 / 164 |
| `requests` (urllib3, OpenSSL, HTTP/1.1) | 200 / 83,156 | 200 / 146,571 | 200 / 65,718 |

### 2.1 Why `curl.exe` fails

```
HTTP/1.1 307 Temporary Redirect
Server: nginx
Set-Cookie: __Secure-ETC=...; HttpOnly; Secure
Location: https://www.ozon.ru/api/composer-api.bx/page/json/v2?url=%2F&__rr=1
```

Following with `-L` increments the marker forever: `final=307 ... &__rr=3`.
It is a soft-ban loop, not a hard 403 — no diagnostic, just spinning.

Header tinkering does not help (all still 307):

```
base(HTTP/1.1)      307 164
+http2              curl: option --http2: the installed libcurl version does not support this
+ae-gzip-deflate    307 164
+sec-fetch-*        307 164
```

### 2.2 `requests` is usable but unreliable

Earlier, the same jar against the same URL produced **6 consecutive 403s**
(0–5), while minutes before it had returned 200 / 147 KB. Fine for diagnostics,
not for a collector.

---

## 3. `entrypoint-api.bx` and the `x-o3-*` headers

`entrypoint-api.bx` was 403 for a long time and was assumed to need extra
headers. Real SPA request headers were captured by clicking a product card
(client-side navigation) and recording the resulting request
(`browser_capture/entrypoint_headers.json`):

```
accept                    application/json
accept-language           ru-RU
content-type              application/json
referer                   https://www.ozon.ru/category/aksessuary-7697/?__rr=1&abt_att=1
sec-ch-ua                 "Not/A)Brand";v="99", "Chromium";v="148"
sec-ch-ua-mobile          ?0
sec-ch-ua-platform        "Windows"
user-agent                ...Chrome/148.0.0.0 Safari/537.36
x-o3-app-name             dweb_client
x-o3-app-version          release_3-10-2026_51972759
x-o3-manifest-version     frontend-ozon-ru:51972759693b18985fb38e04074bba816a4837b0,
                          checkout-render-api:96f60853ce7f0a870a0f3838b362c52c96840b70,search-rend…
x-o3-parent-requestid     d67ca9ad899c76eeb8bbefd0733169e7
x-page-previous           (empty)
x-page-view-id            aeb20b2c-7f17-40d4-625d-2e6e23b307f8
```

Notes: `x-o3-manifest-version` is a **multi-app manifest signature**
(one 40-hex commit id per app: `frontend-ozon-ru`, `checkout-render-api`,
`search-rend…`). `x-page-view-id` is a uuid, `x-o3-parent-requestid` is 32 hex,
`x-page-previous` empty on first load. The live site runs **Chromium 148**
(UA-CH greasing `"Not/A)Brand";v="99"`).

### 3.1 First replay: 8/8 → 403 (Playwright header loss)

```
chrome    entrypoint captured  403 6971      chrome124 entrypoint captured 403 6999
chrome    entrypoint bare      403 5325      safari    composer  captured  403 6911
```

Cause: `page.on("request")` / `request.headers` **drops** `cookie`,
`sec-fetch-*`, `priority`. Fixed by reading the wire bytes through CDP:

```js
cdp = ctx.new_cdp_session(page)
cdp.on("Network.requestWillBeSentExtraInfo", lambda p: extra.append(p["headers"]))
```

### 3.2 Full wire headers: 4/4 → 200

```
browser fetch -> [200, 78086]   header sets: 1   picked: 17
  chrome    full              200 81945    chrome124 full              200 83971
  chrome    full-no-secfetch  200 85725    chrome124 full-no-secfetch  200 83971
```

### 3.3 Ablation: the headers are *not* the gate

13 requests, one header removed at a time, same jar:

| Variant | Status | Bytes |
|---|---|---|
| FULL | 200 | 85,424 |
| drop `x-o3-manifest-version` | 200 | 85,910 |
| drop `x-o3-timezone` | 200 | 86,746 |
| drop `x-o3-app-version` | 200 | 89,405 |
| drop `x-o3-app-name` | 200 | 88,789 |
| drop `x-page-view-id` | 200 | 86,178 |
| drop `x-o3-parent-requestid` | 200 | 82,820 |
| drop `priority` | 200 | 85,317 |
| drop `accept-encoding` | 200 | 79,438 |
| **drop all `x-o3-*`** | **200** | 84,608 |
| min 4 headers | 200 | 84,480 |
| **bare `accept` + `referer`** | **200** | 74,724 |

`accept` + `referer` is enough. `x-o3-*` are **telemetry/gray-release metadata**,
not auth — but they do shift the returned component set (74 KB ↔ 89 KB).

What made entrypoint work was not the headers, it was the **warm jar** produced
by a session where the browser had already made a successful API call.

---

## 4. End-to-end run (8/8 → 200)

`abt_batch.py /category/aksessuary-7697/` → 42.3 s, `abt_data` 624 chars, one
`POST /abt/result` (31,081 bytes), jar exported. Then `curl_cffi`:

```
entrypoint root       bare  200   85559  1.4s
entrypoint root       +o3   200   85271  0.5s
entrypoint cat        bare  200  150221  0.6s
entrypoint cat        +o3   200  150548  0.6s
entrypoint product    bare  200  160578  0.6s   ← ogurtsy-luhovitskie-500-700-g-3761197655
entrypoint product    +o3   200  160495  0.5s
composer product      bare  200  157369  0.5s
composer product      +o3   200  157336  0.5s
```

Earlier 403s on "product pages" were an artifact of using a **fabricated** id.
With a real id both endpoints return `layout[0] = {"component":"header"}`.

Batch stability (composition-api, `curl_cffi`, 3 URLs × 2 repeats):

```
00.0 200   79173  1.5s      00.1 200   86388  0.5s
01.0 200  145434  0.5s      01.1 200  145871  0.5s
02.0 200   65745  0.3s      02.1 200   65745  0.3s
[done] ok=6/6 total 9.7s
```

Browser batch (`ctx.request`) for comparison: 3/3 → 200, two independent runs
27.5 s and 34.7 s, with **different** `abt_data` heads per run
(`7.ES_4UzHv5w` vs `7.eEiR7bRn3W`) — proof that each run is a fresh session.

---

## 5. Usage

```powershell
cd workspace/ozon
pip install curl_cffi playwright

# stage 1 — warm a session (~25-40 s), passes the challenge once, exports the jar
python abt_batch.py /category/aksessuary-7697/
#   -> collect/00_*.json, collect/_batch_summary.json, abt_cookies_latest.json

# stage 2 — high-throughput batch, no browser (0.3-1.5 s/URL)
python ozon_curl.py /category/sumki-7698/ "/api/entrypoint-api.bx/page/json/v2?url=%2Fproduct%2F<id>%2F" --repeat 3
#   -> curlout/*.json, curlout/_summary.json
```

`abt_batch.py` flags: `[URL...] --urls-file f --start URL --out dir --retry 1 --wait 1.5`.
`ozon_curl.py` flags: `[URL...] --urls-file f --out dir --repeat n`.
Bare paths are auto-prefixed with `/api/composer-api.bx/page/json/v2?url=`.

Data lives in `widgetStates` — a **stringified JSON dict**, keys like
`searchResultsV2-…`; `layout` only carries component shells.

Cost model: fixed ~20–25 s per session (challenge + settle), then 0.3–1.5 s per
URL regardless of count. Always warm once, then drain the whole URL list.

---

## 6. Open items

| Item | Status |
|---|---|
| `fp` cipher key | **not broken** — key lives in VM registers, not hookable; 189k candidate search hit 0. Not needed for collection. |
| jar lifetime / request budget | unmeasured; re-warm every ~200–500 requests as a precaution |
| product-page throughput at scale | untested (only 8/8 single-point) |
| `fab_cp_*` trigger threshold | unknown |
| `checkStr` | `md5(Math.random())[:10]` (confirmed earlier, not required for the current path) |

## 7. Repository hygiene

Cookies, tokens, `fp` blobs and raw captures are **not** committed
(`.gitignore`: `*cookies*.json`, `live_*`, `browser_capture/hook_*`,
`capture_body_*`, `collect/`, `curlout/`, `*.bin`). Only scripts and this report
are tracked. Re-running stage 1 regenerates everything locally.
