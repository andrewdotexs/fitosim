# Gli script della documentazione

Dal 15 maggio 2026 **i sorgenti della documentazione sono i file `.md`** di
`docs/`. Si modificano a mano, come il codice, e da loro si producono i PDF di
`docs/pdf/` con l'unico script rimasto:

| File | Cosa fa |
|---|---|
| `06_convert_md_to_pdf.py` | Converte ogni `.md` di `DEFAULT_TARGETS` in HTML (libreria `markdown`) e poi in PDF con Edge o Chrome in headless (motore Chromium, font di sistema: i documenti sono pieni di θ, frecce e pedici). Un `--user-data-dir` temporaneo evita che un Edge già aperto intercetti il comando. |

```
.venv/Scripts/python.exe docs/scripts/06_convert_md_to_pdf.py
.venv/Scripts/python.exe docs/scripts/06_convert_md_to_pdf.py fitosim_user_manual.md
```

Dipendenze: `markdown` (puro Python, nel venv) e Microsoft Edge o Google Chrome.

## Com'era prima: le consegne di maggio

Fino al 1° maggio 2026 i quattro documenti tecnici — manuale utente, manuale
di calibrazione, status report, synthesis report — erano `.docx`: lo status
report generato da zero con docx-js (`01_build_status_report.js`), il
manuale utente modificato in place con il pattern unpack → patch XML →
repack (`02_build_new_chapters.py`, `03_insert_chapters_into_manual.py`,
`04_manual_str_replaces.md`), e il 15 maggio tutti e quattro convertiti in
`.md` con `mammoth` e in PDF con Word (`05_convert_docx_to_md_pdf.py`, con
le immagini estratte in `docs/images/`). Da quel giorno i `.md` hanno preso
le modifiche — la fascia 3 a luglio, le decisioni di modello di settembre —
e i `.docx` sono rimasti al 1° maggio.

Il 20 settembre 2026 (blocco C) i `.docx` e gli script `01`–`05` sono stati
tolti dal repository: un sorgente solo, e i PDF rigenerati dai `.md`. Chi
volesse rivedere quella pipeline la trova nella storia di git prima del
commit che li ha rimossi.
