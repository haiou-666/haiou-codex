# -*- coding: utf-8 -*-
"""
Ozon Aegis ABT (v47_1) bytecode disassembler.
Opcode table reverse-engineered from class S in script_v47_1.deobf.js (lines 1386-1700).

Instruction stream model
------------------------
PC register index = 200 (d), "return/status" register = 201 (e),
253 = f, 254 = l, 255 = m  (see `let d = 200, e = 0xc9, f = 0xfd, l = 254, m = 255`)

Operand primitives
------------------
u8           : one byte
i32 (long)   : 4 bytes big-endian, AS SIGNED via <<24|... (JS bitwise)
f64 (float)  : 8 bytes big-endian, IEEE754 double
str          : len = (b<<8) || next_byte ; then len raw bytes (latin1)
reglist      : count byte, then count register bytes
"""
import struct, sys, json

OPS = {
    1:  ("LOAD_STR",  "R", "str"),
    2:  ("LOAD_BYTE", "R", "u8"),
    3:  ("LOAD_F64",  "R", "f64"),
    4:  ("LOAD_NUM",  "R", "i32"),
    5:  ("LOAD_ARR",  "R", "reglist"),
    10: ("GET_PROP",  "R", "R", "R"),
    11: ("CALL",      "R", "R", "R", "reglist"),
    12: ("EVAL",      "R", "R"),
    13: ("CALLF",     "i32", "u8", "reglist"),
    14: ("RET",       "R", "reglist"),
    15: ("MOV",       "R", "R"),
    16: ("HALT",),
    17: ("JMP_IF",    "R", "i32"),
    18: ("JMP",       "i32"),
    19: ("JMP_IFNOT", "R", "i32"),
    20: ("CLOSURE",   "R", "i32", "reglist"),
    21: ("SET_PROP",  "R", "R", "R"),
    22: ("TRY",       "R", "i32", "i32"),
    23: ("THROW",     "R"),
    50: ("EQ",   "R", "R", "R"),
    51: ("NE",   "R", "R", "R"),
    52: ("SEQ",  "R", "R", "R"),
    53: ("SNE",  "R", "R", "R"),
    54: ("LT",   "R", "R", "R"),
    55: ("GT",   "R", "R", "R"),
    56: ("LE",   "R", "R", "R"),
    57: ("GE",   "R", "R", "R"),
    100:("ADD",  "R", "R", "R"),
    101:("MUL",  "R", "R", "R"),
    102:("SUB",  "R", "R", "R"),
    103:("DIV",  "R", "R", "R"),
}

# registers pre-loaded by class S#init()
PRESET_REGS = {
    200: "<PC>", 201: "<RET>", 253: "<f>", 254: "<l>", 255: "<m>",
    0x00: "<undef0>", 0x3b: "<undef59>",
    35: "Math", 0x48: "performance", 28: "String", 29: "window",
    63: "<undef63>", 0xe5: "Number", 1: "Function", 125: "document",
    91: "Array", 0xb0: "Object", 48: "Boolean", 0x52: "RegExp",
    41: "Promise", 51: "Float32Array",
}

def regname(i):
    return PRESET_REGS.get(i, "r%d" % i)

class Reader:
    def __init__(self, buf):
        self.b = buf
        self.i = 0
    def eof(self):
        return self.i >= len(self.b)
    def u8(self):
        v = self.b[self.i]; self.i += 1; return v
    def i32(self):
        v = self.b[self.i] << 24 | self.b[self.i+1] << 16 | self.b[self.i+2] << 8 | self.b[self.i+3]
        self.i += 4
        if v & 0x80000000: v -= 1 << 32
        return v
    def f64(self):
        v = struct.unpack(">d", self.b[self.i:self.i+8])[0]; self.i += 8; return v
    def string(self):
        hi = self.u8()
        n = (hi << 8) or self.u8()
        raw = self.b[self.i:self.i+n]; self.i += n
        return raw.decode("latin1")
    def reglist(self):
        n = self.u8()
        return [self.u8() for _ in range(n)]

def esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if 0x20 <= o < 0x7f and ch not in '"\\':
            out.append(ch)
        elif ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif o == 10: out.append("\\n")
        elif o == 13: out.append("\\r")
        elif o == 9:  out.append("\\t")
        else: out.append("\\x%02x" % o)
    return "".join(out)

def disassemble(buf, base=0):
    """linear sweep; returns (list_of_instr, labels used)"""
    instrs = []
    labels = set()
    r = Reader(buf)
    while not r.eof():
        start = r.i
        op = r.u8()
        spec = OPS.get(op)
        if spec is None:
            instrs.append({"pc": start, "op": op, "mn": "DB(db 0x%02x)" % op, "args": [], "raw": [op], "bad": True})
            continue
        mn = spec[0]
        args = []
        raw = [op]
        # decode operands in the exact order the handler reads them
        idx = 1
        while idx < len(spec):
            kind = spec[idx]
            if kind == "R":
                args.append(("R", r.u8())); raw.append(buf[r.i-1])
            elif kind == "u8":
                v = r.u8(); args.append(("u8", v)); raw.append(v)
            elif kind == "i32":
                v = r.i32(); args.append(("i32", v)); raw.extend(buf[r.i-4:r.i])
                if mn in ("JMP", "JMP_IF", "JMP_IFNOT", "CALLF", "CLOSURE", "TRY"):
                    labels.add(v)
            elif kind == "f64":
                args.append(("f64", r.f64())); raw.extend(buf[r.i-8:r.i])
            elif kind == "str":
                s = r.string(); args.append(("str", s))
                raw.extend(buf[start+1:r.i])
            elif kind == "reglist":
                l = r.reglist(); args.append(("reglist", l))
                raw.extend(buf[start+1:r.i])
            idx += 1
        instrs.append({"pc": start, "op": op, "mn": mn, "args": args, "raw": raw})
        # extra: TRY has 2 i32 targets (already added once each) -> ok
    return instrs, labels

def fmt_args(mn, args, labels):
    parts = []
    for kind, v in args:
        if kind == "R":
            parts.append(regname(v))
        elif kind == "u8":
            parts.append(str(v))
        elif kind == "i32":
            if mn in ("JMP", "JMP_IF", "JMP_IFNOT", "CALLF", "CLOSURE", "TRY"):
                parts.append("L%04x" % (v & 0xffffffff) if v >= 0 else "@%d" % v)
            else:
                parts.append(str(v))
        elif kind == "f64":
            parts.append(repr(v))
        elif kind == "str":
            parts.append('"%s"' % esc(v))
        elif kind == "reglist":
            parts.append("[" + ", ".join(regname(x) for x in v) + "]")
    return ", ".join(parts)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "bytecode_v47.bin"
    buf = open(path, "rb").read()
    instrs, labels = disassemble(buf)
    lines = ["; Ozon Aegis ABT bytecode disassembly  (%d bytes, %d insns)" % (len(buf), len(instrs)), ""]
    pcs = {i["pc"] for i in instrs}
    for ins in instrs:
        if ins["pc"] in labels:
            lines.append("L%04x:" % ins["pc"])
        if ins.get("bad"):
            lines.append("    %06x  %-14s ; UNKNOWN" % (ins["pc"], ins["mn"]))
            continue
        lines.append("    %06x  %-11s %s" % (ins["pc"], ins["mn"], fmt_args(ins["mn"], ins["args"], labels)))
    out = "\n".join(lines)
    with open(path.rsplit(".", 1)[0] + ".asm", "w", encoding="utf-8") as f:
        f.write(out + "\n")
    print(out[:4000])
    print("\n... total lines", len(lines))
    print("labels:", len(labels), "bad insns:", sum(1 for i in instrs if i.get("bad")))

if __name__ == "__main__":
    main()
