#!/usr/bin/env python3
"""Check that every parent->child element pair of generated items also
appears in a reference Canoprof workspace (extracted .scar)."""
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

PREFIX = {"http://www.utc.fr/ics/scenari/v3/core": "sc",
          "http://www.utc.fr/ics/scenari/v3/primitive": "sp",
          "canope.fr:canoprof": "cp"}


def short(tag: str) -> str:
    ns, _, local = tag[1:].partition("}")
    return f"{PREFIX.get(ns, ns)}:{local}"


def pairs(root: ET.Element) -> set[tuple[str, str]]:
    return {(short(p.tag), short(c.tag)) for p in root.iter() for c in p}


def main() -> int:
    ref_dir, scar = Path(sys.argv[1]), Path(sys.argv[2])
    known: set[tuple[str, str]] = set()
    for f in ref_dir.rglob("*"):
        if f.suffix in (".activite", ".code", ".question"):
            known |= pairs(ET.parse(f).getroot())
    unknown = set()
    with zipfile.ZipFile(scar) as z:
        for name in z.namelist():
            if name.endswith((".activite", ".code")):
                unknown |= pairs(ET.fromstring(z.read(name))) - known
    for p, c in sorted(unknown):
        print(f"UNKNOWN nesting: {p} > {c}")
    print("OK: all nestings exist in the reference workspace" if not unknown else "")
    return 1 if unknown else 0


if __name__ == "__main__":
    sys.exit(main())
