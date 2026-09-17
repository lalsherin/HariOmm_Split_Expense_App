#!/usr/bin/env python3
"""Catch smali that writes a local over a method parameter.

In dex, parameters live in the LAST registers of a method's frame. A method
declaring `.registers 4` with one parameter keeps `this` in v3 — so

    .registers 4
    const/4 v3, 0x0        # <-- this is now the integer 0
    invoke-virtual {p0, ...}

destroys `this`, and the verifier rejects the whole class at load time:

    java.lang.VerifyError: ... tried to get class from non-reference register v3

The app does not start, and nothing before install says a word about it —
the assembler is happy, the APK signs and verifies, `aapt dump badging` looks
perfect. That shipped once. Hence this check, which runs in the build.

The rule: a numeric `vN` must stay below the parameter area. Touching a
parameter on purpose is spelled `pN`, which is checked and allowed, so the
only thing flagged is an accidental collision.
"""
import re
import sys
from pathlib import Path

# ops whose FIRST register operand is written
WRITES = re.compile(r"""^\s*(
    const(?:/4|/16|/high16|-string(?:/jumbo)?|-class|-wide(?:/16|/32|/high16)?)?|
    move(?:/from16|/16|-object(?:/from16|/16)?|-wide(?:/from16|/16)?)?|
    move-result(?:-object|-wide)?|move-exception|
    new-instance|new-array|filled-new-array(?:/range)?|
    instance-of|array-length|
    [ais]get(?:-object|-boolean|-byte|-char|-short|-wide)?|
    neg-(?:int|long|float|double)|not-(?:int|long)|
    (?:int|long|float|double)-to-(?:int|long|float|double|byte|char|short)|
    cmp[lg]?-(?:long|float|double)|
    (?:add|sub|mul|div|rem|and|or|xor|shl|shr|ushr)-(?:int|long|float|double)
        (?:/2addr|/lit8|/lit16)?|
    rsub-int(?:/lit8)?
)\s+(v\d+)""", re.VERBOSE)

# these write a 64-bit value, so they clobber the next register too
WIDE = re.compile(r"^\s*(const-wide|move-wide|move-result-wide|[ais]get-wide|"
                  r"(?:add|sub|mul|div|rem|and|or|xor|shl|shr|ushr)-(?:long|double)|"
                  r"neg-(?:long|double)|not-long|"
                  r"(?:int|float|double|long)-to-(?:long|double))\b")

SIG = re.compile(r"^\.method\s+(.*?)\(([^)]*)\)")


def param_registers(modifiers: str, params: str) -> int:
    """How many registers the parameters occupy, `this` included."""
    n = 0 if "static" in modifiers.split() else 1
    i = 0
    while i < len(params):
        c = params[i]
        if c == "[":
            i += 1
            continue
        if c == "L":
            i = params.index(";", i) + 1
            n += 1
            continue
        n += 2 if c in "JD" else 1
        i += 1
    return n


def check(path: Path):
    problems = []
    name = total = base = None
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        m = SIG.match(line)
        if m:
            name = line.strip()
            mods, params = m.group(1), m.group(2)
            # ".method public foo" -> modifiers are everything before the name
            mods = " ".join(mods.split()[:-1]) if mods.split() else ""
            base = None
            pregs = param_registers(mods, params)
            continue
        if line.startswith(".end method"):
            name = total = base = None
            continue
        if name and base is None:
            r = re.match(r"\s*\.registers\s+(\d+)", line)
            if r:
                total = int(r.group(1))
                base = total - pregs
                continue
            r = re.match(r"\s*\.locals\s+(\d+)", line)
            if r:                        # .locals counts only the locals
                base = int(r.group(1))
                total = base + pregs
                continue
        if base is None:
            continue
        w = WRITES.match(line)
        if not w:
            continue
        reg = int(w.group(2)[1:])
        last = reg + 1 if WIDE.match(line) else reg
        if last >= base:
            problems.append(
                f"{path.name}:{lineno}: {line.strip()}\n"
                f"    {name}\n"
                f"    writes v{reg}{' (wide, so v%d too)' % (reg + 1) if last != reg else ''}"
                f" but parameters start at v{base} of {total}"
                f" — this overwrites a parameter"
            )
    return problems


def main(roots):
    files = []
    for root in roots:
        p = Path(root)
        files += sorted(p.rglob("*.smali")) if p.is_dir() else [p]
    problems = []
    for f in files:
        problems += check(f)
    if problems:
        print("smali register check FAILED:\n", file=sys.stderr)
        for p in problems:
            print(p + "\n", file=sys.stderr)
        return 1
    print(f"smali register check ok ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["smali"]))
