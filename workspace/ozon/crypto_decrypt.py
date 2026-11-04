# -*- coding: utf-8 -*-
"""ozon ABT v47_1 — 解密侧完整实现（独立于 JS harness）

管线（逆向实证）:
    plain_json  --XOR('undefined' 循环)-->  masked  --AES-256-CBC/PKCS7-->  ciphertext
解密侧反向:
    ciphertext  --AES-CBC 解密-->           masked  --XOR('undefined' 循环)-->  plain_json

密钥: key(32B) / iv(16B) 由脚本内部的 md5 链派生（见 derive_notes()）。
      本模块不重推链条，直接消费 harness 导出的 fp_key.txt / fp_iv.txt，
      同时提供 EVP_BytesToKey(MD5) 与链条旁证函数，便于后续版本回归。

用法:
    python crypto_decrypt.py                    # 解密 harness 产物并打印摘要
    python crypto_decrypt.py out.json           # 解密并另存 JSON
    python crypto_decrypt.py --selftest         # 断言 nonce / checkStr 派生规则
"""
import os
import sys
import json
import hashlib
import argparse

from Crypto.Cipher import AES

DIR = os.path.dirname(os.path.abspath(__file__))
XOR_KEY = b"undefined"          # 字符级 XOR 掩码密钥（9 字节，循环）


# --------------------------------------------------------------------------
# 基础原语
# --------------------------------------------------------------------------
def xor_mask(data: bytes, key: bytes = XOR_KEY) -> bytes:
    """字符级 XOR，等价于 JS: P += String.fromCharCode(c ^ key[i % 9])"""
    n = len(key)
    return bytes((b ^ key[i % n]) for i, b in enumerate(data))


def xor_mask_str(text: str, key: bytes = XOR_KEY) -> str:
    """逐字符 XOR（等价于 JS 的 String.fromCharCode(c ^ key[i % 9])）"""
    n = len(key)
    return "".join(chr(ord(c) ^ key[i % n]) for i, c in enumerate(text))


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty plaintext")
    pad = data[-1]
    if pad < 1 or pad > 16 or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding: %r" % data[-16:])
    return data[:-pad]


def aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    if len(key) not in (16, 24, 32):
        raise ValueError("bad key length %d" % len(key))
    if len(iv) != 16:
        raise ValueError("bad iv length %d" % len(iv))
    if len(ct) % 16:
        raise ValueError("ciphertext not block aligned: %d" % len(ct))
    return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)


def evp_bytes_to_key(password: bytes, salt: bytes = b"",
                     key_len: int = 32, iv_len: int = 16,
                     digest: str = "md5"):
    """OpenSSL EVP_BytesToKey（CryptoJS OpenSSL.kdf 的等价实现）。
    注意：D_i = HASH(D_{i-1} || password || salt)，D_0 = b''。
    顺序写反是 CryptoJS <-> pycryptodome 最常见的翻车点。
    """
    out = b""
    prev = b""
    d = hashlib.new(digest)
    while len(out) < key_len + iv_len:
        d = hashlib.new(digest)
        d.update(prev + password + salt)
        prev = d.digest()
        out += prev
    return out[:key_len], out[key_len:key_len + iv_len]


# --------------------------------------------------------------------------
# 派生规则（已实证，见 FINDINGS）
# --------------------------------------------------------------------------
def nonce_from_ts(ts) -> str:
    """nonce = md5(str(ts)) 末 7 位 hex"""
    return hashlib.md5(str(ts).encode()).hexdigest()[-7:]


def checkstr_from_seed(seed) -> str:
    """checkStr = md5(str(seed)) 前 10 位 hex。
    seed 在真实浏览器里是 Math.random() 的十进制全精度字符串
    （由 JS Number->String 产生），harness 里因 PRNG 被种子化而恒定。
    """
    return hashlib.md5(str(seed).encode()).hexdigest()[:10]


# --------------------------------------------------------------------------
# harness 产物解密
# --------------------------------------------------------------------------
def load_harness_artifacts(directory: str = DIR):
    kp = os.path.join(directory, "fp_key.txt")
    ip = os.path.join(directory, "fp_iv.txt")
    cp = os.path.join(directory, "fp_ct.bin")
    for p in (kp, ip, cp):
        if not os.path.exists(p):
            raise FileNotFoundError(p)
    key = bytes.fromhex(open(kp, encoding="utf-8").read().strip())
    iv = bytes.fromhex(open(ip, encoding="utf-8").read().strip())
    ct = open(cp, "rb").read()
    return key, iv, ct


def decrypt_payload(key: bytes, iv: bytes, ct: bytes):
    """返回 (plaintext_json_str, 诊断字典)"""
    # 顺序关键：AES 解密 -> 去 PKCS7 -> UTF-8 解码 -> 逐"字符"XOR
    # CryptoJS 侧是 String.fromCharCode(c ^ key[i % 9])，作用在 UTF-16 码元上，
    # 所以必须先解码成字符串再做 XOR，不能对字节做异或。
    masked = aes_cbc_decrypt(key, iv, ct)
    unstuffed = pkcs7_unpad(masked)
    plain_str = unstuffed.decode("utf-8")
    text = xor_mask_str(plain_str)
    diag = {
        "ct_len": len(ct),
        "decoded_utf8_bytes": len(text.encode("utf-8")),
        "replacement_chars": text.count("\ufffd"),
        "xor_key": XOR_KEY.decode(),
        "key_hex": key.hex(),
        "iv_hex": iv.hex(),
    }
    return text, diag


def decrypt_from_harness(directory: str = DIR):
    key, iv, ct = load_harness_artifacts(directory)
    text, diag = decrypt_payload(key, iv, ct)
    return json.loads(text), diag


# --------------------------------------------------------------------------
def selftest():
    ok = True

    # 1) nonce 规则
    ts = "1700000000000"
    n = nonce_from_ts(ts)
    print("[selftest] md5(%s) = %s" % (ts, hashlib.md5(ts.encode()).hexdigest()))
    print("[selftest] nonce       = %s (期望 1a2bddf)" % n)
    ok &= (n == "1a2bddf")

    # 2) checkStr 规则
    seed = "0.10590326134115458"
    cs = checkstr_from_seed(seed)
    print("[selftest] checkStr    = %s (期望 8809c2839d)" % cs)
    ok &= (cs == "8809c2839d")

    # 3) EVP_BytesToKey 自检：与 openssl 语义一致（空 salt, 已知向量）
    k, iv = evp_bytes_to_key(b"password")
    print("[selftest] EVP md5 key = %s" % k.hex())
    ok &= (k.hex().startswith("5f4dcc3b5aa765d61d8327deb882cf99"))  # md5('password')

    # 4) 解密 harness 产物
    try:
        payload, diag = decrypt_from_harness()
        print("[selftest] decrypt OK: %d top keys, replacement=%d"
              % (len(payload), diag["replacement_chars"]))
        print("[selftest] challenge.checkStr = %s"
              % payload.get("challenge", {}).get("checkStr"))
        ok &= (diag["replacement_chars"] == 0)
    except Exception as e:                                        # noqa: BLE001
        print("[selftest] decrypt FAIL: %s" % e)
        ok = False

    print("[selftest] RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="ozon ABT v47_1 payload 解密器")
    ap.add_argument("out", nargs="?", help="输出 JSON 路径")
    ap.add_argument("--dir", default=DIR, help="harness 产物目录")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--summary", action="store_true", help="只打印摘要")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    payload, diag = decrypt_from_harness(a.dir)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print("wrote", a.out)

    if a.summary or not a.out:
        print("ct_len=%d  utf8=%d  replacement=%d" %
              (diag["ct_len"], diag["decoded_utf8_bytes"], diag["replacement_chars"]))
        print("key=", diag["key_hex"])
        print("iv =", diag["iv_hex"])
        ch = payload.get("challenge", {})
        print("challenge.version =", json.dumps(ch.get("version"), ensure_ascii=False))
        print("challenge.id      =", json.dumps(ch.get("id"), ensure_ascii=False))
        print("challenge.checkStr=", ch.get("checkStr"))
        print("ts=%s nonce=%s (recompute=%s) matches=%s" % (
            payload.get("ts"), payload.get("nonce"),
            nonce_from_ts(payload.get("ts")),
            payload.get("nonce") == nonce_from_ts(payload.get("ts"))))
        print("top keys:", list(payload.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
