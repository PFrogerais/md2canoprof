"""
Structure check: every parent > child element nesting of a generated item
must already exist in a real Canoprof workspace.

The reference nestings (tag names only, no content) are embedded in
data/known_nestings.txt, extracted from a Canoprof Expert 3 export.
Regenerate them from your own export with `canoprof-check --learn`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from importlib import resources
from pathlib import Path

from .schema import ITEM_SUFFIXES, short

Nesting = tuple[str, str]
KNOWN_FILE = "known_nestings.txt"


def nestings(root: ET.Element) -> set[Nesting]:
    return {(short(parent.tag), short(child.tag)) for parent in root.iter() for child in parent}


def load_known() -> set[Nesting]:
    text = resources.files(__package__).joinpath("data", KNOWN_FILE).read_text(encoding="utf-8")
    pairs = (line.split(" > ") for line in text.splitlines() if " > " in line)
    return {(parent, child) for parent, child in pairs}


def learn(archive: Path) -> set[Nesting]:
    """Collect nestings from a Canoprof export (.scar)."""
    found: set[Nesting] = set()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.endswith(ITEM_SUFFIXES):
                found |= nestings(ET.fromstring(z.read(name)))
    return found


def unknown_nestings(archive: Path, known: set[Nesting] | None = None) -> set[Nesting]:
    """Nestings of a generated .scar that Canoprof has never produced."""
    return learn(archive) - (known if known is not None else load_known())


def save_known(pairs: set[Nesting], path: Path) -> None:
    path.write_text("".join(f"{p} > {c}\n" for p, c in sorted(pairs)), encoding="utf-8")
