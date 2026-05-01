# Edit puntuali ai file di testo

Questo file documenta le modifiche puntuali (find-and-replace) fatte al
`README.md` e al `word/document.xml` del manuale già decompattato. Sono
modifiche piccole che non vale la pena automatizzare in uno script
dedicato, ma che vanno applicate per ottenere il risultato finale
mostrato nei deliverable.

L'ordine indicato è quello in cui le ho applicate. Ogni edit è formattato
come blocco "OLD →→→ NEW".

---

## A. Modifiche a `README.md`

### A.1 — Stato del progetto: numeri e percentuali

```text
OLD:
## Stato del progetto

- **865 test verdi** (più 1 skipped intenzionale, 340 sub-test)
- **Tempo esecuzione suite**: ~2.4 secondi su laptop standard
- **Linguaggio**: Python ≥ 3.10
- **Dipendenze esterne nel core**: zero (solo standard library)
- **Schema database**: SQLite v3 con migrazioni automatiche v1→v2→v3
- **Fascia 1**: completa (modello idrico FAO-56 esteso)
- **Fascia 2**: 4 tappe complete su 5 (80% del percorso)

```
$ python -m pytest tests/
============================= 865 passed, 1 skipped in 2.36s =============================
```
```

```text
NEW:
## Stato del progetto

- **1007 test verdi** (più 1 skipped intenzionale, 357 sub-test)
- **Tempo esecuzione suite**: ~11 secondi su laptop standard
- **Linguaggio**: Python ≥ 3.10
- **Dipendenze esterne nel core**: zero (solo standard library)
- **Schema database**: SQLite v3 con migrazioni automatiche v1→v2→v3
- **Fascia 1**: completa (modello idrico FAO-56 esteso)
- **Fascia 2**: **completa** (5 tappe su 5, 100% del percorso)
- **Prossimo passo**: apertura fascia 3 di calibrazione contro dati reali del balcone

```
$ python -m pytest tests/
======================== 1007 passed, 1 skipped in 11.43s ========================
```
```

### A.2 — Sezione "Cosa fa": aggiungo le capacità della tappa 5

Allungo l'elenco di capacità con tre nuovi bullet inseriti dopo
"Sistema di allerte ...". I nuovi bullet sono: "Selettore best
available dell'evapotraspirazione", "Modello dei vasi indoor", "Supporto
sensore di substrato evoluto".

### A.3 — Comando di verifica installazione: numero di test atteso

```text
OLD: python -m pytest tests/  # verifica che la suite gira (865 verdi attesi)
NEW: python -m pytest tests/  # verifica che la suite gira (1007 verdi attesi)
```

### A.4 — Apertura sezione "Storia delle tappe"

```text
OLD: ... la fascia 2 sta estendendo la libreria con sensoristica reale, modello chimico, e architettura applicativa.
NEW: ... la fascia 2 ha esteso la libreria con sensoristica reale, modello chimico, architettura applicativa, e raffinamento scientifico (Penman-Monteith e modello indoor).
```

### A.5 — Titolo della sezione Fascia 2

```text
OLD: ### Fascia 2 — Sensori, chimica, architettura applicativa (4/5 tappe)
NEW: ### Fascia 2 — Sensori, chimica, architettura applicativa (chiusa)
```

### A.6 — Riscrittura completa della sezione "Tappa 5"

La vecchia sezione (work in progress, "in pianificazione") è stata
sostituita da una nuova sezione "Tappa 5 — Penman-Monteith fisico e
modello indoor (completa)" con:

- Paragrafo di introduzione (142 test verdi totali aggiunti).
- Tabella delle 5 sotto-tappe (A, B, C, D, E) con colonne sotto-tappa,
  capacità, test (+25/+17/+30/+64/+6).
- Paragrafo sulla complementarietà dei due raffinamenti.
- Rimando allo status report per i dettagli di design.
- Nuova sotto-sezione "Prossimo passo: fascia 3 di calibrazione".

Per il testo completo vedi le righe corrispondenti del `README.md`
consegnato.

### A.7 — Architettura: descrizioni dei tre layer

Aggiornate le tre frasi che descrivono i layer `science/`, `domain/` e
`io/` per menzionare:

- **`science/`**: Penman-Monteith fisico/standard e selettore best
  available, modulo `indoor` per la radiazione, dataclass `EtResult`.
- **`domain/`**: nuovo modulo `room` per gli spazi indoor, modulo
  `weather` per `WeatherDay`, menzione che le strutture sono "introdotte
  dalle tappe 4 e 5".
- **`io/`**: `ecowitt.py` espone tre classi distinte
  (`EcowittEnvironmentSensor`, `EcowittWH51SoilSensor` parametrizzato per
  WH51/WH52, `EcowittAmbientSensor` per WN31).

### A.8 — Albero del repository

Aggiunti i file nuovi:

- `domain/room.py` (Room, IndoorMicroclimate)
- `domain/weather.py` (WeatherDay)
- `science/indoor.py` (radiazione indoor)

Aggiornati i commenti dei file modificati:

- `domain/garden.py` ora dice "(tappe 4-5)"
- `science/et0.py` ora dice "Penman-Monteith + Hargreaves + selettore"
- `io/sensors/ecowitt.py` ora dice "adapter Ecowitt: WH51/WH52, WN31, Env"

Aggiunti gli script demo della tappa 5 sotto `examples/`:

- `tappa5_A_penman_monteith_demo.py`
- `tappa5_B_selettore_demo.py`
- `tappa5_C_garden_demo.py`
- `tappa5_E_appartamento_demo.py`

Aggiornato il numero di test verdi nel commento di `tests/` da 865 a 1007.

### A.9 — Sezione Documentazione: estensione delle demo

Sostituita la riga della "Demo end-to-end" che parlava solo della tappa 4
con tre paragrafi: demo della tappa 4, demo end-to-end della tappa 5
(`tappa5_E_appartamento_demo.py`), e demo pedagogiche delle sotto-tappe
A/B/C.

### A.10 — Paragrafo introduttivo del README (sopra "Stato del progetto")

```text
OLD: ... Estende lo standard FAO-56 con sei capacità specifiche del giardinaggio in vaso che i modelli per il pieno campo non coprono.

NEW: ... Estende lo standard FAO-56 con capacità specifiche del giardinaggio in vaso che i modelli per il pieno campo non coprono, dalle geometrie reali del vaso al sottovaso, dalle miscele di substrati al modello chimico, dal bilancio indoor con microclima della stanza al selettore "best available" del metodo di evapotraspirazione.
```

E nel paragrafo successivo ho aggiunto "(anche distribuiti tra più stanze
indoor)" all'enumerazione delle capacità del Garden.

---

## B. Modifiche a `manual_unpacked/word/document.xml`

Da applicare PRIMA di lanciare `03_insert_chapters_into_manual.py`. Sono
quattro edit tutti su `<w:t>...</w:t>` interni a paragrafi esistenti, e
preservano formattazione e paraId dei `<w:p>` che li contengono.

### B.1 — Sottotitolo della copertina

```text
OLD: <w:t>Aprile 2026 — Aggiornato a fine tappa 4 fascia 2</w:t>
NEW: <w:t>Maggio 2026 &#x2014; Aggiornato a fine tappa 5 fascia 2 (chiusura fascia 2)</w:t>
```

Nota: il trattino lungo va come entity HTML (`&#x2014;`) per coerenza
con quanto fa `unpack.py`, che converte tutti gli smart-quotes in entity.

### B.2 — Risultato di `pytest` nel cap 2

```text
OLD: <w:t>==================== 865 passed, 1 skipped in 2.36s =====================</w:t>
NEW: <w:t>==================== 1007 passed, 1 skipped in 11.43s =====================</w:t>
```

### B.3 — Commento sul numero di test nel cap 2

```text
OLD: <w:t>Se vedi un risultato simile (al momento della scrittura di questo manuale la suite conta 865 test verdi più 1 skipped intenzionale, organizzati in fascia 1 e fascia 2), tutto è a posto e puoi proseguire. Se vedi errori di import, è possibile che la directory src/ non sia nel tuo path: ricorda di lanciare gli script con PYTHONPATH=src impostato, oppure di installare la libreria in modalità sviluppo con pip install -e .</w:t>
```

```text
NEW: <w:t>Se vedi un risultato simile (al momento della scrittura di questo manuale la suite conta 1007 test verdi pi&#xF9; 1 skipped intenzionale e 357 sub-test, organizzati in fascia 1 e fascia 2), tutto &#xE8; a posto e puoi proseguire. Se vedi errori di import, &#xE8; possibile che la directory src/ non sia nel tuo path: ricorda di lanciare gli script con PYTHONPATH=src impostato, oppure di installare la libreria in modalit&#xE0; sviluppo con pip install -e .</w:t>
```

### B.4 — Mappa del manuale (cap 1)

Sostituisce la frase che diceva "Il capitolo 17 raccoglie le domande
frequenti" con una versione estesa che cita i nuovi cap 17 e 18 sulla
tappa 5, e sposta le FAQ al cap 19. Vedi il file consegnato per il testo
preciso (frase lunga, con accenti come entity).

### B.5 — FAQ "Le mie piante sono indoor, devo cambiare qualcosa?"

Sostituita interamente la risposta. Quella vecchia rimandava alla tappa 5
"futura"; la nuova è un consuntivo del modello indoor effettivamente
implementato (Room, WN31, LightExposure, WH52, modulo `science/indoor.py`).

---

## C. Ordine di esecuzione completo

Per riprodurre da zero la consegna, partendo dal repository fitosim
allo stato di fine tappa 5:

```bash
# 1) Setup
mkdir -p ~/work && cd ~/work
unzip /percorso/fitosim.zip   # (o git clone del repo)
cd fitosim

# 2) Diagrammi UML
#    I sorgenti aggiornati sono direttamente in docs/uml/*.dot
dot -Tpng docs/uml/fitosim_packages.dot -o docs/uml/fitosim_packages.png
dot -Tpng docs/uml/fitosim_classes.dot -o docs/uml/fitosim_classes.png

# 3) README.md
#    Applicare gli edit A.1 → A.10 sopra elencati al README.md.
#    (Nessuno script automatico: sono str_replace puntuali.)

# 4) Status report
#    Generato da zero con docx-js.
NODE_PATH=$(npm root -g) node /percorso/01_build_status_report.js
#    Produce: ./docs/fitosim_status_report.docx

# 5) Manuale utente
#    a) decompattare
python3 /mnt/skills/public/docx/scripts/office/unpack.py \
    docs/fitosim_user_manual.docx /home/claude/manual_unpacked/
#    b) applicare gli edit B.1 → B.5 al document.xml
#    c) generare il blocco XML dei nuovi capitoli
python3 /percorso/02_build_new_chapters.py
#       → produce /home/claude/new_chapters.xml
#    d) inserire il blocco e rinumerare il cap FAQ
python3 /percorso/03_insert_chapters_into_manual.py
#    e) ripack
python3 /mnt/skills/public/docx/scripts/office/pack.py \
    /home/claude/manual_unpacked/ docs/fitosim_user_manual.docx \
    --original docs/fitosim_user_manual.docx.orig
```
