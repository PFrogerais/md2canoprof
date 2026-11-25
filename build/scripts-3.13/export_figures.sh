#!/usr/bin/env bash
# Export KiCad and Fritzing figures to clean SVG for MkDocs and Canoprof.
#
# Usage: tools/export_figures.sh [SRC_DIR] [OUT_DIR]
#   SRC_DIR  folder holding .kicad_sch / .kicad_pcb files and SVG files
#            exported by hand from Fritzing (default: sources)
#   OUT_DIR  folder receiving the cleaned SVG files (default: img)
#
# Requires: kicad-cli (KiCad >= 7) for KiCad files, inkscape (>= 1.0).
set -euo pipefail

readonly SRC_DIR="${1:-sources}"
readonly OUT_DIR="${2:-img}"
readonly PCB_LAYERS="${PCB_LAYERS:-F.Cu,F.Silkscreen,Edge.Cuts}"

TMP_DIR="$(mktemp -d)"
readonly TMP_DIR
trap 'rm -rf "${TMP_DIR}"' EXIT

require()
{
    if ! command -v "$1" > /dev/null 2>&1; then
        echo "error: '$1' not found (sudo dnf install $2)" >&2
        exit 1
    fi
}

[[ -d "${SRC_DIR}" ]] || { echo "error: ${SRC_DIR} is not a folder" >&2; exit 1; }
require inkscape inkscape
mkdir -p "${OUT_DIR}"
shopt -s nullglob

# KiCad schematics (one SVG per sheet)
for sch in "${SRC_DIR}"/*.kicad_sch; do
    require kicad-cli kicad
    kicad-cli sch export svg -e -n -o "${TMP_DIR}/" "${sch}"
done

# KiCad boards (board area only, no title block)
for pcb in "${SRC_DIR}"/*.kicad_pcb; do
    require kicad-cli kicad
    kicad-cli pcb export svg --page-size-mode 2 --exclude-drawing-sheet \
        --layers "${PCB_LAYERS}" \
        -o "${TMP_DIR}/$(basename "${pcb%.kicad_pcb}")_pcb.svg" "${pcb}"
done

# Fritzing exports already saved as SVG in SRC_DIR
for svg in "${SRC_DIR}"/*.svg; do
    cp "${svg}" "${TMP_DIR}/"
done

# Clean every SVG: crop to drawing, text to paths, plain SVG
count=0
for svg in "${TMP_DIR}"/*.svg; do
    out="${OUT_DIR}/$(basename "${svg}")"
    inkscape --export-area-drawing --export-text-to-path --export-plain-svg \
        -o "${out}" "${svg}"
    echo "OK  ${out}"
    count=$((count + 1))
done

echo "${count} figure(s) exported to ${OUT_DIR}"
