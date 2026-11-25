"""Markdown -> Canoprof conversion."""

from __future__ import annotations

from conftest import NS


def texts(root, path: str) -> list[str]:
    return ["".join(e.itertext()) for e in root.iterfind(path, NS)]


def test_front_matter_fills_activity_metadata(make_md, to_activity):
    source = make_md('---\ntitle: "TP : LED"\nabstract: Résumé\nduration: 2h\n'
                     'organisation: En binôme\nmaterials: "Arduino | LED"\n---\n\nTexte\n')
    root, _, _ = to_activity(source)
    meta = root.find(".//cp:activityM", NS)
    assert meta.findtext("sp:title", namespaces=NS) == "TP : LED"
    assert texts(meta, "sp:abstract//sc:para") == ["Résumé"]
    org = meta.find("sp:organisationData", NS)
    assert [c.tag.split("}")[1] for c in org] == ["duration", "materials", "organisation"]
    assert texts(org, "sp:materials//sc:para") == ["Arduino", "LED"]


def test_title_falls_back_to_h1_then_file_name(make_md, to_activity):
    root, _, _ = to_activity(make_md("# Mon titre\n\nTexte\n"))
    assert root.findtext(".//cp:activityM/sp:title", namespaces=NS) == "Mon titre"
    root, _, _ = to_activity(make_md("Texte\n", name="seance_3.md"))
    assert root.findtext(".//cp:activityM/sp:title", namespaces=NS) == "seance_3"


def test_headings_and_admonitions_become_blocks(make_md, to_activity):
    source = make_md(
        "## Cours\n\nTexte\n\n"
        '!!! definition "Loi d\'Ohm"\n    U = RI\n\n'
        "!!! attention\n    Danger\n\n"
        "!!! rappel\n    Boucle\n"
    )
    root, _, _ = to_activity(source)
    blocks = root.find(".//cp:blocks", NS)
    assert [b.tag.split("}")[1] for b in blocks] == ["info", "definition", "warning", "reminder"]
    assert texts(blocks, "*/cp:block/cp:blockM/sp:title") == ["Cours", "Loi d'Ohm"]


def test_consigne_and_answer_zone_stay_in_the_flow(make_md, to_activity):
    source = make_md("## TP\n\nIntro\n\n!!! consigne\n    Mesurer U\n\n<!-- zone: 5 -->\n")
    root, _, _ = to_activity(source)
    flow = root.find(".//cp:flow", NS)
    assert [c.tag.split("}")[1] for c in flow] == ["txt", "studentInstruction", "studentArea"]
    assert flow.findtext(".//sp:lines", namespaces=NS) == "5"


def test_inline_styles_math_and_links(make_md, to_activity):
    source = make_md("Un **mot**, `digitalWrite()`, $U=RI$ et [site](https://example.org).\n")
    root, _, _ = to_activity(source)
    para = root.find(".//sc:para", NS)
    roles = [(e.tag.split("}")[1], e.get("role")) for e in para]
    assert roles == [("inlineStyle", "emphasis"), ("inlineStyle", "specific"),
                     ("textLeaf", "mathtex"), ("phrase", "url")]
    assert para.findtext(".//sp:url", namespaces=NS) == "https://example.org"


def test_images_with_spaces_and_accents_are_embedded(make_md, to_activity):
    source = make_md("Schéma :\n\n![](%C3%A9tape%201/sch%C3%A9ma%20RC.svg)\n",
                     files={"étape 1/schéma RC.svg": b"<svg/>"})
    root, members, conv = to_activity(source)
    assert conv.warnings == []
    assert "schéma RC.svg/schéma RC.svg" in members
    ext = root.find(".//sc:extBlock", NS)
    assert ext.get(f"{{{NS['sc']}}}refUri") == "schéma RC.svg"


def test_resource_name_clash_is_renamed(make_md, to_activity):
    source = make_md("![](a/img.png)\n\n![](b/img.png)\n",
                     files={"a/img.png": b"one", "b/img.png": b"two"})
    _, members, _ = to_activity(source)
    assert {"img.png/img.png", "img_2.png/img_2.png"} <= set(members)


def test_code_fence_becomes_code_item(make_md, to_activity):
    source = make_md("```cpp\nint main()\n{\n    return 0;\n}\n```\n\n```rust\nfn main() {}\n```\n")
    _, members, conv = to_activity(source)
    assert "lesson_code01.code" in members and "lesson_code02.code" in members
    assert any("unknown code language 'rust'" in w for w in conv.warnings)


def test_table_columns_and_missing_cells(make_md, to_activity):
    source = make_md("| A | B | C |\n|---|---|---|\n| 1 | 2 |   |\n")
    root, _, _ = to_activity(source)
    table = root.find(".//sc:table", NS)
    assert len(table.findall("sc:column", NS)) == 3
    assert all(len(r.findall("sc:cell", NS)) == 3 for r in table.findall("sc:row", NS))


def test_missing_file_is_reported(make_md, to_activity):
    _, _, conv = to_activity(make_md("[sujet](absent.pdf)\n"))
    assert conv.warnings == ["missing file: absent.pdf"]
