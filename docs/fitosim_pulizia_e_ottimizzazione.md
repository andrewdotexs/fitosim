# fitosim — pulizia e ottimizzazione

*Analisi del 23 ottobre 2026 (seconda passata). Versione 0.35.0, 44 moduli,
26 032 righe in `src/`, 1 578 test in 11,5 s.*

Questo documento è il risultato di un'analisi, non un piano eseguito: dice
che cosa c'è, quanto pesa, chi lo usa e che cosa si propone di farne. Le
decisioni restano quelle di sempre — ogni cambiamento al modello scientifico
si propone prima e si fa dopo — e qui di modello non si tocca nulla: si
parla di codice che nessuno chiama più, di strumenti che mancano e di
numeri misurati sul motore.

**Come sono state prese le misure.** Un grafo degli import costruito con
`ast` sui 44 moduli e sui sorgenti, gli script e i test di The Pot (che
monta fitosim come dipendenza editabile); `ruff` con le regole di The Pot e
con quelle di complessità; `vulture` per il codice morto; `deptry` per le
dipendenze; `mypy` in modalità normale e strict; `cProfile` su una
simulazione di sessanta giorni, a blocchi orari e giornaliera; le durate
della suite con `--durations`. Lo script dell'analisi sta fuori dal repo: le
misure sono ripetibili coi comandi citati in ogni paragrafo.

---

## Pulizia

### 1. Lo strato standalone: 8 400 righe che The Pot non usa

fitosim è nato per girare da solo — un giardino, i suoi vasi, la
persistenza SQLite, i sensori letti via HTTP, l'agenda — e dal 19 settembre
è il motore di The Pot, che ne usa il modello e si tiene tutto il resto
(database, sensori, meteo, pianificazione). Lo strato standalone era stato
congelato a settembre con la clausola «si decide dopo la fase 2 dello
strumento di calibrazione»; la fase 2 ha le sue prime due fette dal 22
ottobre, e la decisione è matura.

| Modulo | Righe | Importato da (dentro fitosim) | Test che lo citano | Chi lo usa fuori |
|---|---:|---|---:|---|
| `io/persistence` | 2 233 | nessuno | 2 file | la fase 0 dello strumento in The Pot (`scripts/calibrazione_wh5x/workflow.py`) |
| `domain/garden` | 1 411 | `io/persistence`, `io/serialization` | 4 file | la fase 0 (`workflow.py`) |
| `io/sensors/*` (8 moduli) | 3 456 | `domain/garden`; `domain/pot` solo in un esempio di docstring | 9 file | nessuno |
| `io/serialization` | 819 | nessuno | 2 file | nessuno |
| `io/openmeteo` | 571 | `io/sensors/openmeteo`; `io/ecowitt` in un import dentro una funzione | 3 file | la fase 0 (`forcing.py`) e il suo test in The Pot |
| `domain/scheduling` | 173 | `domain/garden`, `io/persistence`, `io/serialization` | 4 file | la fase 0 (`forcing.py`) e il suo test |

The Pot ha i suoi client Open-Meteo (`services/previsione.py`,
`meteo_service.py`, `luoghi.py`: una scelta dichiarata a settembre, «due
client per scelta») e la sua persistenza; di `fitosim.io` usa soltanto
`io/ecowitt` (sei simboli: `EcowittObservation`, `EcowittTimeSeries`,
`EcowittSeriesPoint`, `fetch_real_time`, `fetch_history`,
`aa_battery_fraction`), che **resta**.

**Il vincolo.** La fase 0 dello strumento di calibrazione vive in The Pot
(`scripts/calibrazione_wh5x/{workflow,forcing,gateways,catalogo}.py` e
`tests/test_calibrazione_wh5x.py`: 1 889 righe e 97 test) ed è superata dal
21 ottobre dal lettore che legge tutto dal database (`--dal-db`). Finché
quei file esistono, `garden`, `scheduling`, `persistence` e `openmeteo` non
si possono togliere senza rompere la CI di The Pot. Da qui i due passi:

- **P1-a, subito, senza toccare The Pot**: `io/serialization` e i test
  `test_serialization.py` (35 test) più la parte SQLite di
  `test_canopy_in_pot.py`.
- **P1-b, dopo che The Pot ha tolto la fase 0**: `domain/garden`,
  `domain/scheduling`, `io/persistence`, `io/openmeteo`, `io/sensors/*`,
  i loro test (`test_garden`, `test_persistence`, `test_scheduling`,
  `test_openmeteo`, `test_sensors_*`, `test_measurement`, circa 330 test) e
  l'import interno di `DailyWeather` in `io/ecowitt.py` (riga 1528), che
  serve solo alla conversione per la fase 0. Il grosso dei 44 nomi di
  classe fuori convenzione (`N801`) sta nei test dei sensori e se ne va con
  loro.

Quello che resta dopo P1 è il motore: `domain/{pot, species, weather, room,
alerts, blocks}`, `science/*`, `io/ecowitt`. Circa 16 000 righe e 1 100
test.

### 2. Scienza che nessuno raggiunge più

Due moduli di `science/` non sono importati da nessun modulo di fitosim né
da The Pot:

| Modulo | Righe | Test | Che cos'era |
|---|---:|---:|---|
| `science/behavioral_calibration` | 830 | 46 | la calibrazione «comportamentale» dalle osservazioni, superata da `science/calibration` (àncore e valli, Kc per finestra) che è quella che The Pot chiama |
| `science/calibration_resolution` | 613 | 24 | la risoluzione dei conflitti fra proposte, mai arrivata nel lettore di The Pot |

`science/retention` (378 righe) non è raggiunto nemmeno lui, ma è
intenzionale: è la matematica della capacità di contenitore contro l'altezza
della colonna, scritta il 21 ottobre e in attesa delle pesate per essere
agganciata. Resta.

Se le proposte della console (H.9-c in The Pot) avranno bisogno di una
regola per comporre più stime, la si riscriverà sui dizionari del lettore;
riportare in vita `calibration_resolution` com'è significherebbe trascinarsi
il modello di dati della fase 0.

### 3. `examples/` e le dipendenze opzionali

Trentuno script e quattro PNG, 12 566 righe, scritti tappa per tappa fra
luglio e settembre come dimostrazioni dello strato standalone
(`tappa5_*`, `ecowitt_dashboard`, `sensors_integration_demo`,
`openmeteo_real_forecast`…). Nessuno è citato dai sorgenti; li citano il
`README` (sezioni «Repository» e «Documentazione»), lo status report, il
manuale utente e il design del root modeling. `numpy` e `matplotlib`, le due
sole dipendenze non di test, servono soltanto a loro.

`tests/test_demo_appartamento.py` esegue uno di quegli script cinque volte
in sottoprocesso: 9,1 s degli 11,5 della suite intera (sei test). Via gli
esempi, la suite scende sotto i tre secondi.

Nello stesso cesto: `output/plots/pot_characteristics_comparison.png` e
`.vscode/` sono tracciati e non dovrebbero esserlo.

### 4. Gli strumenti che mancano

fitosim non ha una configurazione `ruff`, non ha `mypy`, **non ha una CI**:
nessun workflow in `.github/`. The Pot lo clona da `main` a ogni corsa della
sua CI e lo controlla di riflesso. Il `requires-python` dice `>=3.10`
mentre tutto gira su 3.14 e The Pot chiede 3.12.

Con la configurazione di The Pot (`E, W, F, I, N, UP, B, C4, SIM`, riga da
100, target 3.12) escono 700 segnalazioni, di cui queste sono automatiche:

| Regola | Quante | Che cosa |
|---|---:|---|
| `UP045`, `UP006`, `UP037`, `UP007` | 277 | `Optional[X]` → `X \| None`, `List[` → `list[`, annotazioni fra virgolette |
| `I001` | 115 | import non ordinati |
| `UP017` | 77 | `timezone.utc` → `datetime.UTC` |
| `F401` | 42 | import inutilizzati (in `src/` sono 8, il resto nei test) |
| `F811`, `F841` | 15 | ridefinizioni e variabili inutilizzate |

A mano restano `C408` (45 `dict()` al posto di `{}`), `SIM102` (19 `if`
annidati), `SIM117` (12 `with` doppi) e 5 `B017`. Le regole di complessità
di The Pot troverebbero 13 funzioni oltre 10 (`PLR0913`: 25 funzioni con più
di cinque argomenti), in linea con la natura del codice (FAO-56 ha molti
parametri).

`mypy` conta 86 errori in modalità normale e 170 in strict. Manca il
marcatore `py.typed`: The Pot ha dovuto scrivere un override
`module = ["fitosim.*"]` nel suo `mypy` per non vedere il pacchetto come
non tipizzato. Il marcatore è una riga; gli 86 errori sono il lavoro.

### 5. Le piccole cose

- `vulture`: `theta_to_mm` importato e mai usato in `domain/pot.py`;
  `args` in `io/persistence.py` (se ne va con P1-b).
- Quattordici `print(` in `src/`: dieci sono esempi dentro docstring, quattro
  sono veri (`io/sensors/__init__.py`, `io/sensors/ecowitt.py`,
  `io/sensors/http_json.py`) e vanno via con lo strato standalone. Una
  libreria non stampa.
- Un solo `TODO` (`pot.py:2300`) e sei `# type: ignore`.
- `domain/pot.py`: 3 172 righe, 50 fra metodi e funzioni, 7 classi. I
  metodi più lunghi: `update_from_sensor` 250 righe,
  `apply_balance_step_from_weather` 238, `apply_balance_step_from_indoor`
  191, `__post_init__` 142, `apply_fertigation_step` 141. Non è codice morto
  ed è coperto da `test_pot.py` (3 480 righe): una spaccatura in moduli
  (bilancio, fertirrigazione, sensore, blocchi) è possibile ma non urgente,
  e va fatta solo dopo P1 e P3, quando ruff e mypy la sorvegliano.
- `io/ecowitt.py`: 1 611 righe per sei simboli usati. Dentro ci sono anche
  le serie storiche e la conversione in `DailyWeather` per la fase 0: dopo
  P1-b si misura quanto ne resta vivo.

### 6. La documentazione da allineare

Dopo P1 vanno toccati il `README` (le due sezioni che elencano gli esempi e
lo strato standalone), lo status report (la riga «Strato standalone, 8 400
righe, congelato, 440 test» e la tabella dei moduli), il manuale utente e il
design del root modeling dove citano `examples/`. `docs/developer_documentation.html`
è un file HTML generato, solo, senza sorgente accanto: o si rigenera o si
toglie.

### 7. L'ordine proposto

1. **P3 prima di P1**: configurazione `ruff` e `mypy` nel `pyproject`,
   `requires-python = ">=3.12"`, `py.typed`, le correzioni automatiche in un
   commit a sé (solo forma), gli errori di `mypy` a zero in modalità normale,
   una CI con `ruff`, `mypy` e `pytest` su 3.12, 3.13 e 3.14. Così le
   cancellazioni successive hanno una rete.
2. **P1-a**: `io/serialization`, `behavioral_calibration`,
   `calibration_resolution`, `examples/`, `numpy` e `matplotlib`, i loro
   test, i file tracciati fuori posto, la documentazione.
3. **Consegna a The Pot**: togliere la fase 0 (`workflow.py`, `forcing.py`,
   `gateways.py`, `catalogo.py`, i comandi a cartella in `__main__.py`,
   `tests/test_calibrazione_wh5x.py`) e il `--dal-db` resta l'unico modo.
4. **P1-b**: lo strato standalone, con la versione che sale a 0.36.0 e lo
   status report riscritto sul motore che resta.

Ogni passo è un commit proprio, nessuno cambia un numero del modello.

---

## Ottimizzazione

### 1. Il motore, misurato

Un basilico in un vaso da cinque litri a Milano, sessanta giorni di luglio e
agosto, una fertirrigazione ogni quattro giorni, su Python 3.14:

| Passo | 60 giorni | Per giorno |
|---|---:|---:|
| A blocchi orari, Penman-Monteith per ora (`et0_for_blocks` + `apply_step_blocks`) | 22 ms | 0,36 ms |
| Giornaliero (`apply_balance_step_from_weather` + fertirrigazione) | 1,2 ms | 0,02 ms |
| Import di `domain.pot`, `blocks`, `species`, `weather` | 53 ms | — |

L'anello che The Pot rifà a ogni apertura della scheda di un vaso — due
mesi a blocchi — costa venti millisecondi di motore. **Non c'è niente da
ottimizzare in fitosim per l'uso che ne fa The Pot**: il tempo di quelle
pagine sta nelle query e nella composizione, e si misura di là.

Per completezza, il profilo dice dove andrebbero i secondi se un giorno
servissero (per esempio per una calibrazione su mesi e decine di vasi):

- `current_et_c` vale il 60 % del passo a blocchi (22 ms su 37 nel profilo):
  ricalcola `kp`, `ks` e `kc` a ogni blocco, mentre dentro il giorno cambia
  solo `ks` con lo stato. Calcolarli una volta per giorno taglierebbe circa
  un terzo.
- `_clipped_hour_angles` è chiamata due volte per blocco (2 880 volte in 60
  giorni) con gli stessi argomenti; `seasonal_correction_hours` 5 820 volte.
  Una memoria per giorno nel modulo `radiation` le ridurrebbe a 24 e a 1.

Sono micro-ottimizzazioni con un guadagno da millisecondi: si annotano, non
si fanno.

### 2. La suite di test

11,5 s, di cui 9,1 sono `test_demo_appartamento` (vedi Pulizia, §3). Dopo
P1 la suite sta sotto i tre secondi e può girare a ogni salvataggio. Non
serve parallelismo.

### 3. Il pacchetto

- **`py.typed`**: senza, The Pot non vede i tipi di fitosim e deve
  ignorarlo in `mypy`. È il primo guadagno di P3 per l'altro repo.
- **Versione e distribuzione**: The Pot clona `main` (`FITOSIM_REF=main`
  nel Dockerfile, `git clone --depth 1` nella CI). Con una CI propria in
  fitosim, un tag per versione (`0.36.0`…) e il riferimento al tag in The
  Pot rendono ripetibile una build di ieri. Non è urgente finché i due repo
  avanzano a coppie di commit, ma è il passo che chiude il «quando fitosim
  sarà pubblicata» scritto nel `pyproject` di The Pot.
- **Dipendenze**: dopo P1 fitosim resta a zero dipendenze di runtime, e
  `dev` tiene solo `pytest` e `pytest-cov`.

### 4. Che cosa non si misura qui

Il giro del mattino, le pagine della scheda e della dashboard, la
calibrazione su tutti i vasi: sono tempi di The Pot (database, HTTP,
composizione) e stanno nel documento gemello di quel repo
(`docs/pulizia-e-ottimizzazione.md`), col capitolo «Fitosim» che elenca
modulo per modulo quello che The Pot importa.
