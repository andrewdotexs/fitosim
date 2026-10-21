__fitosim — Status Report__

*Stato dello sviluppo della libreria di simulazione FAO-56*

*Maggio 2026 — Aggiornato a fine tappa 5 fascia 2 (chiusura fascia 2). In testa, gli aggiornamenti del 21 ottobre, del 29, del 22 e del 20 settembre 2026; il corpo del documento è la fotografia di maggio, lasciata com'era.*

# Aggiornamento al 21 ottobre 2026 — la calibrazione legge dall'app, e le pressioni di vapore dagli estremi

**Le pressioni di vapore dagli estremi del giorno** (21 ottobre, A9, versione 0.35.0). Dal 29 aprile, quando il Penman-Monteith è entrato con la tappa 5, le due funzioni giornaliere di `science/et0.py` calcolavano e_s come e°(T_media); FAO-56 prescrive la media di e°(T_max) ed e°(T_min), eq. 12, e avverte che la temperatura media sottostima e_s e l'ET₀, perché e° è convessa. Misurato sulle tre settimane vere dell'esempio delle stagioni, prima di cambiare: la giornaliera di fitosim stava −3.1 % (luglio), −2.0 % (gennaio) e −4.0 % (settembre) sotto la FAO eq. 6; metà dello scarto era e_s, l'altra metà e_a dalla media invece che dalle umidità estreme (eq. 17 contro eq. 19). Andrea ha scelto la terza opzione fra tre — lasciare, eq. 12 e 19, eq. 12 e 17 e 19 —: le due Penman-Monteith prendono `t_min`, `t_max`, `humidity_min` e `humidity_max` facoltativi, il selettore passa sempre gli estremi di temperatura e le umidità estreme quando ci sono, `WeatherDay` le porta (a coppia, validate) e `weather_day_from_blocks` le ricava dai blocchi; la stessa e_a entra nella radiazione netta del passo del vaso e del cammino a blocchi; la forma oraria non cambia. Quattro helper nuovi (`mean_saturation_vapor_pressure`, `actual_vapor_pressure_from_extremes`, `actual_vapor_pressure_from_mean`, `daily_vapor_pressures`) e l'esempio 18 del FAO-56 — Bruxelles, il 6 luglio — che torna a un decimo di millimetro, come test. In The Pot la stazione dà le umidità estreme alla calibrazione e alla fase 0 dello strumento; i vasi in casa cambiano dello 0.1 %, l'ET₀ di riferimento della calibrazione del 2–4 %. Nell'esempio delle stagioni la colonna di fitosim ora coincide con la FAO al decimo di percento — 40.58 contro 40.62 mm a luglio, 3.25 contro 3.26 a gennaio, 20.48 contro 20.50 a settembre —: quello che resta è il coefficiente aerodinamico, 900/(T+273) fisso nella FAO ed esplicito in fitosim. Due test del selettore riscritti, 1 556 nel core.

**Le formule di miscela in un posto solo** (21 ottobre, B5, il punto rimasto aperto del blocco B dal 20 settembre). `compose_substrate` faceva solo θ_FC e θ_PWP; la densità, il pH e la CEC di un mix li derivava The Pot in due copie, il seed del catalogo e i substrati personali, con le formule di A1: densità e pH medie sui volumi dei componenti che li dichiarano, CEC pesata sulla massa (quota × densità) e solo se ogni componente dichiara densità e CEC. Da oggi le formule stanno in fitosim: `BaseMaterial` porta i tre campi facoltativi, `compose_substrate` restituisce un `Substrate` con `bulk_density_kg_l`, `ph_typical` e `cec_meq_per_100g` derivati, senza arrotondare — l'arrotondamento è del catalogo che li scrive —, e in The Pot il seed e i substrati personali chiamano la libreria al posto delle loro copie. Verificato sui 18 substrati con ricetta del catalogo vero, sulle due vie: zero differenze al quarto decimale di θ, al terzo della densità, al secondo della CEC. Sei test nuovi in fitosim, 1 562 nel core; la versione resta 0.35.0, perché nessun numero cambia. Del blocco B resta B6, che aspetta la pagina della calibrazione.

**La colonna, solo la matematica** (21 ottobre, `science/retention.py`). La capacità del vaso dall'altezza della colonna, annotata il 28 settembre qui sotto come cosa da decidere coi dati, ha da oggi la sua matematica, non collegata a niente: a drenaggio finito la colonna è in equilibrio idrostatico con l'acqua sul fondo, a quota z la tensione vale z centimetri d'acqua, e la θ effettiva è la media della curva di ritenzione fra zero e h, integrata con Simpson. La tensione media è h/2: a 20 cm fa −1 kPa, il punto di De Boodt & Verdonck che il catalogo chiama θ_FC; una cassetta da 13 sta più bagnata, un vaso da 30 più asciutto. Due forme della curva: van Genuchten, che da due punti del catalogo si ricava per bisezione note θ_s e la residua (`from_catalog`), e una curva per punti per quando si misura; lo spazio d'aria come complemento, il profilo lungo la colonna, la tabella per altezze. Sedici test, 1 578 nel core, versione ferma a 0.35.0. Restano da decidere, e vogliono i dati, tre cose: la θ a saturazione dei 28 componenti (la porosità totale, che il catalogo non ha), la forma della curva per il catalogo coi suoi due punti, e l'ingresso in `Pot.fc_mm`. La verifica non la può dare la sonda, la cui taratura mappa la lettura bagnata sulla θ_FC del catalogo per costruzione: serve l'acqua per litro di terriccio a drenaggio finito su una cassetta da 13 cm e su un vaso da 20, cioè le pesate del livello 1, quando arriva la bilancia.

**Lo strumento legge tutto dall'app** (21 ottobre, fase 1 dello strumento ridefinita). Il 1° ottobre le àncore dei cinque vasi erano state registrate nello strumento della fase 0, e da allora nessun `osserva`: i vasi vivevano in The Pot, che faceva lo stesso anello da sola — la WH52 ogni quarto d'ora, la taratura automatica dopo ogni annaffiata a fondo del diario (il tratto fermo è l'àncora), il bilancio dell'alba, la stazione sul giardino. Andrea ha chiesto se i dati dell'app bastassero: l'export no (vasi e diario, ma niente letture, tarature, albe né meteo), il database sì. Da oggi `src/the_pot/services/calibrazione_fitosim.py` legge dall'app il vaso con lo stesso adattatore di `idrica_service`, la sonda con la taratura valida in quel momento, le àncore dallo storico delle tarature, la forzante dalla stazione (Penman-Monteith sul sole misurato; senza stazione gli aggregati Open-Meteo e Hargreaves, e lo dice), l'acqua dal diario, le pesate da righe «misura» con `peso_g`, e rifà l'anello a posteriori: il modello parte dalla misura delle sei, avanza con la forzante del giorno, la lettura delle sei dopo è l'osservazione. I rapporti sono quelli della fase 0 — `stato`, `confronta`, `calibra`, `gemelli`, `pesa` — con `--dal-db` sulla riga di comando. Ventidue test in The Pot. **fitosim non cambia**: la matematica è `science/calibration.py` e `science/lysimeter.py`, chiamate come prima; cambia da dove arrivano le serie. Lo strato standalone perde così il suo ultimo utente vero oltre agli esempi, e la decisione sulla sua sorte, fissata «dopo la fase 2», si avvicina.

**Lo stesso pomeriggio, in The Pot (H.8-a e b)**: il giro del mattino scrive all'alba di ogni vaso con la sonda le evidenze della calibrazione — la sonda alle sei, l'ET₀ del passo e da dove veniva, l'acqua entrata, l'annaffiata a fondo nella notte, lo stato che il modello avrebbe detto senza la sonda, lo scarto — nella hypertable coi parametri `fitosim:calibrazione:*`, rifacendo i giorni che mancano; lo storico del meteo salva anche l'ET₀ FAO di Open-Meteo, la radiazione del giorno e le umidità estreme (il vocabolario le aveva, nessuno le scriveva), e per chi ha la stazione la pioggia dei giorni passati è quella del pluviometro; lo strumento le legge accanto al ricalcolo. Resta fuori, per scelta, il grezzo AD. **I prossimi passi**: E.10-b, c e d in The Pot (lo zoom orario della curva, l'ora nell'avviso e nella notifica, la riga nel widget); il dry-down dei gemelli per `p` (finora rosmarino-2 e lattuga-2 hanno avuto la stessa acqua dei fratelli); le pesate quando arriva la bilancia, col livello 1 del manuale (A.6); il livello 4 con una stagione di fertirrigazioni. Il lisimetro fisico resta rimandato.

**La sera, il giorno a blocchi in The Pot (E.10-a).** Il passo a blocchi di A7 è entrato nei servizi dell'app: `idrica_service` avanza ogni giorno un'ora alla volta con `Pot.apply_step_blocks`, costruendo i `WeatherBlock` con `services/blocchi.py` — dalle letture a quarti d'ora della stazione per i giorni passati di chi ce l'ha (`weather_blocks_from_samples`), dalle ore di Open-Meteo per i giorni previsti (la richiesta chiede ora anche `shortwave_radiation` e l'ET₀ FAO oraria, e le ore viaggiano dentro il `Giorno`), dal profilo del sole per il resto (`distribute_daily_et0` sulla R_a di ogni ora, con l'ET₀ di sempre, anche per i vasi in casa) — e con la stazione o con le ore complete l'ET₀ è `et0_for_blocks`, Penman-Monteith ora per ora col riparo del vaso e la versione fisica della specie. Prima di scrivere, misurato su Open-Meteo vero (Milano, 19–27 ottobre, la settimana del cambio dell'ora dentro): il servizio stampa radiazione, pioggia ed ET₀ come «ora precedente» e applica uno scostamento fisso a tutta la risposta, anche attraverso il cambio (la correlazione oraria con la sua ET₀ sale a 0,996 solo leggendole così), e la somma oraria di fitosim sta il 4,6 % sotto l'ET₀ FAO giornaliera del servizio, che i giorni previsti usavano prima. Il giorno resta l'unità — i gradi-giorno li conta l'app, per questo il secchio è `apply_step_blocks` e non `apply_blocks_from_weather` —; le quantità del diario entrano nella loro ora; i punti della curva portano le ventiquattro ore e l'istante dell'allerta, per lo zoom orario e l'avviso che vengono dopo (b, c, d). Trentasette test in The Pot. **fitosim non cambia**: la versione resta 0.35.0.

# Aggiornamento al 29 settembre 2026 — il giorno fatto di blocchi

**Il giorno fatto di blocchi** (29 settembre, A7). Il vaso sa avanzare a blocchi di ore dentro il giorno: `Pot.apply_blocks_from_weather` calcola l'ET₀ di ogni blocco con la forma oraria di Penman-Monteith (FAO-56 eq. 53, R_a e R_n del blocco, G di giorno e di notte), valuta Ks sullo stato del momento e fa entrare pioggia e irrigazioni alla loro ora; il giorno resta l'unità di Kc, stadio, gradi-giorno e nutrienti, e il passo giornaliero è il caso di un blocco di 24 ore, con gli stessi numeri. Misurato su una settimana vera di settembre a Milano: la somma delle ore sta +3 % sopra la giornaliera FAO (+7 % sopra quella di fitosim, che usa e°(T_mean)); Ks a ore vale −1,4 % di ET_c; un litro alle 20 invece che «al mattino» tiene 2,5 mm in più nel vaso; l'allerta ha un'ora. Le nove decisioni (Kc costante nel giorno, D_e a blocchi, tasso capillare riscalato, notte a zero, forma FAO-56 e non ASCE-EWRI, …) sono nel docstring di `domain/blocks.py`, con le fonti. Lo strumento di calibrazione non cambia: confronta cali giornalieri.

**L'esempio delle stagioni** (`examples/confronto_et0_risoluzione_temporale.py`, con quattro grafici se matplotlib c'è): Hargreaves e Penman-Monteith a 24 h, 6 h, 4 h e 1 h su due settimane vere di Milano — la canicola del 13–19 luglio 2026 e la nebbia del 12–18 gennaio — con lo stesso rosmarino in un mix drenante, a giorni e a blocchi. Il segno dello scarto fra la giornaliera FAO e la somma delle ore non è fisso (−3.5 % d'estate, +2.8 % a settembre); nella nebbia le due procedure divergono per il pavimento di R_s/R_so che la forma oraria ha e la giornaliera no (+21 % la 24 h, +12 % Hargreaves, su 2.7 mm in sette giorni); d'estate l'allerta arriva «il 16/07 dalle 15:00» e un litro dato alle 20 invece che alle 8 tiene 4.6 mm in più nel vaso, un quarto della riserva utile; d'inverno 2.6 mm in una settimana e l'ora del litro vale 0.1 mm.

**The Pot** riceverà i blocchi dopo la prima ancora del WH52; fino ad allora il suo passo resta giornaliero, e lo strumento di calibrazione confronta cali giornalieri in ogni caso.

__Il quadro al 21 ottobre 2026__

__Metrica__

__Valore__

__Note__

Test verdi nel core

1578

520 sub-test; 1584 con la demo end-to-end (matplotlib); circa dieci secondi

Righe di sorgente

25 233

science 9 102 (18 moduli), domain 7 580 (8), io 5 095 (4) \+ io/sensors 3 456 (8)

Strato standalone

8 400 righe

garden, persistence, serialization, scheduling, openmeteo, io/sensors: congelato, 440 test

Schema SQLite

v8

v5 fenologia e GDD (luglio), v6 chioma, v7 densità del substrato, v8 pendenza salina della specie

Formato JSON

v3

esportazione fedele del giardino (luglio)

Versione

0.35.0

`pyproject.toml`; continua la serie dei commit `v0_NN`, fermata a `v0_30` il 22 luglio

Esempi

30

`scheduler_demo.py` tolto con il pianificatore

Catalogo

The Pot

369 specie, 17 substrati, 28 componenti, con le fonti; in fitosim 5 \+ 5 \+ 9 fixture

**I prossimi passi** sono, nell'ordine: la calibrazione sul WH52 (fase 0 dello strumento completa; rinvasi e prima ancora nella settimana del 28 settembre; da metà ottobre il dry-down dei gemelli per `p`), i blocchi in The Pot dopo la prima ancora (`shortwave_radiation` fra le variabili orarie di `previsione.py`, un passo a blocchi accanto a `_un_giorno`, l'ora dell'allerta nella pagina; *il passo è entrato il 21 ottobre, E.10-a*), lo spostamento dello strumento sui dispositivi e sui modelli di The Pot (fasi 1–2), e con i primi dati la decisione sul terzo punto dell'acqua a −1500 kPa nei componenti del catalogo, e quella sulla capacità del vaso dall'altezza della colonna (qui sotto). Il lisimetro (`the-pot-lisimetro`) è rimandato perché costoso, non abbandonato: la sua stima di Kc entrerà nella regola di precedenza sopra la pendenza del sensore.

**Da fare dopo la calibrazione: la capacità del vaso dall'altezza della colonna** (Andrew, 28 settembre, dallo strato drenante di The Pot, C.9-bis). Oggi la riserva piena è θ_FC × profondità, con θ_FC il valore del substrato a −1 kPa: la capacità di contenitore di una colonna alta una ventina di centimetri, la stessa per ogni vaso. Ma un vaso a capacità di contenitore non è bagnato uguale dappertutto: sul fondo c'è la falda sospesa, a tensione zero, e sopra la tensione cresce di un centimetro d'acqua per ogni centimetro d'altezza. Una colonna bassa — la ciotola del bonsai, la cassetta da 13 cm, il terriccio sopra uno strato drenante, che fa da barriera capillare e porta la falda sul confine — tiene per litro più acqua di θ_FC e meno aria in fondo; una alta ne tiene meno. Lo strato drenante oggi entra solo come profondità in meno (`active_depth_fraction`, o i litri di terriccio che The Pot passa da C.9): il conto dei litri è giusto, ma il terriccio che resta ha il θ_FC di una colonna di venti centimetri, e il modello sottostima l'acqua dopo un'annaffiatura — dice «sete» un po' prima del vero, mentre il fondo è ancora zuppo. L'idea: la capacità del vaso dalla curva di ritenzione del substrato mediata sull'altezza della colonna (a quota z la tensione vale z), con θ_FC a −1 kPa come punto di taratura; servono i punti della curva del catalogo (−1 e −10 kPa, e il terzo a −1500 in discussione) o una forma come van Genuchten. L'altezza della colonna The Pot la sa già: l'altezza del vaso meno lo spazio sopra e lo strato. Si decide coi dati del WH52 — il θ_FC effettivo che `calibra` stima per le cassette (13 cm) e per i vasi tondi (20 cm), coi substrati diversi da tenere in conto e sapendo che la sonda misura intorno a dove è infilata, mentre la falda sta sul fondo. *(21 ottobre: la matematica è pronta in `science/retention.py`, vedi sopra; la decisione aspetta θ_s, la forma della curva e le pesate.)*

# Aggiornamento al 22 settembre 2026 — il colore dei sali, e la sonda che lo corregge

**La sonda EC** (0.33.0, `science/soil_ec.py`, `Pot.update_from_ec_sensor`): una sonda nel vaso legge la conducibilità *apparente* del substrato, non quella della soluzione su cui stanno le soglie; le due stanno fra loro come l'acqua sta nel vaso. Il modello di **Hilhorst** (2000) — σ_p = ε_p σ_b / (ε_b − ε_σb=0), con la permittività apparente da **Topp** (1980) invertita per bisezione, quella dell'acqua con la temperatura, l'intercetta 4,1 dei suoli — porta la lettura sull'EC della soluzione, e **un fattore per vaso** (`ec_sensor_factor`, tarato a capacità di campo con `factor_at_field_capacity`: subito dopo un'annaffiata a fondo la soluzione è quella della vasca) chiude il conto sul substrato vero. Da lì la massa salina si allinea (`salt = EC × 10 × acqua`, come la WH51 allinea l'acqua) e i serbatoi nutritivi la seguono in proporzione, restando dentro i sali. Un substrato troppo asciutto perché la corrente passi non dice niente, e non tocca niente. Dieci test.

Il bilancio dei sali sapeva *quanto* sale c'è nel vaso; da oggi sa anche *che cosa*, e quanto la pianta ne mangia. `science/nutrients.py` (versione 0.32.0) mette accanto alla massa salina tre serbatoi — azoto, fosforo come P₂O₅, potassio come K₂O, in milligrammi per vaso, le unità delle etichette — che **seguono la massa salina**: entrano con la concimazione (`volume × concentrazione`, o la quota del giorno di un secco), escono col drenaggio nella stessa frazione dei sali (il nitrato un quinto in più), e la loro somma in milliequivalenti non supera mai `salt_mass_meq`. Il pezzo nuovo è **la domanda del giorno**: la pianta mangia il flusso di massa della sua traspirazione (Kcb × Ks × ET₀, la sola pianta) alla concentrazione che il piano della specie vuole quel mese, per una *frazione di alimentazione* — l'intervallo fra le annaffiature sulla cadenza delle concimazioni: 1 per chi fertirriga sempre, circa 0,7 per un liquido ogni due settimane — e col cancello del freddo (rampa 8–12 °C, pavimento 10 %). Quello che mangia lo toglie anche dai sali: è la «metà mangiata» di The Pot fatta giorno per giorno. La `Species` porta il piano (`nutrient_targets_mg_per_l`, dodici terne), la frazione e i micronutrienti che contano; il `Pot` ha i tre serbatoi, le bandierine datate dei micro, la carica iniziale del substrato (`apply_starter_charge`), la **riserva** — la frazione della carica piena occupata dal serbatoio più vuoto fra quelli che il piano chiede, col *quale* («al 40 %, manca soprattutto azoto») e i giorni che restano — e la sesta allerta, `nutrient_low`. I rilasci dei concimi secchi hanno la loro cinetica per classe (`daily_release_fraction`): il rivestito con la temperatura (Q10 = 2 intorno a 21 °C, la scheda Osmocote), l'organico con temperatura e umidità (Hartz 2000), il granulare solubile con l'acqua. Il vincolo di taratura è il **bilancio annuale** (`tests/test_nutrients.py`): un vaso di profilo medio concimato secondo il suo piano — un liquido ogni quattordici giorni, l'acqua quando serve, sei millimetri di pioggia ogni nove giorni — mangia il 90 % di quello che riceve, il resto lo porta via la pioggia, e finisce l'anno senza accumulo; chi mangia meno di quel che riceve accumula. Tutto retrocompatibile: senza piano i serbatoi restano a zero e il modello è quello di prima. 33 test nuovi, 1457 nel core.

# Aggiornamento al 20 settembre 2026

Da maggio fitosim è cambiato in tre modi, e questo capitolo li racconta prima che il documento torni allo stato di allora.

**È diventato il motore di un'applicazione.** The Pot (`../the-pot`, FastAPI e Postgres) monta fitosim come dipendenza editabile e ne usa il modello — tutto `science/`, il `Pot`, la `Species`, `WeatherDay`, le regole delle allerte, il client Ecowitt grezzo — attraverso un adattatore (`services/fitosim_adapter.py`) che traduce le sue righe di database nelle dataclass di fitosim. Dal 19 settembre **il catalogo ufficiale di specie, substrati e componenti è quello di The Pot** (369 schede con le fonti; 17 substrati derivati da 28 componenti): le cinque specie e i cinque substrati definiti in fitosim sono fixture per i test e gli esempi. Quello che The Pot non importa — `Garden`, la persistenza SQLite, la serializzazione JSON, i `Protocol` dei sensori, il client Open-Meteo — è lo **strato standalone**: 8 400 righe, il 36 % dei sorgenti, congelato per iscritto nel README dal 20 settembre; lo usano lo strumento di calibrazione e gli esempi. Il pianificatore (`domain/scheduler.py`) è stato tolto lo stesso giorno perché nessuno lo chiamava.

**La fascia 3 ha la sua matematica** (luglio, `v0_21`–`v0_30`): il layer di feedback come funzioni pure — Kc dalla pendenza di asciugamento del sensore, ancoraggio fenologico doppio (annuali dai giorni o dai gradi-giorno, perenni dal calendario stagionale), riduzione del Kc in dormienza, calibrazione comportamentale dalle irrigazioni e dai giudizi sulle allerte, lisimetro come ground truth, regola di precedenza fra fonti — con lo schema SQLite v5 e il formato JSON v3 che la persistono. A settembre la **chioma misurata** (H.1-c: copertura e altezza della pianta nel Kc e in Penman-Monteith, schema v6), il WH52 letto dalla sezione giusta dell'API Ecowitt con le unità metriche, la history con il vento e i due pluviometri del GW2000, e la **procedura di calibrazione sul WH52** (`docs/calibrazione_con_WH5X.md`) con il suo strumento a riga di comando, che vive in The Pot: cinque vasi — due rosmarini gemelli, un basilico, due cassette gemelle di lattuga — pronti a partire la settimana del 28 settembre.

**Il modello è stato rivisto numero per numero** (18–20 settembre), con la regola che ogni costante deve avere una fonte o essere dichiarata come stima da tarare:

- il coefficiente nutrizionale Kn penalizza solo l'eccesso di sali, con la forma e la pendenza di FAO-56 eq. 83 (12 % di ET per mS/cm sopra il massimo; per gruppo in The Pot: ortive 9, agrumi 11, mediterranee 5, dalla tab. 23), applicato al Kcb nel dual-Kc; **il pH non entra più nel Kn** — agisce sulla nutrizione in settimane, non sulla traspirazione del giorno, e nel vaso è uno stato stimato — resta un'allerta;
- la CEC e la densità dei substrati vengono dai componenti del catalogo, con la fonte, e il mix pesa la CEC sulla massa; il vaso pesa il tampone del pH con la sua densità vera (`Substrate.bulk_density_kg_l`, schema v7) invece di 0,4 kg/L per tutti;
- la frazione di deplezione `p` resta il prior di FAO-56, letto per quello che vale sulla riserva a −10 kPa dei substrati (un setpoint a 2–4 kPa), e si misurerà nel dry-down dei vasi gemelli; intanto `calibrate_kc` inverte il Kc sui soli giorni senza stress, perché il Ks dell'inversione dipende da `p`;
- la dormienza è il Kc del suolo nudo (0,20, il `Kc min` di FAO-56) e il riposo è il Kc dello stadio: via i due fattori 0,25 e 0,50 che non avevano una fonte; i sempreverdi di The Pot (mediterranee, conifere) riposano invece di dormire.

Le decisioni, con i numeri misurati sul catalogo e sui test prima di cambiare, sono nei messaggi di commit del 20 settembre (A1–A5) e nei commenti dei moduli.

# Executive summary

fitosim è la libreria Python che stai costruendo per modellare il bilancio idrico e chimico del tuo balcone milanese, basata sulla metodologia FAO-56 estesa con componenti specifici per la coltivazione in vaso. Il progetto è suddiviso in due fasce di lavoro distinte: la fascia 1 ha costruito il modello idrico completo del singolo vaso ed è chiusa da diverso tempo; la fascia 2 ha esteso la libreria con sensoristica reale, modello chimico, architettura applicativa e raffinamento scientifico, ed è ora completa al 100% (cinque tappe complete su cinque).

Lo stato attuale è una libreria a 1007 test verdi (più 1 skipped intenzionale e 357 sub-test) che integra: il modello idrico FAO-56 con dual-Kc; gestione del sottovaso; calibrazione da sensore; sensori reali via HTTP/JSON con gateway ESP32; modello chimico completo del substrato (massa salina, pH, EC come grandezza derivata); coefficiente nutrizionale Kn che modula l’evapotraspirazione in funzione dello stato chimico; coefficiente di esposizione alla pioggia per i vasi parzialmente coperti. Da fine tappa 4 si aggiunge il dashboard operativo completo: il Garden come orchestratore di più vasi, la persistenza SQLite con storia completa, il formato di trasporto JSON, l’integrazione dei sensori reali in batch, gli eventi pianificati con previsioni a N giorni, e il sistema di allerte derivato dallo stato.

La tappa 5, completata alla chiusura della fascia 2, ha aggiunto un raffinamento sostanziale del modello scientifico articolato in cinque sotto-tappe progressive per un totale di 142 test verdi nuovi: introduzione di Penman-Monteith come funzioni pure (versione fisica con resistenza stomatica della specie e versione FAO-56 standard, accanto a Hargreaves-Samani); selettore "best available" che sceglie automaticamente tra le tre formule in funzione dei dati meteo e dei parametri specie disponibili, con tracciabilità del metodo via EtResult; integrazione del selettore nel ciclo di vita del Pot e del Garden tramite WeatherDay e i nuovi metodi apply\_balance\_step\_from\_weather e apply\_step\_all\_from\_weather; modello completo dei vasi indoor con la nuova entità Room, IndoorMicroclimate, LightExposure a tre livelli, modulo science/indoor.py per la radiazione, EcowittAmbientSensor per il sensore WN31, supporto WH52 nel EcowittWH51SoilSensor, persistenza delle Room nel database SQLite; demo end-to-end di un appartamento invernale con tre vasi indoor in due Room diverse.

Con la fascia 2 chiusa, il progetto è pronto per aprire la fascia 3 di calibrazione contro i dati reali del tuo balcone. La fascia 3 sarà concettualmente diversa dalle precedenti: meno "costruzione di nuove API" e più "messa a punto e validazione contro realtà". I dati raccolti dalla stazione Ecowitt nei prossimi mesi saranno usati per raffinare le frazioni della radiazione indoor, i parametri Kc del catalogo specie, le soglie del selettore "best available", la resistenza stomatica delle specie. Lo scopo è trasformare fitosim da "libreria genericamente plausibile" a "libreria calibrata per il TUO balcone milanese".

# Quadro quantitativo del progetto

Lo stato della libreria può essere riassunto con qualche numero che dà la misura del lavoro accumulato e della copertura della suite di test.

__Metrica__

__Valore__

__Note__

Test verdi totali

1007

\+ 1 skipped intenzionale

Sub-test verdi

357

via subTest di unittest

Test fascia 1 (storici)

423

non toccati dalla fascia 2

Test fascia 2 (nuovi)

584

263 tappe 1-3 \+ 179 tappa 4 \+ 142 tappa 5

Tempo esecuzione suite

≈ 11 sec

su laptop standard, no parallelismo

Moduli science/

11

aggiunto indoor.py (tappa 5)

Moduli domain/

7

Pot, Species, Garden, scheduling, alerts, room, weather

Moduli io/

11

Protocol \+ 5 adapter \+ persistence \+ serialization (3 classi Ecowitt)

Schema SQLite

v3

8 tabelle \+ estensione per Room (tappa 5)

Linguaggio

Python ≥ 3.10

no dipendenze esterne nel core

Firmware ESP32

5 file Arduino

esempio per gateway HTTP-Modbus

Esempi e demo

20\+

incluse 4 demo della tappa 5 (A, B, C, E)

# Fascia 1: modello idrico completo (chiusa)

La fascia 1 è stata completata in sei tappe ed ha costruito il cuore idrico del modello: il bilancio FAO-56 standard nel vaso, esteso con componenti specifiche del giardinaggio domestico. È chiusa da tempo, non viene toccata dalle tappe successive, e i suoi 423 test continuano a passare al byte ad ogni nuova consegna della fascia 2.

## Cosa contiene la fascia 1

Le sei tappe completate hanno introdotto progressivamente:

- La caratterizzazione fisica del vaso come contenitore: volume, diametro, forma (cilindrica, rettangolare, ovale), materiale (plastica, terracotta, ceramica), colore (chiaro, medio, scuro) ed esposizione solare. Il coefficiente Kp di vaso modula l’evapotraspirazione in base a queste caratteristiche.
- Il modello del sottovaso opzionale come componente di stato distinto, con trasferimento capillare verso il substrato, evaporazione propria, e capacità di drenaggio dell’eccesso idrico.
- L’astrazione del substrato di coltivazione con i parametri idrici θ\_FC (capacità di campo) e θ\_PWP (punto di appassimento permanente), più i parametri opzionali REW/TEW per il modello dual-Kc.
- Il modello dual-Kc di FAO-56 capitolo 7 che separa il coefficiente colturale in componente basale (traspirazione) ed evaporazione superficiale. Si attiva automaticamente quando specie e substrato sono entrambi caratterizzati per il dual-Kc, ricadendo sul single-Kc in caso contrario.
- Il sistema di calibrazione e diagnostica delle deviazioni del modello dalle osservazioni, che fornisce il framework per il tuning fine dei parametri del singolo vaso.
- Il feedback loop sensore-modello via il metodo update\_from\_sensor del Pot, che permette di agganciare la previsione alla realtà osservata e produrre diagnostica strutturata della discrepanza.

# Fascia 2: sensori, chimica, architettura applicativa, raffinamento scientifico

La fascia 2 estende fitosim oltre il bilancio idrico puro per includere la sensoristica reale del balcone, la chimica del substrato, l’architettura applicativa del dashboard, e il raffinamento scientifico del modello di evapotraspirazione e del bilancio indoor. È strutturata in cinque tappe, tutte completate alla data di questo report.

L’aspetto importante della fascia 2 è che è completamente opt-in: ogni estensione che introduce è retrocompatibile per costruzione, e la fascia 1 non si è accorta di nulla. Le 423 prove originarie continuano a girare identiche, e il chiamante che vuole le nuove funzionalità le attiva esplicitamente configurando i nuovi parametri delle dataclass o importando i nuovi moduli.

## Tappa 1: astrazione dei sensori (completata)

La prima tappa ha costruito l’astrazione di sensore di fitosim come Protocol Python, separando il modello scientifico dai dettagli di acquisizione dei dati. Il Protocol SoilSensor definisce l’interfaccia che qualsiasi sensore deve implementare: un metodo current\_state(channel\_id) che ritorna un SoilReading strutturato. La stessa cosa per i sensori ambientali tramite il Protocol EnvironmentSensor.

I tipi di ritorno EnvironmentReading e SoilReading raccolgono in dataclass frozen tutte le grandezze fisiche che un sensore può misurare, tutte con timestamp UTC aware obbligatorio. La gerarchia di eccezioni canoniche (SensorTemporaryError, SensorPermanentError, SensorDataQualityError) classifica gli errori in base alla loro recuperabilità, permettendo al chiamante di reagire differenziatamente.

## Tappa 2: gateway hardware-to-HTTP (completata)

La seconda tappa ha aggiunto il primo sensore di suolo "ricco" che misura non solo θ ma anche temperatura del substrato, EC e pH. Il pattern adottato è generico e disaccoppiato: invece di scrivere un adapter dedicato a un sensore specifico, abbiamo costruito un adapter HTTP JSON generico che parla con un gateway esterno. Il gateway si occupa dei dettagli hardware (Modbus RTU su bus RS485 nel caso ATO) e li espone come endpoint REST con uno schema JSON V1 ben documentato.

## Tappa 3: modello chimico del substrato (completata)

La terza tappa ha esteso il Pot col modello chimico completo: massa salina come stato canonico (salt\_mass\_meq), pH del substrato come stato indipendente (ph\_substrate), e EC come property derivata dal rapporto sali/acqua. Il fenomeno della concentrazione per evapotraspirazione emerge automaticamente: meno acqua a parità di sali significa EC più alta, senza nessuna riga di codice che lo gestisce esplicitamente.

Il coefficiente nutrizionale Kn modula la traspirazione della pianta in funzione dello stato chimico: vaso in range chimico ottimale ha Kn=1. Lo stress da EC è solo per eccesso di sali (stress osmotico, forma e pendenza di FAO-56 eq. 83 e tab. 23: 12% di ET per mS/cm sopra il massimo della specie, pavimento 0.30): l’EC sotto il range non riduce l’ET, è una carenza nutrizionale segnalata dalle allerte. Il pH non entra nel Kn (dal 2026-09-20): agisce sulla nutrizione in settimane, non sulla traspirazione del giorno, e nel vaso è uno stato stimato; resta un’allerta, oltre la tolleranza di ±0.3. Nel dual-Kc il Kn sta sul Kcb, non su Ke. Implementato come funzione lineare a tratti, semplice e debugabile, calibrabile in fascia 3.

Il rainfall\_exposure (frazione 0..1) modella la copertura ambientale del vaso. Vasi sotto balcone o sotto chioma di alberi ricevono solo una frazione della pioggia caduta sull’area aperta — fenomeno che per i vasi outdoor produce salinizzazione differenziale di lungo termine, importante per la calibrazione futura del modello.

## Tappa 4: dashboard operativo completo (completata)

La quarta tappa è la più sostanziosa della fascia 2 in termini di scope architetturale: trasforma fitosim da "libreria scientifica per singolo vaso" a "sistema operativo per il dashboard del giardiniere". È strutturata in cinque sotto-tappe, ognuna con un focus specifico, e in totale ha aggiunto 179 test verdi alla suite portandola a 865.

__Sotto-tappa__

__Capacità__

__Test nuovi__

A: Garden in-memory

Orchestrazione di più vasi come unità coerente

\+30

B fase 1: SQLite

Persistenza con storia completa degli stati

\+32

B fase 2: JSON

Formato di trasporto per backup e migrazione

\+20

C: integrazione sensori

Update batch dai sensori reali con robustezza errori

\+23

D: forecast e eventi

Eventi pianificati e proiezione dello stato a N giorni

\+36

E: sistema di allerte

Allerte derivate dallo stato per dashboard proattivo

\+38

Il Garden della sotto-tappa A è un orchestratore puro: contiene una collezione di Pot indicizzati per label, e i suoi metodi (apply\_step\_all, update\_all\_from\_sensors, forecast) iterano sui vasi senza aggiungere logica scientifica al modello. Una proprietà inchiodata da test specifici è che apply\_step\_all su un Garden con un vaso solo produce stati identici a apply\_step chiamato direttamente sul Pot.

La persistenza SQLite della sotto-tappa B fase 1 ha introdotto uno schema a otto tabelle (schema\_metadata, species, base\_materials, substrates, substrate\_components, gardens, pots, pot\_states, events) con la convenzione "id come PK sintetica e <tabella>\_id come FK". Lo schema è alla versione 3 e la classe GardenPersistence applica automaticamente le migrazioni v1→v2 (channel\_id) e v2→v3 (scheduled\_events) ai database esistenti.

Le altre sotto-tappe della 4 (B fase 2 JSON disaccoppiato dalla persistenza SQLite, C integrazione sensori in batch con gestione errori a tre livelli, D eventi pianificati e forecast su deep copy del Garden, E sistema di allerte come funzioni pure in cinque categorie e tre severità) hanno consolidato l’architettura applicativa del dashboard.

## Tappa 5: Penman-Monteith fisico e modello indoor (completata)

La quinta e ultima tappa della fascia 2 ha raffinato sostanzialmente il modello scientifico in due direzioni complementari: l’introduzione di Penman-Monteith come formula di evapotraspirazione (in due varianti, fisica e standard FAO-56) con un selettore "best available" che sceglie automaticamente tra le formule disponibili, e il modello completo dei vasi indoor con l’entità Room come spazio fisico con microclima condiviso. La tappa è strutturata in cinque sotto-tappe progressive che in totale hanno aggiunto 142 test verdi alla suite portandola a 1007.

__Sotto-tappa__

__Capacità__

__Test nuovi__

A: Penman-Monteith come funzioni pure

Penman-Monteith fisico (con resistenza stomatica della specie) e standard FAO-56 nel modulo science/et0.py, accanto a Hargreaves-Samani. Tutte funzioni pure ben testate contro i casi di letteratura FAO-56.

\+25

B: selettore "best available"

compute\_et sceglie automaticamente Penman-Monteith fisico → standard → Hargreaves in funzione dei dati meteo e dei parametri specie disponibili. Tracciabilità del metodo via EtResult e EtMethod.

\+17

C: integrazione nel Pot e nel Garden

WeatherDay come dataclass meteo giornaliera; apply\_balance\_step\_from\_weather sul Pot e apply\_step\_all\_from\_weather sul Garden, che invocano il selettore al posto di un ET₀ pre-calcolato.

\+30

D: modello indoor

Entità Room, IndoorMicroclimate (varianti istantanea/giornaliera), LightExposure a tre livelli, modulo science/indoor.py per la radiazione (categoriale e continua), EcowittAmbientSensor per il WN31, supporto WH52 nel EcowittWH51SoilSensor, persistenza delle Room nel database SQLite.

\+64

E: demo end-to-end appartamento

Script eseguibile (tappa5\_E\_appartamento\_demo.py) che simula un appartamento invernale con tre vasi indoor in due Room diverse, mostra in azione la selezione automatica del metodo ET, la persistenza delle Room, e produce quattro grafici PNG di analisi.

\+6

La sotto-tappa A ha introdotto Penman-Monteith come funzioni pure in due varianti: compute\_et0\_penman\_monteith calcola l’ET₀ di riferimento usando i parametri della coltura standard FAO-56 (rs=70 s/m, h=0.12 m), da moltiplicare per il Kc della specie come si fa con Hargreaves; compute\_et\_penman\_monteith\_physical calcola direttamente l’ET applicando l’equazione alla specie usando la sua resistenza stomatica e altezza colturale, producendo un valore già specifico per la pianta che NON va moltiplicato per il Kc. La distinzione tra le due varianti è semanticamente cruciale: confondere ET₀ e ET introducerebbe errori del 100-200%.

La sotto-tappa B ha introdotto il selettore "best available" come funzione compute\_et che riceve i dati meteo disponibili (temperature minima e massima, umidità relativa, vento, radiazione) e i parametri specie (resistenza stomatica e altezza colturale opzionali) e sceglie automaticamente la formula migliore disponibile: prima Penman-Monteith fisico se la specie ha la resistenza stomatica e tutti i dati meteo sono presenti, poi Penman-Monteith standard FAO-56 se solo i dati meteo sono completi, infine Hargreaves-Samani come fallback robusto che richiede solo le temperature. Il risultato include la tracciabilità del metodo usato (EtResult.method) per permettere al chiamante di fare diagnostica del modello.

La sotto-tappa C ha integrato il selettore nel ciclo di vita del Pot e del Garden tramite la nuova dataclass WeatherDay (modulo domain/weather.py) che incapsula i dati meteo giornalieri completi, e i nuovi metodi apply\_balance\_step\_from\_weather (sul Pot) e apply\_step\_all\_from\_weather (sul Garden) che invocano internamente compute\_et con i dati appropriati. I metodi precedenti apply\_balance\_step e apply\_step\_all che ricevono ET₀ pre-calcolato continuano a funzionare invariati per retrocompatibilità.

La sotto-tappa D è la più sostanziosa della tappa 5 e ha introdotto il modello indoor in tre fasi articolate. La fase 1 ha aggiunto le entità di dominio Room (spazio fisico con microclima condiviso) e IndoorMicroclimate (lettura del microclima con varianti INSTANT per il dashboard e DAILY per il bilancio idrico), più l’enum LightExposure a tre livelli (DARK, INDIRECT\_BRIGHT, DIRECT\_SUN) e il modulo science/indoor.py per la radiazione indoor (modi categoriale e continuo). La fase 2 ha esteso il Pot col campo room\_id (riferimento alla Room di appartenenza) e light\_exposure, e ha aggiunto il metodo apply\_balance\_step\_from\_indoor che alimenta il bilancio idrico dal microclima della stanza invece che dal meteo esterno. La fase 3 ha aggiunto l’EcowittAmbientSensor per il sensore WN31 ambientale e il supporto al sensore di substrato WH52 nel EcowittWH51SoilSensor parametrizzato; ha esteso la persistenza SQLite con la tabella delle Room e la mappa Pot → room\_id; ha aggiunto al Garden i metodi di gestione delle Room (add\_room, get\_room, pots\_in\_room, ecc.) e il metodo apply\_step\_all\_from\_indoor.

La sotto-tappa E ha consolidato il lavoro con uno script demo end-to-end (tappa5\_E\_appartamento\_demo.py) che simula un appartamento invernale con tre vasi indoor sparsi tra salotto (Room "salotto" con due vasi) e camera da letto (Room "camera" con un vaso), mostra in azione la selezione automatica del metodo ET, la persistenza completa delle Room nel database SQLite, e produce quattro grafici PNG di analisi (andamento idrico per vaso, bilancio idrico per Room, heatmap dei metodi ET selezionati, confronto dei metodi). I sei test di integrazione associati verificano che lo script gira senza errori, che produce i PNG attesi, che le sezioni di output contengono i pattern attesi, e che la persistenza è round-trip.

## Decisioni architetturali consolidate

Le scelte di design fatte nelle tappe 4 e 5 hanno consolidato le proprietà strutturali che rendono fitosim manutenibile.

- Disaccoppiamento netto tra layer: il modello scientifico vive in science/ e domain/Pot; l’orchestrazione vive in domain/Garden; la persistenza vive in io/persistence e io/serialization che non si conoscono tra loro; le allerte vivono in domain/alerts come funzioni pure indipendenti dal Garden. Ogni layer può essere usato senza i layer superiori.
- Persistenza esplicita e non magica: il Garden in-memory non ha autosave; il chiamante decide quando chiamare persistence.save\_garden(). È più verboso ma non sorprendente, e permette ai test del modello scientifico di restare semplici senza dipendenze SQLite.
- Selettore "best available" con tracciabilità: la tappa 5 ha applicato lo stesso pattern del catalogo specie (cascata di parametri opzionali con fallback automatici) al calcolo di evapotraspirazione. EtResult include il metodo usato così il chiamante può fare diagnostica e calibrazione, e il modello rimane utilizzabile anche con dati meteo incompleti.
- Room come entità di dominio fisica, non logica: la Room non è un raggruppamento arbitrario di vasi ma rispecchia il fatto fisico che il sensore WN31 di Ecowitt misura il microclima di una stanza intera. Cinque vasi che condividono il salotto condividono lo stesso WN31, lo stesso microclima, la stessa Room nel modello.
- Distinzione semantica ET₀ vs ET: il modello distingue rigorosamente tra evapotraspirazione di riferimento (da moltiplicare per Kc) e evapotraspirazione effettiva della specie (già specifica). EtMethod cattura la distinzione e il Pot la gestisce automaticamente, ma il chiamante che consuma direttamente il selettore deve guardare il metodo per decidere se moltiplicare per Kc.
- Idempotenza dei register\_\*: chiamare register\_species, register\_base\_material, register\_substrate o register\_room su un oggetto già registrato aggiorna silenziosamente i parametri. Permette al codice del chiamante di restare lineare senza condizioni speciali.
- Schema versioning con migrazioni automatiche: il database SQLite si aggiorna alla nuova versione del codice senza intervento del chiamante. Il pattern è rodato (v1→v2 channel\_id, v2→v3 scheduled\_events) e l’estensione per le Room della tappa 5 è stata aggiunta con la stessa logica.
- Allerte come vista derivata, non come dato: niente persistenza, niente serializzazione, niente add/cancel. Aggiungere una nuova categoria di allerta in futuro è una funzione pura in più nel modulo alerts.py e una sua aggiunta a ALL\_RULES, niente migrazione di schema.
- Forecast su deep copy senza side effects: il Garden può essere interrogato "se le cose andassero così cosa succederebbe?" senza compromettere il suo stato corrente. È la proprietà che permette al dashboard di mostrare scenari alternativi al giardiniere.

# Roadmap della fascia 2

La fascia 2 è ora completa al 100%. Tutte le cinque tappe sono state portate a termine; non ci sono lavori in sospeso a livello di tappa. Il prossimo passo naturale è l’apertura della fascia 3 di calibrazione contro dati reali.

__Tappa__

__Contenuto__

__Stato__

Tappa 1

Astrazione sensori, Protocol, eccezioni canoniche, adapter Open-Meteo/Ecowitt

Completa

Tappa 2

HttpJsonSoilSensor \+ firmware ESP32 di esempio

Completa

Tappa 3

Modello chimico completo: substrato, fertirrigazione, Kn, feedback loop

Completa

Tappa 4

Garden orchestratore, persistenza SQLite/JSON, sensori in batch, forecast, allerte

Completa

Tappa 5

Penman-Monteith fisico e standard, selettore "best available", modello indoor con Room, sensori WN31 e WH52, demo appartamento

Completa

## Cosa ha portato la tappa 5

La tappa 5 ha chiuso la fascia 2 con un raffinamento del modello scientifico in cinque sotto-tappe progressive. Lo scope della tappa è stato volutamente scientifico — non ha aggiunto nuove capacità applicative ma ha raffinato la qualità delle previsioni del modello esistente, con un’enfasi particolare sui vasi indoor che fino a tappa 4 erano trattati come outdoor con risultati poco realistici. Le capacità nuove introdotte sono articolate in due gruppi complementari: il selettore "best available" dell’evapotraspirazione, e il modello completo dei vasi indoor con la nuova entità Room.

Il primo gruppo riguarda l’introduzione del modello Penman-Monteith per il calcolo dell’evapotraspirazione. La libreria fino a tappa 4 usava la formula di Hargreaves-Samani, robusta perché richiede solo la temperatura ma con un errore tipico del 10-20% rispetto al Penman-Monteith che combina temperatura, umidità relativa, velocità del vento e radiazione solare in un’equazione fisica. La tappa 5 ha introdotto Penman-Monteith in due varianti: la versione FAO-56 standard che produce ET₀ da moltiplicare per il Kc della specie, e la versione fisica che applica direttamente l’equazione alla specie usando la sua resistenza stomatica e produce ET senza bisogno del Kc. Il selettore compute\_et sceglie automaticamente la formula migliore disponibile in funzione dei dati meteo e dei parametri specie presenti, seguendo il pattern "best available" raccomandato dalla pubblicazione FAO-56.

Il secondo gruppo riguarda il modello completo dei vasi indoor. La novità architetturale principale è la nuova entità Room nel modulo domain/room.py, che rappresenta lo spazio fisico (una stanza, una zona di una stanza) in cui vivono uno o più vasi indoor con il loro microclima condiviso. La Room ha un room\_id univoco, un nome leggibile, l’eventuale channel\_id del sensore WN31 mappato, il microclima corrente come stato mutabile, e un default\_wind\_m\_s di 0.5 m/s per rappresentare il vento minimo convettivo della stanza. Il Pot indoor acquisisce un campo opzionale room\_id che lo associa alla sua Room di appartenenza, e un campo opzionale light\_exposure che cattura il livello di esposizione luminosa (DARK, INDIRECT\_BRIGHT, DIRECT\_SUN). Il Garden mantiene una collezione di Room parallela alla collezione di Pot, con i metodi di gestione (add\_room, get\_room, has\_room, remove\_room, room\_ids, iter\_rooms, pots\_in\_room, num\_rooms) e il nuovo metodo apply\_step\_all\_from\_indoor che alimenta il bilancio idrico dei vasi indoor dal microclima delle Room invece che dal meteo esterno.

La tappa 5 ha anche aggiunto il supporto al sensore WH52, che è l’upgrade del WH51 e misura non solo l’umidità volumetrica ma anche la temperatura e l’EC del substrato. L’adapter EcowittWH51SoilSensor è parametrizzato con l’argomento model="WH51" o model="WH52" e popola i campi aggiuntivi del SoilReading solo quando il modello è il WH52. Il WH51 continua a essere supportato indefinitamente per compatibilità con chi ce l’ha già installato. Per il sensore ambientale WN31, è stato aggiunto un adapter dedicato EcowittAmbientSensor con due metodi: current\_state(channel\_id) per la lettura istantanea (kind=INSTANT), e daily\_aggregate(channel\_id, target\_date) per l’aggregato giornaliero (kind=DAILY) che alimenta il bilancio idrico indoor.

Le raffinatezze del modello indoor sono state affrontate con un meccanismo di fallback automatico verso la formula più semplice quando i parametri non sono disponibili. Il riscaldamento è catturato indirettamente attraverso la temperatura misurata dal WN31 (niente da modellare esplicitamente). La ventilazione, che in stanza chiusa è zero, è gestita come "vento minimo convettivo" di 0.5 m/s (default\_wind\_m\_s della Room) per evitare evapotraspirazione irrealisticamente bassa, sovrascrivibile dal chiamante. L’esposizione luminosa è parametrizzata come radiazione solare media giornaliera in MJ/m²/giorno, con tre livelli preimpostati (DARK ≈ 1.5, INDIRECT\_BRIGHT ≈ 4.0, DIRECT\_SUN ≈ 8.0) che il giardiniere attribuisce a ogni vaso in base all’osservazione, con la possibilità di passare alla modalità continua (frazione della radiazione outdoor) quando i dati outdoor sono disponibili.

# Storico delle consegne

Lungo la fascia 2 sono stati prodotti diversi pacchetti zip che hanno permesso di sincronizzare progressivamente il repository sul tuo PC con lo stato di sviluppo. Le consegne attuali sono le seguenti, in ordine cronologico.

__Pacchetto / Tag git__

__Tappa__

__Contenuto__

fitosim\_tappa1\_fascia2\_v2.zip

1

Astrazione sensori, adapter Open-Meteo, Ecowitt, fixture CSV

fitosim\_tappa2\_fascia2.zip

2

HttpJsonSoilSensor \+ firmware ESP32 in 5 file Arduino

fitosim\_tappa3\_complete\_fascia2.zip

3 A-E

Tappa 3 completa: 5 sotto-tappe, 6 file modificati

fitosim\_tappa3\_F\_fascia2.zip

3 F

Coefficiente esposizione pioggia, 2 file modificati

fitosim\_tappa4\_A\_fascia2.zip

4 A

Garden in-memory orchestratore

fitosim\_tappa4\_B1\_fascia2.zip

4 B1

Persistenza SQLite con schema a 8 tabelle

fitosim\_tappa4\_B2\_fascia2.zip

4 B2

Serializzazione JSON come trasporto

fitosim\_tappa4\_C\_fascia2.zip

4 C

Integrazione sensori in batch \+ migrazione schema v2

fitosim\_tappa4\_D\_fascia2.zip

4 D

Eventi pianificati e forecast \+ migrazione schema v3

fitosim\_tappa4\_E\_fascia2.zip

4 E

Sistema di allerte con cinque categorie

fitosim\_tappa4\_demo.zip

Demo

Esempio end-to-end della tappa 4 completa

v0\_19  (tag git)

5 A

Penman-Monteith ET₀ come funzioni pure (FAO-56 standard e fisico)

v0\_19\_1 (tag git)

5 B

Selettore "best available" compute\_et con EtResult/EtMethod

v0\_19\_2 (tag git)

5 C

Integrazione del selettore nel Pot e nel Garden via WeatherDay

v0\_19\_3 (tag git)

5 D-1

Entità Room con IndoorMicroclimate, MicroclimateKind, LightExposure

v0\_19\_4 (tag git)

5 D-2

Bilancio idrico indoor: apply\_balance\_step\_from\_indoor sul Pot, modulo science/indoor.py

v0\_19\_5 (tag git)

5 D-3

Persistenza Room, EcowittAmbientSensor (WN31), supporto WH52

v0\_19\_6 (tag git)

5 E

Demo end-to-end appartamento invernale con quattro grafici PNG di analisi

v0\_20 – v0\_20\_1 (15 maggio)

sensori

Spec sensori v1 (`Measurement` canonico); `shelter_level` sul vaso

v0\_21 – v0\_30 (18–22 luglio)

fascia 3, fase A

Kc dalla pendenza del sensore; ancoraggio fenologico doppio e vocabolario botanico; dormienza; gradi-giorno; schema v5; JSON v3; calibrazione comportamentale; soglia dai giudizi; lisimetro; precedenza tra fonti

5 settembre

chioma (H.1-c)

Copertura e altezza della pianta nel Kc e in Penman-Monteith; schema v6

11–19 settembre

Ecowitt e The Pot

WH52 nella sua sezione con le unità metriche; history con il vento; i due pluviometri; il catalogo ufficiale è quello di The Pot; procedura e strumento di calibrazione sul WH52

18–20 settembre

modello

Kn solo per eccesso di sali (eq. 83) e pH fuori dal Kn; CEC e densità dal catalogo (v7); `p` come prior e Kc senza stress; pendenza salina per specie (v8); dormienza = suolo nudo; via lo scheduler; versione 0.31.0

22 settembre

modello

i serbatoi nutritivi N, P₂O₅, K₂O (`science/nutrients.py`, versione 0.32.0) e la sonda EC che corregge i sali (`science/soil_ec.py`, `Pot.update_from_ec_sensor`, versione 0.33.0)

29 settembre

modello

il giorno fatto di blocchi (A7): il vaso avanza a ore dentro il giorno, il passo giornaliero è un blocco di 24 ore, nove decisioni con le fonti in `domain/blocks.py`; l'esempio delle stagioni; versione 0.34.0

21 ottobre

strumento

la calibrazione legge dall'app (fase 1 ridefinita, in The Pot): `services/calibrazione_fitosim.py` e `--dal-db`; in fitosim solo la documentazione (`calibrazione_con_WH5X.md`)

21 ottobre

modello

B5: densità, pH e CEC del mix da `compose_substrate`, con le formule del catalogo di The Pot (A1); il seed e i substrati personali chiamano fitosim; nessun numero cambia

21 ottobre

modello

la colonna, solo la matematica: `science/retention.py` — la capacità di contenitore dalla curva di ritenzione (van Genuchten, anche da due punti del catalogo; o per punti), lo spazio d'aria, il profilo lungo la colonna; non collegata al vaso; versione 0.35.0

21 ottobre

modello

A9: e_s ed e_a dagli estremi del giorno nel Penman-Monteith giornaliero: la media di e°(T_max) ed e°(T_min) (FAO-56 eq. 12) al posto di e°(T_media), che la sottostima, ed e_a dalle umidità estreme (eq. 17) quando la stazione le dà, dalla media (eq. 19) altrimenti; `WeatherDay` ha `humidity_min` e `humidity_max`; la forma oraria non cambia; versione 0.35.0

21 ottobre

app

E.10-a in The Pot: il giorno a blocchi nei servizi dell'app — `services/blocchi.py` e `idrica_service._a_blocchi`, la stazione, le ore di Open-Meteo e il profilo del sole, `Pot.apply_step_blocks` ed `et0_for_blocks` di A7; in fitosim nessun cambiamento

Da settembre le consegne non hanno più un numero nel titolo del commit: la versione si alza in `pyproject.toml`, e il repository è condiviso con The Pot, che monta fitosim come dipendenza editabile.

I tag git della tappa 5 corrispondono alle sotto-tappe progressive: ognuno aggiunge capacità senza rompere quelle precedenti, esattamente come avveniva con i pacchetti incrementali della tappa 4. Per integrare l’ultimo stato del codice nel repository, basta fare git checkout v0\_19\_6 (o checkout di main se il main è stato aggiornato). I quattro PNG prodotti dalla demo della sotto-tappa E vivono in examples/ (tappa5\_E\_andamento\_idrico.png, tappa5\_E\_bilancio\_per\_ambiente.png, tappa5\_E\_heatmap\_et.png, tappa5\_E\_metodi\_et.png) e mostrano in modo immediato il tipo di analisi che il modello indoor permette.

# Quadro operativo per il tuo balcone (e per il tuo appartamento)

Lo stato attuale della libreria ti permette di costruire un dashboard operativo completo non solo per il balcone outdoor ma anche per i vasi indoor sparsi tra le stanze dell’appartamento, con tutte le capacità necessarie. Concretamente puoi fare le cose seguenti.

Puoi creare un Garden col nome del tuo balcone (oppure del tuo appartamento, oppure un Garden ibrido che li copre entrambi) e aggiungere i tuoi vasi reali con tutte le loro caratteristiche (volume, diametro, esposizione al sole, esposizione alla pioggia per i vasi outdoor; room\_id e light\_exposure per i vasi indoor). Per ogni vaso puoi configurare la specie e il substrato (anche con misture personalizzate), il modello chimico se la specie ha i range definiti, e mappare il vaso al canale del sensore di substrato se ne ha uno collegato (WH51 per il modello base, WH52 per il modello con temperatura ed EC del substrato).

Per i vasi indoor, puoi creare le Room corrispondenti alle stanze del tuo appartamento (per esempio "salotto", "camera-da-letto", "studio") con il loro nome, il channel\_id del sensore WN31 ambientale di quella stanza, e l’eventuale default\_wind\_m\_s personalizzato se hai un ventilatore acceso costantemente. I vasi indoor si associano alla loro Room tramite il campo room\_id; la libreria gestisce automaticamente l’aggiornamento del microclima della Room dal sensore WN31 e l’applicazione del bilancio idrico ai vasi della Room dal microclima della stanza.

Puoi salvare il Garden in un database SQLite locale che vivrà sul tuo Raspberry Pi 5 o sull’Android in Termux. Ogni save\_garden aggiunge uno snapshot dello stato dei vasi alla tabella pot\_states, preservando la storia per i grafici di evoluzione. Il database persiste anche le Room con i loro parametri e le mappe Pot → room\_id; il Garden può essere esportato in JSON per backup o per migrare tra ambienti, e ricaricato senza perdita di informazioni.

Puoi aggiornare in batch tutti i vasi mappati dai sensori reali con una singola chiamata a update\_all\_from\_sensors, e gestire automaticamente gli errori transitori (batteria scarica del WH51) senza bloccare il sistema. Per i vasi indoor, puoi aggiornare le Room dai sensori WN31 in modo simmetrico tramite EcowittAmbientSensor.daily\_aggregate, e poi applicare il bilancio idrico ai vasi della Room con apply\_step\_all\_from\_indoor. Puoi pianificare fertirrigazioni e altri eventi futuri come ScheduledEvent, e produrre una previsione dello stato dei vasi a N giorni che incorpora gli eventi pianificati e il forecast meteo da Open-Meteo.

Puoi infine ottenere allerte strutturate sullo stato corrente del giardino (current\_alerts), con cinque categorie e tre severità, e allerte previste nei prossimi giorni (forecast\_alerts) per una gestione proattiva. Il dashboard "Il Mio Giardino" può presentare al giardiniere queste allerte come notifiche con icone diverse per severità, ognuna con un message descrittivo e una recommended\_action concreta da fare.

Quando avrai dati reali raccolti dai tuoi sensori per qualche settimana, cominceremo le prime calibrazioni della fascia 3: confronto sistematico tra previsioni del modello e letture del sensore, identificazione dei parametri (CEC, densità del substrato, range di Kc, frazioni della radiazione indoor, resistenza stomatica delle specie) che producono il fit migliore. È questo che trasforma fitosim da "libreria genericamente plausibile" a "libreria calibrata per il TUO balcone milanese".

# Considerazioni finali

Il progetto è in salute, e la fascia 2 si chiude in uno stato pulito e coerente. La copertura dei test è alta (1007 verdi, 1 skipped intenzionale, 357 sub-test) e la suite continua a girare in poco più di dieci secondi; la retrocompatibilità è preservata strettamente attraverso tutte le tappe (le 423 prove originali della fascia 1 continuano a passare al byte ad ogni nuova consegna, così come i 442 test delle tappe 1-4); l’architettura modulare con separazione rigorosa tra modello scientifico (modulo science/), oggetti di dominio (modulo domain/) e adapter di acquisizione e persistenza (modulo io/) ha pagato concretamente nelle tappe più complesse, in particolare nella tappa 5 dove l’introduzione di Penman-Monteith e del modello indoor avrebbe richiesto refactoring profondi se l’architettura non fosse stata modulare.

L’aspetto che merita di essere sottolineato dopo la chiusura della fascia 2 è che le decisioni di design prese nelle prime tappe stanno rendendo possibili le tappe successive senza frizioni. Il Protocol dei sensori della tappa 1 ha reso meccanica la scrittura dell’orchestratore update\_all\_from\_sensors della sotto-tappa 4-C, e la stessa cosa è successa per il sensore WN31 ambientale e per l’aggiornamento del microclima delle Room nella sotto-tappa 5-D. La separazione tra apply\_balance\_step (idrico) e apply\_step (orchestratore) ha permesso al forecast della sotto-tappa 4-D di applicare tutti gli eventi del giorno simulato senza riimplementare nessuna logica scientifica, e ha permesso al apply\_balance\_step\_from\_indoor della sotto-tappa 5-D di alimentare il bilancio idrico dal microclima della Room senza toccare nulla del modello scientifico sottostante. È un esempio concreto di come il lavoro architetturale ben fatto all’inizio paghi nel medio termine.

I prossimi passi sono nell’ordine di importanza decrescente. Il primo è consolidare lo stato attuale facendolo girare in produzione sul Raspberry Pi 5 (o sull’Android in Termux) con i vasi reali del tuo balcone e del tuo appartamento, e raccogliere dati dai sensori reali per qualche settimana. Il secondo è eseguire la demo end-to-end dell’appartamento invernale (tappa5\_E\_appartamento\_demo.py) per avere un’intuizione concreta di come il modello indoor risponde a scenari diversi (microclima freddo vs caldo, esposizione luminosa diversa, presenza/assenza di sensori). Il terzo è cominciare a costruire il dashboard operativo "Il Mio Giardino" con i vasi reali, salvando lo stato in SQLite e raccogliendo i primi dati dal sensore ATO via gateway ESP32 quando l’hardware sarà operativo. Il quarto è aprire la fascia 3 di calibrazione quando avremo qualche mese di dati reali raccolti, per raffinare i numeri specifici del modello (frazioni della radiazione indoor, parametri Kc del catalogo specie, soglie del selettore, resistenza stomatica delle specie con dati reali) e trasformare fitosim da "libreria genericamente plausibile" a "libreria calibrata per il TUO balcone milanese".

