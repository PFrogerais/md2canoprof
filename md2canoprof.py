#!/usr/bin/env python3
"""
md2canoprof.py - Convert a MkDocs-flavoured Markdown file into a Canoprof
(Scenari) archive (.scar) ready to be imported in one step.

The same Markdown source can be published with MkDocs Material and imported
into Canoprof, so a single file feeds both the website and Canoprof.

Supported Markdown -> Canoprof mapping
--------------------------------------
    front matter title/abstract/...   -> cp:activityM (title, abstract, duration,
                                         organisation, materials "a | b | c")
    ## Heading                        -> new sp:info block with that title
    ### Heading                       -> emphasised paragraph inside the block
    !!! info|definition|example|      -> typed block (sp:info, sp:definition,
        warning|reminder|extra "T"       sp:example, sp:warning, sp:reminder, sp:extra)
    !!! consigne                      -> sp:studentInstruction inside the current flow
    <!-- zone: N -->                  -> sp:studentArea with N answer lines
    paragraphs, lists, tables         -> sc:para, sc:itemizedList/orderedList, sc:table
    **bold** / *italic*               -> sc:inlineStyle role="emphasis"
    `code`                            -> sc:inlineStyle role="specific"
    $...$  /  $$...$$                 -> sc:textLeaf role="mathtex"
    [text](https://...)               -> sc:phrase role="url"
    [text](local_file.ino)            -> sc:uLink role="media" (file is embedded)
    ![alt](image.png) / video.mp4     -> sc:extBlock role="illustration" (file is embedded)
    ```cpp ... ```                    -> separate .code item + sc:extBlock

Usage
-----
    python3 md2canoprof.py seance.md                      # -> seance.scar
    python3 md2canoprof.py seance.md -o out.scar

In Canoprof, import the .scar into any folder: a sub-folder named after the
archive is created, holding the activity and all its resources.

Dependencies: markdown-it-py, mdit-py-plugins
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from urllib.parse import unquote
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.admon import admon_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

# --------------------------------------------------------------------------
# Scenari / Canoprof constants
# --------------------------------------------------------------------------
NS_SC = "http://www.utc.fr/ics/scenari/v3/core"
NS_SP = "http://www.utc.fr/ics/scenari/v3/primitive"
NS_CP = "canope.fr:canoprof"
NS_XML = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("sc", NS_SC)
ET.register_namespace("sp", NS_SP)
ET.register_namespace("cp", NS_CP)

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

# Admonition tag -> Canoprof block element (top level of cp:blocks).
BLOCK_TYPES = {
    "info": "info", "note": "info",
    "definition": "definition",
    "example": "example", "exemple": "example",
    "warning": "warning", "attention": "warning", "danger": "warning",
    "reminder": "reminder", "rappel": "reminder",
    "extra": "extra", "complement": "extra", "tip": "extra",
    "solution": "extra",   # `??? solution` from scar2md, kept as an extra block
}

# Admonition tag -> element placed inside the current cp:flow.
FLOW_TYPES = {
    "consigne": "studentInstruction",
    "instruction": "studentInstruction",
}

# Fenced code language -> MIME type of the sc:code element.
CODE_MIME = {
    "cpp": "text/x-c++src", "c++": "text/x-c++src", "cxx": "text/x-c++src",
    "arduino": "text/x-c++src", "ino": "text/x-c++src",
    "c": "text/x-csrc", "h": "text/x-csrc",
    "python": "text/x-python", "py": "text/x-python",
    "bash": "text/x-sh", "sh": "text/x-sh",
}
DEFAULT_CODE_MIME = "text/x-c++src"

ZONE_RE = re.compile(r"<!--\s*zone\s*:\s*(\d+)\s*-->")
URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def sc(tag: str) -> str:
    return f"{{{NS_SC}}}{tag}"


def sp(tag: str) -> str:
    return f"{{{NS_SP}}}{tag}"


def cp(tag: str) -> str:
    return f"{{{NS_CP}}}{tag}"


def sub(parent: ET.Element, tag: str, attrib: dict | None = None) -> ET.Element:
    return ET.SubElement(parent, tag, attrib or {})


def new_para(parent: ET.Element) -> ET.Element:
    return sub(parent, sc("para"), {f"{{{NS_XML}}}space": "preserve"})


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def parse_front_matter(text: str) -> dict[str, str]:
    """Minimal 'key: value' parser (avoids a YAML dependency)."""
    meta: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            key, value = line.split(":", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            elif len(value) >= 2 and value[0] == value[-1] == "'":
                value = value[1:-1].replace("''", "'")
            meta[key.strip().lower()] = value
    return meta


def append_text(elem: ET.Element, text: str) -> None:
    """Append text to an element, respecting ElementTree text/tail semantics."""
    if not text:
        return
    if len(elem):
        last = elem[-1]
        last.tail = (last.tail or "") + text
    else:
        elem.text = (elem.text or "") + text


def is_external(target: str) -> bool:
    return bool(URL_RE.match(target)) or target.startswith("#")


@dataclass
class Resource:
    """A file embedded in the archive next to the activity."""
    name: str               # file name inside the destination folder
    data: bytes
    is_binary_asset: bool   # True for images/videos/files (stored as name/name)


@dataclass
class Converter:
    source: Path
    resources: dict[str, Resource] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _code_count: int = 0

    # ---------------------------------------------------------------- refs
    def _ref(self, name: str) -> str:
        """Reference URI used inside the activity to point at a resource."""
        return name  # relative: resources sit next to the activity

    def _embed_file(self, target: str) -> str | None:
        """Embed a local file; return its reference URI or None if missing."""
        target = unquote(target)  # the parser percent-encodes spaces/accents
        path = (self.source.parent / target).resolve()
        if not path.is_file():
            self.warnings.append(f"missing file: {target}")
            return None
        data = path.read_bytes()
        name = path.name
        suffix = 2
        # All resources sit next to the activity: rename on name clashes.
        while name in self.resources and self.resources[name].data != data:
            name = f"{path.stem}_{suffix}{path.suffix}"
            suffix += 1
        if name not in self.resources:
            self.resources[name] = Resource(name, data, True)
        return self._ref(name)

    def _embed_code(self, code: str, lang: str) -> str:
        self._code_count += 1
        name = f"{self.source.stem}_code{self._code_count:02d}.code"
        mime = CODE_MIME.get(lang.lower(), DEFAULT_CODE_MIME)
        if lang and lang.lower() not in CODE_MIME:
            self.warnings.append(f"unknown code language '{lang}', using {mime}")
        item = ET.Element(sc("item"))
        code_root = sub(item, cp("code"))
        code_elem = sub(code_root, sc("code"),
                        {"mimeType": mime, f"{{{NS_XML}}}space": "preserve"})
        code_elem.text = code
        self.resources[name] = Resource(name, serialize(item), False)
        return self._ref(name)

    # ------------------------------------------------------------- inline
    def inline(self, node: SyntaxTreeNode, para: ET.Element,
               images: list[str]) -> None:
        """Render inline children of `node` into `para`.

        Images cannot live inside a paragraph in Canoprof: their reference
        URIs are collected in `images` and emitted after the paragraph.
        """
        for child in node.children:
            kind = child.type
            if kind == "text":
                append_text(para, child.content)
            elif kind == "softbreak":
                append_text(para, " ")
            elif kind == "hardbreak":
                append_text(para, "\n")
            elif kind in ("strong", "em"):
                style = sub(para, sc("inlineStyle"), {"role": "emphasis"})
                self.inline(child, style, images)
            elif kind == "code_inline":
                style = sub(para, sc("inlineStyle"), {"role": "specific"})
                style.text = child.content
            elif kind == "math_inline":
                leaf = sub(para, sc("textLeaf"), {"role": "mathtex"})
                leaf.text = child.content.strip()
            elif kind == "link":
                self._link(child, para, images)
            elif kind == "image":
                ref = self._embed_file(str(child.attrs.get("src", "")))
                if ref:
                    images.append(ref)
            elif kind == "html_inline":
                continue  # inline HTML is ignored on the Canoprof side
            else:
                self.warnings.append(f"unsupported inline element: {kind}")
                append_text(para, child.content)

    def _link(self, node: SyntaxTreeNode, para: ET.Element,
              images: list[str]) -> None:
        href = str(node.attrs.get("href", ""))
        if is_external(href):
            phrase = sub(para, sc("phrase"), {"role": "url"})
            link = sub(phrase, cp("link"), {f"{{{NS_XML}}}space": "default"})
            sub(link, sp("url")).text = href
            self.inline(node, phrase, images)
            return
        ref = self._embed_file(href)
        if ref is None:
            self.inline(node, para, images)
            return
        ulink = sub(para, sc("uLink"), {"role": "media", f"{{{NS_SC}}}refUri": ref})
        self.inline(node, ulink, images)

    def inline_block(self, inline_node: SyntaxTreeNode | None,
                     container: ET.Element) -> None:
        """Emit one sc:para (if not empty) followed by its extracted images."""
        if inline_node is None:
            return
        images: list[str] = []
        para = new_para(container)
        self.inline(inline_node, para, images)
        if not len(para) and not (para.text or "").strip():
            container.remove(para)  # paragraph contained only images
        for ref in images:
            sub(container, sc("extBlock"),
                {"role": "illustration", f"{{{NS_SC}}}refUri": ref})

    def paragraph(self, node: SyntaxTreeNode, txt: ET.Element) -> None:
        self.inline_block(node.children[0] if node.children else None, txt)

    # ------------------------------------------------------- block content
    def txt_content(self, node: SyntaxTreeNode, txt: ET.Element) -> None:
        """Render a block-level Markdown node into a cp:txt container."""
        kind = node.type
        if kind == "paragraph":
            self.paragraph(node, txt)
        elif kind in ("bullet_list", "ordered_list"):
            tag = "itemizedList" if kind == "bullet_list" else "orderedList"
            lst = sub(txt, sc(tag))
            for item in node.children:
                li = sub(lst, sc("listItem"))
                for part in item.children:
                    self.txt_content(part, li)
        elif kind == "table":
            self.table(node, txt)
        elif kind == "math_block":
            para = new_para(txt)
            sub(para, sc("textLeaf"), {"role": "mathtex"}).text = node.content.strip()
        elif kind in ("fence", "code_block"):
            lang = (node.info or "").strip().split(" ")[0]
            ref = self._embed_code(node.content, lang)
            sub(txt, sc("extBlock"), {"role": "illustration", f"{{{NS_SC}}}refUri": ref})
        elif kind == "heading":
            para = new_para(txt)
            style = sub(para, sc("inlineStyle"), {"role": "emphasis"})
            self.inline(node.children[0], style, [])
        elif kind == "blockquote":
            for part in node.children:
                self.txt_content(part, txt)
        elif kind in ("hr", "html_block"):
            pass
        else:
            self.warnings.append(f"unsupported block element: {kind}")

    def table(self, node: SyntaxTreeNode, txt: ET.Element) -> None:
        rows = [tr for section in node.children for tr in section.children]
        if not rows:
            return
        ncols = max(len(tr.children) for tr in rows)
        table = sub(txt, sc("table"), {"role": ""})
        width = str(max(1, 84 // ncols))
        for _ in range(ncols):
            sub(table, sc("column"), {"width": width})
        for tr in rows:
            row = sub(table, sc("row"))
            for cell_node in tr.children:
                cell = sub(row, sc("cell"))
                inline_node = cell_node.children[0] if cell_node.children else None
                self.inline_block(inline_node, cell)
            for _ in range(ncols - len(tr.children)):
                sub(row, sc("cell"))

    # ---------------------------------------------------------------- flow
    def flow(self, nodes: list[SyntaxTreeNode], flow: ET.Element) -> None:
        """Render a sequence of Markdown nodes into a cp:flow."""
        current_txt: ET.Element | None = None

        def txt() -> ET.Element:
            nonlocal current_txt
            if current_txt is None:
                current_txt = sub(sub(flow, sp("txt")), cp("txt"))
            return current_txt

        for node in nodes:
            if node.type == "admonition":
                tag = node.meta.get("tag", "").lower()
                if tag in FLOW_TYPES:
                    current_txt = None
                    holder = sub(sub(flow, sp(FLOW_TYPES[tag])), cp("txt"))
                    for part in node.children:
                        if part.type != "admonition_title":
                            self.txt_content(part, holder)
                    continue
                self.warnings.append(
                    f"nested block '!!! {tag}' flattened into the current block")
                for part in node.children:
                    if part.type != "admonition_title":
                        self.txt_content(part, txt())
                continue
            if node.type == "html_block":
                match = ZONE_RE.search(node.content)
                if match:
                    current_txt = None
                    area = sub(sub(flow, sp("studentArea")), cp("studentArea"))
                    sub(area, sp("lines")).text = match.group(1)
                continue
            self.txt_content(node, txt())

    # --------------------------------------------------------------- blocks
    def new_block(self, blocks: ET.Element, kind: str, title: str | None) -> ET.Element:
        block = sub(sub(blocks, sp(kind)), cp("block"))
        block_meta = sub(block, cp("blockM"))
        if title:
            sub(block_meta, sp("title")).text = title
        return sub(sub(block, sp("body")), cp("flow"))

    @staticmethod
    def admonition_title(node: SyntaxTreeNode) -> str | None:
        """Explicit title only (`!!! warning "Title"`), not the default one."""
        if '"' not in (node.info or ""):
            return None
        for part in node.children:
            if part.type == "admonition_title":
                return part.children[0].content if part.children else None
        return None

    # ------------------------------------------------------------- document
    def convert(self, markdown: str) -> tuple[ET.Element, str]:
        parser = (MarkdownIt("commonmark").enable("table")
                  .use(front_matter_plugin).use(admon_plugin).use(dollarmath_plugin))
        tree = SyntaxTreeNode(parser.parse(markdown))

        meta: dict[str, str] = {}
        nodes = list(tree.children)
        if nodes and nodes[0].type == "front_matter":
            meta = parse_front_matter(nodes.pop(0).content)

        # A leading H1 provides the title when the front matter does not.
        if nodes and nodes[0].type == "heading" and nodes[0].tag == "h1":
            h1 = nodes.pop(0)
            meta.setdefault("title", h1.children[0].content)

        item = ET.Element(sc("item"), {"version": "1"})
        activity = sub(item, cp("textActivity"))
        self.activity_meta(sub(activity, cp("activityM")), meta)
        blocks = sub(sub(activity, sp("body")), cp("blocks"))

        pending: list[SyntaxTreeNode] = []
        pending_title: str | None = None

        def flush() -> None:
            nonlocal pending, pending_title
            if pending or pending_title:
                self.flow(pending, self.new_block(blocks, "info", pending_title))
            pending, pending_title = [], None

        for node in nodes:
            if node.type == "heading" and node.tag in ("h1", "h2"):
                flush()
                pending_title = node.children[0].content
            elif (node.type == "admonition"
                  and node.meta.get("tag", "").lower() in BLOCK_TYPES):
                flush()
                kind = BLOCK_TYPES[node.meta["tag"].lower()]
                body = [c for c in node.children if c.type != "admonition_title"]
                self.flow(body, self.new_block(blocks, kind, self.admonition_title(node)))
            else:
                pending.append(node)
        flush()

        title = meta.get("title", self.source.stem)
        return item, title

    @staticmethod
    def activity_meta(activity_m: ET.Element, meta: dict[str, str]) -> None:
        sub(activity_m, sp("title")).text = meta.get("title", "Sans titre")
        if meta.get("abstract"):
            desc = sub(sub(activity_m, sp("abstract")), cp("txtDesc"))
            new_para(desc).text = meta["abstract"]
        if meta.get("duration") or meta.get("organisation") or meta.get("materials"):
            org = sub(activity_m, sp("organisationData"))
            if meta.get("duration"):
                sub(org, sp("duration")).text = meta["duration"]
            if meta.get("materials"):
                desc = sub(sub(org, sp("materials")), cp("txtDesc"))
                for item in meta["materials"].split(" | "):
                    new_para(desc).text = item
            if meta.get("organisation"):
                desc = sub(sub(org, sp("organisation")), cp("txtDesc"))
                new_para(desc).text = meta["organisation"]


# --------------------------------------------------------------------------
# Archive writer
# --------------------------------------------------------------------------
def serialize(item: ET.Element) -> bytes:
    body = ET.tostring(item, encoding="unicode")
    return ('<?xml version="1.0"?>\n' + body).encode("utf-8")


def write_scar(output: Path, activity_name: str, activity: bytes,
               resources: dict[str, Resource]) -> None:
    """Write a flat .scar: the activity and its resources side by side.

    Canoprof imports the archive into the folder you pick (as a sub-folder
    named after the .scar), so relative references always resolve.
    """
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(".wspmeta", WSP_META)
        archive.writestr(activity_name, activity)
        for res in resources.values():
            if res.is_binary_asset:
                # Scenari stores a binary as a folder named after the file.
                archive.writestr(f"{res.name}/{res.name}", res.data)
            else:
                archive.writestr(res.name, res.data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("markdown", type=Path, help="source Markdown file")
    parser.add_argument("-o", "--output", type=Path, help="output .scar file")
    args = parser.parse_args()

    if not args.markdown.is_file():
        print(f"error: {args.markdown} not found", file=sys.stderr)
        return 1

    text = args.markdown.read_text(encoding="utf-8")
    conv = Converter(args.markdown)
    item, title = conv.convert(text)

    output = args.output or args.markdown.with_suffix(".scar")
    activity_name = f"{args.markdown.stem}.activite"
    write_scar(output, activity_name, serialize(item), conv.resources)

    for warning in conv.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{output}: '{title}' -> {activity_name} "
          f"({len(conv.resources)} embedded resource(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
