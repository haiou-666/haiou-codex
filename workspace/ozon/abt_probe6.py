# -*- coding: utf-8 -*-
"""用 CDP Network.requestWillBeSentExtraInfo 抓 entrypoint-api 的逐字全量请求头
（Playwright 的 request.headers 会漏掉 cookie / sec-fetch-* / priority），再逐层复放到 curl_cffi。
"""
import json
import os
import sys
import time

CW = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CW)
from abt_batch import AbtBatch  # noqa: E402

OUT = os.path.join(CW, "browser_capture")
EP = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=%2F"
PROXY = os.environ.get("ABT_PROXY", "http://127.0.0.1:7897")
extra, rep = [], {"replay": []}


def on_extra(ev):
    h = ev.get("headers") or {}
    extra.append(h)


def main():
    with AbtBatch(start="https://www.ozon.ru/category/aksessuary-7697/") as c:
        cdp = c.ctx.new_cdp_session(c.page)
        cdp.on("Network.requestWillBeSentExtraInfo", on_extra)
        cdp.send("Network.enable")
        c.page.wait_for_timeout(800)
        extra.clear()
        res = c.page.evaluate(
            """async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}});
                   const t = await r.text(); return [r.status, t.length]; }""", EP)
        c.page.wait_for_timeout(1500)
        ck = {x["name"]: x["value"] for x in c.ctx.cookies("https://www.ozon.ru/")}

    full = {}
    for h in extra:
        low = {k.lower(): v for k, v in h.items()}
        if "x-o3-app-name" in low or "entrypoint" in str(low.get(":path", "")):
            full = low
            break
    if not full:
        cand = [ {k.lower(): v for k, v in h.items()} for h in extra ]
        cand = [h for h in cand if h.get("cookie") or "x-o3-app-name" in h]
        full = cand[0] if cand else {}
    rep["browser_fetch"] = res
    rep["full_headers"] = full
    with open(os.path.join(OUT, "entrypoint_full_headers.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print("browser fetch ->", res, "| header sets:", len(extra), "| picked:", len(full))
    print(json.dumps(full, ensure_ascii=False)[:1800])

    base = {k: v for k, v in full.items()
            if not k.startswith(":") and k not in ("cookie", "content-length", "host")}
    cookie_str = full.get("cookie", "")
    ckj = dict(p.split("=", 1) for p in cookie_str.split("; ") if "=" in p)
    ckj = {k: v for k, v in ckj.items() if v}
    from curl_cffi import requests as creq
    variants = [("full", base), ("full-no-secfetch", {k: v for k, v in base.items() if not k.startswith("sec-fetch")})]
    for imp in ("chrome", "chrome124"):
        s = creq.Session(impersonate=imp, proxies={"http": PROXY, "https": PROXY})
        for tag, hd in variants:
            try:
                r = s.get(EP, headers=hd, cookies=ckj or ck, timeout=45)
                rep["replay"].append({"imp": imp, "tag": tag, "status": r.status_code, "len": len(r.content),
                                      "snip": r.text[:60]})
            except Exception as e:
                rep["replay"].append({"imp": imp, "tag": tag, "err": str(e)[:80]})
            time.sleep(0.6)
    with open(os.path.join(OUT, "entrypoint_full_headers.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    for x in rep["replay"]:
        print("  %-9s %-18s %s" % (x.get("imp"), x.get("tag"), x.get("err") or "%s %s %s" % (x["status"], x["len"], x.get("snip", ""))))


if __name__ == "__main__":
    main()
