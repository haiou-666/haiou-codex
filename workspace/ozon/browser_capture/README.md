# 浏览器侧真实抓包（abt_challenge）操作手册

目标物：真实 `POST /abt/result`，body = `{"token":"<challenge token>","fp":"<base64(Salted__+salt+ct)>"}`。
拿到它就能一次性验证三件事：① 真实 token 形态 ② fp 的真实长度/盐 ③ abt_data 与本请求的时间绑定关系。

## 三个硬约束（本轮踩坑实录）

1. **`Page.addScriptToEvaluateOnNewDocument` 只在注册它的那个 debugger 会话里有效。**
   必须和 `Page.navigate` 放在**同一次 `{cmd:'batch'}`** 里，否则导航后钩子丢失
   （现象：`window.__ABT_LOG` 存在但 `total=0`，或 `hooked:false`）。
2. **桥返回的 tabId 可能立刻失效。** `{cmd:'tabs',method:'create'}` 返回的 id 与工具层的
   `tab_id` 不是一回事，且新建的 about:blank 常被回收。**先 `web_scan` 列标签页拿真实 id**再发 CDP。
3. **删 `abt_data` / `__Secure-ETC` 会立刻触发 fab 阻断页**（HTTP 403，"Похоже, нет соединения"）。
   该页是静态页：5296 字节、只有 1 段 174 字节内联脚本 `handleReload()`（200ms 后 reload 自循环）、
   图像来自 `cdn2.ozone.ru/s3/abt-challenge/incidents/images/warn.png`、
   带事件号 `fab_<YYYYMMDDHHMMSS>_<ULID>`。**没有 `#challenge` 输入框、零 XHR** —— 它不是挑战页。
   → 想抓挑战，不要删 cookie；等自然出现，或在**干净出口 IP** 上用未预热 profile 首次访问。

## 一次 batch 模板（tabId 换成真实值）

```json
{"cmd":"batch","commands":[
 {"cmd":"cdp","tabId":TAB,"method":"Page.enable","params":{}},
 {"cmd":"cdp","tabId":TAB,"method":"Page.addScriptToEvaluateOnNewDocument","params":{"source":"<abt_hook.js 的全文，压成一行>"}},
 {"cmd":"cdp","tabId":TAB,"method":"Page.navigate","params":{"url":"https://www.ozon.ru/"}}
]}
```

然后（同 tab）：

```js
await new Promise(r=>setTimeout(r,6000));
return JSON.stringify(window.__ABT_LOG||[]);
```

## 判定标准

- 命中：`kind` ∈ {`fetch`,`xhr-send`,`beacon`} 且 `url` 含 `/abt/result`，`body` 里同时出现 `token` 与 `fp`
- 同时抓 `chall`（提交瞬间 `#challenge` 的原始值，含 3 字符版本前缀）与 `cookie`
- HttpOnly 的 `abt_data` 用 CDP 取：`{"cmd":"cdp","tabId":TAB,"method":"Network.getAllCookies"}`

## 本轮实测（2026-11-05）

| 事件 | 结果 |
|---|---|
| 已预热会话直接导航 | 钩子生效，捕获 10 条真实业务请求（tracker beacon、entrypoint-api 等），**无 /abt/result**（cookie 有效故无挑战） |
| 删 abt_data + 导航 | 命中 fab 阻断页，`__ABT_LOG` 为 0 条，无挑战元素 |
| 再次删 cookie + 导航 | 同一 fab 阻断页（事件号更新），由此确认**出口 IP 已被标记** |

结论：本机出口已被 fab 名单命中，短期内拿不到干净挑战页；流程与钩子已固化，换出口或等名单冷却后一条命令即可复现。
