# -*- coding: utf-8 -*-
"""stress_conc.py — 同一个暖好的 jar，W 并发打 N 个商品页

与 stress_test.py（串行基线）唯一的差别是并发度：
  - 服务端看到的身份完全一致（同一批 cookie，尤其同一个 abt_data）
  - 客户端用 W 个独立 curl_cffi Session，各自 cookie 罐内容相同（避免共享 Session 的竞态）
记录每条请求的 start 时间线，用来判断 403 是"第 k 条"还是"第 t 秒进窗口"触发。
"""
import json
import os
import queue
import re
import sys
import threading
import time
from urllib.parse import quote

CW = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CW)
import curl_cffi.requests as creq
from abt_batch import AbtBatch

API = "https://www.ozon.ru/api/composer-api.bx/page/json/v2?url="
PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
HDR = {"accept": "application/json",
       "accept-language": "ru-RU,ru;q=0.9",
       "referer": "https://www.ozon.ru/",
       "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}
N = int(os.environ.get("STRESS_N", "300"))
W = int(os.environ.get("STRESS_W", "8"))
OUT = os.path.join(CW, "stress")

lock = threading.Lock()
rows = []
bad_bodies = []


def session_for(ck):
    s = creq.Session(impersonate="chrome", proxies=PROXY)
    s.cookies.update(ck)
    return s


def worker(wid, q, ck, t0):
    s = session_for(ck)
    while True:
        try:
            i, path = q.get_nowait()
        except queue.Empty:
            return
        ts = time.time()
        st, nb, sec, body = 0, 0, 0.0, b""
        for attempt in range(2):
            try:
                r = s.get(API + quote(path, safe=""), headers=HDR, timeout=40)
                st, nb, body = r.status_code, len(r.content), r.content
                break
            except Exception as e:
                st = -1
                body = str(e).encode()[:200]
            sec = time.time() - ts
        sec = round(time.time() - ts, 2)
        rec = {"i": i, "w": wid, "t": round(ts - t0, 2), "status": st,
               "sec": sec, "bytes": nb, "path": path}
        with lock:
            rows.append(rec)
            if st != 200 and len(bad_bodies) < 3:
                bad_bodies.append({"i": i, "t": rec["t"], "status": st,
                                   "head": body[:400].decode("utf-8", "replace")})
            if i % 25 == 0:
                ok = sum(1 for x in rows if x["status"] == 200)
                print("  %d/%d ok=%d elapsed=%.1fs" % (i, N, ok, time.time() - t0), flush=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    with AbtBatch(start="https://www.ozon.ru/category/aksessuary-7697/") as b:
        ck = {x["name"]: x["value"] for x in b.ctx.cookies("https://www.ozon.ru/")}
    print("[warm] %.1fs cookies=%d abt_data=%d" % (time.time() - t0, len(ck), len(ck.get("abt_data", ""))), flush=True)

    paths = []
    prev = os.path.join(OUT, "stress_results.jsonl")
    if os.path.exists(prev):
        seen = set()
        for line in open(prev, encoding="utf-8"):
            if line.strip():
                p = json.loads(line)["path"]
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
    print("[paths] %d unique from previous run" % len(paths), flush=True)
    if not paths:
        paths = ["/product/noski-muzhskie-10-par-3236858564/"]
    pool = [paths[i % len(paths)] for i in range(N)]

    q = queue.Queue()
    for i, p in enumerate(pool, 1):
        q.put((i, p))
    t1 = time.time()
    ths = [threading.Thread(target=worker, args=(w, q, ck, t1), daemon=True) for w in range(W)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.time() - t1

    rows.sort(key=lambda r: r["t"])
    first_bad = next((r for r in rows if r["status"] != 200), None)
    codes = {}
    for r in rows:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    sec = [r["sec"] for r in rows]
    sec_sorted = sorted(sec)
    summary = {"n": len(rows), "workers": W, "wall_sec": round(wall, 1),
               "req_per_sec": round(len(rows) / wall, 2), "warm_sec": round(t1 - t0, 1),
               "unique_paths": len(paths), "codes": codes,
               "first_non200": first_bad,
               "total_mb": round(sum(r["bytes"] for r in rows) / 1048576, 1),
               "lat_p50": sec_sorted[len(sec_sorted) // 2],
               "lat_p95": sec_sorted[int(len(sec_sorted) * .95)],
               "lat_max": sec_sorted[-1],
               "ok_by_10s": {}}
    for r in rows:
        b = int(r["t"] // 10) * 10
        d = summary["ok_by_10s"].setdefault(b, {"ok": 0, "bad": 0})
        d["ok" if r["status"] == 200 else "bad"] += 1
    with open(os.path.join(OUT, "conc_results.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "conc_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "bad_bodies": bad_bodies}, f, ensure_ascii=False, indent=1)
    print("[done]", json.dumps(summary, ensure_ascii=False), flush=True)
    for bb in bad_bodies:
        print("[bad]", json.dumps(bb, ensure_ascii=False)[:500], flush=True)


if __name__ == "__main__":
    main()
