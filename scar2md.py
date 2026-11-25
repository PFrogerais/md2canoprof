#!/usr/bin/env python3
"""
scar2md.py - Convert a Canoprof (Scenari) export (.scar) into a tree of
MkDocs-flavoured Markdown files, the reverse of md2canoprof.py.

Every text activity (.activite) becomes a .md file placed at its workspace
path; images, SVG, videos and attached files are copied next to it, and code
items (.code) are inlined as fenced code blocks. Collections become index
pages listing their children.

Usage
-----
    python3 scar2md.py periode1.scar -o docs/
    python3 scar2md.py periode1.scar -o docs/ --force     # overwrite files

Not converted (reported at the end): quiz items, HTML activities, lists of
skills / notions. A comment is left in the Markdown where they appear.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

NS_SC = "http://www.utc.fr/ics/scenari/v3/core"
NS_SP = "http://www.utc.fr/ics/scenari/v3/primitive"
NS_CP = "canope.fr:canoprof"
REF_URI = f"{{{NS_SC}}}refUri"

# Canoprof block element -> admonition tag (md2canoprof understands them all).
BLOCK_ADMONITION = {
    "info": "info",
    "definition": "definition",
    "example": "example",
    "warning": "warning",
    "reminder": "reminder",
    "extra": "extra",
}

MIME_LANG = {
    "text/x-c++src": "cpp",
    "text/x-csrc": "c",
    "text/x-python": "python",
    "text/x-sh": "bash",
}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".webm"}

# Characters that would be read as Markdown syntax inside plain text.
MD_SPECIAL = re.compile(r"([\\`*\[\]])")
LINE_START_SPECIAL = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])(\s)")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def escape_text(text: str) -> str:
    text = MD_SPECIAL.sub(r"\\\1", text)
    return text.replace("<", "&lt;").replace("$", r"\$")


def yaml_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line.strip() else "" for line in text.split("\n"))


@dataclass
class Archive:
    """Workspace view of a .scar: workspace path -> archive member."""
    zip_file: zipfile.ZipFile
    files: dict[str, str] = field(default_factory=dict)   # '/a/b.activite' -> member

    @classmethod
    def open(cls, path: Path) -> "Archive":
        archive = cls(zipfile.ZipFile(path))
        root_uri = None
        if ".wsporigin" in archive.zip_file.namelist():
            origin = ET.fromstring(archive.zip_file.read(".wsporigin"))
            root = origin.find("root")
            if root is not None:
                root_uri = root.get("srcUri")
        for member in archive.zip_file.namelist():
            if member.endswith("/") or member.startswith("."):
                continue
            if member.startswith("&/"):
                ws_path = "/" + member[2:]
            elif "/" not in member and root_uri and member.endswith(Path(root_uri).name):
                ws_path = root_uri
            else:
                ws_path = "/" + member
            archive.files[ws_path] = member
        return archive

    def resolve(self, item_path: str, ref: str) -> str:
        """Workspace path of a reference made from item_path."""
        if ref.startswith("&/"):       # export-relative form used by Canoprof
            ref = ref[1:]
        if ref.startswith("/"):
            return posixpath.normpath(ref)
        return posixpath.normpath(posixpath.join(posixpath.dirname(item_path), ref))

    def binary_member(self, ws_path: str) -> str | None:
        """Scenari stores a binary 'x.png' as folder 'x.png/x.png'."""
        inner = f"{ws_path}/{posixpath.basename(ws_path)}"
        if inner in self.files:
            return self.files[inner]
        return self.files.get(ws_path)

    def read_xml(self, ws_path: str) -> ET.Element | None:
        member = self.files.get(ws_path)
        if member is None:
            return None
        return ET.fromstring(self.zip_file.read(member))


@dataclass
class Converter:
    archive: Archive
    out_dir: Path
    force: bool = False
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    _copied: set[str] = field(default_factory=set)
    _item: str = ""   # workspace path of the item being converted

    # ------------------------------------------------------------ outputs
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
        """Relative, URL-encoded link from the current .md to a workspace file."""
        here = posixpath.dirname(self._item)
        rel = posixpath.relpath(ws_target, here)
        return quote(rel)

    def copy_resource(self, ref: str) -> str | None:
        ws_path = self.archive.resolve(self._item, ref)
        member = self.archive.binary_member(ws_path)
        if member is None:
            self.warnings.append(f"{self._item}: missing resource {ref}")
            return None
        if ws_path not in self._copied:
            target = self.out_dir / ws_path.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.archive.zip_file.read(member))
            self._copied.add(ws_path)
        return self.link_to(ws_path)

    # ------------------------------------------------------------- inline
    def inline(self, elem: ET.Element) -> str:
        parts = [escape_text(elem.text or "")]
        for child in elem:
            parts.append(self.inline_child(child))
            parts.append(escape_text(child.tail or ""))
        return "".join(parts)

    @staticmethod
    def wrap(marker: str, content: str) -> str:
        """Wrap content in an inline marker, keeping spaces outside it."""
        stripped = content.strip()
        if not stripped:
            return content
        lead = content[: len(content) - len(content.lstrip())]
        trail = content[len(content.rstrip()):]
        return f"{lead}{marker}{stripped}{marker}{trail}"

    def inline_child(self, child: ET.Element) -> str:
        tag, role = local(child.tag), child.get("role", "")
        if tag == "inlineStyle" and role == "specific":
            code = "".join(child.itertext())
            return self.wrap("`", code) if "`" not in code else code
        if tag == "inlineStyle":
            return self.wrap("**", self.inline(child))
        if tag == "textLeaf" and role == "mathtex":
            return f"${(child.text or '').strip()}$"
        if tag == "textLeaf":                       # cloze gap, etc.
            return f"[{escape_text(child.text or '')}]"
        if tag == "phrase" and role == "url":
            link = child.find(f"{{{NS_CP}}}link")
            url = link.findtext(f"{{{NS_SP}}}url", "") if link is not None else ""
            label_elem = ET.Element("label")
            label_elem.text = child.text
            for sub_child in child:
                if sub_child is not link:
                    label_elem.append(sub_child)
            label = self.inline(label_elem).strip() or url
            return f"[{label}]({url})" if url else label
        if tag == "uLink":
            label = self.inline(child).strip()
            target = self.copy_resource(child.get(REF_URI, ""))
            return f"[{label}]({target})" if target else label
        if tag == "inlineImg":
            target = self.copy_resource(child.get(REF_URI, ""))
            return f"![]({target})" if target else ""
        self.warnings.append(f"{self._item}: unsupported inline <{tag}>")
        return self.inline(child)

    # --------------------------------------------------------- block text
    def para(self, elem: ET.Element) -> str:
        children = list(elem)
        if (len(children) == 1 and local(children[0].tag) == "textLeaf"
                and children[0].get("role") == "mathtex"
                and not (elem.text or "").strip() and not (children[0].tail or "").strip()):
            return f"$$\n{(children[0].text or '').strip()}\n$$"
        text = self.inline(elem)
        text = re.sub(r"[ \t]*\n[ \t]*", " ", text).strip()
        return LINE_START_SPECIAL.sub(r"\1\\\2\3", text)

    def txt(self, container: ET.Element) -> str:
        """Render a cp:txt / cp:txtDesc / sc:listItem / sc:cell content."""
        blocks: list[str] = []
        prev_tag = ""
        for child in container:
            tag = local(child.tag)
            if tag == "para":
                text = self.para(child)
                if text:
                    blocks.append(text)
            elif tag in ("itemizedList", "orderedList"):
                if prev_tag == tag:
                    blocks.append("<!-- -->")  # keeps two adjacent lists apart
                blocks.append(self.list_block(child, ordered=(tag == "orderedList")))
            elif tag == "table":
                blocks.append(self.table(child))
            elif tag == "extBlock":
                rendered = self.ext_block(child)
                if rendered:
                    blocks.append(rendered)
            else:
                self.warnings.append(f"{self._item}: unsupported block <{tag}>")
            prev_tag = tag
        return "\n\n".join(blocks)

    def list_block(self, elem: ET.Element, ordered: bool) -> str:
        lines = []
        for number, item in enumerate(elem, start=1):
            marker = f"{number}." if ordered else "-"
            body = self.txt(item)
            pad = " " * (len(marker) + 1)
            first, _, rest = body.partition("\n")
            entry = f"{marker} {first}"
            if rest:
                entry += "\n" + indent(rest, pad)
            lines.append(entry)
        loose = any("\n\n" in line for line in lines)
        return ("\n\n" if loose else "\n").join(lines)

    def table(self, elem: ET.Element) -> str:
        rows = []
        for row in elem.findall(f"{{{NS_SC}}}row"):
            cells = [self.txt(cell).replace("\n\n", "<br>").replace("\n", " ")
                     .replace("|", r"\|") for cell in row.findall(f"{{{NS_SC}}}cell")]
            rows.append(cells)
        if not rows:
            return ""
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        out = ["| " + " | ".join(c or " " for c in rows[0]) + " |",
               "|" + "|".join(["---"] * ncols) + "|"]
        out += ["| " + " | ".join(c or " " for c in r) + " |" for r in rows[1:]]
        return "\n".join(out)

    def ext_block(self, elem: ET.Element) -> str:
        ref = elem.get(REF_URI, "")
        ws_path = self.archive.resolve(self._item, ref)
        if ws_path.endswith(".code"):
            root = self.archive.read_xml(ws_path)
            if root is None:
                self.warnings.append(f"{self._item}: missing code item {ref}")
                return ""
            code_elem = root.find(f".//{{{NS_SC}}}code")
            code = (code_elem.text or "") if code_elem is not None else ""
            lang = MIME_LANG.get(code_elem.get("mimeType", "") if code_elem is not None else "",
                                 "")
            fence = "````" if "```" in code else "```"
            return f"{fence}{lang}\n{code.rstrip()}\n{fence}"
        target = self.copy_resource(ref)
        if target is None:
            return ""
        name = posixpath.basename(ws_path)
        if Path(name).suffix.lower() in IMAGE_EXT:
            return f"![{escape_text(Path(name).stem)}]({target})"
        return f"[{escape_text(name)}]({target})"

    # ---------------------------------------------------------------- flow
    def flow(self, flow: ET.Element | None) -> str:
        if flow is None:
            return ""
        parts: list[str] = []
        for child in flow:
            tag = local(child.tag)
            if tag == "txt":
                text = self.txt(child[0]) if len(child) else ""
                if text:
                    parts.append(text)
            elif tag == "studentInstruction":
                text = self.txt(child[0]) if len(child) else ""
                parts.append("!!! consigne\n" + indent(text or "…"))
            elif tag == "studentArea":
                lines = child.findtext(f".//{{{NS_SP}}}lines", "3")
                parts.append(f"<!-- zone: {lines} -->")
            elif tag == "visavis":
                # Side-by-side layout: rendered one after the other.
                for side in ("first", "next"):
                    side_elem = child.find(f".//{{{NS_SP}}}{side}")
                    if side_elem is not None and len(side_elem):
                        text = self.flow(side_elem[0])
                        if text:
                            parts.append(text)
            else:
                self.warnings.append(f"{self._item}: unsupported flow <{tag}>")
        return "\n\n".join(parts)

    # -------------------------------------------------------------- blocks
    def block(self, wrapper: ET.Element, level: int) -> str:
        kind = local(wrapper.tag)
        if kind in ("exercice", "question") and wrapper.find(f"{{{NS_CP}}}openQuestion") is not None:
            return self.exercise(wrapper)
        if kind == "question" and wrapper.get(REF_URI):
            self.skipped.append(f"{self._item}: question {wrapper.get(REF_URI)}")
            return f"<!-- canoprof: question non convertie ({wrapper.get(REF_URI)}) -->"
        block = wrapper.find(f"{{{NS_CP}}}block")
        if block is None:
            self.warnings.append(f"{self._item}: unsupported block <{kind}>")
            return ""
        title = block.findtext(f"{{{NS_CP}}}blockM/{{{NS_SP}}}title")
        body = self.flow(block.find(f"{{{NS_SP}}}body/{{{NS_CP}}}flow"))
        if kind == "info" and title:
            return f"{'#' * level} {title.strip()}\n\n{body}".rstrip()
        tag = BLOCK_ADMONITION.get(kind, "info")
        head = f"!!! {tag}" + (f" {yaml_value(title.strip())}" if title else "")
        return f"{head}\n{indent(body or '…')}"

    def exercise(self, wrapper: ET.Element) -> str:
        question = wrapper.find(f"{{{NS_CP}}}openQuestion")
        if question is None:
            self.skipped.append(f"{self._item}: exercise without open question")
            return "<!-- canoprof: exercice non converti -->"
        title = question.findtext(f"{{{NS_CP}}}questionM/{{{NS_SP}}}title") or "Exercice"
        body = self.flow(question.find(f"{{{NS_SP}}}question/{{{NS_CP}}}flow"))
        out = f"## {title.strip()}\n\n{body}".rstrip()
        solution = question.find(f"{{{NS_SP}}}solution/{{{NS_CP}}}flow")
        if solution is not None:
            out += "\n\n??? solution \"Solution\"\n" + indent(self.flow(solution) or "…")
        return out

    def blocks(self, activity: ET.Element, level: int) -> list[str]:
        parts = []
        container = activity.find(f"{{{NS_SP}}}body/{{{NS_CP}}}blocks")
        if container is not None:
            for wrapper in container:
                text = self.block(wrapper, level)
                if text:
                    parts.append(text)
        for section in activity.findall(f"{{{NS_SP}}}section"):
            sub_activity = section.find(f"{{{NS_CP}}}textActivity")
            if sub_activity is None:
                continue
            title = sub_activity.findtext(f"{{{NS_CP}}}activityM/{{{NS_SP}}}title", "")
            parts.append(f"## {title.strip()}")
            parts.extend(self.blocks(sub_activity, level + 1))
        return parts

    # ---------------------------------------------------------- documents
    def front_matter(self, meta: ET.Element | None) -> str:
        fields: list[tuple[str, str]] = []
        if meta is not None:
            title = meta.findtext(f"{{{NS_SP}}}title")
            if title:
                fields.append(("title", title.strip()))
            abstract = meta.find(f"{{{NS_SP}}}abstract/{{{NS_CP}}}txtDesc")
            if abstract is not None:
                fields.append(("abstract", re.sub(r"\s+", " ", self.txt(abstract))))
            org = meta.find(f"{{{NS_SP}}}organisationData")
            if org is not None:
                duration = org.findtext(f"{{{NS_SP}}}duration")
                if duration:
                    fields.append(("duration", duration.strip()))
                organisation = org.find(f"{{{NS_SP}}}organisation/{{{NS_CP}}}txtDesc")
                if organisation is not None:
                    fields.append(("organisation",
                                   re.sub(r"\s+", " ", self.txt(organisation))))
                materials = org.find(f"{{{NS_SP}}}materials/{{{NS_CP}}}txtDesc")
                if materials is not None:
                    items = [self.para(p) for p in materials.findall(f"{{{NS_SC}}}para")]
                    fields.append(("materials", " | ".join(i for i in items if i)))
        lines = [f"{key}: {yaml_value(value)}" for key, value in fields]
        return "---\n" + "\n".join(lines) + "\n---\n" if lines else ""

    def text_activity(self, ws_path: str, activity: ET.Element) -> None:
        meta = activity.find(f"{{{NS_CP}}}activityM")
        body = "\n\n".join(self.blocks(activity, level=2))
        self.write(self.md_path(ws_path), self.front_matter(meta) + "\n" + body + "\n")

    def collection(self, ws_path: str, activity: ET.Element) -> None:
        title = activity.findtext(f"{{{NS_CP}}}activityM/{{{NS_SP}}}title", "").strip()
        lines = [f"# {title or Path(ws_path).stem}", ""]
        for entry in activity:
            ref = entry.get(REF_URI) or ""
            if not ref:
                ref_elem = entry.find(f".//{{{NS_SP}}}ref")
                ref = ref_elem.get(REF_URI, "") if ref_elem is not None else ""
            if not ref:
                continue
            target = self.archive.resolve(ws_path, ref)
            root = self.archive.read_xml(target)
            child_title, converted = "", False
            if root is not None and len(root):
                child_title = root.findtext(f".//{{{NS_SP}}}title", "")
                converted = local(root[0].tag) in ("textActivity", "collectionActivity")
            label = escape_text(child_title.strip() or Path(target).stem)
            if converted:
                md_target = target.rsplit(".", 1)[0] + ".md"
                lines.append(f"- [{label}]({self.link_to(md_target)})")
            else:
                lines.append(f"- {label} *(non converti, voir Canoprof)*")
        self.write(self.md_path(ws_path), "\n".join(lines) + "\n")

    def run(self) -> None:
        for ws_path in sorted(self.archive.files):
            if not ws_path.endswith(".activite"):
                continue
            self._item = ws_path
            root = self.archive.read_xml(ws_path)
            if root is None or not len(root):
                continue
            activity = root[0]
            kind = local(activity.tag)
            if kind == "textActivity":
                self.text_activity(ws_path, activity)
            elif kind == "collectionActivity":
                self.collection(ws_path, activity)
            else:
                self.skipped.append(f"{ws_path}: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scar", type=Path, help="Canoprof export (.scar)")
    parser.add_argument("-o", "--output", type=Path, default=Path("docs"),
                        help="output folder (default: docs)")
    parser.add_argument("--force", action="store_true", help="overwrite existing .md files")
    args = parser.parse_args()

    if not args.scar.is_file():
        print(f"error: {args.scar} not found", file=sys.stderr)
        return 1

    conv = Converter(Archive.open(args.scar), args.output, force=args.force)
    conv.run()

    for warning in conv.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for skipped in conv.skipped:
        print(f"skipped: {skipped}", file=sys.stderr)
    print(f"{len(conv.written)} Markdown file(s) written to {args.output}, "
          f"{len(conv._copied)} resource(s) copied, {len(conv.skipped)} item(s) skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
