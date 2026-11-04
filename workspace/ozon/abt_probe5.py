# -*- coding: utf-8 -*-
"""抓 entrypoint-api 的真实请求头，并验证 curl_cffi 能否复现。
思路：只看 composer-api 是拿不到 entrypoint 头的——必须让 SPA 自己发起。
做法：过挑战 → 停在类目页 → 点第一个商品链接（client-side 导航）→ SPA 自己调 entrypoint-api
      → page.on('request') 记录完整 headers（含 x-o3-*）→ 再用 curl_cffi 带这套头复放。
"""
import json
import os
import re
import sys
import time

CW = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CW)
from abt_batch import AbtBatch  # noqa: E402

API = "https://www.ozon.ru/api/"
CAT = "https://www.ozon.ru/category/aksessuary-7697/"
OUT = os.path.join(CW, "browser_capture")
rep = {"meta": {}, "entrypoint": [], "replay": []}


def real_product():
    """从已落盘的类目 JSON 里挖一个真实商品路径。"""
    d = os.path.join(CW, "collect")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        t = open(os.path.join(d, fn), encoding="utf-8", errors="ignore").read()
        m = re.search(r"/product/[a-z0-9][a-z0-9\-]{4,}/", t)
        if m:
            rep["meta"]["product_from"] = fn
            return "https://www.ozon.ru" + m.group(0)
    return None


def main():
    prod = real_product()
    rep["meta"]["product"] = prod
    with AbtBatch(start=CAT) as c:
        rec = []
        c.page.on("request", lambda r: rec.append(
            {"url": r.url, "method": r.method, "headers": dict(r.headers),
             "post": (r.post_data or "")[:300]})
            if "/api/entrypoint-api" in r.url else None)
        c.page.wait_for_timeout(1500)
        try:
            c.page.click('a[href*="/product/"]', timeout=20000)
            rep["meta"]["click"] = "ok"
        except Exception as e:
            rep["meta"]["click"] = "FAIL " + str(e)[:160]
        for _ in range(20):
            if rec:
                break
            c.page.wait_for_timeout(500)
        rep["entrypoint"] = rec[:3]
        # 兜底：页内 fetch 直接打 entrypoint，拿到浏览器自己的 header 集
        try:
            body = c.page.evaluate(
                """async (u) => { const r = await fetch(u, {headers:{'Accept':'application/json'}});
                       const t = await r.text(); return [r.status, t.length, t.slice(0,120)]; }""",
                API + "entrypoint-api.bx/page/json/v2?url=%2F")
            rep["meta"]["inflight_fetch"] = body
        except Exception as e:
            rep["meta"]["inflight_fetch"] = "ERR " + str(e)[:160]
        ck = {x["name"]: x["value"] for x in c.ctx.cookies("https://www.ozon.ru/")}

    with open(os.path.join(OUT, "entrypoint_headers.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)

    # ---- curl_cffi 复放 ----
    from curl_cffi import requests as creq
    base = rec[0]["headers"] if rec else {}
    keep = {k: v for k, v in base.items()
            if k.lower() not in ("cookie", "content-length", "host", ":authority", ":method", ":path", ":scheme")}
    targets = [("entrypoint", API + "entrypoint-api.bx/page/json/v2?url=%2F"),
               ("composer", API + "composer-api.bx/page/json/v2?url=%2F")]
    for imp in ("chrome", "chrome124", "safari"):
        s = creq.Session(impersonate=imp, proxies={"http": os.environ.get("ABT_PROXY", "http://127.0.0.1:7897"),
                                                   "https": os.environ.get("ABT_PROXY", "http://127.0.0.1:7897")})
        for name, u in targets:
            for tag, hd in (("bare", {}), ("captured", keep)):
                try:
                    r = s.get(u, cookies=ck, headers=hd, timeout=45)
                    rep["replay"].append({"imp": imp, "target": name, "hdr": tag,
                                          "status": r.status_code, "len": len(r.content)})
                except Exception as e:
                    rep["replay"].append({"imp": imp, "target": name, "hdr": tag, "err": str(e)[:80]})
                time.sleep(0.6)
    with open(os.path.join(OUT, "entrypoint_replay.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print("meta", json.dumps(rep["meta"], ensure_ascii=False)[:600])
    print("captured entrypoint reqs:", len(rec))
    if rec:
        print("HEADERS:", json.dumps(base, ensure_ascii=False)[:1200])
    for x in rep["replay"]:
        print("  %-9s %-10s %-8s %s" % (x.get("imp"), x.get("target"), x.get("hdr"),
                                        x.get("err") or "%s %s" % (x.get("status"), x.get("len"))))


if __name__ == "__main__":
    main()
