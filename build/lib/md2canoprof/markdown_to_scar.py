"""
Markdown (MkDocs Material flavour) -> Canoprof text activity.

    front matter title/abstract/...   -> cp:activityM
    ## Heading                        -> sp:info block with that title
    ### Heading                       -> emphasised paragraph inside the block
    !!! info|definition|example|      -> typed block (see schema.BLOCK_ALIASES)
        warning|reminder|extra "T"
    !!! consigne                      -> sp:studentInstruction in the current flow
    <!-- zone: N -->                  -> sp:studentArea with N answer lines
    paragraphs, lists, tables         -> sc:para, sc:itemizedList/orderedList, sc:table
    **bold** / *italic*               -> sc:inlineStyle role="emphasis"
    `code`                            -> sc:inlineStyle role="specific"
    $...$  /  $$...$$                 -> sc:textLeaf role="mathtex"
    [text](https://...)               -> sc:phrase role="url"
    [text](local_file.ino)            -> sc:uLink role="media" (file embedded)
    ![alt](image.svg) / video.mp4     -> sc:extBlock role="illustration" (file embedded)
    ```cpp ... ```                    -> separate .code item + sc:extBlock
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.admon import admon_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from . import frontmatter
from .archive import Resource, serialize, write_scar
from .schema import (
    ADMONITION_TO_BLOCK,
    ADMONITION_TO_FLOW,
    DEFAULT_CODE_MIME,
    LANGUAGE_TO_MIME,
    REF_URI,
    ROLE_EMPHASIS,
    ROLE_ILLUSTRATION,
    ROLE_MATH,
    ROLE_MEDIA,
    ROLE_SPECIFIC,
    ROLE_URL,
    XML_SPACE,
    cp,
    sc,
    sp,
)

ZONE_RE = re.compile(r"<!--\s*zone\s*:\s*(\d+)\s*-->")
URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
TABLE_WIDTH = 84    # total width Canoprof uses for 3 columns of 28


def _parser() -> MarkdownIt:
    return (MarkdownIt("commonmark").enable("table")
            .use(front_matter_plugin).use(admon_plugin).use(dollarmath_plugin))


def sub(parent: ET.Element, tag: str, attrib: dict | None = None) -> ET.Element:
    return ET.SubElement(parent, tag, attrib or {})


def new_para(parent: ET.Element) -> ET.Element:
    return sub(parent, sc("para"), {XML_SPACE: "preserve"})


def append_text(elem: ET.Element, text: str) -> None:
    """Append text to an element, respecting ElementTree text/tail semantics."""
    if not text:
        return
    if len(elem):
        elem[-1].tail = (elem[-1].tail or "") + text
    else:
        elem.text = (elem.text or "") + text


@dataclass
class MarkdownConverter:
    """Convert one Markdown file; resources are resolved from its folder."""
    source: Path
    resources: dict[str, Resource] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _code_count: int = 0

    # ----------------------------------------------------------- resources
    def embed_file(self, target: str) -> str | None:
        """Embed a local file next to the activity; return its reference."""
        target = unquote(target)        # the parser percent-encodes paths
        path = (self.source.parent / target).resolve()
        if not path.is_file():
            self.warnings.append(f"missing file: {target}")
            return None
        data = path.read_bytes()
        name, suffix = path.name, 2
        # Everything is flattened next to the activity: rename on clashes.
        while name in self.resources and self.resources[name].data != data:
            name = f"{path.stem}_{suffix}{path.suffix}"
            suffix += 1
        self.resources.setdefault(name, Resource(name, data, binary=True))
        return name

    def embed_code(self, code: str, lang: str) -> str:
        self._code_count += 1
        name = f"{self.source.stem}_code{self._code_count:02d}.code"
        mime = LANGUAGE_TO_MIME.get(lang.lower(), DEFAULT_CODE_MIME)
        if lang and lang.lower() not in LANGUAGE_TO_MIME:
            self.warnings.append(f"unknown code language '{lang}', using {mime}")
        item = ET.Element(sc("item"))
        sub(sub(item, cp("code")), sc("code"),
            {"mimeType": mime, XML_SPACE: "preserve"}).text = code
        self.resources[name] = Resource(name, serialize(item), binary=False)
        return name

    @staticmethod
    def ext_block(container: ET.Element, ref: str) -> None:
        sub(container, sc("extBlock"), {"role": ROLE_ILLUSTRATION, REF_URI: ref})

    # -------------------------------------------------------------- inline
    def inline(self, node: SyntaxTreeNode, para: ET.Element, images: list[str]) -> None:
        """Render inline children into `para`.

        Canoprof does not allow images inside a paragraph: their references
        are collected in `images` and emitted after it.
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
                self.inline(child, sub(para, sc("inlineStyle"), {"role": ROLE_EMPHASIS}), images)
            elif kind == "code_inline":
                sub(para, sc("inlineStyle"), {"role": ROLE_SPECIFIC}).text = child.content
            elif kind == "math_inline":
                sub(para, sc("textLeaf"), {"role": ROLE_MATH}).text = child.content.strip()
            elif kind == "link":
                self.link(child, para, images)
            elif kind == "image":
                ref = self.embed_file(str(child.attrs.get("src", "")))
                if ref:
                    images.append(ref)
            elif kind != "html_inline":      # inline HTML is dropped
                self.warnings.append(f"unsupported inline element: {kind}")
                append_text(para, child.content)

    def link(self, node: SyntaxTreeNode, para: ET.Element, images: list[str]) -> None:
        href = str(node.attrs.get("href", ""))
        if URL_RE.match(href) or href.startswith("#"):
            phrase = sub(para, sc("phrase"), {"role": ROLE_URL})
            link = sub(phrase, cp("link"), {XML_SPACE: "default"})
            sub(link, sp("url")).text = href
            self.inline(node, phrase, images)
            return
        ref = self.embed_file(href)
        target = para if ref is None else \
            sub(para, sc("uLink"), {"role": ROLE_MEDIA, REF_URI: ref})
        self.inline(node, target, images)

    def inline_block(self, inline_node: SyntaxTreeNode | None, container: ET.Element) -> None:
        """Emit one sc:para (unless empty) followed by its extracted images."""
        if inline_node is None:
            return
        images: list[str] = []
        para = new_para(container)
        self.inline(inline_node, para, images)
        if not len(para) and not (para.text or "").strip():
            container.remove(para)
        for ref in images:
            self.ext_block(container, ref)

    # --------------------------------------------------------- block content
    def content(self, node: SyntaxTreeNode, txt: ET.Element) -> None:
        """Render a block-level node into a cp:txt (or list item / cell)."""
        kind = node.type
        if kind == "paragraph":
            self.inline_block(node.children[0] if node.children else None, txt)
        elif kind in ("bullet_list", "ordered_list"):
            lst = sub(txt, sc("itemizedList" if kind == "bullet_list" else "orderedList"))
            for item in node.children:
                li = sub(lst, sc("listItem"))
                for part in item.children:
                    self.content(part, li)
        elif kind == "table":
            self.table(node, txt)
        elif kind == "math_block":
            sub(new_para(txt), sc("textLeaf"), {"role": ROLE_MATH}).text = node.content.strip()
        elif kind in ("fence", "code_block"):
            lang = (node.info or "").strip().split(" ")[0]
            self.ext_block(txt, self.embed_code(node.content, lang))
        elif kind == "heading":
            style = sub(new_para(txt), sc("inlineStyle"), {"role": ROLE_EMPHASIS})
            self.inline(node.children[0], style, [])
        elif kind == "blockquote":
            for part in node.children:
                self.content(part, txt)
        elif kind not in ("hr", "html_block"):
            self.warnings.append(f"unsupported block element: {kind}")

    def table(self, node: SyntaxTreeNode, txt: ET.Element) -> None:
        rows = [tr for section in node.children for tr in section.children]
        if not rows:
            return
        ncols = max(len(tr.children) for tr in rows)
        table = sub(txt, sc("table"), {"role": ""})
        for _ in range(ncols):
            sub(table, sc("column"), {"width": str(max(1, TABLE_WIDTH // ncols))})
        for tr in rows:
            row = sub(table, sc("row"))
            for cell_node in tr.children:
                self.inline_block(cell_node.children[0] if cell_node.children else None,
                                  sub(row, sc("cell")))
            for _ in range(ncols - len(tr.children)):
                sub(row, sc("cell"))

    # ---------------------------------------------------------------- flow
    def flow(self, nodes: list[SyntaxTreeNode], flow: ET.Element) -> None:
        """Render a sequence of nodes into a cp:flow."""
        current: ET.Element | None = None

        def txt() -> ET.Element:
            nonlocal current
            if current is None:
                current = sub(sub(flow, sp("txt")), cp("txt"))
            return current

        for node in nodes:
            if node.type == "admonition":
                tag = node.meta.get("tag", "").lower()
                body = [c for c in node.children if c.type != "admonition_title"]
                if tag in ADMONITION_TO_FLOW:
                    current = None
                    holder = sub(sub(flow, sp(ADMONITION_TO_FLOW[tag])), cp("txt"))
                    for part in body:
                        self.content(part, holder)
                else:
                    self.warnings.append(f"nested block '!!! {tag}' flattened")
                    for part in body:
                        self.content(part, txt())
            elif node.type == "html_block":
                match = ZONE_RE.search(node.content)
                if match:
                    current = None
                    area = sub(sub(flow, sp("studentArea")), cp("studentArea"))
                    sub(area, sp("lines")).text = match.group(1)
            else:
                self.content(node, txt())

    # -------------------------------------------------------------- document
    @staticmethod
    def explicit_title(node: SyntaxTreeNode) -> str | None:
        """Title of `!!! warning "Title"`, not the default capitalised tag."""
        if '"' not in (node.info or ""):
            return None
        for part in node.children:
            if part.type == "admonition_title" and part.children:
                return part.children[0].content
        return None

    @staticmethod
    def new_block(blocks: ET.Element, kind: str, title: str | None) -> ET.Element:
        block = sub(sub(blocks, sp(kind)), cp("block"))
        block_meta = sub(block, cp("blockM"))
        if title:
            sub(block_meta, sp("title")).text = title
        return sub(sub(block, sp("body")), cp("flow"))

    @staticmethod
    def activity_meta(activity_m: ET.Element, meta: dict[str, str]) -> None:
        def desc(parent: ET.Element, tag: str, paragraphs: list[str]) -> None:
            holder = sub(sub(parent, sp(tag)), cp("txtDesc"))
            for text in paragraphs:
                new_para(holder).text = text

        sub(activity_m, sp("title")).text = meta.get("title", "Sans titre")
        if meta.get("abstract"):
            desc(activity_m, "abstract", [meta["abstract"]])
        if any(meta.get(k) for k in ("duration", "materials", "organisation")):
            org = sub(activity_m, sp("organisationData"))      # Canoprof order
            if meta.get("duration"):
                sub(org, sp("duration")).text = meta["duration"]
            if meta.get("materials"):
                desc(org, "materials", meta["materials"].split(frontmatter.LIST_SEPARATOR))
            if meta.get("organisation"):
                desc(org, "organisation", [meta["organisation"]])

    def convert(self, markdown: str) -> tuple[ET.Element, dict[str, str]]:
        nodes = list(SyntaxTreeNode(_parser().parse(markdown)).children)
        meta: dict[str, str] = {}
        if nodes and nodes[0].type == "front_matter":
            meta = frontmatter.parse(nodes.pop(0).content)
        if nodes and nodes[0].type == "heading" and nodes[0].tag == "h1":
            meta.setdefault("title", nodes.pop(0).children[0].content)
        meta.setdefault("title", self.source.stem)

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
            tag = node.meta.get("tag", "").lower() if node.type == "admonition" else ""
            if node.type == "heading" and node.tag in ("h1", "h2"):
                flush()
                pending_title = node.children[0].content
            elif tag in ADMONITION_TO_BLOCK:
                flush()
                body = [c for c in node.children if c.type != "admonition_title"]
                self.flow(body, self.new_block(blocks, ADMONITION_TO_BLOCK[tag],
                                               self.explicit_title(node)))
            else:
                pending.append(node)
        flush()
        return item, meta


def convert_file(markdown: Path, output: Path | None = None) -> tuple[Path, MarkdownConverter, str]:
    """Convert a Markdown file to a .scar; return (output, converter, title)."""
    conv = MarkdownConverter(markdown)
    item, meta = conv.convert(markdown.read_text(encoding="utf-8"))
    output = output or markdown.with_suffix(".scar")
    write_scar(output, f"{markdown.stem}.activite", serialize(item),
               list(conv.resources.values()))
    return output, conv, meta["title"]
