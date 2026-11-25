"""
Canoprof export (.scar) -> tree of MkDocs-flavoured Markdown files.

Every text activity becomes a .md file at its workspace path; images, SVG,
videos and attachments are copied next to it, code items are inlined as
fenced blocks, and collections become index pages. The output can be
imported back with markdown_to_scar.

Not converted (reported): quiz activities, HTML activities.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from . import frontmatter
from .archive import ScarReader
from .schema import (
    BLOCK_TO_ADMONITION,
    FLOW_TO_ADMONITION,
    IMAGE_EXTENSIONS,
    MIME_TO_LANGUAGE,
    REF_URI,
    ROLE_MATH,
    ROLE_SPECIFIC,
    ROLE_URL,
    cp,
    local,
    sc,
    sp,
)

CONVERTED_KINDS = ("textActivity", "collectionActivity")

# Characters read as Markdown syntax inside plain text.
MD_SPECIAL = re.compile(r"([\\`*\[\]])")
LINE_START_SPECIAL = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])(\s)")
EMPTY_BODY = "…"


def escape_text(text: str) -> str:
    return MD_SPECIAL.sub(r"\\\1", text).replace("<", "&lt;").replace("$", r"\$")


def indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line.strip() else "" for line in text.split("\n"))


def wrap(marker: str, content: str) -> str:
    """Wrap content in an inline marker, keeping surrounding spaces outside."""
    stripped = content.strip()
    if not stripped:
        return content
    lead = content[: len(content) - len(content.lstrip())]
    trail = content[len(content.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def admonition(tag: str, body: str, title: str | None = None) -> str:
    head = f"!!! {tag}" + (f" {frontmatter.quote(title)}" if title else "")
    return f"{head}\n{indent(body or EMPTY_BODY)}"


@dataclass
class ScarConverter:
    reader: ScarReader
    out_dir: Path
    force: bool = False
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    copied: set[str] = field(default_factory=set)
    _item: str = ""     # workspace path of the item being converted

    # ------------------------------------------------------------- output
    def md_path(self, ws_path: str) -> Path:
        return self.out_dir / (ws_path.lstrip("/").rsplit(".", 1)[0] + ".md")

    def write(self, path: Path, text: str) -> None:
        if path.exists() and not self.force:
            self.warnings.append(f"exists, not overwritten (use --force): {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.written.append(path)

    def link_to(self, ws_target: str) -> str:
        """Relative, URL-encoded link from the current .md to a workspace path."""
        return quote(posixpath.relpath(ws_target, posixpath.dirname(self._item)))

    def warn(self, message: str) -> None:
        self.warnings.append(f"{self._item}: {message}")

    def copy_resource(self, ref: str) -> str | None:
        ws_path = self.reader.resolve(self._item, ref)
        data = self.reader.binary(ws_path)
        if data is None:
            self.warn(f"missing resource {ref}")
            return None
        if ws_path not in self.copied:
            target = self.out_dir / ws_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.copied.add(ws_path)
        return self.link_to(ws_path)

    # ------------------------------------------------------------- inline
    def inline(self, elem: ET.Element) -> str:
        parts = [escape_text(elem.text or "")]
        for child in elem:
            parts.append(self.inline_child(child))
            parts.append(escape_text(child.tail or ""))
        return "".join(parts)

    def inline_child(self, child: ET.Element) -> str:
        tag, role = local(child.tag), child.get("role", "")
        if tag == "inlineStyle" and role == ROLE_SPECIFIC:
            code = "".join(child.itertext())
            return code if "`" in code else wrap("`", code)
        if tag == "inlineStyle":
            return wrap("**", self.inline(child))
        if tag == "textLeaf" and role == ROLE_MATH:
            return f"${(child.text or '').strip()}$"
        if tag == "textLeaf":                           # cloze gap...
            return f"[{escape_text(child.text or '')}]"
        if tag == "phrase" and role == ROLE_URL:
            return self.url_phrase(child)
        if tag == "uLink":
            label = self.inline(child).strip()
            target = self.copy_resource(child.get(REF_URI, ""))
            return f"[{label}]({target})" if target else label
        if tag == "inlineImg":
            target = self.copy_resource(child.get(REF_URI, ""))
            return f"![]({target})" if target else ""
        self.warn(f"unsupported inline <{tag}>")
        return self.inline(child)

    def url_phrase(self, phrase: ET.Element) -> str:
        link = phrase.find(cp("link"))
        url = link.findtext(sp("url"), "") if link is not None else ""
        label_elem = ET.Element("label")
        label_elem.text = phrase.text
        label_elem.extend(c for c in phrase if c is not link)
        label = self.inline(label_elem).strip() or url
        return f"[{label}]({url})" if url else label

    # ---------------------------------------------------------- block text
    def para(self, elem: ET.Element) -> str:
        children = list(elem)
        if (len(children) == 1 and local(children[0].tag) == "textLeaf"
                and children[0].get("role") == ROLE_MATH
                and not (elem.text or "").strip() and not (children[0].tail or "").strip()):
            return f"$$\n{(children[0].text or '').strip()}\n$$"
        text = re.sub(r"[ \t]*\n[ \t]*", " ", self.inline(elem)).strip()
        return LINE_START_SPECIAL.sub(r"\1\\\2\3", text)

    def txt(self, container: ET.Element) -> str:
        """Render a cp:txt / cp:txtDesc / sc:listItem / sc:cell."""
        blocks: list[str] = []
        prev_tag = ""
        for child in container:
            tag = local(child.tag)
            if tag == "para":
                blocks.append(self.para(child))
            elif tag in ("itemizedList", "orderedList"):
                if prev_tag == tag:
                    blocks.append("<!-- -->")      # keeps adjacent lists apart
                blocks.append(self.list_block(child, ordered=(tag == "orderedList")))
            elif tag == "table":
                blocks.append(self.table(child))
            elif tag == "extBlock":
                blocks.append(self.ext_block(child))
            else:
                self.warn(f"unsupported block <{tag}>")
            prev_tag = tag
        return "\n\n".join(b for b in blocks if b)

    def list_block(self, elem: ET.Element, ordered: bool) -> str:
        entries = []
        for number, item in enumerate(elem, start=1):
            marker = f"{number}." if ordered else "-"
            first, _, rest = self.txt(item).partition("\n")
            entry = f"{marker} {first}"
            if rest:
                entry += "\n" + indent(rest, " " * (len(marker) + 1))
            entries.append(entry)
        loose = any("\n\n" in entry for entry in entries)
        return ("\n\n" if loose else "\n").join(entries)

    def table(self, elem: ET.Element) -> str:
        rows = [[self.txt(cell).replace("\n\n", "<br>").replace("\n", " ").replace("|", r"\|")
                 for cell in row.findall(sc("cell"))]
                for row in elem.findall(sc("row"))]
        if not rows:
            return ""
        ncols = max(len(r) for r in rows)
        lines = ["| " + " | ".join((c or " ") for c in r + [""] * (ncols - len(r))) + " |"
                 for r in rows]
        lines.insert(1, "|" + "|".join(["---"] * ncols) + "|")
        return "\n".join(lines)

    def ext_block(self, elem: ET.Element) -> str:
        ref = elem.get(REF_URI, "")
        ws_path = self.reader.resolve(self._item, ref)
        if ws_path.endswith(".code"):
            return self.code_block(ws_path, ref)
        target = self.copy_resource(ref)
        if target is None:
            return ""
        name = Path(posixpath.basename(ws_path))
        if name.suffix.lower() in IMAGE_EXTENSIONS:
            return f"![{escape_text(name.stem)}]({target})"
        return f"[{escape_text(name.name)}]({target})"

    def code_block(self, ws_path: str, ref: str) -> str:
        root = self.reader.xml(ws_path)
        code_elem = root.find(f".//{sc('code')}") if root is not None else None
        if code_elem is None:
            self.warn(f"missing code item {ref}")
            return ""
        code = code_elem.text or ""
        lang = MIME_TO_LANGUAGE.get(code_elem.get("mimeType", ""), "")
        fence = "````" if "```" in code else "```"
        return f"{fence}{lang}\n{code.rstrip()}\n{fence}"

    # ---------------------------------------------------------------- flow
    def flow(self, flow: ET.Element | None) -> str:
        if flow is None:
            return ""
        parts: list[str] = []
        for child in flow:
            tag = local(child.tag)
            if tag == "txt":
                parts.append(self.txt(child[0]) if len(child) else "")
            elif tag in FLOW_TO_ADMONITION:
                parts.append(admonition(FLOW_TO_ADMONITION[tag],
                                        self.txt(child[0]) if len(child) else ""))
            elif tag == "studentArea":
                lines = child.findtext(".//" + sp("lines"), "3")
                parts.append(f"<!-- zone: {lines} -->")
            elif tag == "visavis":
                # Side-by-side layout: rendered one after the other.
                for side in ("first", "next"):
                    side_elem = child.find(f".//{sp(side)}")
                    if side_elem is not None and len(side_elem):
                        parts.append(self.flow(side_elem[0]))
            else:
                self.warn(f"unsupported flow <{tag}>")
        return "\n\n".join(p for p in parts if p)

    # -------------------------------------------------------------- blocks
    def block(self, wrapper: ET.Element, level: int) -> str:
        kind = local(wrapper.tag)
        if wrapper.find(cp("openQuestion")) is not None:
            return self.exercise(wrapper.find(cp("openQuestion")))
        if kind == "question" and wrapper.get(REF_URI):
            self.skipped.append(f"{self._item}: question {wrapper.get(REF_URI)}")
            return f"<!-- canoprof: question non convertie ({wrapper.get(REF_URI)}) -->"
        block = wrapper.find(cp("block"))
        if block is None:
            self.warn(f"unsupported block <{kind}>")
            return ""
        title = (block.findtext(f"{cp('blockM')}/{sp('title')}") or "").strip() or None
        body = self.flow(block.find(f"{sp('body')}/{cp('flow')}"))
        if kind == "info" and title:
            return f"{'#' * level} {title}\n\n{body}".rstrip()
        return admonition(BLOCK_TO_ADMONITION.get(kind, "info"), body, title)

    def exercise(self, question: ET.Element) -> str:
        title = question.findtext(f"{cp('questionM')}/{sp('title')}") or "Exercice"
        body = self.flow(question.find(f"{sp('question')}/{cp('flow')}"))
        out = f"## {title.strip()}\n\n{body}".rstrip()
        solution = question.find(f"{sp('solution')}/{cp('flow')}")
        if solution is not None:
            out += '\n\n??? solution "Solution"\n' + indent(self.flow(solution) or EMPTY_BODY)
        return out

    def blocks(self, activity: ET.Element, level: int) -> list[str]:
        parts = []
        container = activity.find(f"{sp('body')}/{cp('blocks')}")
        for wrapper in (container if container is not None else []):
            parts.append(self.block(wrapper, level))
        for section in activity.findall(sp("section")):
            sub_activity = section.find(cp("textActivity"))
            if sub_activity is not None:
                title = sub_activity.findtext(f"{cp('activityM')}/{sp('title')}", "")
                parts.append(f"## {title.strip()}")
                parts.extend(self.blocks(sub_activity, level + 1))
        return [p for p in parts if p]

    # ---------------------------------------------------------- documents
    def metadata(self, meta: ET.Element | None) -> dict[str, str]:
        if meta is None:
            return {}

        def desc(path: str) -> str:
            elem = meta.find(path)
            return re.sub(r"\s+", " ", self.txt(elem)) if elem is not None else ""

        org = f"{sp('organisationData')}/"
        materials = meta.find(f"{org}{sp('materials')}/{cp('txtDesc')}")
        return {
            "title": (meta.findtext(sp("title")) or "").strip(),
            "abstract": desc(f"{sp('abstract')}/{cp('txtDesc')}"),
            "duration": (meta.findtext(f"{org}{sp('duration')}") or "").strip(),
            "organisation": desc(f"{org}{sp('organisation')}/{cp('txtDesc')}"),
            "materials": frontmatter.LIST_SEPARATOR.join(
                p for p in (self.para(e) for e in materials.findall(sc("para"))) if p)
            if materials is not None else "",
        }

    def text_activity(self, ws_path: str, activity: ET.Element) -> None:
        head = frontmatter.dump(self.metadata(activity.find(cp("activityM"))))
        body = "\n\n".join(self.blocks(activity, level=2))
        self.write(self.md_path(ws_path), head + "\n" + body + "\n")

    def collection(self, ws_path: str, activity: ET.Element) -> None:
        title = activity.findtext(f"{cp('activityM')}/{sp('title')}", "").strip()
        lines = [f"# {title or Path(ws_path).stem}", ""]
        for entry in activity:
            ref_elem = entry if entry.get(REF_URI) else entry.find(f".//{sp('ref')}")
            ref = ref_elem.get(REF_URI, "") if ref_elem is not None else ""
            if not ref:
                continue
            target = self.reader.resolve(ws_path, ref)
            root = self.reader.xml(target)
            child_title, converted = "", False
            if root is not None and len(root):
                child_title = root.findtext(f".//{sp('title')}", "")
                converted = local(root[0].tag) in CONVERTED_KINDS
            label = escape_text(child_title.strip() or Path(target).stem)
            if converted:
                lines.append(f"- [{label}]({self.link_to(target.rsplit('.', 1)[0] + '.md')})")
            else:
                lines.append(f"- {label} *(non converti, voir Canoprof)*")
        self.write(self.md_path(ws_path), "\n".join(lines) + "\n")

    def run(self) -> None:
        for ws_path in self.reader.items(".activite"):
            self._item = ws_path
            root = self.reader.xml(ws_path)
            if root is None or not len(root):
                continue
            activity, kind = root[0], local(root[0].tag)
            if kind == "textActivity":
                self.text_activity(ws_path, activity)
            elif kind == "collectionActivity":
                self.collection(ws_path, activity)
            else:
                self.skipped.append(f"{ws_path}: {kind}")


def convert_archive(scar: Path, out_dir: Path, force: bool = False) -> ScarConverter:
    reader = ScarReader.open(scar)
    try:
        conv = ScarConverter(reader, out_dir, force=force)
        conv.run()
    finally:
        reader.close()
    return conv
