# -*- coding: utf-8 -*-
"""Real-Chromium ABT pass: drive ozon.ru through the clean proxy, capture /abt/result."""
import json, os, time, sys
from playwright.sync_api import sync_playwright

OUT = r"E:\A\haiou-codex\workspace\ozon\browser_capture"
PROXY = "http://127.0.0.1:7897"
os.makedirs(OUT, exist_ok=True)
rep = {"req": [], "resp": [], "steps": []}

def url_of(r):
    try: return r.url
    except Exception: return ""

with sync_playwright() as p:
    br = p.chromium.launch(headless=False, proxy={"server": PROXY},
                           args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    ctx = br.new_context(locale="ru-RU", timezone_id="Europe/Moscow",
                         viewport={"width": 1920, "height": 1000}, device_scale_factor=1)
    pg = ctx.new_page()

    def on_req(r):
        if "/abt/" in url_of(r):
            try:
                rep["req"].append({"url": r.url, "method": r.method, "post": (r.post_data or ""),
                                   "headers": dict(r.headers)})
            except Exception as e:
                rep["req"].append({"err": str(e)})
    def on_resp(r):
        if "/abt/" in url_of(r):
            body = ""
            try: body = r.text()[:2000]
            except Exception: pass
            try:
                rep["resp"].append({"url": r.url, "status": r.status, "headers": dict(r.headers), "body": body})
            except Exception as e:
                rep["resp"].append({"err": str(e)})
    pg.on("request", on_req)
    pg.on("response", on_resp)
    pg.on("console", lambda m: rep["steps"].append("console:" + m.text[:200]) if m.type == "error" else None)

    try:
        pg.goto("https://www.ozon.ru/", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        rep["steps"].append("goto err " + str(e)[:200])

    t0 = time.time()
    while time.time() - t0 < 45:
        u = pg.url; t = ""
        try: t = pg.title()
        except Exception: pass
        rep["steps"].append(f"{int(time.time()-t0)}s url={u[:90]} title={t[:60]}")
        if "abt_att=1" in u or ("Antibot" not in t and "Похоже" not in t and "ozon" in u and len(t) > 5):
            break
        time.sleep(3)

    try: rep["final_url"] = pg.url
    except Exception: rep["final_url"] = ""
    try: rep["title"] = pg.title()
    except Exception: rep["title"] = ""
    try: rep["cookies"] = [{"name": c["name"], "domain": c["domain"], "value_len": len(c["value"]), "httpOnly": c["httpOnly"]} for c in ctx.cookies()]
    except Exception as e: rep["cookies"] = str(e)
    abt = [c for c in (ctx.cookies() or []) if c["name"] == "abt_data"]
    rep["abt_data"] = [(c["domain"], len(c["value"]), c["value"]) for c in abt]
    # probe an internal action API in-page (same-origin, real cookies)
    try:
        rep["probe"] = pg.evaluate("""async () => {
            const out = {};
            out.cards = document.querySelectorAll('[data-widget="searchResultsV2"] a, .tile-clickable-element').length;
            try { const r = await fetch('/api/composer-api.bx/page/json/v2?url=%2Fcategory%2Faksessuary-7697%2F', {credentials:'include'}); out.cat = r.status; } catch(e){ out.cat = 'ERR '+e.message; }
            return out; }""")
    except Exception as e:
        rep["probe"] = "ERR " + str(e)[:200]
    try: pg.screenshot(path=os.path.join(OUT, "abt_live_playwright.png"))
    except Exception: pass
    br.close()

json.dump(rep, open(os.path.join(OUT, "playwright_abt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("final:", rep.get("final_url"), "|", rep.get("title"))
print("abt_req:", len(rep["req"]), "abt_resp:", len(rep["resp"]), "probe:", rep.get("probe"))
for r in rep["resp"]:
    print("RESP", r.get("status"), str(r.get("url"))[:80], (r.get("body") or "")[:160])
for r in rep["req"]:
    b = r.get("post") or ""
    print("REQ", str(r.get("url"))[:80], "len", len(b))
    try:
        j=json.loads(b); print("  keys:", {k:(len(v) if isinstance(v,str) else type(v).__name__) for k,v in j.items()})
        for k in ("fp","token"):
            if isinstance(j.get(k),str): open(os.path.join(OUT,"live_"+k+".txt"),"w",encoding="utf-8").write(j[k]); print("  saved",k,len(j[k]))
    except Exception as e: print("  parse err",e)
print("abt_data:", [(d, n) for d, n, _ in rep["abt_data"]])
print("steps tail:", rep["steps"][-6:])
