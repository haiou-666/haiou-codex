# -*- coding: utf-8 -*-
"""stress_test.py — 一个暖好的 jar 连续打 N 个商品页，记录 403 出现的位置与形态

阶段：
  1) AbtBatch 暖一次会话（浏览器过挑战 + 成功请求过一次），导出 jar
  2) 用该 jar 分页抓类目，harvest 商品 URL
  3) 顺序打 N 个商品页（composer-api），逐条落盘 jsonl，统计首 403 位置/403 率/耗时分布
"""
import json
import os
import re
import sys
import time
from urllib.parse import quote

CW = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CW)
from abt_batch import AbtBatch           # noqa: E402
from curl_cffi import requests as creq   # noqa: E402

API = "https://www.ozon.ru/api/composer-api.bx/page/json/v2?url="
PROXY = {"http": "http://127.0.0.1:7897", "https://": "http://127.0.0.1:7897"}
PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
HDR = {"accept": "application/json",
       "accept-language": "ru-RU,ru;q=0.9",
       "referer": "https://www.ozon.ru/",
       "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"}
N = int(os.environ.get("STRESS_N", "300"))
OUT = os.path.join(CW, "stress")


def norm(path):
    if path.startswith("http"):
        return path
    return API + quote(path, safe="")


def harvest(s, ck):
    cats = ["/category/aksessuary-7697/", "/category/sumki-7698/", "/category/golovnye-ubory-7699/"]
    found = []
    for c in cats:
        for page in range(1, 9):
            u = API + quote(c, safe="") + "&page=%d" % page
            try:
                r = s.get(u, headers=HDR, cookies=ck, timeout=30)
            except Exception:
                continue
            for m in re.findall(r'/product/[a-z0-9\-]+-\d{6,}/', r.text):
                found.append(m)
            if r.status_code != 200:
                break
            time.sleep(0.3)
    seen, out = set(), []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    with AbtBatch(start="https://www.ozon.ru/category/aksessuary-7697/") as b:
        ck = {x["name"]: x["value"] for x in b.ctx.cookies("https://www.ozon.ru/")}
    warm_s = time.time() - t0
    print("[warm] %.1fs cookies=%d abt_data=%d" % (warm_s, len(ck), len(ck.get("abt_data", ""))))
    s = creq.Session(impersonate="chrome", proxies=PROXY)
    pool = harvest(s, ck)
    print("[harvest] %d unique product urls" % len(pool))
    while len(pool) < N:
        pool += pool[: N - len(pool)]
    print("[harvest] padded to %d" % len(pool))

    fp = os.path.join(OUT, "stress_results.jsonl")
    open(fp, "w", encoding="utf-8").close()
    rows, first403 = [], None
    for i, p in enumerate(pool[:N], 1):
        t = time.time()
        try:
            r = s.get(norm(p), headers=HDR, cookies=ck, timeout=40)
            st, ln, body = r.status_code, len(r.content), r.text
        except Exception as e:
            st, ln, body = 0, 0, str(e)[:80]
        rec = {"i": i, "path": p, "status": st, "bytes": ln, "sec": round(time.time() - t, 2)}
        if st != 200:
            m = re.search(r'"incidentId":\s*"([a-z0-9]+_[a-z0-9]+)', body)
            rec["incident"] = m.group(1) if m else ""
        rows.append(rec)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if st != 200 and first403 is None:
            first403 = i
            print("[!] first non-200 at #%d -> %s %s" % (i, st, rec.get("incident", "")))
        if i % 25 == 0:
            ok = sum(1 for x in rows if x["status"] == 200)
            print("  %3d/%d ok=%d avg=%.2fs" % (i, N, ok, sum(x["sec"] for x in rows) / len(rows)))
    ok = sum(1 for x in rows if x["status"] == 200)
    summary = {"n": N, "ok": ok, "fail": N - ok, "first_non200": first403,
               "warm_sec": round(warm_s, 1), "total_sec": round(time.time() - t0, 1),
               "codes": {str(c): sum(1 for x in rows if x["status"] == c) for c in set(x["status"] for x in rows)},
               "avg_sec": round(sum(x["sec"] for x in rows) / len(rows), 2)}
    with open(os.path.join(OUT, "stress_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("[done]", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
