# md2canoprof

Convertit un fichier **Markdown** (syntaxe MkDocs Material) en archive
**Canoprof** (`.scar`) importable en une seule opération.

Une même source `.md` sert donc à la fois :

- au site web, publié avec **MkDocs** ;
- à **Canoprof**, par un simple import.

```
seance.md ──► md2canoprof.py ──► seance.scar ──► Canoprof (Importer)
    │
    └──────► mkdocs build ──► site web
```

## Installation (Fedora / Debian / Ubuntu)

```bash
python3 -m venv ~/.venv/md2canoprof
source ~/.venv/md2canoprof/bin/activate
pip install -r requirements.txt
```

## Utilisation

```bash
python3 md2canoprof.py examples/tp_led.md            # -> examples/tp_led.scar
python3 md2canoprof.py examples/tp_led.md -o tp.scar
```

Dans Canoprof, importe le `.scar` dans le dossier de ton choix. Un
sous-dossier portant le nom de l'archive est créé ; il contient l'activité et
toutes ses ressources (code, images, fichiers joints).

Les images, vidéos et fichiers liés sont lus dans le dossier du `.md` et
embarqués dans l'archive.

## Syntaxe

En-tête facultatif :

```markdown
---
title: TP 4 - Commande d'une LED
abstract: Dimensionner la résistance de protection d'une LED.
duration: 2h
organisation: En binôme
---
```

| Markdown                                  | Canoprof                     |
|-------------------------------------------|------------------------------|
| `## Titre`                                | bloc Information             |
| `!!! definition "Titre"`                  | bloc Définition              |
| `!!! example` / `!!! exemple`             | bloc Exemple                 |
| `!!! warning` / `!!! attention`           | bloc Attention               |
| `!!! reminder` / `!!! rappel`             | bloc Rappel                  |
| `!!! extra` / `!!! complement`            | bloc Complément              |
| `!!! consigne`                            | consigne élève               |
| `<!-- zone: 4 -->`                        | zone de réponse (4 lignes)   |
| `**gras**`, `*italique*`                  | emphase                      |
| `` `code` ``                              | style spécifique             |
| `$x^2$`, `$$ ... $$`                      | formule LaTeX (mathtex)      |
| `![alt](schema.png)`, `video.mp4`         | illustration                 |
| bloc ```` ```cpp ````                     | item `.code` séparé          |
| `[texte](https://...)`                    | lien web                     |
| `[texte](fichier.ino)`                    | fichier téléchargeable       |
| listes, tableaux                          | listes, tableaux             |

Côté MkDocs, activer au minimum :

```yaml
markdown_extensions:
  - admonition
  - pymdownx.superfences
  - pymdownx.arithmatex:
      generic: true
```

## Sens inverse : `scar2md.py` (Canoprof → Markdown)

Pour migrer un existant : un export Canoprof devient une arborescence de
fichiers `.md`, prête pour MkDocs et réimportable avec `md2canoprof.py`.

```bash
python3 scar2md.py periode1.scar -o docs/          # --force pour écraser
mkdocs serve
```

- Chaque activité texte devient un `.md` rangé à son chemin d'atelier ; images,
  SVG, vidéos et fichiers joints sont copiés à côté ; le code des items `.code`
  est intégré en blocs ```` ```cpp ````.
- Les collections (périodes, séquences) deviennent des pages d'index.
- Exercices à question ouverte : `## Titre` + `??? solution` (repliable).
- Non convertis (signalés) : quiz/QCM, activités HTML. La disposition
  côte à côte est remise à la suite.

MkDocs doit alors activer aussi `pymdownx.details` (solutions repliables).

## Figures KiCad et Fritzing

`tools/export_figures.sh` produit des SVG propres (recadrés, textes en
chemins, SVG simple) pour MkDocs et Canoprof :

```bash
sudo dnf install kicad inkscape
tools/export_figures.sh sources/ docs/img/
```

- Fichiers `.kicad_sch` : exportés via `kicad-cli` (sans cartouche, fond transparent).
- Fichiers `.kicad_pcb` : surface de la carte seule, couches
  `F.Cu,F.Silkscreen,Edge.Cuts` (modifiable : `PCB_LAYERS=B.Cu,Edge.Cuts`).
- Fritzing : exporter à la main (*Fichier > Exporter > comme image > SVG*)
  dans `sources/`, le script se charge du nettoyage.

Les options de `kicad-cli` varient selon la version de KiCad :
vérifier avec `kicad-cli pcb export svg -h`.

## Vérification de structure

`tools/check_structure.py` vérifie que chaque imbrication XML générée existe
dans un atelier Canoprof de référence (un export `.scar` décompressé) :

```bash
mkdir /tmp/ref && unzip -q mon_export.scar -d /tmp/ref
python3 tools/check_structure.py "/tmp/ref/&" examples/tp_led.scar
```

## Limites actuelles

- QCM et quiz, mise en page côte à côte (`visavis`), solutions : non gérés.
- Les blocs typés imbriqués sont aplatis dans le bloc courant.
- Testé avec Canoprof Expert 3.
