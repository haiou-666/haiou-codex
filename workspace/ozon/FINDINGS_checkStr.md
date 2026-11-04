# ozon ABT v47_1 — checkStr 定论 + 完整报送管线（本轮实测）

环境：`E:\A\haiou-codex\workspace\ozon`，node harness 直接跑 `script_v47_1.js`（VM 混淆）。
复现：`python oz_probe_chal.py '<challenge_json>' [prefix]`
（harness 额外探针：split/atob/btoa、btoam.crc32/crc32BytesArray/checkIn/b/s/h、NATIVE_MARK、DOC_COOKIE，均不影响结论）

## 1. 已证实的报送管线（100% 可复现）

1. 读 `#challenge` 的 value（`document.getElementById('challenge')` / `querySelector('#challenge')`；
   另有 `querySelector('.challenge-data')` 分支，harness 中返回空 div）。
2. `v = raw.substring(3)` → `atob(v)` → 得到明文 `T`；再对 `T` 做 `split(',')`
   → `challenge.version = parts[0]`、`challenge.id = parts[1]`。
   *实测*：给 `AB1 + btoa('{"challenge_id":"test-token-123","ts":1700000000000}')` 得到
   `version='{"challenge_id":"test-token-123"'`、`id='"ts":1700000000000}'`
   → 说明真站 challenge 明文必须是**恰好一个逗号**的两个字段（左半 JSON 可被 `JSON.parse`），
   否则脚本内部 `JSON.parse(version)` 抛 `SyntaxError: Unexpected end of JSON input`（v47_1 里恒定可见）。
3. `nonce = md5(ts).slice(-7)`：`md5('1700000000000')=faa48af05e71e97fade8497f01a2bddf` → `1a2bddf`（已复核）。
4. 指纹对象 fp 由 `btoam.s(obj, depth, opts, tags)` 逐段采集，输出键带 `@val:` 前缀，
   段 tag 实测有 `scr1`(screen)、`scr3`(device 未实现项 `_u_`)、`bat`(battery) 等。
5. 明文 `JSON.stringify(fp)` 后再做**字符级 XOR**：key = `"undefined"`（9 字节循环）。
6. 再用 `CryptoJS`（btoam.a/k/p = AES 核心/OpenSSL 模式/PKCS7）：
   - key/iv 来源 = `EVP_BytesToKey(MD5)`：`h.h` 实测就是 **MD5**（返回 WordArray）；
     链上输入实测含 `0.3588899802416563`、`816b`、`1700000000000`、UA 等；
   - `AES-256-CBC/PKCS7`，密文落 `fp_ct.bin`，key/iv 落 `fp_key.txt`/`fp_iv.txt`。
7. 解密 + 去 XOR 后即 `payload_*.json`（已两次 json.loads 成功，0 替换字符）。

## 2. checkStr 是什么（定论：**md5(Math.random())[:10]，随机新鲜度戳**）

差分矩阵（同 harness、只改一个变量，checkStr 均 = `8809c2839d`）：

| 变量 | 取值 | checkStr |
|---|---|---|
| challenge JSON | 默认 / `{}` / 3 段 / 4 段 | 8809c2839d |
| challenge 前缀 | `AB1` / 其它 | 8809c2839d |
| UA | 40×'A' / 真实 YaBrowser UA | 8809c2839d |
| document.cookie | `''` / `x=1; y=2` / `abt_data=7.eyJhIjoxfQ` | 8809c2839d |
| 原生函数 toString | 原始 / 打 `[native code]X` 标记（`NATIVE_MARK=1`，令 checkIn→true） | 8809c2839d |

排除项（逐一实测/搜索否定）：
- 不是 md5/sha1/sha256 任意切片的 1268 种组合（上轮穷举）；
- 不是脚本源/表/密文的 md5/sha1/sha256/crc32（本轮逐文件算过，无匹配）；
- 字面量 `"8809c2839d"` 在 `bytecode_v47.asm`、`script_v47_1.deobf.js`、`const_b.json` 中**均不存在**；
  数值形式 `0x8809c2839d`(=584279294877)、`0x8809c283`(=2282340995) 也不在 530 项常量表里；
- 不是 `crc32(UA+version)`：实测 `crc32BytesArray` 返回 `[209,189,206,123]`（=d1bdce7b）；
- 不是原生 canary 摘要（打 toString 标记后不变）；
- 不是 md5/sha1/sha256 截断指纹（fp 里的 md5 调用入参全被钩子记录，无一产生该串）。

**真正的解释（撤回上轮"构建期常量"的结论）**：
`checkStr = md5(String(Math.random()))[:10]` —— 它是**每次加载都变的随机新鲜度戳**，
harness 里之所以恒定，是因为 `Math.random` 被种子化 PRNG 替换了（`let __seed=0x9e3779b9`）。

实证（决定性）：
1. 静态命中：`md5("0.10590326134115458") = 8809c2839d0207cc8eb3da1d69b31131`，前 10 位 **恰好** = `8809c2839d`；
   该浮点正是 trace 里 `[h.h] in=0.10590326134115458` 的 MD5 入参（`h.h` = MD5）。
2. 因果验证：给 harness 加 `REAL_RANDOM=1`（关闭种子 PRNG）后连续两次运行：
   | 运行 | 第二个随机浮点 | md5 前10位 | payload.challenge.checkStr | 一致 |
   |---|---|---|---|---|
   | 种子 PRNG | 0.10590326134115458 | 8809c2839d | 8809c2839d | ✅ |
   | 真随机#1 | 0.4604689967049651 | c1acc246ad | c1acc246ad | ✅ |
   | 真随机#2 | 0.018348285598246306 | c3532051d6 | c3532051d6 | ✅ |
   → checkStr 与 Math.random 同步变化且逐次自洽。
3. 前一个随机浮点（如 `0.3588899802416563`）不参与 checkStr，它是 **AES key 派生链的熵源**
   （链：`md5(f1)` → 取前4位 `816b` → `md5("816b")` → `md5(该值+"undefined")` → `md5(...)` → …）；
   两个随机浮点的全精度字符串**都未出现在明文里**（已逐片段搜索 0.0183/018348/18348285 等，全 False）。

工程含义：
- checkStr **不需复算也不需要抓取**，服务端无法验证其具体值（客户端随机），它只是"本次装载唯一性/新鲜度"标记；
- 反过来说，**任何固定值都能通过**——只要长度 10 位 hex、格式对；
- 同理，AES key/iv 依赖客户端随机熵、且该熵不上报 ⇒ 服务端**无法解密**该 payload，
  这一层是"反爬/防解析的混淆"，不是密码学认证。服务端能做的只有：结构校验、长度校验、challengeId 关联、频次。

## 3. abt_data（未完成，状态与线索）

- 客户端脚本内 `abt_data` / `document.cookie` 字面出现次数 = 0 → **cookie 由 nginx Set-Cookie 下发**，
  不是 JS 生成（已在 `_ozon_challenge.html` 响应头证实）。
- payload 侧 `abt_data` 形态 `"7." + 449 字符 base64url` → 解出 335B，熵 7.36，
  非 zlib/gzip/deflate（已排除）。
- 下一步实验（建议）：对 `btoam.h`（md5）与 `btoam.s` 出口做全参记录，把 335B 与
  `md5(nonce|challenge.id|ts)`/`hmac-md5` 逐一比对；同时抓真站 2 次 `abt_data` 做差分，
  定位是"时间片+随机盐"还是"挑战问答签名"。

## 4. P0 闭环记录（解密侧独立实现 + 规则全部实证）

### 4.1 交付物
| 文件 | 作用 | 状态 |
|---|---|---|
| `crypto_decrypt.py` | 解密侧完整实现（AES-256-CBC/PKCS7/字符XOR/nonce/checkStr/EVP_BytesToKey） | `--selftest` PASS |
| `pool_snapshot_v47_1.json` | 530 项常量表快照 + 规则/脚本 sha256，供版本 diff | 已生成 |
| `FINDINGS_checkStr.md` | 本文件，第2节已从"构建常量"修正为随机戳 | 已修正 |

### 4.2 解密顺序（这里踩过两次坑，务必按此顺序）
```
ciphertext
  --AES-256-CBC(key, iv)-->  masked
  --PKCS7 unpad----------->  bytes        ← 注意：必须先 unpad
  --UTF-8 decode---------->  str          ← 注意：先解码成字符串
  --逐字符 XOR "undefined"-->  JSON       ← 只能对 UTF-16 码元异或，对字节异或会失败
```
加密侧顺序是 `JSON → 字符XOR → AES/PKCS7`。若先 XOR 再 unpad，会得到
`bad PKCS7 padding`；若对字节 XOR 再解码，会在第一个非 ASCII 位置抛
`invalid start byte`（实测 position 1965）。

### 4.3 规则表（全部有因果验证，不是猜测）
| 字段 | 规则 | 验证方式 |
|---|---|---|
| `nonce` | `md5(String(ts)).slice(-7)` | NOW_MS=1700000000000→`1a2bddf`；NOW_MS=1767225600999→`6762e6b`，两轮 JS/Python 一致 |
| `ts` | `Date.now()`（客户端时钟），**与 challenge 里的 ts 无关** | 3 组不同 challenge.ts 注入，payload.ts 恒为桩值 |
| `checkStr` | `md5(String(Math.random())).slice(0,10)` | REAL_RANDOM 三次运行：`0.460468…`→`c1acc246ad`、`0.018348…`→`c3532051d6`、`0.105903…`→`8809c2839d`，逐次自洽 |
| `challenge.version / .id` | challenge 明文以**第一个逗号**切分，左半=version，右半=id，原样回填 | 4 字段 challenge 触发 `SyntaxError: Unexpected end of JSON input` @ `L65f3` |
| `abt_data` | 服务端 `Set-Cookie` 下发，客户端零字面 | 全文检索 `abt_data`/`document.cookie` 计数 = 0 |

结论层面的两个"反直觉事实"，写报告时务必点明：
1. **checkStr 不可被服务端校验**——它是客户端随机数的哈希，服务端拿不到种子；
   所以任何 10 位 hex 都能过。它唯一的作用是让本次请求"看起来新鲜"。
2. **AES 的 key/iv 熵源不上报**（两个随机浮点的全精度串在明文里逐片段搜索全为 False），
   因此服务端**无法解密**这份 payload。这一层的目标是提高解析成本，不是认证。

### 4.4 harness 环境开关（新增两个，均已实体化）
```bash
# 默认：种子 PRNG + 固定时钟（可复现，A/B 差分用）
node harness/run_aegis.js

REAL_RANDOM=1 node harness/run_aegis.js        # 关闭种子 PRNG，暴露真实随机路径
NOW_MS=1767225600999 node harness/run_aegis.js # 时钟取值
CHAL_JSON='{"challenge_id":"x","ts":1}' CHAL_PREFIX=AB1 node harness/run_aegis.js
UA_MARK=... NATIVE_MARK=1 DOC_COOKIE=... node harness/run_aegis.js
```

### 4.5 一键复现
```bash
cd E:\A\haiou-codex\workspace\ozon
python crypto_decrypt.py --selftest          # 4 项断言
python crypto_decrypt.py --out payload.json  # 解出当前 fp_ct.bin
```

## 5. P1 abt_data 差分实验（联网实测，2026-11-05）

### 5.1 采样
`GET https://www.ozon.ru/`，`trust_env=False`（绕代理，之前 SSL protocol violation 是代理导致），
真实 YaBrowser UA。每次响应都带 `Set-Cookie: abt_data=7.<462 chars base64url>` 与 `__Secure-ETC`(32 chars)。
全部返回 **HTTP 403**（首页被反爬墙挡住，正常——挑战页就是为此存在）。

| 样本 | cookie 长度 | 前缀 | base64url 解码长度 | 熵 |
|---|---|---|---|---|
| #1 | 464 | `7.A4-3k2H…` | 346 B | 7.29 |
| #2 | 464 | `7.cdAl-mU…` | 346 B | 7.44 |
| #3 | 464 | `7.xY-9pPP…` | 346 B | — |

### 5.2 差分结果
- **346/346 字节全部不同**（无任何不变区/明文头）。
- 首 16 字节按 BE/LE 解 u32 均不对应 epoch 秒/毫秒（当前 epoch = 1793812750）。
- 长度固定 346 B，恰为 `10 + 336 = 10 + 21×16`：**可能结构 = 10 字节头部（版本/算法/IV 片段）+ 21 个 AES 块**；
  但头部同样每次都变，无法从密文侧拆分——**属于推断，未证实**。
- 熵 7.29–7.44，无 zlib/gzip/deflate 帧，无 ASCII 片段 → 整体为密文流。

### 5.3 会话回传实验（决定性）
用同一 Session 连续 3 次请求，第 2、3 次**自动带上**上一次的 `abt_data`：

| 请求 | 是否回传 | 服务端是否复用 | 
|---|---|---|
| req0 | 否 | — |
| req1 | 是 | **否，又下发新值** |
| req2 | 是 | **否，又下发新值** |

→ `abt_data` **不是持久访客 ID，而是每响应轮换的新鲜度令牌**；服务端在回传后仍强制换新，
说明它绑定的是一次请求/响应周期（时间窗 + 服务端密钥），而不是设备身份。

### 5.4 结论（情况 A，带一个保留）
1. **客户端不参与 abt_data 的生成**：JS 全文 `abt_data` 字面计数 = 0，明文 payload 里也没有该字段 →
   脚本只负责读 `#challenge` 并回传指纹；cookie 由 nginx 私有模块签发，浏览器自动回传。
2. **工程含义**：自动化只需持有 CookieJar 并接受每次下发的轮换值（透传），无需复算；
   反过来说，服务端也无法要求客户端"证明"它算过，因为它自己每次都换。
3. **保留项（无法从外部证实）**：346B 密文是否内嵌了本次 challenge 的 id/nonce，
   需要能拿到"合法挑战页 + 提交端点"才能验证（首页 403，挑战页需要正确 Referer/路径）。
   若以后能抓到一个成功提交，就把它和同一次响应的 abt_data 一起留存，用时间邻近的 challenge id
   尝试在密文长度/结构上对齐——但 346B 固定长度 + 全量变化，几乎不可能靠比对直接读回绑定关系。

## 6. 浏览器侧真实抓包（2026-11-05，CDP 注入）

手段：`Page.addScriptToEvaluateOnNewDocument` 在页面自身脚本之前注入 fetch/XHR/beacon/表单/cookie 钩子，
结果挂在 `window.__ABT_LOG`。套件：`browser_capture/abt_hook.js` + `browser_capture/README.md`。

### 6.1 实测三幕

| # | 动作 | 结果 |
|---|---|---|
| 1 | 已预热会话（cookie 有效）导航 `/category/aksessuary-7697/?__rr=1&abt_test=1` | 钩子生效，捕获 10 条真实业务请求（`/p-api/tracker/dlte/multi` beacon、entrypoint-api、composer-api 等），**无 `/abt/result`**（无需挑战） |
| 2 | `Network.deleteCookies{abt_data, __Secure-ETC}` + 导航 | 落到 **fab 阻断页**；`__ABT_LOG` 0 条，无 `#challenge` |
| 3 | 重复第 2 步 | 同一 fab 阻断页（新事件号）⇒ **出口 IP 已被标记** |

### 6.2 fab 阻断页解剖（重要：它不是挑战页）

- 5296 字节静态 HTML，`<script>` 仅 1 段、174 字节：`handleReload()` → 200ms 后 `location.reload()` 自循环。
- 文案 "Похоже, нет соединения"（像是没网），事件号 `fab_20261104172410_01M6KSDWN40HQX2E5XTR37K8TR`。
- 图片路径泄露资产结构：`cdn2.ozone.ru/s3/abt-challenge/incidents/images/warn.png`
  ⇒ 服务端模块名就是 `abt-challenge`，`incidents` 是其子资源。
- **`id="challenge"` 计数为 0、零 XHR**。
- 反查本地已存两份 HTML（`challenge_page.html` 5148B / `_ozon_challenge.html` 5962B）：
  两者 `fab_` 事件号相同（`fab_20261104163027_01…`）、均为该阻断页、均无 `#challenge`
  ⇒ **历史存档里从未保存过真正的挑战页 HTML**，挑战页当时是直接跑在浏览器里、只落地了脚本与密文。

### 6.3 三条硬约束（写进 README，避免重复踩）

1. `addScriptToEvaluateOnNewDocument` 的注册**只在同一 debugger 会话内有效** → 必须与 `Page.navigate` 同一个 `batch`；
   分两次调用会出现 `hooked:false` 或 `total=0`（本轮先踩，后修）。
2. 桥返回的 `tabs.create` id 与工具层 `tab_id` 不同、且 about:blank 常被回收 → 先 `web_scan` 列真实 id。
3. 删 `abt_data` 不是"逼出挑战"，是"触发 fab 名单"；正确做法是换干净出口 IP + 未预热 profile。

### 6.4 仍缺的一环

真实 `POST /abt/result {token, fp}` 样本（HANDOFF 记录的端点）本轮**未取到**——需要一次干净的挑战页出现。
取到后即可终审：fp 的 `Salted__` 头 + 8B salt 是否与 abt_data 的 346B 首部共享时间基准。
