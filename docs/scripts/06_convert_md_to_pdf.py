"""Conversione dei .md della cartella docs/ in PDF, in docs/pdf/.

Pipeline
--------
    md  ->  HTML (libreria `markdown`, estensioni tables/fenced_code/...)
        ->  HTML impaginato con un foglio di stile di stampa
        ->  PDF (Microsoft Edge / Chrome in headless, motore Chromium)

Perche' Chromium invece di weasyprint o xhtml2pdf
-------------------------------------------------
Su Windows weasyprint richiede le librerie native GTK/Pango e xhtml2pdf
passa da reportlab: entrambe fragili, e con problemi di glyph mancanti.
I documenti fitosim sono pieni di caratteri non-ASCII (theta, frecce,
sottoinsieme, pedici) e servono i font di sistema con fallback: quelli
del browser. Edge e Chrome ci sono gia' su Windows, non c'e' nulla da
installare tranne il pacchetto puro-Python `markdown`.

Un dettaglio che evita un bug silenzioso: si usa un `--user-data-dir`
temporaneo e isolato, altrimenti un'istanza di Edge gia' aperta con il
profilo dell'utente intercetterebbe il comando e il PDF non verrebbe
prodotto.

Uso
---
    .venv/Scripts/python.exe docs/scripts/06_convert_md_to_pdf.py
    .venv/Scripts/python.exe docs/scripts/06_convert_md_to_pdf.py fitosim_user_manual.md

Dipendenze: `markdown` (puro Python) + Microsoft Edge o Google Chrome.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS / "pdf"

# I documenti da convertire. TODO.md e gli .md interni di scripts/ sono
# esclusi di proposito: non fanno parte del set di documentazione.
DEFAULT_TARGETS = [
    "fitosim_user_manual.md",
    "fitosim_calibration_manual.md",
    "fitosim_feedback_layer_design.md",
    "fitosim_root_modeling_design.md",
    "fitosim_status_report.md",
    "fitosim_synthesis_report.md",
]

_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# Foglio di stile di stampa. Bianco su nero per la carta, accenti verdi
# coerenti con la documentazione tecnica del progetto. Le regole di
# page-break tengono insieme tabelle e blocchi di codice.
CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", "Inter", system-ui, sans-serif;
  font-size: 10.5pt; line-height: 1.5; color: #24211c;
}
h1, h2, h3, h4 { color: #2f6b46; line-height: 1.25; page-break-after: avoid; }
h1 { font-size: 20pt; margin: 0 0 .6rem; border-bottom: 2px solid #cfc9ba;
     padding-bottom: .3rem; }
h2 { font-size: 15pt; margin: 1.6rem 0 .5rem; border-bottom: 1px solid #e2ddd0;
     padding-bottom: .2rem; }
h3 { font-size: 12.5pt; margin: 1.2rem 0 .4rem; }
h4 { font-size: 11pt; margin: 1rem 0 .3rem; color: #3d4a40; }
p { margin: .5rem 0; }
a { color: #2f6b46; text-decoration: none; }
strong { font-weight: 600; }
ul, ol { padding-left: 1.4rem; margin: .5rem 0; }
li { margin: .2rem 0; }
code {
  font-family: "JetBrains Mono", "Consolas", monospace; font-size: .86em;
  background: #eef2ee; padding: .1em .35em; border-radius: 3px;
}
pre {
  background: #f6f7f4; border: 1px solid #e0dccf; border-radius: 5px;
  padding: .8rem 1rem; font-size: 8.7pt; line-height: 1.45;
  white-space: pre-wrap; word-wrap: break-word;
  page-break-inside: avoid; margin: .8rem 0;
}
pre code { background: none; padding: 0; font-size: inherit; }
table {
  border-collapse: collapse; width: 100%; margin: .9rem 0; font-size: 9pt;
  page-break-inside: avoid;
}
th, td { border: 1px solid #d3cdbe; padding: .35rem .5rem; text-align: left;
         vertical-align: top; }
th { background: #eef2ee; color: #2d3a30; font-weight: 600; }
tr { page-break-inside: avoid; }
blockquote {
  border-left: 3px solid #6b9a7a; background: #f7f9f6; margin: .8rem 0;
  padding: .3rem 1rem; color: #4d574c;
}
hr { border: none; border-top: 1px solid #ddd7c8; margin: 1.4rem 0; }
img { max-width: 100%; }
"""

HTML_TEMPLATE = (
    "<!doctype html><html lang=\"it\"><head><meta charset=\"utf-8\">"
    "<base href=\"{base}\"><style>{css}</style></head>"
    "<body>{body}</body></html>"
)

# Le immagini nei .md (es. i grafici del synthesis report) sono
# referenziate con path relativi tipo `images/xxx.png`. L'HTML viene
# scritto in una cartella temporanea, quindi senza un <base> quei path
# non si risolverebbero: lo ancoriamo a docs/ (con lo slash finale,
# altrimenti l'ultimo segmento verrebbe sostituito invece che esteso).
_BASE_HREF = DOCS.as_uri() + "/"


def find_browser() -> Path:
    for candidate in _BROWSER_CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit(
        "Nessun browser Chromium trovato (Edge/Chrome). "
        "Installa uno dei due o adatta _BROWSER_CANDIDATES."
    )


def md_to_html(md_text: str) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )
    return HTML_TEMPLATE.format(base=_BASE_HREF, css=CSS, body=body)


def render_pdf(browser: Path, html_path: Path, pdf_path: Path, profile: Path) -> None:
    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    subprocess.run(
        cmd, check=True, timeout=180,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"PDF non prodotto o vuoto: {pdf_path}")


def main(argv: list[str]) -> int:
    targets = argv[1:] or DEFAULT_TARGETS
    OUT_DIR.mkdir(exist_ok=True)
    browser = find_browser()
    print(f"Browser: {browser.name}")
    tmp = Path(tempfile.mkdtemp(prefix="md2pdf_"))
    profile = tmp / "profile"
    failures = 0
    try:
        for name in targets:
            src = DOCS / name
            if not src.is_file():
                print(f"  SKIP (assente): {name}")
                failures += 1
                continue
            html_path = tmp / (src.stem + ".html")
            html_path.write_text(md_to_html(src.read_text(encoding="utf-8")),
                                 encoding="utf-8")
            pdf_path = OUT_DIR / (src.stem + ".pdf")
            render_pdf(browser, html_path, pdf_path, profile)
            kb = pdf_path.stat().st_size // 1024
            print(f"  OK  {name}  ->  pdf/{pdf_path.name}  ({kb} KB)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
