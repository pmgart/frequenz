#!/usr/bin/env python3
"""Remove duplicate LC_RPATH entries from the Mach-O files in an app bundle.

dylibbundler rewrites every rpath of a binary to the same @executable_path
prefix, so a plugin that had two or three rpaths ends up with duplicate
LC_RPATH commands. dyld refuses to load such a library ("duplicate LC_RPATH"),
which silently removes GStreamer plugins. Keep the first copy of each path.

usage: packaging/macos/fix-rpaths.py dist/FREQUENZ.app
"""

from __future__ import annotations

import os
import subprocess
import sys

MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe",  # 64-bit, little endian (arm64)
    b"\xce\xfa\xed\xfe",  # 32-bit, little endian
    b"\xfe\xed\xfa\xcf",  # 64-bit, big endian
    b"\xfe\xed\xfa\xce",  # 32-bit, big endian
}


def is_macho(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def rpaths(path: str) -> list[str]:
    output = subprocess.run(["otool", "-l", path], capture_output=True, text=True).stdout
    found: list[str] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("cmd LC_RPATH"):
            for follow in lines[index + 1:index + 4]:
                stripped = follow.strip()
                if stripped.startswith("path "):
                    found.append(stripped[5:].split(" (offset")[0])
                    break
    return found


def dedupe(path: str) -> int:
    seen: set[str] = set()
    removed = 0
    for value in rpaths(path):
        if value in seen:
            subprocess.run(["install_name_tool", "-delete_rpath", value, path],
                           check=True, capture_output=True)
            removed += 1
        else:
            seen.add(value)
    return removed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fix-rpaths.py <app bundle>", file=sys.stderr)
        return 2
    root = sys.argv[1]
    files = 0
    removed = 0
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            if not is_macho(path):
                continue
            files += 1
            removed += dedupe(path)
    print(f"checked {files} Mach-O files, removed {removed} duplicate rpaths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
