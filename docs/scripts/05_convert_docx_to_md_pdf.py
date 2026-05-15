"""Conversione dei .docx della cartella docs/ in formato Markdown e PDF.

Per ciascuno dei 4 documenti tecnici di fitosim:
  - fitosim_calibration_manual.docx
  - fitosim_status_report.docx
  - fitosim_synthesis_report.docx (con immagini)
  - fitosim_user_manual.docx

produce un file `<basename>.md` e un file `<basename>.pdf` nella
stessa cartella docs/.

Strategia
---------

  - Markdown: estratto con `mammoth` (libreria Python pura). Conserva
    intestazioni h1/h2/h3, paragrafi, liste, tabelle. Le immagini
    incorporate nel docx vengono estratte come file separati nella
    sottocartella `docs/images/` e referenziate nel markdown via
    path relativo.
  - PDF: conversione diretta dal docx originale con `docx2pdf`, che
    su Windows usa Word via COM automation. Preserva la formattazione
    nativa del documento (font, stili, immagini, headers/footers).

Esecuzione
----------

    cd fitosim/
    .venv/Scripts/python.exe docs/scripts/05_convert_docx_to_md_pdf.py

Dipendenze (installate nel venv di fitosim):
    mammoth, docx2pdf, pywin32 (transitiva di docx2pdf, solo Windows).
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import mammoth
from docx2pdf import convert as docx_to_pdf


# Caratteri che mammoth esce in modo conservativo ma che NON hanno
# significato speciale in markdown standard quando appaiono in
# posizioni narrative (parole, fine frase). Li ripuliamo per
# leggibilità del .md sorgente. Lasciamo intatti gli escape che
# coprono caratteri ambigui in contesto markdown:
#   - \* \_ \# \[ \] \` \\ \< \> \| \~  (formatting)
# Questi NON vanno toccati: potrebbero essere intenzionali.
_HARMLESS_ESCAPES_RE = re.compile(r"\\([.\-(){}!?,;:/'\"])")


def _clean_md_escapes(text: str) -> str:
    """Rimuove i backslash davanti a punteggiatura non-speciale.

    mammoth esce per default tutti i caratteri che POTREBBERO essere
    interpretati come markdown, anche quando appaiono in contesto
    narrativo dove non lo sono mai (es. `FAO\\-56`, `versione\\.`).
    Questo rende il sorgente .md visivamente rumoroso. Ripuliamo
    solo gli escape su caratteri innocui — punto, virgola, parentesi,
    trattino, ecc. — preservando intatti quelli su caratteri che
    hanno significato markdown reale (`*`, `_`, `#`, `[`, `]`, etc.).
    """
    return _HARMLESS_ESCAPES_RE.sub(r"\1", text)


# Path della cartella docs (lo script vive in docs/scripts/, quindi
# parent risale a docs/).
DOCS_DIR = Path(__file__).resolve().parent.parent

DOCX_FILES = [
    "fitosim_calibration_manual.docx",
    "fitosim_status_report.docx",
    "fitosim_synthesis_report.docx",
    "fitosim_user_manual.docx",
]

# Sottocartella per le immagini estratte (vivere dentro docs/ per
# preservare il path relativo nel markdown).
IMAGES_DIR = DOCS_DIR / "images"


def _image_handler(image):
    """Callback mammoth: salva ciascuna immagine embedded come file
    separato e restituisce il riferimento src per il markdown.

    Il nome del file è derivato da un hash del contenuto (deduplica
    immagini identiche eventualmente ripetute nel documento).
    """
    IMAGES_DIR.mkdir(exist_ok=True)
    with image.open() as image_bytes:
        data = image_bytes.read()
    digest = hashlib.md5(data).hexdigest()[:12]
    content_type = image.content_type or "image/png"
    ext = content_type.split("/")[-1]
    if ext == "jpeg":
        ext = "jpg"
    filename = f"img_{digest}.{ext}"
    output_path = IMAGES_DIR / filename
    if not output_path.exists():
        output_path.write_bytes(data)
    return {"src": f"images/{filename}", "alt": image.alt_text or ""}


def convert_one(docx_name: str) -> None:
    """Converte un singolo .docx in .md e .pdf nella cartella docs/."""
    docx_path = DOCS_DIR / docx_name
    if not docx_path.exists():
        print(f"  ⚠️  saltato: {docx_name} non trovato")
        return

    stem = docx_path.stem
    md_path = DOCS_DIR / f"{stem}.md"
    pdf_path = DOCS_DIR / f"{stem}.pdf"

    print(f"\n=== {docx_name} ===")

    # 1) Markdown via mammoth.
    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_markdown(
            f,
            convert_image=mammoth.images.img_element(_image_handler),
        )
    cleaned = _clean_md_escapes(result.value)
    md_path.write_text(cleaned, encoding="utf-8")
    n_chars = len(cleaned)
    n_escapes_removed = len(result.value) - n_chars
    print(
        f"  MD : {md_path.name} ({n_chars:,} caratteri, "
        f"{n_escapes_removed:,} escape inutili rimossi)"
    )
    if result.messages:
        # Mostriamo solo i warning, non i info: mammoth produce tanti
        # info per casi normali (es. "stile non riconosciuto") che
        # sporcano l'output senza essere actionable.
        warnings = [m for m in result.messages if m.type == "warning"]
        if warnings:
            print(f"       ({len(warnings)} warning mammoth)")

    # 2) PDF via docx2pdf (usa Word COM su Windows).
    print(f"  PDF: convertendo via Word COM...")
    docx_to_pdf(str(docx_path), str(pdf_path))
    if pdf_path.exists():
        size_kb = pdf_path.stat().st_size // 1024
        print(f"  PDF: {pdf_path.name} ({size_kb:,} KB)")
    else:
        print(f"  ⚠️  PDF non generato (Word potrebbe non essere installato)")


def main() -> int:
    print(f"Cartella docs: {DOCS_DIR}")
    print(f"File da convertire: {len(DOCX_FILES)}")

    for docx_name in DOCX_FILES:
        try:
            convert_one(docx_name)
        except Exception as e:
            print(f"  ❌ errore su {docx_name}: {type(e).__name__}: {e}")
            return 1

    print("\n=== Riepilogo finale ===")
    for docx_name in DOCX_FILES:
        stem = Path(docx_name).stem
        md = DOCS_DIR / f"{stem}.md"
        pdf = DOCS_DIR / f"{stem}.pdf"
        md_ok = "✓" if md.exists() else "✗"
        pdf_ok = "✓" if pdf.exists() else "✗"
        print(f"  {stem}:  MD {md_ok}  PDF {pdf_ok}")

    n_images = (
        len(list(IMAGES_DIR.glob("*"))) if IMAGES_DIR.exists() else 0
    )
    if n_images:
        print(f"\nImmagini estratte in docs/images/: {n_images}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
