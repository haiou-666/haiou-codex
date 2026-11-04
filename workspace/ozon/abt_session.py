# -*- coding: utf-8 -*-
"""abt_session.py v2 — 可复用的 ozon abt 会话采集器

v2 修正（v1 的实测缺陷）：
  v1 在 `abt_att=1` 出现的那一刻就导出 cookie，此时页面还有一次整页导航/会话预热未完成，
  导出的 abt_data 是"未激活"的 → 拿去 requests 打 /api/composer-api.bx 会 403 (fab_)。
  v2 增加：networkidle 等待 + reload 一次 + 二次 networkidle，再导出 cookie；
  并且优先用 Playwright 的 ctx.request（与浏览器共享同一 cookie 罐，状态最一致）做对照探针。

用法：
  python abt_session.py                      # 过挑战，打印 cookie 摘要
  python abt_session.py <api_url>            # 过挑战后：ctx.request 探针 + requests 复现
环境变量：
  ABT_PROXY     默认 http://127.0.0.1:7897  （必须是干净出口；直连出口已被 per-IP 拉黑→fab 页）
  ABT_SETTLE    默认 3.0  秒，reload 后的静置时间
  ABT_HEADLESS  默认 0（0=有头，1=无头；无头更容易被判定）
"""
import json
import os
import sys
import time

import requests
from playwright.sync_api import sync_playwright

PROXY = os.environ.get("ABT_PROXY", "http://127.0.0.1:7897")
SETTLE = float(os.environ.get("ABT_SETTLE", "3.0"))
# 起始页决定 abt_data 为哪条路径“激活”；要采类目就设成该类目 URL
START = os.environ.get("ABT_START", "https://www.ozon.ru/")
HEADLESS = os.environ.get("ABT_HEADLESS", "0") == "1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
OUT = os.path.dirname(os.path.abspath(__file__))


def _settle(page, log):
    """挑战通过后：等页面真正稳定（networkidle + 一次 reload），否则 abt_data 未激活。"""
    for name, fn in (
        ("wait_networkidle#1", lambda: page.wait_for_load_state("networkidle", timeout=25000)),
        ("sleep#1", lambda: time.sleep(SETTLE)),
        ("reload", lambda: page.reload(wait_until="domcontentloaded", timeout=40000)),
        ("wait_networkidle#2", lambda: page.wait_for_load_state("networkidle", timeout=25000)),
        ("sleep#2", lambda: time.sleep(SETTLE)),
    ):
        t = time.time()
        try:
            fn()
            log.append("%s ok %.1fs" % (name, time.time() - t))
        except Exception as e:
            log.append("%s FAIL %s" % (name, str(e)[:90]))


def pass_challenge(probe_url=None, timeout_s=50, keep_open_s=0.0):
    """打开 ozon.ru 过 abt 挑战，返回 (cookies_dict, meta)。probe_url 非空时额外做 ctx.request 探针。"""
    meta = {"steps": []}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=HEADLESS,
                               args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(proxy={"server": PROXY}, locale="ru-RU",
                             timezone_id="Europe/Moscow",
                             viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()
        posts = []

        def on_req(r):
            if "/abt/" in r.url and r.method == "POST":
                posts.append({"url": r.url, "len": len(r.post_data or "")})

        page.on("request", on_req)
        t0 = time.time()
        try:
            page.goto(START, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            meta["steps"].append("goto: " + str(e)[:120])
        meta["title_first"] = page.title()

        while time.time() - t0 < timeout_s:
            try:
                # 判据双保险：URL 出现 abt_att=1，或标题已不是挑战页（实测 URL 常滞后于实际通过）
                if "abt_att=1" in page.url or "Antibot" not in page.title():
                    break
            except Exception:
                break
            time.sleep(0.5)
        meta["elapsed_s"] = round(time.time() - t0, 1)
        meta["passed"] = "abt_att=1" in page.url
        meta["url_after_pass"] = page.url
        meta["title_after_pass"] = page.title()

        _settle(page, meta["steps"])
        meta["url_settled"] = page.url
        meta["title_settled"] = page.title()

        if probe_url:
            try:
                r = ctx.request.get(probe_url, timeout=45000,
                                    headers={"Accept": "application/json",
                                             "Referer": "https://www.ozon.ru/"})
                meta["ctx_request"] = {"status": r.status, "len": len(r.body()),
                                       "snippet": r.text()[:140]}
            except Exception as e:
                meta["ctx_request"] = {"error": str(e)[:160]}

        meta["abt_posts"] = posts
        if keep_open_s:
            time.sleep(keep_open_s)
        cookies = {c["name"]: c["value"] for c in ctx.cookies("https://www.ozon.ru/")}
        try:
            ctx.storage_state(path=os.path.join(OUT, "abt_state.json"))
        except Exception:
            pass
        br.close()
    return cookies, meta


def fetch(url, cookies, proxy=PROXY, **kw):
    h = {"User-Agent": UA, "Accept": "application/json",
         "Accept-Language": "ru-RU,ru;q=0.9", "Referer": "https://www.ozon.ru/"}
    h.update(kw.pop("headers", {}))
    return requests.get(url, headers=h, cookies=cookies,
                        proxies={"http": proxy, "https": proxy}, timeout=45, **kw)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else None
    ck, meta = pass_challenge(probe_url=url)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print("abt_data len:", len(ck.get("abt_data", "")), "| cookies:", len(ck))
    with open(os.path.join(OUT, "abt_cookies_latest.json"), "w", encoding="utf-8") as f:
        json.dump(ck, f, ensure_ascii=False, indent=1)
    if url:
        # 主路径：浏览器上下文内的请求（实测唯一稳定 200 的通道）
        cr = meta.get("ctx_request") or {}
        print("CTX-RESULT ->", cr.get("status"), cr.get("len"))
        # 诊断路径：同 cookie 交给 requests，通常 403（缺浏览器 TLS/HTTP2 指纹），仅用于对照
        r = fetch(url, ck)
        print("requests(diagnostic) ->", r.status_code, len(r.content))
