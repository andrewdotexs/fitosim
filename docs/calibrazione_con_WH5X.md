# Calibrazione con il sensore di substrato WH5X

**Data:** 2026-09-17
**Status:** Procedura operativa concordata, da eseguire. Prima calibrazione su hardware reale.
**Scope:** un vaso outdoor con un WH52, forzante meteo locale (WN32P + WS90), previsione da Open-Meteo. Calibra i 
livelli 2 e 3 del manuale di calibrazione: substrato (θ_FC, θ_PWP) e specie (Kc). Il livello 1, la funzione di 
trasferimento della sonda, e il livello 4, il modello chimico, restano fuori da questa prima passata.
**Hardware:** due gateway, perché i sensori Ecowitt si accoppiano a uno solo. GW3000A: WH52 (θ, temperatura ed EC del 
substrato). GW2000: WS90 (vento, radiazione solare, pioggia, temperatura, umidità, pressione), WN32P (temperatura e 
umidità dell'aria), più cinque WH51 preesistenti. Lo strumento legge la sonda dal primo e la forzante dal secondo 
(`weather_gateway`).

## In una frase

Ancorare la curva idrica del vaso all'irrigazione, prevedere sette giorni in avanti, **confrontare** ogni giorno la 
previsione con il sensore, e dopo abbastanza cicli lasciare che il confronto corregga i parametri del vaso. La 
calibrazione è un anello, non una simulazione una tantum.

## Cosa calibra, e cosa no

Il modello arriva con parametri di letteratura "ragionevoli", sbagliati anche del trenta per cento per un vaso 
specifico. Questa procedura ne corregge due, nell'ordine in cui vanno corretti:

| Livello | Parametro | Cosa governa | Da cosa si impara |
|---|---|---|---|
| 2, substrato | θ_FC, θ_PWP | la **dimensione** del serbatoio: TAW e RAW | i picchi e le valli della serie del sensore |
| 3, specie | Kc | la **velocità** di svuotamento | la pendenza della curva tra due irrigazioni |

L'ordine conta: se il serbatoio è stimato male, l'errore viene attribuito alla velocità, e il Kc viene calibrato a 
compensare un errore che non è suo. Prima l'ancora, poi la pendenza.

Restano fuori, per scelta:

- **Livello 1**, la funzione di trasferimento sonda → θ vera per pesata. Richiede la bilancia e il protocollo 
gravimetrico del manuale di calibrazione, capitolo 3. Si può aggiungere in seguito senza rifare nulla di questo.
- **Livello 4**, il modello chimico. Il WH52 misura l'EC, quindi il dato va **registrato fin da subito**, ma la 
calibrazione di Kn e del coefficiente di lavaggio richiede cicli di fertirrigazione e viene dopo.
- **Il lisimetro**, che è il ground truth del Kc. La parte matematica è in `science/lysimeter.py`, quella fisica è il 
progetto sorella `the-pot-lisimetro`, ancora in costruzione. Quando sarà operativo, la sua stima di Kc entrerà nella 
regola di precedenza allo scope di catalogo, sopra la pendenza del sensore.
- **La risoluzione sub-giornaliera**, per le ragioni dette più sotto.

## L'hardware e chi fornisce cosa

Con il WS90 la forzante **osservata** è interamente locale. Open-Meteo serve solo dove misure non ce ne sono: il futuro.

| Grandezza | Sorgente | Parametro canonico | Uso |
|---|---|---|---|
| θ del substrato | WH52 | `soil_theta` | l'osservazione da confrontare |
| temperatura, EC del substrato | WH52 | `soil_temperature_c`, `soil_ec_mscm` | registrati, non usati in questa passata |
| temperatura, umidità dell'aria | WN32P (o WS90) | `air_temperature_c`, `air_humidity` | ET₀ osservata |
| vento | WS90 | `wind_speed_m_s` | ET₀ osservata |
| radiazione solare | WS90 | `solar_radiation_mj_m2` | ET₀ osservata, Penman-Monteith |
| pioggia | WS90 | `rainfall_mm` | apporto idrico osservato, tramite `rainfall_exposure` |
| meteo a 7 giorni | Open-Meteo | `WeatherDayForecast` | ET₀ e pioggia **previste** |

Con temperatura, umidità, vento e radiazione tutti disponibili, il selettore "best available" userà **Penman-Monteith** 
per i giorni osservati: fisico se la specie ha resistenza stomatica e altezza colturale, altrimenti standard FAO-56. 
Hargreaves resta il fallback per i giorni in cui un sensore manca.

Due cautele sulla forzante locale:

- **Il vento va riferito a 2 m.** FAO-56 vuole la velocità a 2 metri; il WS90 la misura all'altezza a cui è montato. Se 
sta su un parapetto a circa un metro e mezzo la differenza è piccola; se sta più in alto va convertita con FAO-56 eq. 
47, `u₂ = u_z · 4.87 / ln(67.8·z − 5.42)`. Fitosim oggi **non ha un helper** per questa conversione: la docstring di 
`et0.py` la lascia al chiamante. Va fatta prima di costruire il `WeatherDay`.
- **La radiazione del WS90 vede il cielo della stazione, non l'ombra del vaso.** Se il vaso sta in ombra parziale per 
parte del giorno, riceve meno radiazione di quella misurata. È esattamente ciò che `sun_exposure` e la calibrazione del 
Kc assorbono, purché lo si sappia: un Kc calibrato più basso della letteratura su un vaso ombreggiato non è 
un'anomalia, è l'ombra.

## Le due calibrazioni da non confondere

La parola "taratura" copre due operazioni diverse, e la procedura funziona solo se restano distinte.

**La taratura dell'app Ecowitt** mappa il valore grezzo AD della sonda su uno 0-100% di comodo, fissando un punto 
"secco" e uno "bagnato". Va fatta, perché rende leggibile l'app. Ma per il modello è **cosmetica**: cambia la scala su 
cui il numero viene mostrato, non l'informazione che contiene.

**L'ancora di fitosim** impara **quale lettura del sensore corrisponde alla capacità di campo e quale al punto di 
appassimento**, e lo impara dalla serie storica. Il `soil_theta` che arriva dall'adapter è l'indice del produttore 
diviso cento, **non** la θ volumetrica vera: è un indice capacitivo che dipende dal substrato. Per questo il modello 
non può fidarsi della scala e deve ancorarsi ai due estremi osservati.

## I due punti dell'ancora, e perché non sono "bagnato" e "asciutto"

**Il punto alto è la capacità di campo dopo il drenaggio, non il picco durante l'annaffiatura.** Mentre si versa 
l'acqua il substrato è saturo: tutti i pori sono pieni. È uno stato transitorio che il vaso non trattiene, e nei 
trenta-sessanta minuti successivi l'acqua in eccesso esce dal foro. Quello che resta è la capacità di campo, ed è il 
vero "100%" del serbatoio disponibile. Ancorare il 100% al picco significa far partire ogni curva da una cima che non 
esiste, e leggere come "consumo" della prima ora un drenaggio.

**Il punto basso è il punto di appassimento, non il substrato secco all'aria.** Sotto θ_PWP la pianta non riesce più a 
estrarre acqua: quella zona per la pianta non esiste. Fissare lo 0% al secco all'aria include nel serbatoio una fascia 
morta, e la soglia di allerta scivola in basso, dove la pianta è già in sofferenza. E il PWP non si può osservare 
direttamente senza portare la pianta al collasso. Fitosim lo **deduce dalle valli**: ogni asciugamento prima di 
un'irrigazione tocca un minimo che è almeno un limite superiore del PWP, e il decimo percentile delle valli ne è la 
stima robusta.

Operativamente, quindi: il punto alto lo **produci** con un'irrigazione fino a drenaggio; il punto basso lo 
**lasci emergere** dalle valli, ciclo dopo ciclo. La soglia di allerta, `alert_mm`, sta in mezzo: la frazione di 
deplezione `p` della specie, che The Pot inizializza dal sim_group, moltiplica la TAW così ottenuta.

## Come convergono le letture sub-giornaliere con il bilancio giornaliero

Il WH52 legge ogni quindici-sessanta minuti; il bilancio avanza di un giorno. La riconciliazione è un'**aggregazione a 
un valore al giorno, sempre alla stessa ora**.

- **L'ora è la prima mattina, intorno alle sei.** Dopo l'equilibratura notturna, prima che l'evapotraspirazione del 
giorno cominci, prima delle irrigazioni tipiche. Confrontare le sei di oggi con le sei di domani dà esattamente un 
giorno di deplezione, cioè la grandezza che il passo di bilancio calcola.
- **Si media una finestra di circa due ore attorno a quell'ora**, per battere il rumore del sensore: la varianza tipica 
del WH51 dopo aggregazione giornaliera è già nota al modello, ma una media è gratis e riduce i falsi cambi di pendenza.
- **Il dettaglio infragiornaliero non va buttato: documenta da solo gli apporti d'acqua.** Una risalita della curva è 
un'irrigazione o una pioggia. `find_drying_windows` spezza le finestre di asciugamento sulle risalite vere e tollera 
quelle da rumore, quindi il sensore fa da diario automatico degli eventi idrici. Il diario umano resta necessario per 
tutto il resto: potature, spostamenti del vaso, guasti.
- **Una cautela: il sensore misura un punto, il modello la media del vaso.** La sonda legge un raggio di cinque-sette 
centimetri attorno alla punta. Subito dopo l'irrigazione l'acqua si ridistribuisce per ore e la lettura è transitoria: 
l'attesa del drenaggio, prima di registrare l'ancora, assorbe la parte peggiore di questo effetto.

## Risoluzione temporale: si resta al giorno

Si è valutato se alzare la risoluzione a due o quattro passi al giorno, o all'ora. È fattibile: due passi giorno/notte 
per disaggregazione costano poco, l'ora è il limite validato di FAO-56. Ma **non in questa calibrazione**, per una 
ragione precisa: l'intero layer di feedback lavora in giornaliero, e l'errore dominante oggi è su Kc, θ_FC e θ_PWP, non 
sul tempo. Cambiare la risoluzione mentre si calibrano i parametri sposta il bersaglio mentre si sta mirando. L'ordine 
è: rendere affidabile il modello giornaliero, poi raffinare il tempo. L'analisi completa delle opzioni resta agli atti 
della discussione di progetto.

## I tre meccanismi con cui il sensore migliora la simulazione

Sono tre, fanno cose diverse, e conviene non chiamarli tutti "feedback".

| Meccanismo | Funzione | Corregge | Quando agisce |
|---|---|---|---|
| Ancora | `calibrate_substrate(theta_series)` | θ_FC, θ_PWP → TAW, RAW | dopo abbastanza picchi e valli |
| Pendenza | `calibrate_kc(...)` | il Kc effettivo del vaso | dopo abbastanza finestre di asciugamento |
| Riconciliazione | `Pot.update_from_sensor(reading)` | lo **stato** di oggi | ogni giorno |

La distinzione che conta: **i primi due correggono i parametri**, e migliorano tutte le previsioni future; 
**il terzo corregge lo stato**, e rende giusto il numero di oggi anche se il Kc è ancora sbagliato. Sono complementari 
e non si sostituiscono. Riconciliare senza calibrare produce un modello sempre giusto oggi e sbagliato su domani; 
calibrare senza riconciliare produce un modello che accumula errore giorno dopo giorno.

E la discrepanza che `update_from_sensor` restituisce ogni giorno non è solo una correzione: è la 
**misura di quanto il modello sbaglia**, cioè il segnale di calibrazione stesso. Se la pendenza simulata è 
sistematicamente diversa da quella osservata, è un errore di Kc. Se il livello di partenza dopo l'irrigazione non 
torna, è un errore di ancora.

Tutte le correzioni di parametro sono **proposte**, con confidenza e spiegazione, e si applicano su una **copia** della 
specie tramite `apply_kc_correction`: il catalogo globale resta intatto, e un errore di calibrazione su questo vaso non 
contamina gli altri.

## La procedura, passo per passo

### 0. Diario

Prima di tutto un diario degli eventi: data, ora approssimativa, vaso, cosa è successo. Irrigazioni e piogge le vede il 
sensore; potature, spostamenti, trattamenti, guasti e viaggi no. Senza diario, un ciclo contaminato da un evento non 
registrato produce un Kc falso, e non c'è statistica che lo salvi.

### 1. Setup

- Taratura dell'app Ecowitt, per la leggibilità.
- In fitosim: il `Pot` con vaso (volume, diametro, forma, materiale, colore, `sun_exposure`, `rainfall_exposure`, 
`shelter_level`), substrato dal catalogo, specie. Se si misurano altezza della pianta e chioma, i tre campi facoltativi 
del canopy: allora la copertura scala il Kc e l'altezza entra nel Penman-Monteith fisico.
- Il collegamento tra il vaso e il canale del WH52: `garden.set_channel_id(label, channel_id)`. La direzione è 
**label → canale**, e la vista di sola lettura è `garden.channel_mapping`.
- Il `Garden` salvato in SQLite con `GardenPersistence`, così la storia si accumula.

### 2. Ancora della capacità di campo

Irrigare **fino a vedere acqua dal foro di drenaggio**. Aspettare trenta-sessanta minuti, finché dal foro non escono 
più gocce. Vuotare il sottovaso, se c'è. Leggere il WH52: **quel valore è la capacità di campo di quel vaso**, e lo 
stato del modello parte da lì. Annotare nel diario data e ora.

### 3. Previsione a sette giorni

Costruire i `WeatherDayForecast` da Open-Meteo per i sette giorni successivi e chiamare `Garden.forecast`. Il selettore 
sceglie la formula di ET₀ in base ai dati disponibili. Questa è la **predizione**: la curva che il modello si aspetta.

### 4. Osservazione, ogni giorno

Scaricare la history del WH52 con `fetch_history`, estrarre il valore delle sei mediato sulla finestra, e passarlo a 
`Pot.update_from_sensor`. Registrare la discrepanza restituita. Per la forzante del giorno appena passato, usare i dati 
**osservati** del WS90 e del WN32P al posto della previsione: temperatura, umidità, vento a 2 m, radiazione, pioggia. 
Il diario riceve gli eventi non idrici.

### 5. Confronto, a fine ciclo

Quando arriva l'irrigazione successiva, il ciclo è chiuso. Si confrontano la curva prevista e quella osservata:

- **pendenze diverse in modo sistematico** → errore di Kc;
- **livello di partenza che non torna** → errore di ancora;
- **scarto solo in alcuni giorni** → cercare nel diario un evento.

### 6. Calibrazione, dopo abbastanza cicli

Sulla serie giornaliera accumulata: prima `calibrate_substrate` per l'ancora, poi `calibrate_kc` per la pendenza. Le 
proposte arrivano con un livello di confidenza; se accettate, `apply_kc_correction` produce la specie calibrata per 
questo vaso, e la previsione successiva parte dai parametri corretti. Poi si ricomincia dal passo 3.

## Aspettative e calendario

La confidenza cresce con il numero di cicli di irrigazione, non con i giorni:

| Cicli chiusi | Confidenza della pendenza | Cosa aspettarsi |
|---|---|---|
| 1 | nessuna | solo riconciliazione dello stato; nessun Kc |
| 3 | bassa | prima proposta, da guardare con sospetto |
| 5 | media | proposta utilizzabile |
| 10 | alta | parametro affidabile per questo vaso |

Su un vaso outdoor a metà settembre l'evapotraspirazione cala, i cicli si allungano e i dati arrivano più lenti: cinque 
cicli possono voler dire un mese o più, e in inverno la calibrazione di fatto si ferma. È il ritmo giusto, non un 
problema: le proposte di bassa confidenza non vanno forzate.

Le metriche di successo restano quelle del manuale di calibrazione: RMSE della θ prevista contro quella osservata, 
giorno per giorno. Sotto 0.02 è un buon risultato, 0.05 è marginale, oltre 0.08 il modello calibrato non è meglio del 
generico e conviene tornare a cercare l'errore, prima nell'ancora, poi nel diario.

## Due correzioni al manuale di calibrazione

Entrambe stanno in esempi di codice da copiare, quindi vanno sapute prima di partire. Sono emerse verificando per via 
programmatica ogni nome citato in questo documento contro il sorgente.

**Capitolo 4.** Il manuale mostra `calibrate_substrate(theta_observations=…, sampling_interval_hours=…)`. 
La firma reale è

```
calibrate_substrate(theta_series: list[float], name="calibrated", min_distance=…, min_prominence=…)
```

con **un valore per giorno**, già aggregato come descritto sopra. L'aggregazione dal campionamento del sensore al 
valore giornaliero è a carico del chiamante, non della funzione.

**Capitolo 2.** Il manuale mostra `giardino.channel_id_map = {"soil_ch1": "phalaenopsis-1-finestra", …}`. L'attributo 
non esiste, e la direzione è invertita: la mappa reale va da **label a canale**, e si scrive con il metodo

```
giardino.set_channel_id("phalaenopsis-1-finestra", "soil_ch1")
```

La vista di sola lettura è `giardino.channel_mapping`.

## Roadmap dello strumento

Lo strumento vive in **The Pot**, non in fitosim. La registrazione dei gateway è la registrazione dei connettori della 
spec sensori, e la raccolta delle evidenze di calibrazione è il compito che il design del layer di feedback assegna a 
The Pot: costruirlo dentro fitosim avrebbe fatto un secondo The Pot in miniatura. fitosim resta la libreria che fa la 
matematica, ed è già una dipendenza dichiarata di `the-pot`, editable via `uv` sulla cartella `../fitosim`.

Tra le due incarnazioni di The Pot si sceglie il **monorepo principale** (`the-pot`: FastAPI, SQLAlchemy, Postgres, 
oltre 77 mila righe in `src/the_pot/`), non il prototipo. Il prototipo importa fitosim da tempo e ha lo stack più 
semplice, ma è dichiaratamente destinato a essere superato: costruirci sopra oggi è costruire sulla sabbia.

**Perché prima la riga di comando.** La parte rischiosa è una sola: la connessione Ecowitt e il parsing del WS90 sul 
tuo account. Va provata prima di costruirci sopra un'interfaccia. E la calibrazione non può aspettare l'interfaccia: 
l'ancora si registra alla prossima irrigazione, e ogni giorno senza il valore delle sei è un giorno perso. Per questo 
la fase 0 è un pacchetto in `the-pot/scripts/`, la cartella degli strumenti del monorepo, che non tocca né Postgres né 
FastAPI: si lancia col venv di `the-pot`, usa fitosim ed Ecowitt, e tiene lo stato nella SQLite di fitosim stessa.

**Perché le pagine sono pagine dell'app, non un backend a parte.** Devono chiamare il cloud Ecowitt, eseguire la 
matematica di fitosim e ricordare lo stato tra un giorno e l'altro: dal browser le chiamate a Ecowitt si scontrano col 
CORS e metterci le chiavi le esporrebbe. Un `http.server` parallelo avrebbe risolto il problema, ma The Pot ha già un 
server, un ORM e un sistema di template. Quindi la logica va in `src/the_pot/services/`, le pagine in `web/`, la 
persistenza nei modelli veri con una migrazione Alembic. Le credenziali dei gateway stanno nei modelli, mai nel template.

| Fase | Dove | Consegna | Cosa dimostra | Criterio di uscita |
|---|---|---|---|---|
| 0 | `the-pot/scripts/calibrazione_wh5x/` | la CLI dell'anello | Ecowitt funziona sull'account; l'anello si chiude end-to-end | un'ancora registrata a un'irrigazione vera, almeno un'osservazione con discrepanza stampata |
| 1 | `src/the_pot/services/` + `web/` | registrazione dei gateway come feature dell'app | gateway e sensori dalla pagina | WH52 mappato sul vaso dalla pagina, misure canoniche visibili |
| 2 | `src/the_pot/services/` + `web/` | pagina di calibrazione | il flusso in sei passi guidato dal browser | un ciclo intero condotto dalla pagina |
| 3 | nessuna | la calibrazione stessa | proposte con confidenza crescente | dal terzo ciclo la prima proposta, dal quinto una utilizzabile |

### Fase 0: l'anello da riga di comando

Un pacchetto autonomo, `scripts/calibrazione_wh5x/`, da lanciare dalla radice di `the-pot` con 
`uv run python -m scripts.calibrazione_wh5x <comando>`. Nasce già diviso lungo la cucitura che le fasi successive 
useranno: due moduli di pura logica, senza persistenza, che passeranno in `services/` così come sono; un modulo di 
flusso la cui persistenza è l'unica parte da riscrivere quando arriveranno i modelli dell'app.

- `gateways.py`: l'account e il registro dei gateway, tenuti distinti. Le due chiavi (application key e api key) 
sono **dell'account** Ecowitt, valgono per tutti i suoi gateway e stanno solo nell'ambiente, nel `.env`; il **MAC** 
è del singolo gateway e si inserisce quando lo si registra, in un file locale ignorato da git che non contiene 
segreti. Le chiamate al cloud prendono account e gateway insieme. È la registrazione dei connettori della spec 
sensori, ridotta a ciò che serve. Pura logica: passa in `services/` senza modifiche.
- `forcing.py`: la forzante meteo. Dalla history del WS90 e del WN32P costruisce il `WeatherDay` **osservato** di 
ciascun giorno, con minima e massima di temperatura, umidità media, vento **riferito a 2 m** con FAO-56 eq. 47 (l'helper 
che a fitosim manca), radiazione integrata sul giorno in MJ/m² e pioggia dal cumulato giornaliero. Da Open-Meteo 
costruisce la lista dei `WeatherDayForecast` a sette giorni. Pura logica: passa in `services/` senza modifiche.
- `workflow.py`: l'anello. Registrare l'ancora FC leggendo il WH52 adesso; prevedere sette giorni con `Garden.forecast`; 
osservare un giorno scaricando la history, aggregando alle sei e chiamando `update_from_sensor`; confrontare previsto e 
osservato a fine ciclo; calibrare con `calibrate_substrate` e `calibrate_kc` quando i cicli bastano. Lo stato vive 
tutto nella SQLite di fitosim: gli stati del vaso in `GardenPersistence`, ancore e diario come eventi con 
`record_event`. Nessun giornale a parte. È il modulo la cui persistenza cambierà in fase 1 e 2.
- `__main__.py`: la CLI. `scopri`, `ancora`, `prevedi`, `osserva`, `confronta`, `calibra`, `diario`.
- Test senza rete, con payload sintetici e le fixture di fitosim: l'aggregazione alle sei, la conversione del vento, 
l'integrazione della radiazione, la chiusura di un ciclo sintetico.

Prerequisito già assolto in fitosim: la history Ecowitt ora porta anche il vento (`EcowittSeriesPoint.wind_speed_m_s`), 
senza il quale la forzante osservata non si poteva ricostruire.

Criterio di uscita: `scopri` che elenca WH52, WN32P e WS90 sull'account; `ancora` registrata alla prossima irrigazione a 
drenaggio; `osserva` che produce una discrepanza per almeno un giorno; `confronta` che stampa previsto contro osservato.

### Fase 1: la registrazione dei gateway come feature dell'app

`gateways.py` diventa un servizio di `src/the_pot/services/`; i gateway e le mappature canale → vaso entrano nei 
modelli con una migrazione Alembic. La pagina in `web/`: form di registrazione, pulsante "scopri sensori" con l'elenco 
dei canali trovati (WH52 con θ, temperatura ed EC; WN32P; WS90 con vento, radiazione e pioggia), mappatura sul vaso, 
misure canoniche in tempo reale. È la registrazione dei connettori della spec sensori, e a quel punto è del prodotto.

Criterio di uscita: un gateway registrato dalla pagina, il WH52 mappato, le misure parsate visibili.

### Fase 2: la pagina di calibrazione

Il flusso di `workflow.py`, con la persistenza riscritta sui modelli dell'app, esposto in `web/`. Il vaso, dai vasi 
dell'utente. Il pulsante "registra ancora FC", da premere dopo l'irrigazione a drenaggio. "Prevedi sette giorni", con 
la curva disegnata. "Osserva oggi", che sovrappone l'osservato al previsto. Il registro dei cicli, integrato con il 
diario che The Pot ha già. "Calibra", abilitato solo dal terzo ciclo chiuso, che mostra le proposte con la loro 
confidenza prima di applicarle su una copia della specie.

Criterio di uscita: un ciclo intero condotto dalla pagina, dall'ancora al confronto.

### Fase 3: la calibrazione, e dopo

Non è codice. Dal terzo ciclo la prima proposta di Kc, da guardare con sospetto; dal quinto una utilizzabile; RMSE 
della θ giornaliera come metrica, con le soglie del manuale. Quando `the-pot-lisimetro` sarà operativo, la sua stima di 
Kc entra nella regola di precedenza allo scope di catalogo, sopra la pendenza del sensore.

### Cosa resta fuori

fitosim resta una libreria: nessuna interfaccia e nessun gateway dentro `src/fitosim/`, solo la matematica e gli 
adapter. La risoluzione sub-giornaliera. I livelli 1 e 4 del manuale. Dipendenze oltre quelle che `the-pot` già ha.

## Riferimenti

- Manuale di calibrazione: `docs/fitosim_calibration_manual.md`, in particolare capitoli 3 e 5
- Ancora e pendenza: `src/fitosim/science/calibration.py`
- Riconciliazione dallo stato del sensore: `Pot.update_from_sensor` in `src/fitosim/domain/pot.py`
- Precedenza tra fonti quando arriverà il lisimetro: `src/fitosim/science/calibration_resolution.py`
- Adapter Ecowitt: `src/fitosim/io/ecowitt.py` (`fetch_real_time`, `fetch_history`) e `src/fitosim/io/sensors/ecowitt.py`
- Spec dei sensori (gateway, routing, validità temporale): `the-pot/docs/the_pot_sensors_spec.md`
- Lisimetro fisico: progetto sorella `the-pot-lisimetro`
- Design del layer di feedback: `docs/fitosim_feedback_layer_design.md`
