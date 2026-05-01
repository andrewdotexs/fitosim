# Script usati per produrre la consegna di fine tappa 5

Questa cartella raccoglie gli script che ho usato per generare i quattro
deliverable della consegna di fine tappa 5:

- I diagrammi UML aggiornati (`uml/fitosim_packages.png` + `.dot`,
  `uml/fitosim_classes.png` + `.dot`)
- Il `README.md` aggiornato del progetto
- `fitosim_status_report.docx`
- `fitosim_user_manual.docx`

## Indice della cartella

| File | Cosa fa | Quando l'ho usato |
|---|---|---|
| `01_build_status_report.js` | Genera da zero `fitosim_status_report.docx` con docx-js. Definisce helper `p`/`h1`/`h2`/`bullet`/`code`/`makeTable` e produce il documento intero a partire da un array `children`. | Per lo status report (ricostruito da zero). |
| `02_build_new_chapters.py` | Genera il blocco XML dei due nuovi capitoli del manuale (cap 17 sul selettore ET, cap 18 sui vasi indoor con Room). Produce `/home/claude/new_chapters.xml`, 272 paragrafi formattati con stile `Titolo1`/`Titolo2` e Courier New 20pt per i blocchi di codice. | Step 1 della modifica del manuale. |
| `03_insert_chapters_into_manual.py` | Inietta il blocco XML prodotto da `02_build_new_chapters.py` immediatamente prima del paragrafo del cap "17 — Domande frequenti" nel `document.xml` decompattato del manuale, e rinumera il titolo del cap FAQ da "17 —" a "19 —". | Step 2 della modifica del manuale. |
| `04_manual_str_replaces.md` | Documenta come patch testuale tutte le modifiche puntuali fatte con find-and-replace al `README.md` (10 edit) e al `document.xml` del manuale (5 edit). Include anche l'ordine di esecuzione completo per riprodurre la consegna da zero. | Riferimento per le modifiche non automatizzate in script. |

## Cosa NON è in questa cartella

- **I sorgenti `.dot` dei diagrammi UML** vivono direttamente in `uml/`
  perché sono già la forma "sorgente" finale: si rigenerano in PNG con
  `dot -Tpng <file>.dot -o <file>.png`.
- **Il `README.md` aggiornato** vive direttamente nella radice della
  consegna. Non c'è uno script che lo genera: è il `README.md` originale
  del progetto modificato con 10 edit puntuali documentati nel file
  `04_manual_str_replaces.md`.

## Ordine di esecuzione completo

Vedi sezione "C. Ordine di esecuzione completo" del file
`04_manual_str_replaces.md` per il workflow end-to-end (dipendenze,
unpack/repack del manuale, generazione dei PNG dei diagrammi).

## Dipendenze

- **Node.js** + `npm install -g docx@9.6.1` — per `01_build_status_report.js`.
  Lo script va lanciato con `NODE_PATH=$(npm root -g) node 01_build_status_report.js`
  perché il package `docx` è installato globalmente.
- **Python ≥ 3.8** standard library — per `02_build_new_chapters.py` e
  `03_insert_chapters_into_manual.py`. Nessun pacchetto esterno.
- **Graphviz** (binario `dot`) — per rigenerare i PNG dei diagrammi UML
  dai sorgenti `.dot`.
- **Skill `docx` di Anthropic** (`/mnt/skills/public/docx/scripts/office/`)
  per `unpack.py`, `pack.py` e `validate.py`. Solo per il manuale.

## Una nota di metodo

Lo status report è stato ricostruito da zero perché le modifiche da
applicare erano molte e distribuite (executive summary, quadro
quantitativo, sezioni Tappa 5 da scrivere, storico delle consegne da
estendere, considerazioni finali). Generarlo da uno script docx-js
in italiano "tu" è risultato più affidabile e riproducibile rispetto
al pattern unpack → str_replace → repack.

Il manuale invece è stato modificato in place con il pattern unpack →
edit XML → repack, perché le modifiche erano localizzate (sottotitolo,
due numeri di test, una FAQ riscritta, due capitoli inseriti prima del
cap FAQ esistente). Questo pattern preserva intatta la formattazione di
tutto il resto del documento, che era importante perché il manuale ha
730 paragrafi originali con stile `Titolo1`/`Titolo2`/`Titolo3` e
indentazioni dei blocchi di codice che sarebbero state rischiose da
ricostruire pari pari.

Il `README.md` è stato modificato con `str_replace` puntuali, sempre per
preservare la prosa esistente che restava valida (filosofia, quick start,
"cosa NON fa", installazione, autore, licenza erano già scritti bene e
non andavano toccati).
