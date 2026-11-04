# Ozon Aegis ABT v47_1 — 实证结论（可复现）

## 1. 传输层事实
- `GET https://www.ozon.ru/` → `307` + `Set-Cookie: __Secure-ETC=...` → `/?__rr=1` → `403`
- 403 响应头：`ozon-antibot: 1`，`Set-Cookie: abt_data=7.<base64url>`（335B，首字节 `0x07` = schema 版本 7）
- 页面为终态 incident 页（`Похоже, нет соединения`），无 `#challenge`、无脚本；含 `Инцидент: fab_20261104163027_01M6KPBJ02FPMBXCP1YXKJ2HJD` 与 `token=1.<b64url>`

## 2. `window.btoam` 导出面（23 键）
```
b s canvasToDataUrl checkIn checkInstance crc32 crc32BytesArray fnCall1 getCaller
getNew getNull getPloc getQueryParams getTop getType getUserFonts getWebGLCtx
getWebGLExtraInfo isCallWithoutErrors not object timeoutThrow tryCatch
a k w cp m p f xs xp h hbs
```
CryptoJS 子模块映射（`btoam_structure.txt` 实证）：
| 键 | 实体 | 自有键 |
|---|---|---|
| `a` | AES algo | `_doReset encryptBlock decryptBlock _doCryptBlock keySize init $super` |
| `k` | `{ OpenSSL: ... }` 格式化器命名空间 | `OpenSSL` |
| `w` | WordArray | `init toString concat clamp clone random $super` |
| `cp` | BufferedBlockAlgorithm | `init toString concat clamp clone random` |
| `m` | BlockCipher Mode 命名空间 | `Encryptor/Decryptor` |
| `p` | pad 命名空间 | `pad unpad` |
| `f` | CipherParams | `stringify parse` |
| `h` | MD5 助手 | `len=2` |
| `hbs` | `{stringify}` 辅助 | — |
| `b`/`s` | `bc`/`bC` 顶层入口 | — |

**本构建没有 `k.execute`（EvpKDF）**——`typeof btoam.k.execute === 'undefined'`，`typeof btoam.a.encrypt === 'undefined'`。旧版钩子路径不存在。

## 3. 挂钩踩坑（真实）
- `defProp(window.btoam)` 走 Proxy `set` 陷阱，`desc.value` 存在但 `btoam` 在该刻尚未挂载 → 钩子里两个 `if` 全落空。
- 解法：在 `helpers.sc` 包装内、`orig.apply` 之前强制 `hookBtoam(win.btoam)`。
- 沙箱里 **没有 `window`**，全局对象用 `globalThis`。
- `AES.encryptBlock` 每次只收到 4 字节、`off` 恒为 0（WordArray 视图语义），不能靠它拼明文。

## 4. AES 口令派生链（Python 100% 复现）
```
seed = "0.3588899802416563"          // Math.random().toString()
h1 = md5(seed)                        = 816b372f153e572b4465ee1031239f2f
cut = h1[0:4]                         = "816b"
h2 = md5(cut)                         = 9c8ca43fc0d7ea48ebb210f2f6f01930
h3 = md5(h2 + token)                  = 281311d3666dda46c2952c40773544d2
PASS = md5(h3)                        = 03e0e7518e3b8ae419cad8019d8629f8
```
`token` 取 `#challenge` 值；无挑战时为字符串 `"undefined"`。`MD5` 输入为 UTF-8 字符串（trace 里 `hex` 字段即其字节）。

## 5. 密文封装
- JSON 序列化格式由 `f`(CipherParams).`stringify` 产出：`"Salted__" + salt(8) + ciphertext`，再 base64。
- 实测 `fp` 前缀 `U2FsdGVkX1` = `base64("Salted__")`；示例 salt `e17f60e528604527` / `457f1fc29e85334d` / `1820e6b9f44b35d6`。
- `cipherInit(xform, key, cfg)` 实证：`cfgKeys = ["iv","salt"]`，`key` 32B，`iv` 16B → **AES-256-CBC + PKCS7**。
- 例：key `ca41786c9abf918628def341b1a03c2833320a765fe0ae02508225d8b4a2f98b`，iv `9b2248eb80335dd62bfd7c371d08cd68`，ct 31856B。
- **反推 KDF 尚未命中**：以 PASS 为口令、salt 为盐做 EVP_BytesToKey（MD5/SHA1/SHA256，迭代 1..1000，口令 13 种形态 × salt 3 种形态）均未复现上述 key/iv → key/iv 不是标准 EvpKDF 输出（内层另有 padding/派生）。

## 6. 外层请求体（`JSON.stringify` 钩子实证）
```json
{"token":"undefined","fp":"U2FsdGVkX1/hf2DlKGBFJ9mS0eN8ZBbvh7wAJUtvb0s3G+2tuday45df7N1zMarUkk3LQUJB+ez6gyQr/dgKCs7TCxU0k..."}
```
- `fp` 长度 42500（base64）→ 31875B 解码，头 `Salted__`+salt(8)，余 31859B
- 抓到的请求 init：`POST`、`credentials:"include"`、`Content-Type: application/json;charset=UTF-8`
- 另有 66KB 的 fetch init 快照（含 headers/method/body）

## 7. 内层 payload（未完全解开，但已定性）
- 用采集的 key/iv 解密 31856B ct：`unpad` 通过（末块 PKCS7 合法），明文 31853B
- 明文**不是 JSON**：146 种字节值，高频 `0x00(1201) 0x0b(1183) 0x01(1071) 0x44(1049) 0x45(1001) 0x4e(988)`
- 变换探测：
  - `^0x10` → 浮现 `DEFINED` / `UNDEFINED` 字样片段
  - `^0x30` → 可打印率 88.4%，浮现 `tidefinedunde` / `tafem&llfo` / `tcnyv` 等词形
  - `+0x10` → 可打印率 66.3%
  - 周期检测：period=39（3×13）单字节密钥可达 98.8% 可打印，密钥多为 `0x60`
- 结论：AES 之下还有一层**自研按位压缩/替换编码**（低位吞掉高频偏移，故 `0x00-0x1f` 与 `0x40-0x5f` 两个簇并存），非标准 base64/hex/deflate。

## 8. 复现入口清单
- harness: `harness/run_aegis.js`（Proxy set/get 陷阱 + helpers.sc 包装 + JSON.stringify 钩子 + cipherInit/encryptBlock/CipherParams/random 钩子）
- 产物：`btoam_structure.txt`、`fp_key.txt`、`fp_iv.txt`、`fp_salt.txt`、`fp_ct.bin`、`fp_plaintext.json`、`fp_json_1..7.json`、`harness_trace.json`、`evp_try.txt`
