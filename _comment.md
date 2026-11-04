## Stress test added: 300 product pages, one warmed jar

Pushed as `STRESS_20261105.md` + `stress_test.py` (commit c5de1d8).

**Setup** — one warmed session (Playwright challenge + settle, 23.9 s, 9 cookies, `abt_data` 625 chars), then 300 sequential `composer-api.bx` product requests via `curl_cffi impersonate=chrome`, no pacing, no retries, 44 distinct product URLs cycled.

**Result**

```
n=300   ok=300   fail=0   first_non200=null   codes={"200": 300}
~1.67 req/s   total wall 224.9 s (incl. 23.9 s warm-up)   51.9 MB
latency  p50 0.54 s   p90 0.74 s   p95 0.85 s   p99 2.71 s   max 3.35 s
```

**Zero 403s.** No challenge re-entry, no `fab_*` incident id, no tail degradation. The only trend is the first 25 requests averaging 1.11 s vs 0.54 s afterwards — TLS/HTTP/2 connection setup, then flat. A per-session request budget would show up as creeping latency or a hard cliff; neither appears.

So the earlier 403s were a **cold-jar** problem, not a volume problem. This closes the "product page mass-collection" open item in the report, with three caveats written into the doc:

- only 44 distinct paths cycled — path-diversity or per-URL counters are not exercised
- sequential only; concurrency is a different signal
- time-based decay untested (jar used within ~4 min of minting)

Repro: `python stress_test.py` → `stress/stress_results.jsonl` (one line per request) + `stress/stress_summary.json`.
