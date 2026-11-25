# md2canoprof

Convertit des fichiers **Markdown** (syntaxe MkDocs Material) en archives
**Canoprof** (`.scar`) importables en une seule opération, et inversement.

Une même source `.md` sert donc à la fois :

- au site web, publié avec **MkDocs** ;
- à **Canoprof**, par un simple import.

```
seance.md ──► md2canoprof ──► seance.scar ──► Canoprof (Importer)
    │
    └──────► mkdocs build ──► site web
```

## Installation (Fedora / Debian / Ubuntu)

```bash
git clone https://github.com/PFrogerais/md2canoprof.git && cd md2canoprof
python3 -m venv ~/.venv/md2canoprof
source ~/.venv/md2canoprof/bin/activate
pip install -e .     # installe md2canoprof, scar2md, canoprof-check, export_figures.sh
```

Avec `-e`, un `git pull` suffit ensuite pour mettre à jour les commandes.

## Utilisation

```bash
md2canoprof examples/tp_led.md                 # -> examples/tp_led.scar
md2canoprof examples/tp_led.md -o tp.scar
md2canoprof docs/terminale/*.md -o build/      # plusieurs fichiers -> un dossier
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

## Sens inverse : `scar2md` (Canoprof → Markdown)

Pour migrer un existant : un export Canoprof devient une arborescence de
fichiers `.md`, prête pour MkDocs et réimportable avec `md2canoprof`.

```bash
scar2md periode1.scar -o docs/          # --force pour écraser
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
export_figures.sh sources/ docs/img/
```

- Fichiers `.kicad_sch` : exportés via `kicad-cli` (sans cartouche, fond transparent).
- Fichiers `.kicad_pcb` : surface de la carte seule, couches
  `F.Cu,F.Silkscreen,Edge.Cuts` (modifiable : `PCB_LAYERS=B.Cu,Edge.Cuts`).
- Fritzing : exporter à la main (*Fichier > Exporter > comme image > SVG*)
  dans `sources/`, le script se charge du nettoyage.

Les options de `kicad-cli` varient selon la version de KiCad :
vérifier avec `kicad-cli pcb export svg -h`.

## Vérification de structure

`canoprof-check` vérifie que chaque imbrication XML d'un `.scar` généré existe
dans un vrai atelier Canoprof. La référence (noms de balises uniquement, aucun
contenu) est embarquée dans `md2canoprof/data/known_nestings.txt`.

```bash
canoprof-check build/*.scar
canoprof-check --learn md2canoprof/data/known_nestings.txt mon_export.scar  # enrichir
```

## Organisation du code

```
md2canoprof/
├── schema.py            # SOURCE UNIQUE : espaces de noms, blocs <-> admonitions,
│                        #   langages <-> types MIME, rôles
├── frontmatter.py       # en-tête --- title: ... --- (lecture et écriture)
├── archive.py           # lecture / écriture des .scar
├── markdown_to_scar.py  # Markdown -> Canoprof
├── scar_to_markdown.py  # Canoprof -> Markdown
├── structure.py         # vérification des imbrications
├── cli.py               # commandes md2canoprof, scar2md, canoprof-check
└── data/known_nestings.txt
tests/                   # pytest : unitaires + aller-retour
tools/export_figures.sh  # figures KiCad / Fritzing
```

**Ajouter un type de bloc ou un langage** : une ligne dans `schema.py`
(`BLOCK_ALIASES` ou `CODE_LANGUAGES`) ; les deux sens de conversion en
profitent.

## Développement

```bash
pip install -e ".[dev]"
ruff check .        # style et erreurs
pytest              # 20 tests, < 1 s
```

La CI GitHub Actions relance `ruff`, `pytest` et la conversion de l'exemple à
chaque `git push`.

## Limites actuelles

- QCM et quiz : non gérés. Côte à côte (`visavis`) : remis à la suite.
- Les blocs typés imbriqués sont aplatis dans le bloc courant.
- Testé avec Canoprof Expert 3.
