# Ozon Aegis ABT v47_1 — 逆向确证结论（滚动更新）

工作目录 `E:\A\haiou-codex\workspace\ozon\`

## 产物
| 文件 | 说明 |
|---|---|
| `bytecode_v47.bin` | 从脚本内硬编码 base64 还原的 VM 字节码，28,728 B |
| `bytecode_v47.asm` | 线性反汇编，3,992 条指令 / 139 个标签 / 0 未知 |
| `bytecode_disasm.py` | 反汇编器（opcode 表来自 class S，行 1386-1700） |
| `script_v47_1.patched.js` | 28 处反调试陷阱替换为 throw 的补丁副本 |
| `harness/run_aegis.js` | 假 DOM 仿真壳（Proxy 观测） |
| `harness/const_b.json` | 复原的常量表 b（530 项） |

## 执行链（实证）
`bE()` → `window.btoam = bD()` → `aF()`（VM 引导，注册 `window.runChallenge`）
→ `await window.runChallenge()` → `m(o)` = `__AEGIS_HELPERS__.sc(o)` 上报

## VM 指令集（31 opcode，全部确认）
1 LOAD_STR, 2 LOAD_BYTE, 3 LOAD_F64, 4 LOAD_NUM, 5 LOAD_ARR, 10 GET_PROP,
11 CALL(fn, thisArg, args), 12 EVAL, 13 CALLF(target, retReg, pairs)=函数调用,
14 RET, 15 MOV, 16 HALT, 17 JMP_IF, 18 JMP, 19 JMP_IFNOT, 20 CLOSURE(dest, addr, params),
21 SET_PROP, 22 TRY(dest, catch, finally), 23 THROW, 50-57 比较, 100 ADD, 101 MUL, 102 SUB, 103 DIV

操作数编码：i32=4 B 大端；f64=8 B；字符串=len((b<<8)||b2)+原始字节；寄存器列表=count+regs。

## 关键格式发现
- **token = 3 字符前缀 + base64(JSON)**：VM 先 `substring(3)` 再 `window.atob()`，解码后还有第二层 3 字符前缀剥离（asm 0x6631 `LOAD_BYTE 3` + `substring`）。
- 字节码为脚本内静态硬编码，**非服务端下发**；`#challenge` 只是 token 载体。

## 实测探测序列（245 条，逐条可复现）
1. `window.addEventListener` ×3（load / error / unhandledrejection）
2. `window.__AEGIS_HELPERS__` 注入
3. `window.crypto` ×2
4. `querySelector(#challenge)` → `(#incident)`（蜜罐）→ `navigator.cookieEnabled` → `(.challenge-data)` → `(#run-status)`
5. `atob(38304 B)` = 字节码 → `window.runChallenge`
6. `performance` ×2 → `btoam` → `location` → `#challenge` 取值 → `atob(token.substring(3))`
7. `navigator.getBattery()` ×3, `navigator.storage`, `navigator.userAgentData.getHighEntropyValues(["architecture","bitness","formFactors","fullVersionList","model","platformVersion","uaFullVersion","wow64"])`, `mediaDevices.enumerateDevices()`
8. 指纹度量：`performance` ×N（时序侧信道）、`screen`、`inner/outer/clientWidth/Height`、`screenX/Y`、`documentElement`、`visualViewport`
9. 特性探测：`webkitFullscreenEnabled`、`fullscreenEnabled`、`webkitVisibilityState`、`webkitHidden`、`document.createEvent`
10. 环境：`location`、`parent`、`referrer`、`isSecureContext`
11. **反自动化扫描**：`navigator.webdriver`、`window.chrome`、`window.opr`、`window.opera`、`window.callPhantom`、`window._phantom`、`window.__nightmare`、`window.webkit`、`window.__gCrWeb`
12. `Object.getOwnPropertyNames(window)` / `(navigator)` 扫描注入属性（找 `cdc_` / `_phantom` / `__nightmare` 等）
13. iframe 环境校验（`createElement('iframe')` + `appendChild` + `contentWindow`）
14. `video.canPlayType('audio/aac' / 'audio/x-m4a' / 'video/mp4; codecs="avc1.42E01E"')`
15. WebGL：`canvas.getContext('webgl')` + `WEBGL_debug_renderer_info`（UNMASKED_VENDOR/RENDERER）+ 着色器管线与 `getParameter` 常量采样
16. 字体探测：128 px span + `offsetWidth` 对比（`aY`）
17. `crc32`(0xedb88320) 校验、`btoam` 自定义 JSON 序列化

## 踩坑记录（可复用）
- 解混淆版必挂死：28 处 `new RegExp("\n").test(fnSrc)` → `while(true){}`（反格式化陷阱）。只能跑**原始单行**文件。
- deobf 删除了常量表 `b`（530 项，位于原始 js offset 24 后），必须注入。
- Node 25 的 `navigator`/`location` 是只读 getter，需 `Object.defineProperty`。
- 假 DOM 必须提供：`iframe.contentWindow`、`video.canPlayType`、`WebGL` 全方法兜底。
