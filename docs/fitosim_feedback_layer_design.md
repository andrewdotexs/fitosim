# Design: layer di feedback e calibrazione

**Data:** 2026-06-01 · **Ultimo aggiornamento:** 2026-07-21
**Status:** **La fase A è implementata in fitosim** (v0_21 → v0_29): tutte e cinque le fonti non ambigue producono correzioni di parametro. Resta da fare il punto 6 della roadmap — gerarchia di aggregazione, store, trasparenza — che è **lavoro di The Pot, non di fitosim**. La fase B è successiva; la fertirrigazione (fase C) è esplicitamente rimandata.
**Scope:** attraversa fitosim (matematica di calibrazione) e The Pot (raccolta evidenze, store gerarchico, privacy).

> **Come leggere questo documento.** Le sezioni di analisi (il problema, i tre stadi, i rischi, il clustering) descrivono il disegno e restano valide. Le sezioni di stato riportano cosa è stato costruito e **cosa si è imparato costruendolo**: dove l'implementazione ha corretto il design, è segnalato esplicitamente. Le decisioni prese in corso d'opera sono raccolte in *Cosa ha insegnato l'implementazione*.

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

| Fonte | Cosa misura | Affidabilità | Latenza | Ambiguità | Cosa calibra | Fase | Stato |
|---|---|---|---|---|---|---|---|
| **Lisimetro** (pesata) | ET reale (grammi) | Ground truth | Nessuna | Nessuna | Kc | A | ✅ `science/lysimeter.py` |
| **Sensore — ancora** | θ ai picchi/valli | Alta | Nessuna | Bassa | θ_FC, θ_PWP | A | ✅ `science/calibration.py` |
| **Sensore — pendenza** | Velocità di asciugamento | Alta | Nessuna | Bassa | **Kc / Kcb** | A | ✅ `science/calibration.py` |
| **Fenologia** (milestone datati) | Data di fioritura/fruttificazione | Alta | Nessuna | Bassa | stadi / soglie GDD | A | ✅ `science/phenology.py` |
| **Comportamentale** (override eventi) | Scostamento sistematico | Media-alta | Bassa | Bassa | Kc del vaso, intervalli | A | ✅ `science/behavioral_calibration.py` |
| **Dismissal negativo** | "L'allerta era sbagliata" | Media | Bassa | Bassa | soglia `p` | A | ✅ `science/behavioral_calibration.py` |
| **Diario — sintomi** | Ingiallimento, appassimento | Bassa | Alta | **Alta** | Kc, p (post-attribuzione) | B | ⬜ |
| **Foto / CV** | Sintomi estratti da immagine | Media | Alta | Alta | come i sintomi | B | ⬜ |
| **Esito / mortalità** | Pianta morta o prosperata | Alta | Altissima | Media | validazione, non tuning | B | ⬜ |
| **Esperto / curato** | Correzioni del team | Altissima | — | Nessuna | promozione a catalogo | A | ⬜ (The Pot) |

Correzione al design originale: la riga del lisimetro prometteva anche **θ_FC/PWP**. La pesata da sola non li dà — servirebbe la massa a secco dell'intero sistema, che non si conosce senza una misura distruttiva. Il lisimetro calibra **Kc**; gli estremi della scala restano compito dell'ancora del sensore.

### Sensori: due segnali distinti, non uno

Questa è la precisazione più importante emersa dalla discussione.

**Segnale A — l'ancora.** Dopo un'irrigazione abbondante con drenaggio, il vaso *è* a capacità di campo per definizione fisica: qualunque cosa legga il sensore in quel momento **è** la lettura di FC per quel vaso. Idem le valli per il basso della scala. Calibra **θ_FC e θ_PWP**.

Nota: la lettura del WH51 (es. 65%) **non è** θ volumetrico, è un indice capacitivo dipendente dal substrato. L'ancora serve esattamente a imparare la mappatura sensore→modello per quel vaso.

Stato: **già implementato** in `science/calibration.py` (`find_peaks`/`find_valleys`, `estimate_theta_fc` al 75° percentile, `estimate_theta_pwp` al 10° percentile).

**Segnale B — la pendenza.** Tra due irrigazioni, la *velocità* di discesa della curva è il consumo reale. Modello a −4 mm/giorno contro sensore a −6 mm/giorno significa **Kc sottostimato del 50%** per quel vaso. Calibra il **consumo (Kc/Kcb)**.

Stato: **implementato** (v0_21) in `science/calibration.py`. L'inversione del bilancio è

```
Kc = Σ(deplezione_mm) / (Kp · Σ(Ks_i · ET₀_i))
```

Il punto che ha deciso la forma della stima — ed è la risposta al punto aperto n. 1 del design originale — è che **Ks si legge dalla θ osservata, non si stima**. Il sensore dice a che livello idrico si trovava il vaso ogni giorno, quindi lo stress è un dato, non un'incognita: senza questo, una finestra che finisce in stress restituirebbe un Kc sistematicamente sottostimato, perché attribuirebbe alla pianta un consumo ridotto che era invece un freno idrico.

Non è una regressione: `find_drying_windows()` isola le finestre di asciugamento tollerando le micro-risalite da rumore ma **spezzando** su quelle vere, e l'aggregazione tra finestre è a **mediana** — un'irrigazione non registrata rovina una finestra, non la stima.

### Lisimetro: 11 sim_group, non 7

I sim_group del catalogo The Pot sono **undici**:

`aromatica` · `mediterranea` · `tropicale` · `succulenta` · `orchidea` · `agrume` · `fiorita` · `bonsai` · `arbusto` · `albero` · `conifera`

Coprirli tutti con vasi strumentati a pesata è un impegno grosso. Prioritizzazione su due criteri incrociati:
1. **Rappresentatività** — quanti vasi reali degli utenti cadono nel gruppo (`aromatica`, `fiorita`, `tropicale` coprono probabilmente la maggioranza domestica).
2. **Distanza dal prior FAO-56** — quanto il gruppo è anomalo rispetto al modello standard (`bonsai` e `orchidea` usano substrati non-suolo e regimi particolari: sono quelli dove **un singolo lisimetro insegna di più**).

Raccomandazione: partire con 4-5 gruppi scelti incrociando i due criteri, non con tutti e 11.

Stato: **matematica implementata** (v0_29) in `science/lysimeter.py`. Il bilancio di massa è

```
ET = (massa_iniziale − massa_finale) + acqua_aggiunta − drenaggio
```

in grammi, convertito in millimetri dividendo per la superficie del vaso (i millimetri di FAO-56 sono un'altezza d'acqua: la stessa massa su un vaso stretto fa una colonna più alta). L'inversione è `Kc = ET / (Ks · Kp · Kn · ET₀)`.

**Il vincolo di protocollo, emerso implementando.** Kc è *definito* in condizioni idriche non limitanti. Chi pesa un vaso in stress non misura Kc: misura il prodotto Ks·Kc, e da una sola pesata i due non si separano. Quindi il protocollo lisimetrico tiene il vaso nella **zona di comfort**, e in quel regime Ks vale 1 per definizione — non è una limitazione dello strumento, è la definizione della grandezza che si vuole misurare. Chi ha ragioni per credere il contrario lo dichiara sull'intervallo, sapendo cosa sta stimando.

**Cosa falsa la pesata.** La massa del sistema cambia anche per ragioni che non sono acqua evaporata, e il protocollo deve escluderle a monte: potature e raccolta (sulla bilancia sono indistinguibili da ET — quegli intervalli vanno **esclusi, non corretti**), pioggia non contabilizzata sui vasi all'aperto, accumulo di biomassa (trascurabile su un giorno, sottostima sistematica su intervalli lunghi), concime solido. Mediana e limiti di plausibilità assorbono l'errore occasionale, mai il vizio sistematico del protocollo.

A differenza delle altre fonti, che correggono il **singolo vaso**, il lisimetro è pensato per misurare il **parametro di catalogo**: un vaso strumentato per sim_group in condizioni controllate.

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

### Fenologia: un mismatch strutturale, sanato

> **Stato: risolto** (v0_22 → v0_26). La descrizione del mismatch qui sotto è quella originale e va letta al passato; la risoluzione è in coda alla sezione.

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

#### Come è stato risolto

**Decisione: sei stadi per entrambi.** I 3 stadi FAO-56 non sono stati estesi né i 6 botanici compressi: fitosim ha adottato il vocabolario a 6 stadi di The Pot (`GrowthStage`, valori identici a quelli del catalogo) e li **traduce** verso FAO-56 solo dove serve, cioè per scegliere il Kc. La traduzione è un unico punto — `fao56_stage_from_growth_stages()` in `domain/species.py` — invece di una corrispondenza sparsa nel codice. I 6 stadi sono osservabili e condivisi con l'utente; i 3 restano un dettaglio interno del calcolo.

**Due ancoraggi, non uno.** Il design originale dava per scontato che la fenologia si ancorasse alla data di impianto. Vale per le annuali, ma applicata alle perenni le lasciava **bloccate in `LATE_SEASON` per sempre** — un rosmarino piantato tre anni fa era permanentemente in fine stagione. Da qui `PhenologyAnchor`: le **annuali** si ancorano all'impianto (e possono usare i GDD), le **perenni** al calendario stagionale, che si ripete ogni anno.

**I GDD valgono solo per le annuali.** Non è una scorciatoia implementativa: lo sviluppo delle perenni è governato anche dal fabbisogno di freddo (chill units, modello Utah), e sommare gradi-giorno a una pianta che deve prima *accumulare freddo* per uscire dalla dormienza dà la risposta sbagliata. `science/phenology.py` documenta il confine. La formula usata è la media semplice modificata, con T_min portata a T_base: una notte a 2 °C non manda la pianta all'indietro.

**Selettore "best available".** `Species.stage_at()` segue lo stesso schema già usato per ET₀: gradi-giorno se la specie ha le soglie **e** il vaso li sta tracciando, altrimenti calendario stagionale per le perenni, altrimenti giorni dall'impianto. Il degrado è silenzioso e sicuro: `gdd_accumulated = None` significa "non sto tracciando" ed è distinto da `0.0`, che significa "traccio da adesso".

**Dormienza con pavimento di evaporazione.** Ridurre il Kc in dormienza è corretto, ma non può portarlo a zero: il substrato nudo evapora comunque. Un modello che dicesse "pianta dormiente, consumo nullo" non suggerirebbe mai di annaffiare, e d'inverno le piante in vaso muoiono anche di secco. Da cui `KC_BARE_SOIL_FLOOR`. Il pavimento si applica a `effective_kc()` ma **non** a `effective_kcb()`, perché nel dual-Kc l'evaporazione è già contabilizzata da Ke e sommarla due volte sarebbe un errore.

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

| Parametro | Dove vive | Fonti che lo calibrano | Fase | Stato |
|---|---|---|---|---|
| `theta_fc`, `theta_pwp` | `science/substrate.py` | sensore (ancora) | A | ✅ |
| **`kc_*` / `kcb_*`** | `domain/species.py` | sensore (pendenza), lisimetro, comportamentale | A | ✅ |
| `initial_stage_days`, `mid_stage_days` → soglie GDD | `domain/species.py` | fenologia | A | ✅ |
| `depletion_fraction` (p) | `domain/species.py` | dismissal, comportamentale | A | ✅ |
| `DEFAULT_PHENOLOGY_BY_GROUP` | The Pot `catalog.py` | fenologia (cluster) | A | ⬜ The Pot |
| `WATER_INTERVAL_DEFAULT_BY_GROUP` | The Pot `catalog.py` | comportamentale (vasi non sensorizzati) | A | ⬜ The Pot |
| Fattori `Kp` (materiale/colore/esposizione) | `science/pot_physics.py` | cluster (confronto fingerprint diversi) | B | ⬜ |
| `shelter_wind_factor` | `science/pot_physics.py` | cluster | B | ⬜ |
| Frazioni radiazione indoor | `science/indoor.py` | cluster indoor | B | ⬜ |
| Curva `root_fraction` | (fascia 3, vedi design doc dedicato) | fenologia, post-rinvaso, sensore | B | ⬜ |
| `ec_optimal_*`, `ph_optimal_*` | `domain/species.py` | fertirrigazione | **C** | ⬜ |

**Tre fonti per `kc_*`, e non è ridondanza.** Le tre hanno costi e affidabilità molto diversi, e coprono popolazioni disgiunte di vasi: il lisimetro dà il valore di catalogo per il sim_group (pochi vasi strumentati, condizioni controllate); la pendenza del sensore corregge il singolo vaso di chi ha un sensore; il comportamentale corregge il vaso di chi **non** ha nulla, leggendo solo quando il giardiniere annaffia. Chi ha più fonti le usa in quest'ordine di precedenza.

**Perché `p` ha due fonti in fase A.** Lo scostamento delle irrigazioni, da solo, non distingue un Kc sbagliato da una soglia `p` sbagliata: entrambi producono *"irriga più tardi del previsto"*. Il dismissal interroga direttamente la soglia, perché chiede all'utente di giudicare **lo stato della pianta**, non il momento dell'irrigazione. Insieme separano le due cause che ciascuno da solo confonde.

## I rischi (perché il layer va progettato, non improvvisato)

1. **Attribuzione ambigua** — il problema centrale. Senza lo stadio 2 si amplifica rumore. Mitigazione: fase A usa solo fonti non ambigue.
2. **Loop di conferma** — se il modello suggerisce e l'utente obbedisce, l'esito **non è evidenza indipendente**: il modello ha influenzato l'azione. Vanno distinti feedback *osservazionali* da *interventionali*.
3. **Bias di selezione** — chi segnala non è un campione casuale (utenti ingaggiati, o con problemi, sovra-riportano). Il cluster impara da una popolazione distorta.
4. **Contaminazione del prior globale** — un singolo utente non deve muovere il catalogo. Aggregazione robusta: mediane, rigetto outlier, soglia minima di osservazioni concordi.
5. **Reversibilità e trasparenza** — ogni delta deve essere spiegabile (*"ho alzato il Kc dell'8% perché hai anticipato l'irrigazione 12 volte"*) e annullabile.
6. **Privacy** — l'apprendimento di cluster aggrega posizione e abitudini. Anonimizzazione e aggregazione obbligatorie: il giardino di uno non deve trapelare a un altro.

## Architettura: dove vive cosa

Simmetrica al sensor layer.

**fitosim** — la *matematica di calibrazione*, come funzioni pure. Realizzata così:

| Modulo | Fonte | Cosa produce |
|---|---|---|
| `science/calibration.py` | sensore: ancora + pendenza | θ_FC, θ_PWP, Kc |
| `science/phenology.py` | temperatura accumulata | GDD, stadio |
| `science/behavioral_calibration.py` | scostamento irrigazioni, giudizi sulle allerte | fattore su Kc, soglia `p` |
| `science/lysimeter.py` | pesata | ET misurata, Kc di catalogo |

Input: serie di osservazioni + contesto. Output: delta di parametro con confidenza. Zero dipendenze, testabile in isolamento.

**Un invariante rispettato ovunque: proporre, non applicare.** Nessuna di queste funzioni muta nulla. Restituiscono una *proposta* — valore, confidenza, spiegazione in italiano — e l'applicazione è un passo separato ed esplicito (`apply_kc_correction`, `apply_depletion_correction`) che lavora su una **copia** della specie. Il catalogo globale non si tocca mai, coerentemente col principio "override locali al workspace, mai globali".

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

**Fase A — fonti non ambigue** (fascia 3 di fitosim) — **chiusa per la parte fitosim**

| | Voce | Stato |
|---|---|---|
| 1 | **Pendenza sensore → Kc** | ✅ v0_21 |
| 2 | **Fenologia → stadi/GDD** (mismatch sanato, gradi-giorno, persistenza) | ✅ v0_22–v0_26 |
| 3 | **Comportamentale** → Kc | ✅ v0_27 |
| 4 | **Dismissal negativo** → soglia `p` | ✅ v0_28 |
| 5 | **Lisimetro** → ground truth per 4-5 sim_group prioritari | ✅ v0_29 (matematica) |
| 6 | **Gerarchia di aggregazione** + store + trasparenza/reversibilità | ⬜ **The Pot** |

Il punto 6 è l'unico rimasto della fase A, e non è lavoro di fitosim: la matematica c'è tutta, manca il control plane che raccoglie le evidenze, le aggrega per fingerprint e mostra all'utente cosa è stato cambiato e perché.

Il lisimetro ha la matematica pronta ma richiede anche la **parte fisica**: i vasi strumentati e il protocollo di pesata. Le due cose sono indipendenti e possono procedere in parallelo.

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

## Cosa ha insegnato l'implementazione

Quattro cose che il design non prevedeva e che vale la pena non ri-derivare male.

**1. Nel dual-Kc, ridurre il Kcb libera energia per l'evaporazione.** Passando un Kcb ridotto al calcolo di Ke, il limite energetico `Ke ≤ Kr·(Kc_max − Kcb)` si allarga e l'evaporazione dal substrato **aumenta**. È fisicamente corretto quando la chioma si è davvero diradata — meno foglie, più sole sul substrato — ed è sbagliato quando la chioma è invariata e il Kcb è stato ridotto per altri motivi (stress, dormienza di una sempreverde). L'errore è insidioso perché il risultato resta plausibile: il consumo totale cambia poco, ma la ripartizione tra traspirazione ed evaporazione è invertita. Da cui la regola: al limite energetico si passa sempre il **Kcb di chioma**, non quello corretto.

**2. Vincoli di verso opposto si delimitano, non si mediano.** Per la soglia `p`, un'allerta rifiutata dice *"la soglia vera sta più in là"* e una sofferenza segnalata dice *"sta più in qua"*. Sono due vincoli che **delimitano un intervallo**: mediarli insieme confonde due affermazioni di natura diversa. La stima è il punto di mezzo tra il 75° percentile delle osservazioni "sana" e il 25° delle "sofferente" — percentili e non estremi, così un singolo giudizio distratto non sposta la soglia. Con osservazioni di un solo verso ci si sposta del minimo difendibile: si sa da che parte sta la soglia, non quanto lontano.

**3. Il loop di conferma (rischio 2), applicato al segnale comportamentale.** Il segnale misura lo scostamento tra quando il modello suggerisce e quando l'utente irriga davvero — cioè esattamente un feedback *interventionale*, quello che il rischio 2 mette in guardia. L'analisi però è rassicurante in un verso e limitante nell'altro:

- Un utente che **obbedisce** produce rapporto 1 e quindi nessuna correzione. Il modello non impara da lui, ma non diverge nemmeno: il fallimento è "non apprende", non "apprende male".
- Un utente **ancorato** dal suggerimento (avrebbe irrigato al giorno 8, ma l'app insiste al 5, e lui cede al 6) produce uno scostamento **attenuato** rispetto a quello vero. La correzione risulta più piccola del dovuto.

In entrambi i casi l'errore è per **difetto**, mai per eccesso: il segnale converge lentamente verso il vero, non lo supera. È la direzione sicura, ed è la ragione per cui questa fonte è accettabile in fase A pur essendo interventionale. Resta valida la raccomandazione di marcare tecnicamente i feedback influenzati (punto aperto 5).

**4. Una calibrazione che non sopravvive a un reload non esiste.** Estendendo la persistenza è emerso che **16 campi della specie non venivano esportati** — quattro dei quali precedevano di molto questo lavoro. Il difetto era invisibile perché il round-trip *sembrava* funzionare: gli oggetti si ricostruivano, con i valori di default al posto di quelli calibrati. Per un layer di feedback è il modo peggiore di rompersi, perché la calibrazione svanisce senza errori. Regola operativa: ogni parametro che una fonte di feedback può correggere deve avere un test che ne verifica la sopravvivenza a scrittura e rilettura, sia su SQLite sia su JSON.

## Punti aperti

Chiusi rispetto alla stesura originale: la **forma della stima di Kc dalla pendenza** (finestre di asciugamento con Ks letto dalla θ osservata e mediana tra finestre, vedi sopra) e la **mappatura tra i due vocabolari fenologici** (`fao56_stage_from_growth_stages()`: non una corrispondenza uno-a-uno ma una traduzione in un punto solo).

1. **T_base e soglie GDD oltre le orticole** — i valori attuali per basilico, pomodoro e lattuga sono derivati dalle durate di stadio FAO-56 moltiplicate per il GDD/giorno di un clima di riferimento. È un punto di partenza difendibile, non una taratura: servono osservazioni reali. Per ornamentali e bonsai la letteratura è scarsa, ed è lì che il feedback fenologico degli utenti vale di più.
2. **Definizione delle zone climatiche** — Köppen, o bucket italiani semplificati? Impatta la granularità dei cluster.
3. **Soglie di consenso a livello cluster e globale** — quelle per-vaso sono fissate (3/5/10 per il sensore e il lisimetro, 5/10/15 per lo scostamento delle irrigazioni, 3/6/10 per i giudizi sulle allerte), ma sono soglie di **numerosità delle osservazioni di un utente**, non di **concordanza tra utenti diversi**. Il livello superiore è ancora tutto da definire.
4. **Chi vince quando due fonti si contraddicono** — se il lisimetro dice Kc 0.95 e la pendenza del sensore di quel vaso dice 1.20, non è per forza un conflitto: il primo è il valore di catalogo, il secondo è il *suo* vaso, che può legittimamente consumare di più. Serve una regola di precedenza esplicita, oggi implicita nell'ordine in cui il chiamante applica le correzioni.
5. **Distinzione osservazionale/interventionale** — come marcare tecnicamente i feedback influenzati da un suggerimento del modello (vedi lezione 3).

## Riferimenti

Moduli di calibrazione (fase A, tutti stdlib e senza effetti collaterali):

- Sensore, ancora e pendenza: `src/fitosim/science/calibration.py`
- Gradi-giorno: `src/fitosim/science/phenology.py`
- Comportamentale (scostamento irrigazioni, giudizi sulle allerte): `src/fitosim/science/behavioral_calibration.py`
- Lisimetro: `src/fitosim/science/lysimeter.py`

Altro:

- Fenologia fitosim: `src/fitosim/domain/species.py` (`GrowthStage`, `PhenologyAnchor`, `stage_at()`, `fao56_stage_from_growth_stages()`)
- Fenologia The Pot: `catalog.py` del prototipo (`DEFAULT_PHENOLOGY_BY_GROUP`, `POST_RINVASO_DEFAULT_BY_GROUP`, `WATER_INTERVAL_DEFAULT_BY_GROUP`)
- Calibrazione passiva già prevista: `the-pot/docs/the_pot_vision.md` cap. 5, "L'autoapprendimento di fitosim"
- Modello del pane radicale (fonte di feedback in fase B): `docs/fitosim_root_modeling_design.md`
- Template architetturale (evidenze canoniche): `the-pot/docs/the_pot_sensors_spec.md`
- Manuale di calibrazione: `docs/fitosim_calibration_manual.md`
