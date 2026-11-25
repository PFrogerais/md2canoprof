"""
Canoprof / Scenari vocabulary shared by both conversion directions.

Every mapping lives here once, so Markdown -> Canoprof and Canoprof ->
Markdown can never drift apart: adding a block type or a code language is a
one-line change in this file.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

# --------------------------------------------------------------------------
# XML namespaces
# --------------------------------------------------------------------------
NS_SC = "http://www.utc.fr/ics/scenari/v3/core"
NS_SP = "http://www.utc.fr/ics/scenari/v3/primitive"
NS_CP = "canope.fr:canoprof"
NS_XML = "http://www.w3.org/XML/1998/namespace"

PREFIXES = {NS_SC: "sc", NS_SP: "sp", NS_CP: "cp"}

for _uri, _prefix in PREFIXES.items():
    ET.register_namespace(_prefix, _uri)

REF_URI = f"{{{NS_SC}}}refUri"
XML_SPACE = f"{{{NS_XML}}}space"


def sc(tag: str) -> str:
    return f"{{{NS_SC}}}{tag}"


def sp(tag: str) -> str:
    return f"{{{NS_SP}}}{tag}"


def cp(tag: str) -> str:
    return f"{{{NS_CP}}}{tag}"


def local(tag: str) -> str:
    """'{uri}para' -> 'para'."""
    return tag.rsplit("}", 1)[-1]


def short(tag: str) -> str:
    """'{uri}para' -> 'sc:para' (readable form used in reports)."""
    uri, _, name = tag[1:].partition("}")
    return f"{PREFIXES.get(uri, uri)}:{name}"


# --------------------------------------------------------------------------
# Blocks: Canoprof element <-> admonition tags (first alias is canonical)
# --------------------------------------------------------------------------
BLOCK_ALIASES: dict[str, tuple[str, ...]] = {
    "info": ("info", "note"),
    "definition": ("definition",),
    "example": ("example", "exemple"),
    "warning": ("warning", "attention", "danger"),
    "reminder": ("reminder", "rappel"),
    "extra": ("extra", "complement", "tip", "solution"),
}

# Admonitions placed inside the current flow rather than as a block.
FLOW_ALIASES: dict[str, tuple[str, ...]] = {
    "studentInstruction": ("consigne", "instruction"),
}

ADMONITION_TO_BLOCK = {a: blk for blk, aliases in BLOCK_ALIASES.items() for a in aliases}
ADMONITION_TO_FLOW = {a: elem for elem, aliases in FLOW_ALIASES.items() for a in aliases}
BLOCK_TO_ADMONITION = {blk: aliases[0] for blk, aliases in BLOCK_ALIASES.items()}
FLOW_TO_ADMONITION = {elem: aliases[0] for elem, aliases in FLOW_ALIASES.items()}

# --------------------------------------------------------------------------
# Code items: MIME type <-> fenced code languages (first alias is canonical)
# --------------------------------------------------------------------------
CODE_LANGUAGES: dict[str, tuple[str, ...]] = {
    "text/x-c++src": ("cpp", "c++", "cxx", "arduino", "ino"),
    "text/x-csrc": ("c", "h"),
    "text/x-python": ("python", "py"),
    "text/x-sh": ("bash", "sh"),
}
DEFAULT_CODE_MIME = "text/x-c++src"

LANGUAGE_TO_MIME = {lang: mime for mime, langs in CODE_LANGUAGES.items() for lang in langs}
MIME_TO_LANGUAGE = {mime: langs[0] for mime, langs in CODE_LANGUAGES.items()}

# --------------------------------------------------------------------------
# Inline roles and misc
# --------------------------------------------------------------------------
ROLE_EMPHASIS = "emphasis"
ROLE_SPECIFIC = "specific"      # rendered as `inline code`
ROLE_MATH = "mathtex"
ROLE_URL = "url"
ROLE_MEDIA = "media"
ROLE_ILLUSTRATION = "illustration"

# Extensions shown as pictures (anything else becomes a download link).
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".webm"}

# Workspace descriptor copied from a genuine Canoprof Expert 3 export.
WSP_META = (
    '<wspMeta><wspType key="canoprof" version="3.0.0" lang="fr-FR" '
    'uri="canoprof_fr-FR_3-0-0" title="Canoprof Expert 3">'
    '<wspOption key="canoprofExtEdx" version="3.0.0" lang="fr-FR" '
    'uri="canoprofExtEdx_fr-FR_3-0-0" title="Export edX 3"/>'
    '<wspOption key="canoprofExtLocalServerExport" version="3.0.0" lang="fr-FR" '
    'uri="canoprofExtLocalServerExport_fr-FR_3-0-0" title="Export serveur local 3"/>'
    "</wspType></wspMeta>"
)

ITEM_SUFFIXES = (".activite", ".code", ".question", ".liste")
