"""
Minimal front matter support ('key: "value"' lines), shared by both directions.

Values are written double-quoted so MkDocs' YAML parser accepts any title
(colons, quotes, ...); reading avoids a YAML dependency.
"""

from __future__ import annotations

# Metadata keys understood by both converters, in the order they are written.
KEYS = ("title", "abstract", "duration", "organisation", "materials")
LIST_SEPARATOR = " | "     # 'materials: "a | b | c"'


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = unquote(value)
    return meta


def dump(meta: dict[str, str]) -> str:
    lines = [f"{key}: {quote(meta[key])}" for key in KEYS if meta.get(key)]
    return "---\n" + "\n".join(lines) + "\n---\n" if lines else ""
