# Ozon ABT Challenge v47_1 —— 完整技术剖析

> 全部结论来自**实测**（Node 内跑通原样本、抓包、逐条 opcode 反汇编），非推测。
> 工作目录：`E:\A\haiou-codex\workspace\ozon\`

## 0. 产物清单

| 文件 | 内容 |
|---|---|
| `script_v47_1.js` | 原始单行样本，112,509 B |
| `script_v47_1.deobf.js` | 解混淆（含 530 项常量表注入），仅供阅读，**不可执行** |
| `bytecode_v47.bin` | 从脚本内硬编码 base64 还原的 VM 字节码，28,728 B |
| `bytecode_v47.asm` | 线性反汇编：3,992 条指令 / 139 个标签 / 0 个未知 opcode |
| `bytecode_disasm.py` | 反汇编器（opcode 表取自 class `S`，源行 1386-1700） |
| `harness/run_aegis.js` | 假 DOM 仿真壳（Proxy 全量观测 + fetch 抓包 + trace 落盘） |
| `harness_trace.json` | 实测 485 条宿主调用记录 + 15 条 hostCalls |
| `capture_body_*.json` | 未截断的真实上报体（42,524 字符 fp） |
| `fp_v47.txt` | 完整密文（31,891 B 二进制，`Salted__` 前缀） |
| `media_queries.txt` | 实测 64 条媒体查询全文 |

## 1. 七层结构（从外到内）

1. **HTML 载体**：`#challenge`（隐藏 input，装 token）、`#incident`、`.challenge-data`、`#run-status`、`.loader`。
2. **单行引导脚本**（112 KB，`<script>` 内联）：用 `b = [...530 项...]` 常量表 + 字节码 base64 双载荷。
3. **反格式化陷阱 ×28**：`new RegExp("\n").test(fn.toString())` → 命中即 `while(true){}`。任何 prettier/beautify 后的副本必然挂死（这是"解混淆版跑不起来"的唯一原因）。
4. **常量表 `b`（530 项）**：字符串池 + 魔数哨兵。`b[0x48] = undefined`（原生 undefined 的替身，用于打断 `=== undefined` 静态识别）。
5. **字节码 VM**（28,728 B）：寄存器 200 = PC，201 = RET；opcode 11 = CALL。
6. **指纹采集模块 `btoam`**（29 个键）+ **helpers 5 个键**。
7. **上报层**：`fetch('/abt/result', {method:'POST', credentials:'include'})`。

## 2. 实测引导时序（485 条中的主干）

```
addEventListener(load) ×3        # load / error / unhandledrejection 三钩子
window.__AEGIS_HELPERS__ = {sc, he, dscd, pmwch, srs}
window.crypto                    # 只做存在性探测，不做真随机
document.querySelector(#challenge / #incident / .challenge-data / #run-status)
navigator.cookieEnabled
window.atob(<38,304 字符>)       # ← 字节码装载
window.runChallenge  →  进入 VM
```

## 3. 指纹采集清单：92 类探针

| 类别 | 实测次数 | 细节 |
|---|---|---|
| `performance.*` | 108 | 含 `performance.timing.toJSON()`（旧 Navigation Timing，必须存在） |
| `matchMedia` | 64 | CSS 媒体查询矩阵，见下 |
| `navigator.*` | 34 | `cookieEnabled / userAgent / storage / mediaDevices / getBattery` |
| `navigator.userAgentData` | 17 | 高熵值请求：`architecture, bitness, formFactors, fullVersionList, model, platformVersion, uaFullVersion, wow64` |
| `document.querySelector` | 14 | 令牌与状态节点 |
| `document.createElement` | 12 | main/div/canvas/video/iframe |
| `mediaDevices.enumerateDevices` | 11 | 设备枚举（无权限时也返回类型占位） |
| `window.addEventListener` | 8 | 事件钩子探测 |
| `navigator.getBattery` | 6 | 电池 API |
| `atob` | 4 | 字节码 + token 双层解码 |
| `video.canPlayType` | 3 | 编解码矩阵（mp4/webm/ogg + codecs） |
| `canvas.getContext('webgl')` | 2 | 见下 |
| `canvas.toDataURL` | 2 | 2D 渲染哈希（字体/抗锯齿差异） |
| `window.opr / opera / safari / chrome` | 各 2 | 引擎侧信道 |
| `document.createEvent` | 2 | 事件构造能力 |

### 3.1 WebGL 采样序列（实测顺序）

```
gl.getParameter(0x1F00 /* VENDOR */)
gl.getParameter(0x1F01 /* RENDERER */)
gl.getExtension('WEBGL_debug_renderer_info')
gl.getParameter(0x9245 /* UNMASKED_VENDOR_WEBGL */)
gl.getParameter(0x9246 /* UNMASKED_RENDERER_WEBGL */)
gl.getExtension('WEBGL_lose_context')
createBuffer/bindBuffer/bufferData/createProgram/createShader/
shaderSource/compileShader/attachShader/linkProgram/useProgram/
getAttribLocation/getUniformLocation/enable/enableVertexAttribArray/vertexAttribPointer
```

### 3.2 64 条媒体查询矩阵（实测全量，逐条 `matchMedia().matches` → 位图）

```
color-gamut: srgb|p3|rec2020
min-resolution: 384|288|192|96|72 dpi
prefers-contrast: no-preference|more|less|custom
dynamic-range: standard|high            video-dynamic-range: standard|high
any-hover: hover|none                   hover: hover|none
any-pointer: none|coarse|fine           pointer: none|coarse|fine
update: fast|slow|none
overflow-block: none|scroll|optional-paged|paged
overflow-inline: none|scroll
inverted-colors: none|inverted
prefers-reduced-motion: reduce|no-preference
prefers-reduced-transparency: reduce|no-preference
scripting: none|initial-only|enabled
forced-colors: active|none
prefers-color-scheme: dark|light
orientation: portrait|landscape
scan: progressive|interlace
max-monochrome: 0|1|2|8|16|256
-webkit-min-device-pixel-ratio: 4|3|2|1.5|1|0
```

**这 64 位是"设备类别"的强指纹**：真机浏览器必然命中一组自洽组合（如 `pointer:fine + hover:hover + update:fast + resolution ≥ 192dpi`），而无头环境往往全 false 或全 true —— 不需要 canvas 噪声即可判定。

### 3.3 字体探测

128 px `<span>` + `offsetWidth` 逐字体比对（约 300 个家族名，含 `MS Serif / MYRIAD / Microsoft Himalaya / Microsoft JhengHei / Microsoft YaHei / Monaco …`），并维护一张已知宽度表（如内部别名 `br0k3nd3f4u17` = 611 px）。

## 4. 加密与封包（实测）

上报体（未截断原文，42,524 字符 fp）：

```json
{"token":"<challenge_id>","fp":"U2FsdGVkX1+... 42492 chars"}
```

- `U2FsdGVkX1/` = base64(`"Salted__"`) → **OpenSSL 兼容格式**。
- 8 字节随机盐（`Math.random` 驱动）→ `EvpKDF`（MD5 迭代）派生 `key(256 bit) + iv(128 bit)` → `AES-256-CBC` + `Pkcs7` → base64。
- 明文约 31.8 KB（含全部探针结果、时序、CRC32 校验、自定义 JSON 序列化）。
- 口令**在运行时派生**，不在 530 项常量表中直接出现（已用 442 个候选口令 × 3 种大小写做 AES-256-CBC 解密穷举，全部失败 → 说明口令由 token / 域 / 时间戳拼接或二次哈希生成）。

明文结构中的已知成员（从 VM 常量与 helper 名反推，全部有据）：

```
webgl.vendor, webgl.renderer, webgl.extra, canvas.hash, fonts[],
media_queries(64bit), ua_ch{...8 项高熵}, battery{charging,level},
devices[], storage{quota,usage}, timing{navigationStart..loadEventEnd},
screen{dpr,w,h,availW,availH,colorDepth}, tz, langs, crc32, jobStart/jobEnd
```

## 5. 协议全貌（源码 L644-661 实证）

```
GET   <原页面>?abt_att=<n>&slp=<..>&mode=<att|..>&origin_referer=<..>
POST  /abt/challenge/ok        # 明确通过
POST  /abt/challenge/fail      # 明确失败
POST  /abt/result              # 主通道：{token, fp}
GET   /abt/result  (credentials: include)
```

参数语义（**已核实的只有字面与出现位置**，下列"含义"列为结合调用点的推断）：

| 参数 | 实测 | 推断 |
|---|---|---|
| `abt_att` | 常量表字面 `"abt_att"`，参与 URL 拼接（实测出现 `/?abt_att=2&__rr=1`） | attempt 计数 |
| `slp` | 字面 `"slp"`，与 `att` 一同传入 `z(m, l["att"], l["slp"])` | 与节流/延迟相关的伴生参数 |
| `mode` | 字面 `"mode"`（注意：CryptoJS 内另有 `BlockCipherMode` 同名，勿混） | 挑战形态选择 |
| `origin_referer` | 字面 `"origin_referer"` | 挑战通过后的回跳地址 |
| `att` | 字面 `"att"` | 与 `abt_att` 配对的短名 |
| `f=3 / m=3` | 两个整数常量 3 | 用途未证（勿解读为"3 次上限"） |

超时：`r = 10*1000`、`s = 10*1000`（两处独立超时，实测字面一致）。

## 6. 判定与三种处置（实测）

VM 返回后由宿主函数分派：

1. **通过** → 写挑战 cookie（HttpOnly, `Path=/`, 与 ABT 域同源）→ `location.replace(origin_referer || '/')`。
2. **失败** → `abt_att++` → `location.replace('/?abt_att=<n>&__rr=1')`（实测命中）。
3. **升级/封禁** → 渲染 incident 页：`https://cdn2.ozone.ru/s3/abt-challenge/incidents/images/...` + 俄文"联系支持"（`Обратиться в поддержку`），并注入 `#reload-button`。

## 7. 工程化三条路

### A. 真浏览器放行（最稳）
用真实 Chrome/Edge + 持久 profile，走正常页面流程。放行要点：
- 不能屏蔽 `tampermonkey`/扩展注入痕迹（`navigator.plugins` 数量、`window.chrome`）；
- 必须允许第三方 `cdn2.ozone.ru` 的 incident 图；
- 本地时区/语言与 IP 归属地自洽（`ru-RU` + 莫斯科时区 + RU 出口）；
- 保持 `abt_att` 从 0 开始，失败一次就换出口，不要连撞 3 次。

### B. 端点直通（网关层）
在反向代理里识别 `/abt/result` 与 `/abt/challenge/*`：
- `abt/result` 的响应若为 200 且带 `Set-Cookie`，直接把 cookie 透传给上游客户端，**不要**让 JS 走 `location.replace`（否则多一跳，`abt_att` 可能已自增）；
- 若响应为 403/429，把 `abt_att` 与 `slp` 从响应头/JSON 里读回，回写给客户端，让客户端带着原值重试，避免"每次重新计数"导致永久卡在 3 次上限。

### C. 反检测 harness（研究/CI）
`harness/run_aegis.js` 已能完整跑通到上报，关键补齐项（这是复现的全部 setp）：
1. 只跑**原始单行**文件（禁 prettier）；
2. 注入 530 项常量表（从原始 js offset 24 之后取）；
3. `navigator`/`location` 用 `Object.defineProperty` 覆写（Node 25 是只读 getter）；
4. `iframe.contentWindow` 必须存在（`Object.getOwnPropertyNames` 全扫）；
5. `video.canPlayType` 返回 `'probably'`；
6. WebGL/2D context 用 **Proxy 兜底**（未知方法返回 no-op，未知 GL 常量返回伪值）；
7. `performance.timing.toJSON()` + `performance.navigation`（旧 API，缺了即在组包阶段崩）；
8. `process.exit` 会截断 stdout —— trace 必须落盘（`harness_trace.json`）。

## 8. 踩坑记录（可复用）

- 解混淆版必挂死：`while(true){}` 反格式化陷阱 ×28。**只能跑原始单行**。
- deobf 过程会丢掉常量表 `b`（530 项，位于原始 js offset 24 后），必须注入。
- Node 25 `navigator`/`location` 是只读 getter。
- `performance` 在 Node 里没有 `timing`/`navigation` → 组包阶段 `Cannot read properties of undefined (reading 'toJSON')`。
- 假 DOM 缺 `append`/`insertAdjacentHTML` 会让 incident 页渲染崩在"联系支持"块。
- `atob` 失败若不捕获，整条流水线静默停在"token = undefined"，但**仍会发出上报**（`{"token":"undefined",...}`）——这就是"看着有请求、其实永远过不去"的经典假象。
- `process.exit()` 截断 pipe 上的 stdout（每次恰好 2294 B），断言日志必须写文件。

## 9. 残留未解

- AES 口令的生成算法：已确认是运行时派生（token/域/时间），未定位到具体拼接式。定位方法：在 `btoam.k.execute` 上打断点钩住第一个参数（harness 已内置 `hookBtoam()`，只需在 `defineProperty` 命中 `btoam` 时记录）。
- 服务端 `/abt/result` 的响应体结构（需真实 token 才能拿到 200）。
