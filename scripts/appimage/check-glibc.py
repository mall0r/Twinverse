#!/usr/bin/env python3
"""Reject AppDirs with ELF requirements newer than the supported host libc."""

import os
import re
import subprocess
import sys
from pathlib import Path


def check(root: Path, maximum: str) -> None:
    """Inspect version requirements of every regular ELF file in root."""
    ceiling = tuple(map(int, maximum.split(".")))
    failures = []
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        count += 1
        output = subprocess.check_output(
            ["readelf", "--version-info", str(path)], text=True, env={**os.environ, "LC_ALL": "C"}
        )
        # Only requirements, not version definitions exported by a library.
        needs = output.partition("Version needs section")[2]
        versions = re.findall(r"Name: GLIBC_(\d+(?:\.\d+)+)", needs)
        newer = sorted({v for v in versions if tuple(map(int, v.split("."))) > ceiling})
        # Packed relative relocations have a named ABI requirement, not a
        # numeric symbol version (the v1.0.0 AppImage failed on exactly this).
        if "Name: GLIBC_ABI_DT_RELR" in needs and ceiling < (2, 36):
            newer.append("GLIBC_ABI_DT_RELR (requires 2.36)")
        if newer:
            failures.append(f"{path.relative_to(root)}: {', '.join(newer)}")
    if not count:
        raise SystemExit("No ELF files found to audit")
    if failures:
        raise SystemExit(f"GLIBC requirements exceed {maximum}:\n" + "\n".join(failures))
    print(f"Checked {count} ELF files: GLIBC requirements <= {maximum}")


if __name__ == "__main__":
    check(Path(sys.argv[1]), sys.argv[2])
