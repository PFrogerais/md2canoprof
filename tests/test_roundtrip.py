"""Both directions together, plus the Canoprof structure check."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import EXAMPLES

from md2canoprof import schema, structure
from md2canoprof.markdown_to_scar import convert_file
from md2canoprof.scar_to_markdown import convert_archive


def activity_xml(scar: Path) -> bytes:
    with zipfile.ZipFile(scar) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".activite")))


@pytest.fixture
def example(tmp_path: Path) -> Path:
    shutil.copytree(EXAMPLES, tmp_path / "examples")
    return tmp_path / "examples" / "tp_led.md"


def test_example_only_uses_known_nestings(example: Path):
    output, conv, _ = convert_file(example)
    assert conv.warnings == []
    assert structure.unknown_nestings(output) == set()


def test_markdown_scar_markdown_scar_is_stable(example: Path, tmp_path: Path):
    """After one normalisation pass, converting again changes nothing."""
    first, _, _ = convert_file(example, tmp_path / "first.scar")
    convert_archive(first, tmp_path / "md1")
    md1 = tmp_path / "md1" / "tp_led.md"
    second, _, _ = convert_file(md1, tmp_path / "second.scar")
    convert_archive(second, tmp_path / "md2")
    md2 = tmp_path / "md2" / "tp_led.md"

    assert md1.read_text(encoding="utf-8") == md2.read_text(encoding="utf-8")
    third, _, _ = convert_file(md2, tmp_path / "third.scar")
    assert activity_xml(second) == activity_xml(third)


def test_unknown_nesting_is_detected(tmp_path: Path):
    bogus = tmp_path / "bogus.scar"
    with zipfile.ZipFile(bogus, "w") as z:
        z.writestr("x.activite", '<sc:item xmlns:sc="http://www.utc.fr/ics/scenari/v3/core">'
                                 "<sc:para><sc:table/></sc:para></sc:item>")
    assert ("sc:para", "sc:table") in structure.unknown_nestings(bogus)


@pytest.mark.parametrize("table", [schema.BLOCK_ALIASES, schema.FLOW_ALIASES,
                                   schema.CODE_LANGUAGES])
def test_aliases_are_unique(table: dict):
    aliases = [a for values in table.values() for a in values]
    assert len(aliases) == len(set(aliases))
