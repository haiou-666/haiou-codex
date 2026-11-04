# LIVE_BREAKTHROUGH_20261105.md — 现场真挑战闭环 + fp 格式定型

## 1. 出口判定（决定性）
- Chrome/系统直连出口已被 **per-IP 硬拉黑**：任何导航 → fab 页（多事件号，m.ozon.ru 同样 fab → 封锁是 per-IP 非 per-host）。
- **环境代理 `127.0.0.1:7897` 出口干净**（ipify 显示 43.199.207.211；ozon 侧看到 36.18.192.182，属同代理池）。
- 走该代理 `GET https://www.ozon.ru/` → **403 + `<title>Antibot Challenge Page</title>`**（8425B, sha 见文件），
  **不是 fab**：页面含 `<input id="challenge" value="6ZON...">`（4727 chars）与 `.challenge-data`、
  `#incident` = `fab_chlg_20261104173558_01M6KT3GPPW95W5AGXZ2ERJ68M`、时间戳 `Wednesday, 04-Nov-2026 17:35:58 UTC`。
- 响应同时下发 `Set-Cookie: abt_data=7.idy28FB...`（新指纹 cookie 由**挑战页 403 响应**种下，不是我方构造）。

## 2. 脚本升级
- 线上已从 **v47_1 → v47_3**：`https://st-20.ozonstatic.cn/s3/abt-challenge/script_v47_3.js`（112368B，md5 20c2ca74859a），
  样式 `style_v47_3.css`。同款 `b[0xNN]` 字符串表混淆，表内 435 条串。
- 入口链（实测）：`window.addEventListener('load', ...)` → `bE()` → `defineProperty(window,'btoam',{value:bD()})` → `await window.runChallenge()`。
- **端点实为 `/abt/result`**（相对路径，同源 POST）；表内 `/abt/challen`+`tor` 是另一处（挑战页自身路径）。
- 通过后跳转 `location.replace('https://www.ozon.ru/?abt_att=1')` → **`abt_att=1` 是"挑战通过"标记**（此前猜测反了）。
- 报错字段同名机制：失败时 payload 带 `error`(含 build_ts/lib_version/challenge_id/user_agent) 与 `info:{cookie_enabled}`。
- 字符串表实锤：`EvpKDF`、`OpenSSL`、`AES`、`CBC`、`Pkcs7`、`salt`、`kdf`、`ivSize`、`sigBytes`、`__AEGIS_HELPERS__`、`UNMASK`、
  `getParameter`、`pmwch/dscd/srs`。

## 3. 真浏览器过挑战（端到端成功，可复用）
`abt_playwright.py`（Playwright chromium headless=False + proxy 7897，locale ru-RU，tz Europe/Moscow）：
- 0s 挑战页 → 6s 自动通过 → `https://www.ozon.ru/?__rr=1&abt_att=1`，标题 `Ozon маркетплейс – миллионы товаров по выгодным ценам`。
- `/abt/result` **HTTP 200**；`abt_data` 重新种下（593B / 628B 两轮）。
- 页面 SSR 商品卡渲染 10 个；但 `fetch('/api/composer-api.bx/page/json/v2?...')` 仍 403（XF/antibot 对 action-API 另管）。

## 4. POST /abt/result 真实 payload 结构（已落盘）
```json
{"token":"sc:<22>:<3371>:<68>","fp":"<26780 chars>","error":[],"info":{"cookie_enabled":"true"},"timings":{...}}
```
- `token` 4 段 `:` 分割：`sc` / 22字符会话id(`zM7wTT2OKaBtJ6en_4vN7w`) / 3371 chars 高熵blob / 68 chars
  **base64url JSON** = `{"ts":1793813973927,"support_domain":"www.ozon.ru"}`。
- `fp` **26780 chars base64**；解码后 **前 8 字节 = `Salted__`**，随后 8B salt(`ceccda590881aee3`)，其后 20075B
  密文 → **CryptoJS/OpenSSL `format:OpenSSL` 结构（EVP_BytesToKey: MD5 迭代, key=32, iv=16）**。
- 注意：`ct` 长度 20075 **不是 16 的倍数**（20075 % 16 = 11），与 CBC+Pkcs7 矛盾 → 待定：可能为流模式、
  或尾部带 11B 校验/或与 abt_data 拼接。清单内仅 1 处 `Salted__`。
- 已排除的口令候选（EVP+CTR/CFB/OFB 全试，t17: 打印率≈0.47 无 JSON 命中）：token 各段、salt hex、`undefined`、
  事件号、UA、`www.ozon.ru`、空串等。

## 5. 结论与下一步
- **纯 Python/Node harness 路线到此为止**：桩环境能跑通脚本并发 POST，但 fp 全是空（VM 需要真 GPU/字体/canvas 指标，
  且 challenge 串需先解）；真指纹只能在真 Chromium 里生成。
- 生产可用方案 = **Playwright + 干净代理**：一次过挑战换 `abt_data`，导出 cookie 给 requests 复用。
- 待解：`fp` 的 passphrase（下步用 page init-script 钩 `CryptoJS.kdf.OpenSSL.execute` / `btoam` 现拦现拿）。
# FINDINGS_live_20261105.md — 补充 ②（真浏览器闭环之后）

## 6. btoam 助手 API 全貌（现场钩住 Object.defineProperty('btoam') 拿到）
脚本在 `bE()` 里 `defineProperty(window,'btoam',{value:bD()})`，对象键：
```
b, s, canvasToDataUrl, checkIn, checkInstance, crc32, crc32BytesArray,
fnCall1, getCaller, getNew, getNull, getPloc, getQueryParams, getTop, getType,
getUserFonts, getWebGLCtx, getWebGLExtraInfo, isCallWithoutErrors, not, object,
timeoutThrow, tryCatch, a, k, w, cp, m, p, f, xs, xp, h, hbs
```
→ 指纹面清晰：canvas(DataUrl) / WebGL(ctx+extra) / 字体枚举(getUserFonts) / crc32 / ploc(位置) /
queryParams / 调用栈(getCaller/fnCall1) / NaN·null·type 探针（反调试）。**这些必须在真 GPU/真字体环境才有值**，
桩环境（Node vm）里全部退化，这正是 harness 生成的 `fp` 恒为空（0 chars）的根因。

## 7. fp 结构二次确认（两独立样本）
| 样本 | base64 字符数 | 解码字节 | 头部 | ct 长度 | ct%16 |
|---|---|---|---|---|---|
| live_fp.txt  | 26780 | 20083 | `Salted__` + salt `ceccda590881aee3` | 20067 | **3** |
| live_fp2.txt | 26864 | 20147 | `Salted__` + salt `eeac8c1d3f4c06..` | 20131 | **3** |
- 两样本 **ct%16 恒为 3** → 不是随机错位，而是「16 的倍数 + 3 字节固定尾」或非 CBC 变换。
- 口令候选（token 各段 / salt hex / 事件号 / UA / 域名 / 空串）× {CBC, CTR, CFB, OFB} 全试：无可打印/JSON 命中。
- `CryptoJS` 全局虽在挑战页存在，但 `kdf.OpenSSL.execute`、`AES.encrypt` 的运行时钩子**从未被调用**
  → **fp 的加密发生在字节码 VM 内部的 crypto-js 闭包**（字符串表里 `EvpKDF/OpenSSL/AES/CBC/Pkcs7` 即其副本），
  外部 JS 钩子够不到。结论：**fp 离线解密不可行（口令不可见）**，也不需要——复用浏览器即可。

## 8. 端到端可用路线（已实测，交付物 `abt_session.py`）
- `pass_challenge()`：Playwright(chromium, headless=False, proxy=7897, locale ru-RU, tz Europe/Moscow)
  → 页面从 `Antibot Challenge Page` 自动过挑战 → `/?__rr=1&abt_att=1`，标题变正常；
  `/abt/result` POST 1 次（body 31KB 级），`abt_data` 626~630 chars 重新种下。
- 导出 9 个 cookie 给 requests，经同一代理请求：
  - `GET /api/composer-api.bx/page/json/v2?url=%2F` → **200 / 82~145 KB 正常 JSON**（可复用，P2 达成）
  - `url=%2Fcategory%2Faksessuary-7697%2F` → **403**，body `{"incidentId":"fab_..."}`
  - `url=%2Fproduct%2F...` → **403** 同上
  - `GET /api/entrypoint-api.bx/...` → 403
  → **封锁是"路径级"而非"会话级"**：首页 composer-api 放行，类目/商品/entrypoint 需另一套（per-request 挑战/签名）。
- 注意：同一次会话里 `?__rr=1` 出现是挑战页自身的行为，不必然等于 fab。

## 9. 对既有结论的修正
- ~~`abt_att=1` 表示被拦~~ → **错**：`abt_att=1` 是"挑战通过"标记；被拦是 fab 页(带 `__rr=N` 且标题 `Antibot Challenge Page` 之外的 fab 事件页)。
- ~~挑战脚本 v47_1~~ → 线上已 **v47_3**（本目录 `script_v47_3.js`、`style_v47_3.css` 已存档，可离线比对）。
- ~~纯 harness 可产 fp~~ → **不可**：VM 依赖真实 canvas/WebGL/字体指标，必须真浏览器。

## 10. 待办（按性价比）
1. 类目/商品 403 的绕过：抓真浏览器里 composer-api 类目请求的**完整请求头**（`x-o3-*`、`x-requested-with`、
   `x-csrf-token`?）再复用到 requests。
2. 长期采集：Playwright `storage_state` 持久化（一次过挑战 → 存 json → 复用 N 小时），配合代理池轮换出口 IP。
3. 版本守护：定期比对 `script_v47_N.js` 的 md5，脚本升级即报警。
