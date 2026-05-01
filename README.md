# fitosim

> Libreria Python per la simulazione FAO-56 del bilancio idrico e chimico
> dei vasi domestici. Il motore agronomico del dashboard "Il Mio Giardino".

fitosim è una libreria Python che ti aiuta a capire quanto e quando irrigare
le piante nei tuoi vasi. Funziona modellando il bilancio idrico e chimico del
singolo vaso giorno per giorno: quanta acqua entra (pioggia, irrigazione),
quanta esce (evapotraspirazione), quanta resta disponibile alla pianta, e
come evolve la concentrazione di sali e il pH del substrato. Estende lo
standard FAO-56 con capacità specifiche del giardinaggio in vaso che i
modelli per il pieno campo non coprono, dalle geometrie reali del vaso al
sottovaso, dalle miscele di substrati al modello chimico, dal bilancio
indoor con microclima della stanza al selettore "best available" del metodo
di evapotraspirazione.

Sopra al modello del singolo vaso, fitosim costruisce un dashboard operativo
completo: il `Garden` orchestra più vasi insieme (anche distribuiti tra più
stanze indoor), la persistenza SQLite conserva la storia, gli eventi
pianificati e le previsioni a N giorni anticipano gli interventi, e il
sistema di allerte trasforma le previsioni in raccomandazioni concrete per
il giardiniere.

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

## Cosa fa

Il dominio in cui fitosim sa fare bene il suo lavoro è il **vaso domestico
singolo o un piccolo gruppo di vasi su un balcone**, su scala di tempo
giornaliera, per piante individualmente identificabili e con substrati di
parametri noti. In questo dominio specifico la libreria copre:

- Bilancio idrico FAO-56 standard con dual-Kc opzionale (capitolo 7 della
  pubblicazione FAO-56)
- Caratterizzazione fisica del vaso: materiale, colore, forma geometrica,
  esposizione solare (coefficiente di vaso Kp)
- Modello del sottovaso opzionale come componente di stato distinto, con
  riassorbimento capillare verso il substrato
- Sostrati personalizzati: catalogo di nove materiali base (akadama, pomice,
  perlite, ecc.) e factory `compose_substrate` per i mix
- Modello chimico completo: massa salina, pH, EC come grandezza derivata,
  coefficiente nutrizionale Kn che modula l'evapotraspirazione
- Esposizione differenziata alla pioggia per i vasi parzialmente coperti
- Calibrazione empirica dei parametri del substrato dalle letture storiche
  del sensore WH51
- Feedback loop sensore-modello in tempo reale con diagnostica strutturata
  della discrepanza
- **Garden**: orchestrazione di più vasi come unità coerente
- **Persistenza SQLite**: database operativo con storia completa degli stati
- **Serializzazione JSON**: formato di trasporto autocontenuto
- **Integrazione sensori in batch**: aggiornamento robusto a errori
  transitori
- **Eventi pianificati e forecast**: piani di fertirrigazione e proiezioni
  dello stato a N giorni
- **Sistema di allerte**: cinque categorie e tre severità, derivate dallo
  stato corrente o proiettato
- **Selettore "best available" dell'evapotraspirazione**: Penman-Monteith
  fisico (con resistenza stomatica della specie), Penman-Monteith standard
  FAO-56 e Hargreaves-Samani come fallback, scelti automaticamente in
  funzione dei dati meteo disponibili e dei parametri della specie
- **Modello dei vasi indoor**: entità `Room` per gli spazi indoor con
  microclima condiviso, sensore ambientale WN31 di Ecowitt, modello a tre
  livelli di esposizione luminosa (`LightExposure`), bilancio idrico
  alimentato dal microclima della stanza invece che dal meteo esterno
- **Supporto sensore di substrato evoluto**: il WH52 (upgrade del WH51 con
  temperatura ed EC del substrato) è gestito dallo stesso adapter
  parametrizzato, con fallback automatico alle capacità del WH51 quando
  i campi nuovi non sono disponibili

## Cosa NON fa

È utile mettere subito in chiaro i confini del dominio, perché fitosim è uno
strumento specializzato e applicarlo fuori dal suo territorio produce
risultati poco affidabili.

fitosim non è un sostituto di modelli idrologici di pieno campo come HYDRUS
o RZWQM, che gestiscono bilanci a scala di parcella con flussi orizzontali
tra suoli adiacenti. Non è un sistema di controllo in tempo reale: le sue
stime sono giornaliere, non al minuto, e non è pensato per guidare
elettrovalvole con feedback continuo. Non è infine un sostituto del
giardiniere: ti dice "il vaso è sceso sotto la soglia di allerta", non
"irriga adesso 250 ml" senza che tu abbia la possibilità di valutare le
condizioni reali del momento.

## Quick start

### Hello basilico (singolo vaso)

L'esempio minimo per verificare che fitosim funzioni nel tuo ambiente. Crea
un vaso di basilico, simula un giorno di evapotraspirazione, e stampa lo
stato risultante.

```python
from datetime import date
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

vaso = Pot(
    label="Basilico balcone-1",
    species=BASIL,
    substrate=UNIVERSAL_POTTING_SOIL,
    pot_volume_l=2.0,
    pot_diameter_cm=18.0,
    location=Location.OUTDOOR,
    planting_date=date(2026, 4, 1),
)

print(f"Stato iniziale: {vaso.state_mm:.1f} mm")
print(f"Soglia di allerta: {vaso.alert_mm:.1f} mm")

vaso.apply_balance_step(
    et_0_mm=4.0, water_input_mm=0.0,
    current_date=date(2026, 4, 2),
)
print(f"Dopo un giorno di sole: {vaso.state_mm:.1f} mm")
```

### Hello balcone (Garden, sensori, allerte, persistenza)

L'esempio "completo" che mostra le capacità della tappa 4 in azione: tre
vasi orchestrati insieme, persistenza SQLite, eventi pianificati, allerte
sullo stato corrente e previste nei prossimi giorni.

```python
from datetime import date, datetime, timedelta, timezone
from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast
from fitosim.io.persistence import GardenPersistence
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

# Costruisci il giardino con tre vasi a esposizioni diverse alla pioggia.
balcone = Garden(name="balcone-milano")
for label, exposure in [("aperto", 1.0),
                        ("ringhiera", 0.5),
                        ("albero", 0.2)]:
    balcone.add_pot(Pot(
        label=label, species=BASIL, substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.0, pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 5, 1),
        rainfall_exposure=exposure,
    ))

# Persisti il giardino in un database SQLite locale.
db = GardenPersistence("/tmp/giardino.db")
db.register_species(BASIL)
db.register_substrate(UNIVERSAL_POTTING_SOIL)
db.save_garden(balcone, snapshot_timestamp=datetime.now(timezone.utc))

# Pianifica una fertirrigazione per il prossimo lunedì.
balcone.add_scheduled_event(ScheduledEvent(
    event_id="fert-aperto-w1",
    pot_label="aperto",
    event_type="fertigation",
    scheduled_date=date(2026, 5, 25),
    payload={"volume_l": 0.3, "ec_mscm": 2.0, "ph": 6.2},
))

# Applica un giorno di simulazione a tutti i vasi insieme.
balcone.apply_step_all(
    et_0_mm=4.5, current_date=date(2026, 5, 20),
    rainfall_mm=0.0,
)

# Allerte sullo stato corrente.
for alert in balcone.current_alerts(date(2026, 5, 20)):
    print(f"[{alert.severity.value}] {alert.pot_label}: {alert.message}")

# Previsione e allerte previste per i prossimi 7 giorni.
forecast_meteo = [
    WeatherDayForecast(
        date_=date(2026, 5, 20) + timedelta(days=i),
        et_0_mm=5.0, rainfall_mm=0.0,
    )
    for i in range(7)
]
risultato = balcone.forecast(forecast_meteo)
for alert in balcone.forecast_alerts(forecast_meteo):
    print(f"Tra {(alert.triggered_date - date(2026, 5, 20)).days} giorni: "
          f"{alert.pot_label} - {alert.category.value}")
```

Se il primo esempio gira e stampa tre numeri sensati, fitosim è installato
correttamente. Se il secondo esempio gira e produce le allerte, hai a
disposizione tutto il dashboard operativo della tappa 4.

## Installazione

fitosim richiede **Python ≥ 3.10**. Non ha dipendenze esterne nel core: tutto
il codice agronomico, dalla matematica FAO-56 alla persistenza SQLite, gira
con la sola standard library di Python. È pensato per girare bene anche su
ambienti vincolati come Termux su Android o Raspberry Pi 5.

Per ora fitosim è distribuito come repository sorgente, non è ancora
pubblicato su PyPI:

```bash
git clone https://github.com/<tuo-username>/fitosim.git
cd fitosim
python -m pytest tests/  # verifica che la suite gira (1007 verdi attesi)
```

Per usare la libreria nei tuoi script puoi scegliere tra due opzioni. La
prima è impostare `PYTHONPATH=src` quando lanci gli script:

```bash
PYTHONPATH=src python tuo_script.py
```

La seconda è installare in modalità sviluppo:

```bash
pip install -e .
python tuo_script.py
```

L'opzione consigliata per uso prolungato è la seconda perché crea un link
simbolico nel virtual environment e rende fitosim importabile da qualsiasi
script.

## Architettura

La libreria è organizzata in tre layer architetturali con dipendenze che
vanno solo "verso il basso": `domain` dipende da `science` (mai il
contrario), `io` dipende da `domain` (mai il contrario). Questo principio
protegge il modello scientifico dai dettagli applicativi: puoi cambiare il
database da SQLite a PostgreSQL senza toccare nulla del modello FAO-56.

![Diagramma dei package di fitosim](docs/uml/fitosim_packages.png)

Il layer `science/` contiene il modello matematico FAO-56 esteso: bilancio
idrico, calcolo ET (Penman-Monteith fisico, Penman-Monteith standard FAO-56,
Hargreaves-Samani, e selettore "best available" che sceglie automaticamente
la formula migliore disponibile), dual-Kc, fisica del vaso (Kp), modello
chimico (coefficiente Kn), sottovaso, fertirrigazione, calibrazione empirica,
e radiazione indoor categoriale e continua per i vasi in casa. Sono
prevalentemente funzioni pure più qualche dataclass (`Substrate`,
`BaseMaterial`, `EtResult`).

Il layer `domain/` contiene gli oggetti di dominio e l'orchestrazione: `Pot`
è la classe centrale che monta insieme tutte le componenti scientifiche in
un'entità coerente, `Garden` orchestra più vasi insieme, `Species` e
`Substrate` caratterizzano la pianta e il terriccio, `Room` modella gli
spazi indoor con il loro microclima condiviso (sotto-tappa 5-D), `Alert`,
`ScheduledEvent`, `WeatherDay` e `WeatherDayForecast` sono le strutture
introdotte dalle tappe 4 e 5.

Il layer `io/` contiene gli adapter di ingresso e uscita: `persistence`
(SQLite) e `serialization` (JSON) sono completamente disaccoppiati tra loro;
sotto `io/sensors/` vivono cinque adapter concreti (Ecowitt, Open-Meteo,
HTTP-JSON, fixtures CSV) che implementano i `Protocol` definiti in
`protocols.py`. Il file `ecowitt.py` espone tre classi distinte:
`EcowittEnvironmentSensor` per il meteo outdoor, `EcowittWH51SoilSensor`
per il substrato (parametrizzato per WH51 e WH52), e `EcowittAmbientSensor`
per il microclima delle stanze indoor (WN31).

### Le entità di dominio

Il diagramma delle classi qui sotto mostra le entità principali con le loro
relazioni. Il `Pot` è la scatola più grande perché concentra tutto il sapere
agronomico della libreria; il `Garden` è il punto di sutura tra modello
scientifico e applicazione operativa.

![Diagramma delle classi del dominio](docs/uml/fitosim_classes.png)

Una proprietà strutturale che il diagramma mette in luce è il pattern
"stato canonico minimo + viste derivate": il `Pot` ha solo quattro veri
attributi di stato dinamico (`state_mm`, `salt_mass_meq`, `ph_substrate`,
`saucer_state_mm`), e tutte le altre quantità (`state_theta`,
`ec_substrate_mscm`, `fc_mm`, `pwp_mm`, `alert_mm`, `kp`) sono property
calcolate on-demand. Conseguenza pratica: il database memorizza solo quei
quattro numeri per ogni snapshot, e tutto il resto viene ricalcolato al
caricamento.

## Repository

```
fitosim/
├── src/fitosim/
│   ├── domain/             # entità di dominio e orchestrazione
│   │   ├── garden.py       # Garden orchestratore (tappe 4-5)
│   │   ├── pot.py          # Pot, classe centrale del modello
│   │   ├── species.py      # Species, catalogo specie predefinite
│   │   ├── room.py         # Room, IndoorMicroclimate (tappa 5-D)
│   │   ├── weather.py      # WeatherDay (tappa 5-C)
│   │   ├── alerts.py       # Sistema di allerte (tappa 4)
│   │   ├── scheduling.py   # ScheduledEvent, WeatherDayForecast
│   │   └── scheduler.py    # Pianificatore irrigazione (fascia 1)
│   ├── science/            # modello matematico FAO-56 esteso
│   │   ├── substrate.py    # Substrate, BaseMaterial, mix
│   │   ├── balance.py      # bilancio idrico FAO-56
│   │   ├── et0.py          # Penman-Monteith + Hargreaves + selettore
│   │   ├── indoor.py       # radiazione indoor (tappa 5-D)
│   │   ├── dual_kc.py      # FAO-56 capitolo 7
│   │   ├── pot_physics.py  # Kp, geometrie del vaso
│   │   ├── saucer.py       # modello sottovaso
│   │   ├── nutrition.py    # coefficiente Kn (tappa 3)
│   │   ├── fertigation.py  # applicazione fertirrigazione
│   │   ├── calibration.py  # calibrazione da sensore
│   │   └── radiation.py    # radiazione solare astronomica
│   └── io/                 # adapter di acquisizione e persistenza
│       ├── persistence.py  # SQLite, schema v3 (tappa 4)
│       ├── serialization.py # JSON formato v2 (tappa 4)
│       └── sensors/
│           ├── protocols.py    # SoilSensor, EnvironmentSensor (Protocol)
│           ├── types.py        # SoilReading, EnvironmentReading
│           ├── errors.py       # gerarchia eccezioni a 3 livelli
│           ├── ecowitt.py      # adapter Ecowitt: WH51/WH52, WN31, Env
│           ├── openmeteo.py    # adapter Open-Meteo (meteo)
│           ├── http_json.py    # adapter generico per gateway ESP32
│           └── fixtures.py     # adapter CSV per test
├── tests/                  # 1007 test verdi
├── examples/               # esempi e demo end-to-end
│   ├── tappa4_complete_demo.py        # demo Garden + persistenza + allerte
│   ├── tappa5_A_penman_monteith_demo.py
│   ├── tappa5_B_selettore_demo.py
│   ├── tappa5_C_garden_demo.py
│   └── tappa5_E_appartamento_demo.py  # demo end-to-end appartamento indoor
├── docs/
│   ├── fitosim_user_manual.docx     # manuale utente
│   ├── fitosim_status_report.docx   # report di status del progetto
│   └── uml/
│       ├── fitosim_packages.dot     # sorgente diagramma package
│       ├── fitosim_packages.png
│       ├── fitosim_classes.dot      # sorgente diagramma classi
│       └── fitosim_classes.png
└── README.md
```

## Storia delle tappe

Il progetto è strutturato in due fasce di lavoro, ognuna composta da più
tappe. La fascia 1 ha costruito il modello idrico completo del singolo vaso;
la fascia 2 ha esteso la libreria con sensoristica reale, modello
chimico, architettura applicativa, e raffinamento scientifico (Penman-Monteith
e modello indoor).

### Fascia 1 — Modello idrico completo (chiusa)

Sei tappe completate che hanno introdotto: caratterizzazione fisica del vaso
(forma, materiale, esposizione), sottovaso opzionale, sostrati
personalizzati con factory `compose_substrate`, dual-Kc di FAO-56 capitolo
7, calibrazione empirica del substrato, feedback loop sensore-modello. La
fascia conta 423 test verdi che continuano a passare al byte ad ogni nuova
consegna della fascia 2.

### Fascia 2 — Sensori, chimica, architettura applicativa (chiusa)

**Tappa 1 — Astrazione sensori (completa).** Ha costruito l'astrazione di
sensore di fitosim come `Protocol` Python, separando il modello scientifico
dai dettagli di acquisizione. Tipi di ritorno strutturati
(`EnvironmentReading`, `SoilReading`) con timestamp UTC obbligatorio,
gerarchia di eccezioni canoniche a tre livelli
(`SensorTemporaryError`/`SensorPermanentError`/`SensorDataQualityError`).

**Tappa 2 — Gateway hardware-to-HTTP (completa).** Ha aggiunto il primo
sensore di suolo "ricco" (θ, temperatura, EC, pH) tramite un pattern
generico: adapter `HttpJsonSoilSensor` che parla con un gateway esterno via
schema JSON V1. Il gateway si occupa dei dettagli hardware (Modbus RTU su
RS485 nel caso ATO) e li espone come endpoint REST. La consegna include un
firmware ESP32 di esempio in cinque file Arduino.

**Tappa 3 — Modello chimico del substrato (completa).** Ha esteso il `Pot`
col modello chimico completo: massa salina come stato canonico, pH come
stato indipendente, EC come property derivata. Coefficiente nutrizionale Kn
che modula l'evapotraspirazione in funzione dello stato chimico. Il
fenomeno della concentrazione per evapotraspirazione emerge automaticamente.
Coefficiente di esposizione alla pioggia (`rainfall_exposure`) per i vasi
parzialmente coperti.

**Tappa 4 — Dashboard operativo completo (completa).** La tappa più
sostanziosa per scope architetturale, organizzata in cinque sotto-tappe che
hanno aggiunto in totale 179 test verdi:

| Sotto-tappa | Capacità | Test |
|---|---|---|
| A: Garden in-memory | Orchestrazione di più vasi come unità coerente | +30 |
| B fase 1: SQLite | Persistenza con storia completa degli stati | +32 |
| B fase 2: JSON | Formato di trasporto per backup e migrazione | +20 |
| C: integrazione sensori | Update batch dai sensori reali con robustezza errori | +23 |
| D: forecast e eventi | Eventi pianificati e proiezione dello stato a N giorni | +36 |
| E: sistema di allerte | Allerte derivate dallo stato per dashboard proattivo | +38 |

**Tappa 5 — Penman-Monteith fisico e modello indoor (completa).** Chiude la
fascia 2 con un raffinamento sostanziale del modello scientifico, articolato
in cinque sotto-tappe progressive che hanno aggiunto in totale 142 test
verdi:

| Sotto-tappa | Capacità | Test |
|---|---|---|
| A: Penman-Monteith come funzioni pure | Penman-Monteith fisico (con resistenza stomatica della specie) e standard FAO-56 nel modulo `science/et0.py`, accanto a Hargreaves-Samani | +25 |
| B: selettore "best available" | `compute_et` sceglie automaticamente Penman-Monteith fisico → standard → Hargreaves in funzione dei dati meteo e dei parametri specie disponibili. Tracciabilità del metodo via `EtResult` e `EtMethod` | +17 |
| C: integrazione nel Pot e nel Garden | `WeatherDay` come dataclass meteo giornaliera, `apply_balance_step_from_weather` sul Pot e `apply_step_all_from_weather` sul Garden, che invocano il selettore al posto di un ET₀ pre-calcolato | +30 |
| D: modello indoor | Entità `Room` per gli spazi indoor con microclima condiviso, `IndoorMicroclimate` con varianti istantanea e giornaliera, `LightExposure` a tre livelli, modulo `science/indoor.py` per la radiazione, `EcowittAmbientSensor` per il sensore WN31, supporto WH52 nel `EcowittWH51SoilSensor`, persistenza delle Room nel database SQLite | +64 |
| E: demo end-to-end appartamento | Script eseguibile (`tappa5_E_appartamento_demo.py`) che simula un appartamento invernale con tre vasi indoor in due Room diverse, mostra in azione la selezione automatica del metodo ET, la persistenza delle Room, e produce quattro grafici PNG di analisi | +6 |

I due raffinamenti sono complementari. Il selettore "best available" cattura
la varianza del meteo outdoor con la migliore formula disponibile per ogni
giorno; il modello indoor lo applica al microclima della stanza invece che
al meteo del balcone, alimentato dal sensore WN31 specifico per ambienti
chiusi. Insieme permettono di trattare con la stessa libreria un balcone
outdoor estivo soleggiato e un appartamento invernale con vasi sparsi tra
salotto e camera da letto, ognuno con il suo microclima e le sue regole.

Per i dettagli architetturali e le decisioni di design di ciascuna
sotto-tappa, vedi lo status report del progetto.

### Prossimo passo: fascia 3 di calibrazione

Con la fascia 2 chiusa, il prossimo passo è la **fascia 3 di calibrazione**:
una fase concettualmente diversa dalle precedenti, meno "costruzione di
nuove API" e più "messa a punto e validazione contro realtà". I dati reali
del balcone milanese (la stazione Ecowitt è già installata e raccoglie dati
da mesi) saranno usati per raffinare i numeri specifici del modello: le
frazioni della radiazione indoor, i parametri Kc del catalogo specie, le
soglie del selettore "best available", la resistenza stomatica delle specie
con dati reali. Lo scopo è trasformare fitosim da "libreria genericamente
plausibile" a "libreria calibrata per il TUO balcone milanese".

## Documentazione

La documentazione del progetto vive in `docs/` e copre tre livelli di
approfondimento.

**Manuale utente** (`docs/fitosim_user_manual.docx`): la guida completa di
17 capitoli più tre appendici, scritta in italiano con stile narrativo. È
il punto di riferimento per imparare a usare la libreria, dai concetti
fondamentali (capitoli 1-3) alle capacità avanzate del singolo vaso
(4-9), dal dashboard operativo del balcone (10-16) alle FAQ (17). Le
appendici contengono il catalogo delle specie pre-definite, i substrati
disponibili, e un glossario dei termini agronomici.

**Status report** (`docs/fitosim_status_report.docx`): il riassunto
quantitativo dello stato di sviluppo, con metriche, roadmap e storico delle
consegne. Aggiornato ad ogni chiusura di tappa.

**Demo end-to-end della tappa 4** (`examples/tappa4_complete_demo.py`):
script Python eseguibile che mostra in azione tutte le capacità della tappa
4 su uno scenario realistico di tre vasi di basilico monitorati per 21
giorni, con output didattico tra blocchi di giorni.

**Demo end-to-end della tappa 5** (`examples/tappa5_E_appartamento_demo.py`):
script che simula un appartamento invernale con tre vasi indoor sparsi tra
salotto e camera da letto, mostra in azione la selezione automatica del
metodo di evapotraspirazione (`compute_et`), la persistenza delle Room nel
database SQLite, e produce quattro grafici PNG di analisi dell'andamento
idrico. Le sotto-tappe A, B e C hanno demo pedagogiche dedicate
(`tappa5_A_penman_monteith_demo.py`, `tappa5_B_selettore_demo.py`,
`tappa5_C_garden_demo.py`) che articolano un pezzo per volta del
raffinamento scientifico.

Tutte le demo girano in pochi secondi senza hardware reale grazie agli
adapter di sensori CSV-fixture.

**Diagrammi UML** (`docs/uml/`): due diagrammi (package e classi del
dominio) come sorgenti DOT versionati e PNG renderizzati. Si rigenerano
con `dot -Tpng <file>.dot -o <file>.png`.

## Licenza

fitosim è distribuito sotto **MIT License**. Vedi il file `LICENSE` per il
testo completo.

```
Copyright (c) 2026 Andrea Ceriani

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction [...]
```

La licenza MIT è permissiva: chiunque può usare, modificare e ridistribuire
il software, anche per scopi commerciali, a condizione di mantenere il
copyright notice originale. Il software è fornito "as is" senza garanzie.

## Autore

Andrea Ceriani — fitosim nasce come progetto personale per modellare con
precisione il bilancio idrico e chimico dei vasi del mio balcone milanese,
con l'obiettivo di costruirci sopra il dashboard "Il Mio Giardino"
self-hosted su Raspberry Pi 5 o Android in Termux. Quando il sistema avrà
raccolto qualche mese di dati reali dai sensori del balcone, comincerà la
fascia 3 di calibrazione che trasformerà fitosim da "libreria genericamente
plausibile" a "libreria calibrata per il TUO balcone milanese".
