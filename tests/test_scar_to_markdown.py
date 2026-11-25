"""Canoprof export -> Markdown conversion."""

from __future__ import annotations

import zipfile
from pathlib import Path

from md2canoprof.archive import serialize
from md2canoprof.scar_to_markdown import convert_archive, escape_text
from md2canoprof.schema import WSP_META

HEADER = ('<?xml version="1.0"?>\n<sc:item xmlns:sc="http://www.utc.fr/ics/scenari/v3/core" '
          'xmlns:sp="http://www.utc.fr/ics/scenari/v3/primitive" xmlns:cp="canope.fr:canoprof">')


def make_export(path: Path) -> Path:
    """A miniature Canoprof export, laid out like the real thing ('&/', .wsporigin)."""
    collection = (HEADER + "<cp:collectionActivity><cp:activityM><sp:title>Période 1</sp:title>"
                  "</cp:activityM><sp:child><cp:childRef><cp:navTitle/>"
                  '<sp:ref sc:refUri="&amp;/Cours/tp1/tp1.activite"/></cp:childRef></sp:child>'
                  '<sp:folder sc:refUri="&amp;/Cours/quiz.activite"/>'
                  "</cp:collectionActivity></sc:item>")
    activity = (HEADER + "<cp:textActivity><cp:activityM><sp:title>TP 1</sp:title>"
                "<sp:organisationData><sp:duration>2h</sp:duration></sp:organisationData>"
                "</cp:activityM><sp:body><cp:blocks>"
                "<sp:info><cp:block><cp:blockM><sp:title>Montage</sp:title></cp:blockM>"
                "<sp:body><cp:flow><sp:txt><cp:txt>"
                '<sc:para xml:space="preserve">Un <sc:inlineStyle role="emphasis">transistor'
                ' </sc:inlineStyle>et <sc:textLeaf role="mathtex">I_B</sc:textLeaf>.</sc:para>'
                '<sc:extBlock role="illustration" sc:refUri="schema.svg"/>'
                '<sc:extBlock role="illustration" sc:refUri="code0.code"/>'
                "</cp:txt></sp:txt>"
                '<sp:studentInstruction><cp:txt><sc:para xml:space="preserve">Calculer R'
                "</sc:para></cp:txt></sp:studentInstruction>"
                "<sp:studentArea><cp:studentArea><sp:lines>4</sp:lines></cp:studentArea>"
                "</sp:studentArea></cp:flow></sp:body></cp:block></sp:info>"
                "<sp:warning><cp:block><cp:blockM/><sp:body><cp:flow><sp:txt><cp:txt>"
                '<sc:para xml:space="preserve">Attention</sc:para></cp:txt></sp:txt>'
                "</cp:flow></sp:body></cp:block></sp:warning>"
                "</cp:blocks></sp:body></cp:textActivity></sc:item>")
    code = (HEADER + '<cp:code><sc:code mimeType="text/x-c++src" xml:space="preserve">'
            "int main()\n{\n}\n</sc:code></cp:code></sc:item>")
    quiz = HEADER + "<cp:quizActivity/></sc:item>"
    origin = ('<?xml version="1.0" encoding="UTF-8"?><wspOrigin scChainUrl="/." wspCode="t" '
              'timestamp="0"><root srcUri="/Classes/periode1.activite"/></wspOrigin>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(".wspmeta", WSP_META)
        z.writestr(".wsporigin", origin)
        z.writestr("periode1.activite", collection)
        z.writestr("&/Cours/tp1/tp1.activite", activity)
        z.writestr("&/Cours/tp1/schema.svg/schema.svg", "<svg/>")
        z.writestr("&/Cours/tp1/code0.code", code)
        z.writestr("&/Cours/quiz.activite", quiz)
    return path


def test_export_becomes_markdown_tree(tmp_path: Path):
    conv = convert_archive(make_export(tmp_path / "p1.scar"), tmp_path / "docs")
    assert conv.warnings == []
    assert conv.skipped == ["/Cours/quiz.activite: quizActivity"]
    docs = tmp_path / "docs"
    assert (docs / "Cours/tp1/schema.svg").read_bytes() == b"<svg/>"

    tp1 = (docs / "Cours/tp1/tp1.md").read_text(encoding="utf-8")
    assert tp1.startswith('---\ntitle: "TP 1"\nduration: "2h"\n---\n')
    assert "## Montage" in tp1
    assert "Un **transistor** et $I_B$." in tp1           # space moved out of the bold
    assert "![schema](schema.svg)" in tp1
    assert "```cpp\nint main()\n{\n}\n```" in tp1
    assert "!!! consigne\n    Calculer R" in tp1
    assert "<!-- zone: 4 -->" in tp1
    assert "!!! warning\n    Attention" in tp1

    index = (docs / "Classes/periode1.md").read_text(encoding="utf-8")
    assert "- [TP 1](../Cours/tp1/tp1.md)" in index
    assert "*(non converti, voir Canoprof)*" in index


def test_existing_files_are_kept_without_force(tmp_path: Path):
    export = make_export(tmp_path / "p1.scar")
    convert_archive(export, tmp_path / "docs")
    again = convert_archive(export, tmp_path / "docs")
    assert again.written == [] and len(again.warnings) == 2
    forced = convert_archive(export, tmp_path / "docs", force=True)
    assert len(forced.written) == 2


def test_markdown_syntax_in_text_is_escaped():
    assert escape_text("a*b [x] `y` <V> 5$") == r"a\*b \[x\] \`y\` &lt;V> 5\$"


def test_serialize_keeps_canoprof_declaration():
    import xml.etree.ElementTree as ET

    assert serialize(ET.Element("x")).startswith(b'<?xml version="1.0"?>\n')
