# -*- coding: utf-8 -*-
"""ozon_curl.py — 用 curl（curl_cffi，Chrome 指纹）做批量采集，不用常驻浏览器

为什么不是系统 curl.exe：实测 curl.exe 打 composer-api 一律 `307` + Location 自加 `&__rr=1`，
`-L` 会陷入 `__rr` 自增重定向环（1→2→3…），且本机 curl 不支持 --http2。
curl_cffi 用 Chrome 的 TLS/JA3 + HTTP/2 指纹，实测 3/3 全 200（83KB / 148KB / 65KB）。

前提：先跑一次 abt_batch.py 生成 abt_cookies_latest.json（浏览器负责过挑战，curl 负责批量）。

用法：
  python ozon_curl.py                    # 内置演示 URL
  python ozon_curl.py /category/sumki-7698/ ...      # 裸路径或完整 URL
  python ozon_curl.py --urls-file urls.txt --out curlout --repeat 3
"""
import argparse
import json
import os
import re
import time
from urllib.parse import quote

from curl_cffi import requests as creq

CW = os.path.dirname(os.path.abspath(__file__))
API = "https://www.ozon.ru/api/composer-api.bx/page/json/v2?url="
PROXY = os.environ.get("ABT_PROXY", "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
DEMO = [API + "%2F", API + "%2Fcategory%2Faksessuary-7697%2F", API + "%2Fcategory%2Fsumki-7698%2F"]


def norm(u):
    if u.startswith("http"):
        return u
    return API + (u if u.startswith("%") else quote(u, safe=""))


def load_cookies(path=None):
    p = path or os.path.join(CW, "abt_cookies_latest.json")
    with open(p, encoding="utf-8") as f:
        ck = json.load(f)
    if not ck.get("abt_data"):
        raise SystemExit("abt_data 缺失：先跑 python abt_batch.py 生成会话（或指定 --cookies 文件）")
    return ck


def session():
    return creq.Session(impersonate="chrome", proxies={"http": PROXY, "https": PROXY})


def get(s, url, ck, timeout=45):
    r = s.get(norm(url), cookies=ck, timeout=timeout,
              headers={"Accept": "application/json",
                       "Accept-Language": "ru-RU,ru;q=0.9",
                       "Referer": "https://www.ozon.ru/"})
    return r.status_code, r.content


def fname(i, url):
    m = re.search(r"url=([^&]*)", norm(url))
    key = (m.group(1) if m else url).replace("%2F", "_").strip("_") or "root"
    return "%02d_%s.json" % (i, re.sub(r"[^0-9A-Za-z_.\-]+", "-", key)[:80])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--urls-file")
    ap.add_argument("--cookies", default=None)
    ap.add_argument("--out", default="curlout")
    ap.add_argument("--repeat", type=int, default=1, help="每个 URL 重复次数，用于测稳定性")
    ap.add_argument("--wait", type=float, default=1.0)
    a = ap.parse_args()

    urls = list(a.urls)
    if a.urls_file:
        urls += [l.strip() for l in open(a.urls_file, encoding="utf-8")
                 if l.strip() and not l.strip().startswith("#")]
    urls = urls or DEMO
    ck = load_cookies(a.cookies)
    out = os.path.join(CW, a.out)
    os.makedirs(out, exist_ok=True)

    s = session()
    print("[session] cookies=%d abt_data=%d  impersonate=chrome" % (len(ck), len(ck["abt_data"])))
    rows, t_all = [], time.time()
    for i, u in enumerate(urls):
        for k in range(a.repeat):
            t = time.time()
            try:
                st, body = get(s, u, ck)
            except Exception as e:
                st, body = 0, str(e).encode()
            if st == 200:
                with open(os.path.join(out, fname(i, u)), "w", encoding="utf-8") as f:
                    f.write(body.decode("utf-8", "replace"))
            print("%02d.%d %s %7d %4.1fs %s" % (i, k, st, len(body or b""), time.time() - t, norm(u)[-64:]))
            rows.append({"i": i, "try": k, "url": norm(u), "status": st, "bytes": len(body or b"")})
            time.sleep(a.wait)
    ok = sum(1 for r in rows if r["status"] == 200)
    summary = {"ok": ok, "n": len(rows), "total_sec": round(time.time() - t_all, 1),
               "mode": "curl_cffi/impersonate=chrome", "rows": rows}
    with open(os.path.join(out, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("[done] ok=%d/%d total %.1fs out=%s" % (ok, len(rows), summary["total_sec"], out))


if __name__ == "__main__":
    main()
