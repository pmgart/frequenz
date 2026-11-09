#!/usr/bin/env python3
"""Fail when a Mach-O file inside an app bundle still loads a Homebrew library.

usage: check-dylibs.py dist/FREQUENZ.app
"""

from __future__ import annotations

import os
import subprocess
import sys

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
}
PREFIXES = ("/opt/homebrew", "/usr/local")


def dependencies(path: str) -> list[str]:
    output = subprocess.run(["otool", "-L", path], capture_output=True, text=True).stdout
    lines = output.splitlines()
    # line 0 is the file name, line 1 the binary's own install name, the rest are dependencies
    result = []
    for line in lines[2:]:
        dependency = line.strip().split(" (")[0]
        if dependency.startswith(PREFIXES):
            result.append(dependency)
    return result


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check-dylibs.py <app bundle>", file=sys.stderr)
        return 2
    root = sys.argv[1]
    leaks = 0
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            try:
                with open(path, "rb") as handle:
                    if handle.read(4) not in MACHO_MAGICS:
                        continue
            except OSError:
                continue
            for dependency in dependencies(path):
                print(f"{path}: {dependency}")
                leaks += 1
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
