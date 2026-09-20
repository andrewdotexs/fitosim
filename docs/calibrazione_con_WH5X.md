# Calibrazione con il sensore di substrato WH5X

**Data:** 2026-09-17, aggiornata il 2026-09-19 con i cinque vasi
**Status:** Procedura operativa concordata, strumento completo (catalogo di The Pot, geometria dei vasi, gemelli,
pluviometri, gradi-giorno, test senza database), cinque vasi configurati; piante e sonde comprate, rinvasi fra una
settimana, la prima ancora alla prima irrigazione a drenaggio dopo. Prima calibrazione su hardware reale.
**Scope:** cinque vasi outdoor sullo stesso balcone — due rosmarini gemelli e un basilico in tre vasi uguali, due
cassette gemelle di lattuga — ciascuno con un WH52, forzante meteo locale (WN32P + WS90), previsione da Open-Meteo.
Calibra i livelli 2 e 3 del manuale di calibrazione: substrato (θ_FC, θ_PWP) e specie (Kc). Il livello 1, la
funzione di trasferimento della sonda, e il livello 4, il modello chimico, restano fuori da questa prima passata.
**Hardware:** due gateway, perché i sensori Ecowitt si accoppiano a uno solo. GW3000A: cinque WH52 (θ, temperatura ed
EC del substrato, uno per vaso) e il WN32P (temperatura e umidità dell'aria, accanto ai vasi). GW2000: WS90 (vento,
radiazione solare, pioggia, temperatura, umidità, pressione), un pluviometro WH40 e cinque WH51 preesistenti, che
restano dove sono. Lo strumento legge sonda e aria dal primo, vento, radiazione e pioggia dal secondo
(`weather_gateway`, `air_gateway`).

Una cosa da sapere sul WN32P, scoperta con la sezione `battery` dell'API: ha il **barometro**, quindi Ecowitt lo tratta 
come un WH25 e ne espone i valori nella sezione **indoor**, ovunque stia fisicamente. La sorgente dell'aria si configura 
per sezione dell'API (`outdoor_source = "indoor"`), non per posizione del sensore.

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

## L'EC del WH52: cosa si registra subito, cosa si calibra dopo

Il WH52 misura anche l'EC, e la domanda "possiamo calibrare anche quella?" ha la stessa struttura della taratura: 
dietro la parola ci sono **due** calibrazioni, e la seconda non ha senso senza la prima.

**Le due EC non sono la stessa grandezza.** Il sensore legge l'EC **apparente** del mezzo, cioè di substrato, acqua 
e aria insieme, alla temperatura del substrato. Fitosim modella l'EC della **soluzione interstiziale** a 25 °C, quella 
che le radici sentono, derivata da massa salina e volume d'acqua. Durante l'asciugamento le due si muovono in 
**direzioni opposte**: meno acqua conduce meno, e l'apparente scende; i sali si concentrano nell'acqua che resta, e 
l'interstiziale sale. In più l'EC cambia di circa il 2 % per grado, e fitosim assume letture a 25 °C.

**Per questo l'EC si registra e non si riconcilia.** `update_from_sensor` con un'EC osservata sovrascrive la massa 
salina, assumendo che il valore sia già interstiziale a 25 °C: passargli l'apparente del WH52 falserebbe lo stato 
chimico, e sempre più man mano che il vaso si asciuga. Lo strumento quindi salva a ogni osservazione, insieme alla θ, 
la temperatura del substrato, l'EC apparente e l'EC compensata a 25 °C, e lascia la chimica del modello intatta.

**Cosa la serie dirà da sola.** L'EC apparente contro la θ lungo un ciclo di asciugamento è la curva di dipendenza 
dall'acqua di questo substrato, la base empirica per una correzione tipo Hilhorst. E l'EC letta **all'ancora**, a 
capacità di campo dopo ogni irrigazione a drenaggio, è l'indice più stabile della salinità della soluzione: la sua 
deriva di ciclo in ciclo è il segnale di accumulo che il coefficiente di lavaggio del modello deve riprodurre.

**Per calibrare davvero, in ordine:**

1. *Livello 1 dell'EC, la funzione di trasferimento apparente → interstiziale.* Serve un riferimento: un misuratore di 
   EC a penna costa poco, e il protocollo è lo stesso della gravimetria. All'irrigazione a drenaggio si misura l'EC 
   dell'acqua che entra e di quella che esce dal foro; il percolato a fine drenaggio è la soluzione interstiziale a 
   capacità di campo. Accoppiato alla lettura del WH52 nello stesso istante dà un punto della funzione di 
   trasferimento, uno per irrigazione.
2. *Livello 4, il coefficiente di lavaggio.* Dalla serie dell'EC all'ancora contro l'EC prevista dal modello dopo gli 
   stessi eventi. Vuole cicli di fertirrigazione e lavaggio: è un lavoro da stagione di crescita.
3. *Kn.* Si osserva solo quando l'EC **supera il massimo** dell'intervallo ottimale della specie, cosa che in substrato 
   fresco senza fertirrigazione non succede. Sotto l'intervallo il Kn vale 1 per definizione: l'EC bassa è una carenza 
   nutrizionale, non uno stress osmotico, e non riduce l'ET. Il rosmarino del catalogo fitosim **non ha un intervallo 
   ottimale di EC**: `supports_chemistry_model` è falso e Kn vale 1 per costruzione. L'intervallo esiste invece nella 
   scheda di The Pot, con la fonte accanto: 1,3–2,0 mS/cm di soluzione del substrato, la colonna «Pour Thru EC (top)» 
   — vasi annaffiati dall'alto — della scheda *Rosmarinus officinalis* dell'e-GRO Nutritional Monitoring Advisor 
   (Whipker, NC State: categoria EC A, 100–150 ppm N). È la grandezza interstiziale, non l'apparente del WH52: per 
   confrontarla con il sensore serve prima il livello 1. Il default del gruppo «aromatica» di The Pot, 1,0–2,0, la 
   conteneva già.

Con una pianta nuova in substrato fresco e senza concime, per mesi la serie dell'EC sarà piatta e bassa. È il 
comportamento atteso, ed è una linea di base preziosa: quando la fertirrigazione comincerà, ogni scostamento da lì 
sarà segnale.

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
problema: le proposte di bassa confidenza non vanno forzate. È anche il motivo dei cinque vasi (vedi la roadmap): con
i numeri del modello, a Milano a fine settembre il rosmarino nel vaso alto (5,7 L, 19,5 cm di substrato) consumerebbe
la sua RAW (29 mm) in venti giorni, il basilico la sua (20 mm) in nove, la lattuga in cassetta (13 cm) la sua (10–13
mm) in cinque-sette. Per questo il rosmarino si annaffia a scadenza e non alla soglia: il ciclo si chiude
all'irrigazione. I primi tre cicli, e la prima proposta di Kc, arriveranno dal basilico e dalle lattughe.

Le metriche di successo restano quelle del manuale di calibrazione: RMSE della θ prevista contro quella osservata, 
giorno per giorno. Sotto 0.02 è un buon risultato, 0.05 è marginale, oltre 0.08 il modello calibrato non è meglio del 
generico e conviene tornare a cercare l'errore, prima nell'ancora, poi nel diario. Sotto queste soglie ce n'è una che
si misura invece di stabilirla: lo scarto tra le θ osservate dei due rosmarini gemelli, e quello fra le due cassette.
È il rumore di due vasi uguali letti da due sonde uguali, e un RMSE previsto-osservato più basso di quello non dice
niente sul modello.

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
| 0 | `the-pot/scripts/calibrazione_wh5x/` | la CLI dell'anello, sui cinque vasi — **completa** al 2026-09-19 | Ecowitt funziona sull'account; l'anello si chiude end-to-end | un'ancora registrata a un'irrigazione vera su ciascun vaso, almeno un'osservazione con discrepanza stampata, il rumore fra i gemelli misurato in entrambe le coppie con `gemelli` |
| 1 | `src/the_pot/services/` | lo strumento legge gateway e canali da `dispositivi` (H.2-a, già in app) | niente registro doppio | un vaso calibrato con gateway e canale presi da «I tuoi dispositivi» |
| 2 | `src/the_pot/services/` + `web/` | pagina di calibrazione | il flusso in sei passi guidato dal browser | un ciclo intero condotto dalla pagina |
| 3 | nessuna | la calibrazione stessa | proposte con confidenza crescente | dal terzo ciclo la prima proposta, dal quinto una utilizzabile |

### I cinque vasi

Un vaso solo non basta a una calibrazione, per una ragione che precede il modello: davanti a una discrepanza non si
sa se sia il modello o il vaso. La fase 0 gira quindi su cinque vasi, sullo stesso balcone, con la stessa
esposizione, **la stessa sonda** (cinque WH52, tutti sul GW3000A col WN32P; i WH51 restano dove sono) e ciascuno
compra una cosa diversa. Sono due coppie di gemelli e un contrasto.

| Vaso | Specie | Vaso e substrato | Cosa compra |
|---|---|---|---|
| `rosmarino-1` | `ROSEMARY` | tronco di cono nero da 6,5 L (Ø 23,5 sopra, 15,5 sotto, alto 21,5; substrato a 19,5 cm, cioè 5,7 L su una bocca di 22,8), ZOMA aromatiche | il riferimento: θ, temperatura ed EC |
| `rosmarino-2` | `ROSEMARY` | identico: stessa pianta da vivaio, stesso vaso, stesso sacco | il **pavimento di rumore** dei vasi tondi: due vasi uguali, stessa sonda, stesso meteo; la differenza fra le due θ osservate è il caso, non il modello |
| `basilico-1` | `BASIL` | identico ai rosmarini | il **contrasto di specie** a parità di tutto il resto: Kc 1,05 contro 0,75, stomi 100 contro 200 s/m, p 0,40 contro 0,60; uno sprint di 3–5 settimane, finché il freddo non lo ferma |
| `lattuga-1` | `LETTUCE` ×3 | cassetta nera 46,5×16 sopra, 44×14 sotto, alta 15 (substrato a 13 cm: 8,7 L su 726 cm²), miscela cocco-humus-carbone | l'**angolo opposto** dei parametri (Kc 1,00, p 0,30, radici corte, annuale a giorni) e il vaso "da campo": tre piante che coprono la superficie stanno più vicine all'ipotesi di FAO-56 di una pianta in un vaso tondo |
| `lattuga-2` | `LETTUCE` ×3 | identica | il pavimento di rumore delle cassette, e la risposta a "il modello sbaglia in modo diverso sui due tipi di vaso?" |

**I substrati.** Due, uno per gruppo, e dentro il gruppo lo stesso sacco: è la condizione perché i gemelli siano
gemelli e il contrasto sia di specie.

- *Vasi tondi:* ZOMA «Terriccio per basilico e piante aromatiche» — torba o cocco con pomice, perlite, corteccia,
akadama e quarzite, humus di lombrico, senza concimi chimici; il produttore non pubblica né composizione in
percentuale né pH, EC o ritenzione. Drenante come vuole il rosmarino; il basilico ci berrà più spesso, che per la
calibrazione è un bene. Il prior è la scheda `drenante-mediterranea` del catalogo di The Pot (universale, pomice e
sabbia: θ_FC 0,405, θ_PWP 0,186), il substrato che The Pot consiglia al rosmarino e il più vicino a un miscuglio
minerale senza scheda tecnica; l'ancora lo corregge dalla prima irrigazione. Il 15 kg per 20 L del formato grande
dice che la frazione minerale è alta: più il mezzo è minerale e grosso, più la percentuale del WH52 si allontana
dalla θ vera (livello 1) — uguale per i tre vasi, quindi interno al gruppo.
- *Cassette:* miscela propria, misurata in volume e scritta nel diario — 50 % fibra di cocco tamponata a basso EC,
20 % humus di lombrico, 10 % carbone vegetale 3–10 mm **pre-caricato** (un giorno a bagno in concime diluito, o una
settimana mescolato all'humus, e sciacquato se la cenere è tanta: il carbone fresco ha pH 8–10 ed è salato), 20 %
pomice 3–8 mm. Le quote sono quelle che la pianta e la sonda tollerano: la lattuga è sensibile ai sali e l'humus
oltre il 20–25 % porta EC e particelle fini che chiudono i pori; il carbone oltre il 10 % alza il pH fuori dal
5,5–6,5 della lattuga e nei primi giorni sequestra azoto e potassio; e il carbone **conduce**, cosa che i sensori
dielettrici sentono: al 10 % l'effetto è piccolo ma è un altro livello 1, diverso da quello dei vasi tondi, e l'EC
delle cassette non si confronta con quella dei tondi. La pomice — non perlite, che galleggia e in una cassetta bassa
finisce tutta in cima — serve al drenaggio più qui che nei vasi alti: in 13 cm la falda sospesa sul fondo è una
frazione grande del profilo. Il prior è la ricetta stessa, scritta in `config.json` con i componenti del catalogo
di The Pot e la media pesata sui volumi del seed: cocco 0,78/0,33, humus 0,70/0,40, carbone 0,35/0,13, pomice
0,30/0,10 → θ_FC 0,625, θ_PWP 0,278, TAW 45 mm, RAW 13,5 mm. Le stesse quote coi materiali dimostrativi di
fitosim darebbero 0,47/0,14, e la differenza non è un errore ma una **convenzione**: The Pot misura i substrati
come si misurano i substrati — θ_FC è l'acqua a capacità di contenitore (−1 kPa), θ_PWP quella a −10 kPa, oltre
la quale la conducibilità crolla e la pianta non estrae più a un ritmo utile (De Boodt & Verdonck 1972; Raviv &
Lieth 2008) — mentre fitosim aveva scritto le sue fixture con il punto di appassimento dei suoli agrari (−1500
kPa). Dal 2026-09-19 il catalogo ufficiale è solo quello di The Pot, con questa convenzione, e la riserva utile
che ne esce è più piccola: il modello annaffia prima, che per un vaso è il verso giusto. Per la calibrazione
conta poco comunque, perché l'ancora rimette i due estremi sulla scala della sonda.

Dal 2026-09-20 (A1) le stesse schede portano anche la **CEC** e la **densità** del mix: i componenti dichiarano
la capacità di scambio con la fonte, il seed la deriva pesandola sulla massa (la CEC è per grammo: la sabbia
pesa tanto e scambia niente), la densità sui volumi. Il drenante viene 24 meq/100 g a 0,57 kg/L, la cassetta 41
a 0,35, una torba pura 120 a 0,20. Prima arrivavano a fitosim CEC 10 e 0,4 kg/L per qualunque substrato — la
sabbia — e in cinque annaffiate d'acqua di rete a 7,5 il pH del modello andava da 6,5 a 7,1; con i numeri veri
si ferma a 6,8, e la torba a 6,7. Nella calibrazione la chimica resta spenta (`chemistry_model`), ma è il vaso
dell'app che da qui tampona con quello che ha dentro.

Quattro cose da sapere, tutte scritte anche nei `config.json`:

- **Per una perenne la data d'impianto non entra nel modello** (il calendario fenologico segue il mese). Le
annuali con le soglie in scheda — basilico e lattuga, `[care.gradi_giorno]` — leggono lo stadio dai **gradi-giorno**:
a `setup` lo strumento li somma fra `planting_date` e ieri dall'archivio Open-Meteo, l'unica forzante che c'era
prima del vaso, e poi li accumula fitosim dalla forzante osservata. Il basilico da vivaio è già cresciuto, e la
sua `planting_date` è la **semina stimata** (inizio agosto): sui 45 giorni fino al 18 settembre l'archivio dà 737
gradi-giorno, fase mediana da subito, finale a 840. Per le lattughe vale il **trapianto**: lo stadio iniziale
FAO-56 è "copertura scarsa", ed è il tempo che ci mettono a chiudere la cassetta.
- **Il primo ciclo dopo il rinvaso è di assestamento.** Substrato fresco, radici non ancora nel nuovo volume, θ_FC
che si sposta con le prime bagnate. L'ancora si registra alla prima irrigazione a drenaggio e si ri-registra alla
seconda; il ciclo 1 si legge come riscaldamento, per i rinvasi come per i trapianti.
- **Un ciclo si chiude a ogni irrigazione, non alla soglia.** Col vaso alto e p = 0,60 il rosmarino consumerebbe la
sua RAW (29 mm) in venti giorni d'autunno: aspettare la soglia vuol dire due cicli prima di dicembre. Si annaffia a
drenaggio a scadenza, ogni sette-dieci giorni: ogni bagnata chiude un ciclo, e Ks resta 1, che è la condizione in
cui il Kc è definito.
- **Il canale lo decide l'accoppiamento.** Cinque WH52 finiscono in `soil_moisture_ec_ch1…5`; quale sonda è quale lo
dice `scopri --tutto`, e va scritto in `soil_channel` prima di `setup`, che fissa il canale nel giardino salvato (se
poi cambia, lo strumento si ferma e lo dice).

Con lo stesso sacco in tre vasi e nessun concime, le tre EC all'ancora dovrebbero coincidere: il loro scarto è il
rumore sonda-sonda dell'EC, misurato gratis prima di qualunque fertirrigazione. Il pomodoro, l'altro che si
fertirriga, è il vaso della primavera; l'agrume, se ci sarà, il vaso grande da lungo periodo per il Kp e per i sali.

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
- `__main__.py`: la CLI. `scopri`, `ancora`, `prevedi`, `osserva`, `confronta`, `calibra`, `diario`. **Un vaso, una
cartella**: ogni vaso è `data/calibrazione/<nome>/` con la sua `config.json`, il suo registro dei gateway e la sua
SQLite, e `--vaso <nome>` lo sceglie; con più vasi il comando rifiuta di indovinare e li elenca. **`--tutti`** ripete
lo stesso comando su ogni vaso: la giornata dei cinque vasi è `--tutti osserva` e `--tutti confronta`. **Il vaso si
descrive come si misura col metro** — forma, dimensioni in alto e al fondo, altezza interna e del substrato — e lo
strumento ne deriva il volume di substrato (tronco di cono o di piramide) e la superficie evaporante all'altezza del
substrato; un vaso «da 6,5 L» con due dita di bordo ne contiene 5,7. Se la config cambia dopo `setup`, il comando si
ferma con le due versioni a confronto invece di simulare in silenzio il vaso vecchio.
- `catalogo.py`: **specie e substrati dal catalogo di The Pot**, che dal 2026-09-19 è l'unico: le cinque specie e
i cinque substrati di fitosim sono fixture per i suoi test, e lo strumento non ne accetta più i nomi. `species` è
uno slug di `catalog/species/`, `substrate` uno slug di `catalog/substrates/` o una ricetta di componenti in
volume; la strada verso fitosim è quella dell'app — il parser del seed e `fitosim_adapter` — letta dal repo senza
database. Prerequisito, chiuso lo stesso giorno: l'adapter non passava la fenologia, e ogni specie girava da
annuale a giorni dall'impianto (un rosmarino piantato ad aprile era in stadio finale da luglio per sempre; un vaso
senza data, Kc iniziale per sempre). Ora le perenni ricevono il calendario stagionale di `fenologia.py` e la
riduzione in riposo e dormienza di fitosim; chi è cosa lo dice la scheda (`[care] ciclo_vita`) o il gruppo.
Sull'anno, a Milano: rosmarino da Kc 0,60 fisso a 0,85 in stagione e 0,42 in riposo, +31 %.
- **Gradi-giorno.** Le annuali con le soglie in scheda (`[care.gradi_giorno]`: basilico 10 / 240 / 840, lattuga
4 / 165 / 440, stime derivate da FAO-56 e dichiarate in Fonti) leggono lo stadio dal calore: a `setup` i
gradi-giorno fra `planting_date` e ieri dall'archivio Open-Meteo, poi li accumula fitosim dalla forzante
osservata. Il basilico seminato il 5 agosto è a 737, in fase mediana; coi giorni sarebbe stato «iniziale» per tre
settimane dal rinvaso.
- **`gemelli A B`**: lo scarto giorno per giorno fra le osservazioni di due vasi — θ, EC a 25 °C, temperatura —
con media, RMSE e massimo, e il **pavimento per vaso** RMSE/√2. Verifica campo per campo che i due siano gemelli
nel modello e avverte se non lo sono. È il comando che il criterio di uscita chiedeva e non c'era.
- **`rain_source`**: i due pluviometri del GW2000 (piezo del WS90, WH40 a basculla) non leggono la stessa pioggia,
17,7 contro 15,0 mm in un giorno di prova. La config sceglie — `auto`, `piezo`, `gauge` — `scopri` li mostra
entrambi, `osserva` registra la sorgente e si ferma se il pluviometro scelto per nome tace. Richiede la history
Ecowitt con i due cumulati separati (fitosim `3fb6d85`).
- Test senza rete **e senza database**, con payload sintetici: l'aggregazione alle sei, la conversione del vento,
l'integrazione della radiazione, la chiusura di un ciclo sintetico, i gemelli, i pluviometri, i gradi-giorno.
Il gancio che provvede al Postgres di prova in The Pot è ora di fine raccolta e si muove solo se un test di `e2e/`
o `browser/` è della partita: con Docker fermo questi test girano lo stesso (86 nel file, 727 con gli unit).

Prerequisiti assolti in fitosim: la history Ecowitt porta il vento (`EcowittSeriesPoint.wind_speed_m_s`), senza il
quale la forzante osservata non si poteva ricostruire, e i due pluviometri uno per uno.

Stato al 2026-09-19, sera: `scopri` elenca WH52, WN32P, WS90, WH40 e i cinque WH51 sui due gateway; i cinque
workspace esistono e costruiscono il vaso dalle misure e dal catalogo di The Pot (vasi tondi su
`drenante-mediterranea`: 5,67 L, 407 cm², FC 56,5 mm, PWP 25,9 mm, soglia 44,2 per i rosmarini e 41,8 per il
basilico; cassette sulla ricetta cocco-humus-carbone-pomice: 8,72 L, 726 cm², FC 75,0 mm, PWP 33,4 mm, soglia
62,5). Dello strumento non manca niente di quanto era in lista. Segnaposto da chiudere al rinvaso: i canali delle
sonde, l'altezza vera del substrato, le date; e tre righe di config che sono ancora ipotesi — `wind_height_m` 2,0,
`rainfall_exposure` 1,0, `shelter_level` STANDARD — che su un balcone con un balcone sopra non sono neutre.
Nessuna ancora ancora.

Criterio di uscita: `ancora` registrata alla prima irrigazione a drenaggio su ciascun vaso; `osserva` che produce una
discrepanza per almeno un giorno; `confronta` che stampa previsto contro osservato; lo scarto fra le θ dei due
rosmarini e fra le due cassette misurato su almeno un ciclo, che da lì in poi è il pavimento di ogni RMSE.

### Fase 1: lo strumento si collega ai dispositivi dell'app

La registrazione dei gateway **esiste già**: `dispositivi.py` (H.2-a) registra i gateway Ecowitt via cloud, scopre i
canali e li mette sotto un vaso — «si registra in I tuoi dispositivi, si mette sotto un vaso, si tara». La prima
stesura di questa roadmap proponeva di costruirla, senza controllare. La fase 1 è quindi il contrario: il
`gateways.py` dello strumento sparisce e l'anello legge gateway e mappature canale → vaso da `dispositivi`; da
verificare che i WH52 (θ, temperatura ed EC nella sezione `soil_moisture_ec_chN`) e il WN32P nello slot indoor
passino dalla scoperta com'è.

Criterio di uscita: lo strumento gira su un vaso i cui gateway e canale vengono da «I tuoi dispositivi».

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

Due decisioni aperte trovate controllando il `domain` di fitosim contro The Pot, fuori da questo lavoro: il
**pianificatore doppio** (`domain/scheduler.py` di fitosim e la proiezione di `idrica_service`, che non lo usa) e i
**due client Open-Meteo** (`io/openmeteo.py` e `previsione.py`, che The Pot preferisce per l'asincrono, la cache e
i campi dell'interfaccia). Garden, persistenza SQLite e serializzazione di fitosim li usano solo lo strumento e gli
esempi: restano, congelati.

## Riferimenti

- Manuale di calibrazione: `docs/fitosim_calibration_manual.md`, in particolare capitoli 3 e 5
- Ancora e pendenza: `src/fitosim/science/calibration.py`
- Riconciliazione dallo stato del sensore: `Pot.update_from_sensor` in `src/fitosim/domain/pot.py`
- Precedenza tra fonti quando arriverà il lisimetro: `src/fitosim/science/calibration_resolution.py`
- Adapter Ecowitt: `src/fitosim/io/ecowitt.py` (`fetch_real_time`, `fetch_history`) e `src/fitosim/io/sensors/ecowitt.py`
- Spec dei sensori (gateway, routing, validità temporale): `the-pot/docs/the_pot_sensors_spec.md`
- Lisimetro fisico: progetto sorella `the-pot-lisimetro`
- Design del layer di feedback: `docs/fitosim_feedback_layer_design.md`
