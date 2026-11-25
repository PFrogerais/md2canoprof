"""Shared fixtures and helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from md2canoprof.archive import ScarReader
from md2canoprof.markdown_to_scar import convert_file
from md2canoprof.schema import NS_CP, NS_SC, NS_SP

NS = {"sc": NS_SC, "sp": NS_SP, "cp": NS_CP}
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def make_md(tmp_path: Path):
    """Write a Markdown file (and optional resources) in a temp folder."""

    def _make(text: str, name: str = "lesson.md", files: dict[str, bytes] | None = None) -> Path:
        for rel, data in (files or {}).items():
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        source = tmp_path / name
        source.write_text(text, encoding="utf-8")
        return source

    return _make


@pytest.fixture
def to_activity():
    """Convert Markdown to .scar and return (activity root, archive members, converter)."""

    def _convert(source: Path):
        output, conv, _ = convert_file(source)
        reader = ScarReader.open(output)
        try:
            root = reader.xml(f"/{source.stem}.activite")
            members = sorted(zipfile.ZipFile(output).namelist())
        finally:
            reader.close()
        return root, members, conv

    return _convert
