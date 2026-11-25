"""
Reading and writing Canoprof archives (.scar).

A .scar is a zip file. In a Canoprof export, the root item sits at the top of
the archive and every dependency lives under '&/' followed by its workspace
path; references made from the root use the same '&/...' form. Binary
resources are stored as a folder named after the file ('x.png/x.png').
"""

from __future__ import annotations

import posixpath
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .schema import WSP_META

EXPORT_ROOT = "&"


def serialize(item: ET.Element) -> bytes:
    """Serialize a Scenari item with the XML declaration Canoprof uses."""
    return ('<?xml version="1.0"?>\n' + ET.tostring(item, encoding="unicode")).encode("utf-8")


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
@dataclass
class Resource:
    """A file embedded next to the activity."""
    name: str
    data: bytes
    binary: bool    # True for images/videos/attachments (stored as name/name)

    @property
    def member(self) -> str:
        return f"{self.name}/{self.name}" if self.binary else self.name


def write_scar(output: Path, activity_name: str, activity: bytes,
               resources: list[Resource]) -> None:
    """Write a flat .scar: the activity and its resources side by side.

    Canoprof imports it into the chosen folder as a sub-folder named after
    the archive, so relative references always resolve.
    """
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(".wspmeta", WSP_META)
        archive.writestr(activity_name, activity)
        for res in resources:
            archive.writestr(res.member, res.data)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
@dataclass
class ScarReader:
    """Workspace view of a .scar: workspace path -> archive member."""
    zip_file: zipfile.ZipFile
    files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def open(cls, path: Path) -> ScarReader:
        reader = cls(zipfile.ZipFile(path))
        root_uri = reader._root_uri()
        for member in reader.zip_file.namelist():
            if member.endswith("/") or member.startswith("."):
                continue
            if member.startswith(EXPORT_ROOT + "/"):
                ws_path = member[len(EXPORT_ROOT):]
            elif "/" not in member and root_uri and member == PurePosixPath(root_uri).name:
                ws_path = root_uri
            else:
                ws_path = "/" + member
            reader.files[ws_path] = member
        return reader

    def close(self) -> None:
        self.zip_file.close()

    def _root_uri(self) -> str | None:
        if ".wsporigin" not in self.zip_file.namelist():
            return None
        root = ET.fromstring(self.zip_file.read(".wsporigin")).find("root")
        return root.get("srcUri") if root is not None else None

    @staticmethod
    def resolve(item_path: str, ref: str) -> str:
        """Workspace path of a reference made from the item at item_path."""
        if ref.startswith(EXPORT_ROOT + "/"):
            ref = ref[len(EXPORT_ROOT):]
        if ref.startswith("/"):
            return posixpath.normpath(ref)
        return posixpath.normpath(posixpath.join(posixpath.dirname(item_path), ref))

    def binary(self, ws_path: str) -> bytes | None:
        member = self.files.get(f"{ws_path}/{posixpath.basename(ws_path)}") \
            or self.files.get(ws_path)
        return self.zip_file.read(member) if member else None

    def xml(self, ws_path: str) -> ET.Element | None:
        member = self.files.get(ws_path)
        return ET.fromstring(self.zip_file.read(member)) if member else None

    def items(self, suffix: str = ".activite") -> list[str]:
        return sorted(p for p in self.files if p.endswith(suffix))
