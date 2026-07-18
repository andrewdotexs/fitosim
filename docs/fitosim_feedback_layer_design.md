# Design: layer di feedback e calibrazione

**Data:** 2026-06-01
**Status:** Decisione di design registrata, NON implementata. La **fase A** è candidata alla fascia 3 di fitosim; la **fase B** è successiva. La fertirrigazione (fase C) è esplicitamente rimandata.
**Scope:** attraversa fitosim (matematica di calibrazione) e The Pot (raccolta evidenze, store gerarchico, privacy).

## In una frase

Generalizzare la calibrazione di fitosim da "un sensore che corregge il substrato" a un **layer di feedback multi-sorgente**, in cui evidenze eterogenee (lisimetro, sensori, diario utente, fenologia, comportamento) vengono normalizzate, **attribuite a una causa**, aggregate gerarchicamente (vaso → cluster → globale) e trasformate in correzioni di parametro tracciabili e reversibili.

## Il problema: perché un feedback layer ingenuo peggiora il modello

L'esempio che ha originato la discussione: *"irrigo ogni 2 giorni, l'utente segnala ingiallimento delle foglie → ritaro per irrigazioni più frequenti"*.

Questa inferenza **può essere esattamente al contrario**. L'ingiallimento da substrato costantemente bagnato (asfissia radicale, marciume) è una delle cause più comuni di foglie gialle in vaso, e la correzione giusta è irrigare **meno**. Lo stesso sintomo mappa su cause opposte.

Ne segue il principio fondativo del layer:

> Il valore non è **raccogliere** i feedback, è **disambiguarli**. Un feedback layer senza stadio di attribuzione non calibra il modello: lo fa divergere nella direzione sbagliata circa la metà delle volte.

La disambiguazione usa il contesto che il sistema già possiede — in particolare **lo stato che il modello prevedeva nei giorni precedenti al sintomo**. Se il modello dice che il vaso era zuppo → ingiallimento da eccesso; se lo dava asciutto → ingiallimento da carenza. Stesso sintomo, correzione opposta, decisa dal contesto.

## Il modello concettuale: tre stadi

Il layer rispecchia l'architettura del sensor layer (ingest → canonico → route → resolve):

| Stadio | Cosa fa | Analogo nel sensor layer |
|---|---|---|
| **1. Osservazione** | Registra il segnale grezzo, tipizzato, con vocabolario controllato | `Measurement` |
| **2. Attribuzione** | Mappa sintomo → causa probabile usando il contesto | resolution multi-sensore |
| **3. Correzione** | Emette un delta su un parametro, con scope, confidenza, provenienza, reversibilità | override di calibrazione |

```
FONTI          →   OSSERVAZIONE   →   ATTRIBUZIONE      →   AGGREGAZIONE          →   CORREZIONE
(eterogenee)       (canonica)          (usa il contesto)     (gerarchica)              (scoped, reversibile)

lisimetro ─┐                          ┌ stato modello                                        │
sensore    ─┤                         ┤ (finestra passata!)   globale (FAO-56/catalogo)      ▼
diario     ─┤──→  FeedbackEvent  ──→  ┤ meteo                 ↑ solo con consenso          fitosim
foto/CV    ─┤                         ┤ altri sintomi         clima × sim_group            (override
fenologia  ─┤                         ┤ stadio fenologico     ↑                             locali)
override   ─┘                         └ sensore se presente   questo vaso ←── il default
```

Nota critica sullo stadio 2: **la latenza**. Un sintomo osservato oggi riflette uno stress di giorni fa. L'attribuzione deve correlare con la **traiettoria di stato del modello nella finestra precedente**, non con lo stato istantaneo al momento della registrazione.

## Le fonti di feedback

| Fonte | Cosa misura | Affidabilità | Latenza | Ambiguità | Cosa calibra | Fase |
|---|---|---|---|---|---|---|
| **Lisimetro** (pesata) | ET reale (grammi) | Ground truth | Nessuna | Nessuna | Kc, θ_FC/PWP | A |
| **Sensore — ancora** | θ ai picchi/valli | Alta | Nessuna | Bassa | θ_FC, θ_PWP | A (già fatto) |
| **Sensore — pendenza** | Velocità di asciugamento | Alta | Nessuna | Bassa | **Kc / Kcb** | **A (manca!)** |
| **Fenologia** (milestone datati) | Data di fioritura/fruttificazione | Alta | Nessuna | Bassa | stadi / soglie GDD | A |
| **Comportamentale** (override eventi) | Scostamento sistematico | Media-alta | Bassa | Bassa | Kc del vaso, intervalli | A |
| **Dismissal negativo** | "L'allerta era sbagliata" | Media | Bassa | Bassa | soglia `p` | A |
| **Diario — sintomi** | Ingiallimento, appassimento | Bassa | Alta | **Alta** | Kc, p (post-attribuzione) | B |
| **Foto / CV** | Sintomi estratti da immagine | Media | Alta | Alta | come i sintomi | B |
| **Esito / mortalità** | Pianta morta o prosperata | Alta | Altissima | Media | validazione, non tuning | B |
| **Esperto / curato** | Correzioni del team | Altissima | — | Nessuna | promozione a catalogo | A |

### Sensori: due segnali distinti, non uno

Questa è la precisazione più importante emersa dalla discussione.

**Segnale A — l'ancora.** Dopo un'irrigazione abbondante con drenaggio, il vaso *è* a capacità di campo per definizione fisica: qualunque cosa legga il sensore in quel momento **è** la lettura di FC per quel vaso. Idem le valli per il basso della scala. Calibra **θ_FC e θ_PWP**.

Nota: la lettura del WH51 (es. 65%) **non è** θ volumetrico, è un indice capacitivo dipendente dal substrato. L'ancora serve esattamente a imparare la mappatura sensore→modello per quel vaso.

Stato: **già implementato** in `science/calibration.py` (`find_peaks`/`find_valleys`, `estimate_theta_fc` al 75° percentile, `estimate_theta_pwp` al 10° percentile).

**Segnale B — la pendenza.** Tra due irrigazioni, la *velocità* di discesa della curva è il consumo reale. Modello a −4 mm/giorno contro sensore a −6 mm/giorno significa **Kc sottostimato del 50%** per quel vaso. Calibra il **consumo (Kc/Kcb)**.

Stato: **NON implementato**. È il buco più rilevante: l'ancora dice quanto è grande il serbatoio, la pendenza dice quanto in fretta si svuota — ed è la seconda a determinare *quando irrigare*. Priorità massima della fase A.

### Lisimetro: 11 sim_group, non 7

I sim_group del catalogo The Pot sono **undici**:

`aromatica` · `mediterranea` · `tropicale` · `succulenta` · `orchidea` · `agrume` · `fiorita` · `bonsai` · `arbusto` · `albero` · `conifera`

Coprirli tutti con vasi strumentati a pesata è un impegno grosso. Prioritizzazione su due criteri incrociati:
1. **Rappresentatività** — quanti vasi reali degli utenti cadono nel gruppo (`aromatica`, `fiorita`, `tropicale` coprono probabilmente la maggioranza domestica).
2. **Distanza dal prior FAO-56** — quanto il gruppo è anomalo rispetto al modello standard (`bonsai` e `orchidea` usano substrati non-suolo e regimi particolari: sono quelli dove **un singolo lisimetro insegna di più**).

Raccomandazione: partire con 4-5 gruppi scelti incrociando i due criteri, non con tutti e 11.

### Diario: due classi di segnale da non confondere

Arrivano dalla stessa interfaccia ma hanno qualità opposta:

| | Milestone fenologici | Sintomi |
|---|---|---|
| Esempi | fioritura, fruttificazione, germogliamento, raccolta | ingiallimento, appassimento, caduta foglie |
| Natura | **evento datato** | **giudizio soggettivo** |
| Ambiguità | bassa ("ha fiorito" è un fatto) | alta (una causa tra molte) |
| Richiede attribuzione | **no** | **sì** |
| Calibra | stadi / soglie GDD → Kc | Kc, p (solo dopo disambiguazione) |
| Fase | A | B |

### Fenologia: un mismatch strutturale da sanare

The Pot ha **già** un modello fenologico: `DEFAULT_PHENOLOGY_BY_GROUP` in `catalog.py` del prototipo — mappa **mese → stadi attivi** per sim_group, vocabolario controllato a 6 stadi (`dormienza`, `riposo`, `germogliamento`, `vegetativo`, `fioritura`, `fruttificazione`), con stadi anche simultanei (gli agrumi a maggio sono in vegetazione *e* fioritura). Il commento nel codice dichiara che sono *"approssimazioni botaniche tipiche del clima mediterraneo (latitudine Italia centro-nord)"*.

Ma fitosim ha un modello fenologico **diverso e incompatibile**:

| | fitosim | The Pot |
|---|---|---|
| Stadi | 3 (`INITIAL` / `MID_SEASON` / `LATE_SEASON`) | 6 botanici |
| Guidati da | giorni dalla semina (`initial_stage_days`, `mid_stage_days`, fissi) | mese del calendario |
| Esclusivi | sì, sequenziali | no, simultanei |
| A cosa servono | determinano **Kc** → domanda idrica | consigli di cura (irrigazione, concime, ritiro) |

**Perché conta più di quanto sembri.** Per il basilico la transizione INITIAL→MID porta Kc da **0.50 a 1.05**: raddoppia la domanda idrica stimata. Sbagliare di due settimane quella transizione produce un errore idrico molto maggiore di qualunque raffinamento sui coefficienti. La fenologia è **a monte** del bilancio idrico.

**Cosa fa il feedback fenologico.** L'utente registra "prima fioritura" con una data (è un'osservazione del diario, non una fonte separata). Quella data, incrociata con la data di semina/rinvaso e con lo storico meteo, permette di calibrare **quando avviene realmente la transizione di stadio in quel clima**. Aggregando sul cluster si corregge la tabella per zona climatica — che oggi, essendo hardcoded su un solo clima, **è già sbagliata** per il sud Italia o l'alta quota.

**L'upgrade agronomico corretto: gradi-giorno (GDD).** Lo sviluppo fenologico è guidato dalla temperatura accumulata sopra una soglia base, non dal calendario:

```
GDD = Σ max(0, T_media_giornaliera − T_base)
```

Sostituire "20 giorni allo stadio MID" con "X gradi-giorno, T_base per gruppo" rende la fenologia **trasferibile tra climi** invece che ancorata all'Italia centro-nord. Con le date di fioritura degli utenti + lo storico meteo si calcolano i GDD effettivamente accumulati e si tara la soglia per sim_group × zona climatica.

## L'aggregazione gerarchica

### Il per-vaso non si butta: è il north star

Durante la discussione era emersa l'ipotesi di aggregare *invece* di calibrare per utente. **Va respinta**: il README dichiara come obiettivo della fascia 3 *"trasformare fitosim da libreria genericamente plausibile a libreria calibrata per il TUO balcone milanese"*. La calibrazione locale è l'obiettivo, non un ripiego.

L'aggregazione multi-utente è un'**aggiunta** che risolve il *cold start*: un utente nuovo eredita il sapere del suo cluster invece del prior generico.

### I tre livelli, con velocità diverse

| Livello | Velocità | Chi ne beneficia | Rischio | Protezione |
|---|---|---|---|---|
| **Questo vaso** | Veloce (poche osservazioni) | Solo il proprietario | Nullo | Override locale, reversibile |
| **Clima × sim_group** | Lenta (serve consenso) | Utenti dello stesso cluster | Medio | Soglia minima di N, mediane |
| **Prior globale / catalogo** | Lentissima | Tutti | Alto | Rigetto outlier, revisione umana |

Un singolo feedback muove **soprattutto il vaso**, contribuisce **debolmente** al cluster, e **quasi nulla** al prior globale. Solo un consenso ampio e concorde nel cluster sposta i livelli superiori. È coerente col principio già fissato nella vision di The Pot: *"override locali al workspace, mai globali; modello globale protetto"*.

### Le chiavi di clustering (raffinate)

Rispetto alla formulazione iniziale (geo, meteo, sim_group, tipo pianta):

- **Geo → zona climatica**, non lat/lon grezze. Bucket (padano / mediterraneo / alpino, o Köppen). Due balconi a 5 km sono lo stesso cluster.
- **Meteo → traiettoria sulla finestra di stress**, non l'istante dell'evento. Vedi la nota sulla latenza: il sintomo di oggi riflette lo stress di giorni fa.
- **sim_group** — la chiave biologica primaria (11 valori).
- **Aggiungere al fingerprint**: substrato, materiale/colore/esposizione del vaso, indoor/outdoor, **stadio fenologico al momento dell'osservazione** (un ingiallimento in fase iniziale ≠ in senescenza).

Due feedback sono confrontabili se i loro fingerprint coincidono.

## Cosa si può calibrare (routing feedback → parametro)

| Parametro | Dove vive | Fonti che lo calibrano | Fase |
|---|---|---|---|
| `theta_fc`, `theta_pwp` | `science/substrate.py` | sensore (ancora), lisimetro | A (fatto) |
| **`kc_*` / `kcb_*`** | `domain/species.py` | **sensore (pendenza)**, lisimetro, comportamentale | **A** |
| `initial_stage_days`, `mid_stage_days` → soglie GDD | `domain/species.py` | **fenologia** | **A** |
| `depletion_fraction` (p) | `domain/species.py` | dismissal, comportamentale | A |
| `DEFAULT_PHENOLOGY_BY_GROUP` | The Pot `catalog.py` | fenologia (cluster) | A |
| `WATER_INTERVAL_DEFAULT_BY_GROUP` | The Pot `catalog.py` | comportamentale (vasi non sensorizzati) | A |
| Fattori `Kp` (materiale/colore/esposizione) | `science/pot_physics.py` | cluster (confronto fingerprint diversi) | B |
| `shelter_wind_factor` | `science/pot_physics.py` | cluster | B |
| Frazioni radiazione indoor | `science/indoor.py` | cluster indoor | B |
| Curva `root_fraction` | (fascia 3, vedi design doc dedicato) | fenologia, post-rinvaso, sensore | B |
| `ec_optimal_*`, `ph_optimal_*` | `domain/species.py` | fertirrigazione | **C** |

## I rischi (perché il layer va progettato, non improvvisato)

1. **Attribuzione ambigua** — il problema centrale. Senza lo stadio 2 si amplifica rumore. Mitigazione: fase A usa solo fonti non ambigue.
2. **Loop di conferma** — se il modello suggerisce e l'utente obbedisce, l'esito **non è evidenza indipendente**: il modello ha influenzato l'azione. Vanno distinti feedback *osservazionali* da *interventionali*.
3. **Bias di selezione** — chi segnala non è un campione casuale (utenti ingaggiati, o con problemi, sovra-riportano). Il cluster impara da una popolazione distorta.
4. **Contaminazione del prior globale** — un singolo utente non deve muovere il catalogo. Aggregazione robusta: mediane, rigetto outlier, soglia minima di osservazioni concordi.
5. **Reversibilità e trasparenza** — ogni delta deve essere spiegabile (*"ho alzato il Kc dell'8% perché hai anticipato l'irrigazione 12 volte"*) e annullabile.
6. **Privacy** — l'apprendimento di cluster aggrega posizione e abitudini. Anonimizzazione e aggregazione obbligatorie: il giardino di uno non deve trapelare a un altro.

## Architettura: dove vive cosa

Simmetrica al sensor layer.

**fitosim** — la *matematica di calibrazione*, come funzioni pure:
- Estensione di `science/calibration.py`: oltre all'ancora (già presente), la **stima di Kc dalla pendenza** e la **stima delle soglie di stadio/GDD dai milestone**.
- Input: serie di osservazioni + contesto. Output: delta di parametro con confidenza. Zero dipendenze, testabile in isolamento.

**The Pot** — il *control plane*:
- Raccolta evidenze (diario, foto, override di calendario, milestone).
- Store gerarchico (per-vaso / cluster / globale) con fingerprint.
- Aggregazione robusta, privacy, anonimizzazione.
- UI di trasparenza e reversibilità degli override.

**Condiviso**: il **vocabolario controllato delle osservazioni** (come il vocabolario dei parametri nella spec sensori). Enum tipizzato, non testo libero — o testo libero più classificatore che mappa sul vocabolario.

## Decisioni prese (le tre forcelle)

**1. Attribution engine: rimandato. Si parte dalle fonti non ambigue.**
Le due fonti quantitative e non ambigue già disponibili (pendenza del sensore → Kc; fenologia → transizione di stadio) toccano i parametri che pesano di più sul bilancio idrico e non richiedono alcun motore di attribuzione. I sintomi ambigui sono il 20% del valore e l'80% della difficoltà.
→ **Fase A senza attribuzione** (pendenza, fenologia, comportamentale, dismissal, lisimetro); **fase B** per sintomi e foto.

**2. Apprendimento globale: conservativo di default, con un'eccezione mirata.**
Il prior globale va protetto. **Eccezione**: `DEFAULT_PHENOLOGY_BY_GROUP` è dichiaratamente un'approssimazione per un solo clima, quindi per gli altri climi non è "da proteggere" — è già sbagliato. Lì l'apprendimento di cluster ha valore alto e rischio basso.
→ **Conservativo, tranne dove il prior è dichiaratamente un'approssimazione.**

**3. Matematica in fitosim, evidenze e aggregazione in The Pot.**
Coerente col principio "lo stato dinamico e il calcolo vivono in fitosim". `calibration.py` esiste già ed è la collocazione naturale.

## Roadmap

**Fase A — fonti non ambigue** (fascia 3 di fitosim)
1. **Pendenza sensore → Kc** — il buco più rilevante, priorità massima.
2. **Fenologia → stadi/GDD** — sanare il mismatch fitosim/The Pot, passare a gradi-giorno.
3. **Comportamentale** — formalizzare la calibrazione passiva già descritta nella vision.
4. **Dismissal negativo** → soglia `p`.
5. **Lisimetro** → ground truth per 4-5 sim_group prioritari.
6. **Gerarchia di aggregazione** + store + trasparenza/reversibilità.

**Fase B — sintomi e attribuzione**
7. Motore di attribuzione (sintomo → causa via contesto e traiettoria passata).
8. Diario sintomi, foto/CV, esito/mortalità.
9. Calibrazione di Kp, shelter, radiazione indoor, curva `root_fraction`.

**Fase C — fertirrigazione** (rimandata)

## Fertirrigazione: perché è rimandata

È il caso peggiore su tutte e tre le dimensioni:
- **Osservabilità**: l'EC richiede un WH52 (pochi lo hanno), il pH quasi nessuno.
- **Ambiguità**: l'ingiallimento nutrizionale si confonde con carenza di azoto, clorosi ferrica, eccesso salino — e con i sintomi idrici già ambigui di loro.
- **Latenza**: gli effetti nutrizionali si manifestano in settimane.

In più il comportamento reale degli utenti è molto variabile e spesso sbagliato (la sovra-concimazione è la norma). Merita un passaggio dedicato **dopo** che il layer idrico funziona.

## Punti aperti

1. **Forma della stima di Kc dalla pendenza** — regressione sulla finestra tra irrigazioni? Robustezza al rumore del sensore, ai giorni di pioggia, agli eventi di irrigazione non registrati.
2. **T_base per sim_group** — i valori delle soglie GDD vanno tarati; esistono riferimenti di letteratura per le colture orticole, meno per ornamentali e bonsai.
3. **Mappatura tra i due vocabolari fenologici** — quale stadio botanico di The Pot corrisponde alla transizione INITIAL→MID di fitosim? Probabilmente `fioritura` per molte specie, ma non per tutte (le aromatiche da foglia si raccolgono prima).
4. **Definizione delle zone climatiche** — Köppen, o bucket italiani semplificati? Impatta la granularità dei cluster.
5. **Soglie di consenso** — quanti feedback concordi servono per muovere il livello cluster? E il globale?
6. **Distinzione osservazionale/interventionale** — come marcare tecnicamente i feedback influenzati da un suggerimento del modello.

## Riferimenti

- Calibrazione attuale (ancora): `src/fitosim/science/calibration.py`
- Fenologia fitosim: `src/fitosim/domain/species.py` (`PhenologicalStage`, `initial_stage_days`, `mid_stage_days`)
- Fenologia The Pot: `catalog.py` del prototipo (`DEFAULT_PHENOLOGY_BY_GROUP`, `POST_RINVASO_DEFAULT_BY_GROUP`, `WATER_INTERVAL_DEFAULT_BY_GROUP`)
- Calibrazione passiva già prevista: `the-pot/docs/the_pot_vision.md` cap. 5, "L'autoapprendimento di fitosim"
- Modello del pane radicale (fonte di feedback in fase B): `docs/fitosim_root_modeling_design.md`
- Template architetturale (evidenze canoniche): `the-pot/docs/the_pot_sensors_spec.md`
- Manuale di calibrazione: `docs/fitosim_calibration_manual.md`
