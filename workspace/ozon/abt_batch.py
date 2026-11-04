# -*- coding: utf-8 -*-
"""abt_batch.py — ozon abt 常驻上下文批量采集器（每次运行 = 全新会话）

实测结论（2026-11-05）：
  * 纯 requests/curl 打 composer-api 不稳定（同 jar 同 URL 会 200 后连 403，缺浏览器 TLS/HTTP2 指纹）
  * 同一浏览器上下文里 ctx.request.get() 稳定 200
  * 过挑战瞬间导出的 abt_data 是“未激活”的 → 必须 settle：networkidle → 静置 → reload → networkidle → 静置
所以：一次过挑战，之后在同一 context 内连打 N 个 URL；每次进程启动都是新 context（新 cookie，不复用）。

用法：
  python abt_batch.py                                  # 跑内置演示 URL 集
  python abt_batch.py URL1 URL2 ...                    # 指定 URL
  python abt_batch.py --urls-file urls.txt --out out2  # 从文件读（每行一个，支持 url=%2F... 或裸路径）
  python abt_batch.py --start https://www.ozon.ru/category/aksessuary-7697/ URL...
环境变量：ABT_PROXY(默认 http://127.0.0.1:7897) ABT_SETTLE(默认 3) ABT_HEADLESS(0/1)
"""
import argparse
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

PROXY = os.environ.get("ABT_PROXY", "http://127.0.0.1:7897")
SETTLE = float(os.environ.get("ABT_SETTLE", "3.0"))
HEADLESS = os.environ.get("ABT_HEADLESS", "0") == "1"
API = "https://www.ozon.ru/api/composer-api.bx/page/json/v2?url="
DEMO = [API + "%2F",
        API + "%2Fcategory%2Faksessuary-7697%2F",
        API + "%2Fcategory%2Fsumki-7698%2F"]


def norm(u):
    """裸路径 / 完整 URL 都归一成 composer-api URL。"""
    if u.startswith("http"):
        return u
    return API + (u if u.startswith("%") else __import__("urllib.parse", fromlist=["quote"]).quote(u, safe=""))


class AbtBatch:
    def __init__(self, start="https://www.ozon.ru/", settle=SETTLE, headless=HEADLESS):
        self.start, self.settle, self.headless = start, settle, headless
        self.log = []
        self.p = self.br = self.ctx = self.page = None

    # ---------- lifecycle ----------
    def __enter__(self):
        self.p = sync_playwright().start()
        self.br = self.p.chromium.launch(headless=self.headless,
                                         args=["--disable-blink-features=AutomationControlled"])
        # 新 context = 新 cookie 罐，绝不与上次运行共享
        self.ctx = self.br.new_context(proxy={"server": PROXY}, locale="ru-RU",
                                       timezone_id="Europe/Moscow",
                                       viewport={"width": 1920, "height": 1080})
        self.page = self.ctx.new_page()
        self.posts = []
        self.page.on("request", lambda r: self.posts.append(len(r.post_data or ""))
                     if "/abt/" in r.url and r.method == "POST" else None)
        self.pass_challenge()
        return self

    def __exit__(self, *a):
        try:
            self.br.close()
        finally:
            self.p.stop()

    def _settle(self, tag):
        for name, fn in (("networkidle", lambda: self.page.wait_for_load_state("networkidle", timeout=25000)),
                         ("sleep", lambda: time.sleep(self.settle)),
                         ("reload", lambda: self.page.reload(wait_until="domcontentloaded", timeout=40000)),
                         ("networkidle2", lambda: self.page.wait_for_load_state("networkidle", timeout=25000)),
                         ("sleep2", lambda: time.sleep(self.settle))):
            t = time.time()
            try:
                fn()
                self.log.append("%s:%s ok %.1fs" % (tag, name, time.time() - t))
            except Exception as e:
                self.log.append("%s:%s FAIL %s" % (tag, name, str(e)[:80]))

    def pass_challenge(self, timeout_s=50):
        t0 = time.time()
        try:
            self.page.goto(self.start, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            self.log.append("goto FAIL " + str(e)[:100])
        while time.time() - t0 < timeout_s:
            try:
                if "abt_att=1" in self.page.url or "Antibot" not in self.page.title():
                    break
            except Exception:
                break
            time.sleep(0.5)
        self._settle("pass")
        self.passed = "abt_att=1" in self.page.url
        self.log.append("passed=%s in %.1fs url=%s" % (self.passed, time.time() - t0, self.page.url))
        return self.passed

    def abt_info(self):
        cs = {c["name"]: c["value"] for c in self.ctx.cookies("https://www.ozon.ru/")}
        return {"cookies": len(cs), "abt_data_len": len(cs.get("abt_data", "")),
                "abt_data_head": cs.get("abt_data", "")[:12],
                "abt_posts": self.posts}

    # ---------- fetch ----------
    def get(self, url, retries=1, wait=1.5):
        """在浏览器上下文内 GET；403 就用 reload 重新激活再试。"""
        url = norm(url)
        last = None
        for attempt in range(retries + 1):
            try:
                r = self.ctx.request.get(url, timeout=60000,
                                         headers={"Accept": "application/json",
                                                  "Accept-Language": "ru-RU,ru;q=0.9",
                                                  "Referer": "https://www.ozon.ru/"})
                body = r.body()
                last = (r.status, body)
                if r.status == 200:
                    return last
            except Exception as e:
                last = (0, str(e).encode())
            if attempt < retries:
                self.log.append("retry %s after %s" % (url[-40:], last[0]))
                time.sleep(wait)
                self._settle("react")
        return last


def fname(i, url):
    m = re.search(r"url=([^&]*)", url)
    key = (m.group(1) if m else url).replace("%2F", "_").strip("_") or "root"
    key = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "-", key)[:80]
    return "%02d_%s.json" % (i, key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--urls-file")
    ap.add_argument("--start", default="https://www.ozon.ru/")
    ap.add_argument("--out", default="collect")
    ap.add_argument("--retry", type=int, default=1)
    ap.add_argument("--wait", type=float, default=1.5)
    a = ap.parse_args()

    urls = list(a.urls)
    if a.urls_file:
        urls += [l.strip() for l in open(a.urls_file, encoding="utf-8") if l.strip()
                 and not l.strip().startswith("#")]
    if not urls:
        urls = DEMO
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), a.out)
    os.makedirs(out, exist_ok=True)

    t_all = time.time()
    with AbtBatch(start=a.start) as c:
        print("[session] %s" % json.dumps(c.abt_info(), ensure_ascii=False))
        rows = []
        for i, u in enumerate(urls):
            t = time.time()
            st, body = c.get(u, retries=a.retry, wait=a.wait)
            fn = fname(i, norm(u))
            ok = st == 200
            if ok:
                try:
                    text = body.decode("utf-8", "replace")
                except Exception:
                    text = ""
                with open(os.path.join(out, fn), "w", encoding="utf-8") as f:
                    f.write(text)
            rows.append({"i": i, "url": norm(u), "status": st, "bytes": len(body or b""),
                         "file": fn if ok else None, "sec": round(time.time() - t, 1)})
            print("%02d %s %7d %.1fs %s" % (i, st, len(body or b""), time.time() - t, norm(u)[-70:]))
            time.sleep(a.wait)
        info = c.abt_info()
        log = c.log
        CK = {x["name"]: x["value"] for x in c.ctx.cookies("https://www.ozon.ru/")}

    summary = {"start": a.start, "passed": None, "session": info, "total_sec": round(time.time() - t_all, 1),
               "ok": sum(1 for r in rows if r["status"] == 200), "rows": rows, "log": log}
    # 导出 cookie 给 ozon_curl.py（curl_cffi 批量）复用：必须含 abt_data，且会话已被浏览器暖过
    if CK:
        here = os.path.dirname(os.path.abspath(__file__))
        for dst in (os.path.join(here, "abt_cookies_latest.json"), os.path.join(out, "_cookies.json")):
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(CK, f, ensure_ascii=False)
        print("[cookies] %d 条 -> abt_cookies_latest.json (abt_data %d 字符)" % (len(CK), len(CK.get("abt_data", ""))))
    with open(os.path.join(out, "_batch_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("[done] ok=%d/%d  total %.1fs  out=%s" % (summary["ok"], len(rows), summary["total_sec"], out))


if __name__ == "__main__":
    main()
