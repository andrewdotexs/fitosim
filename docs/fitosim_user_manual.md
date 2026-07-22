__fitosim__

*Manuale utente*

Una guida pratica per usare fitosim nel tuo giardino domestico

*Dall’installazione al primo “hello basilico”, dai concetti fondamentali al dashboard operativo del balcone. Diciassette capitoli più tre appendici per orientarti tra vasi, substrati, sensori, persistenza, eventi e allerte.*

*Maggio 2026 — Contenuti a fine fascia 2 (tappa 5). Numeri e riferimenti (test, schema DB, calibrazione) riallineati a luglio 2026, con la fascia 3 in corso.*

# 1 — Benvenuto in fitosim

fitosim è una libreria Python che ti aiuta a capire quanto e quando irrigare le piante nei tuoi vasi. Funziona modellando il bilancio idrico e chimico del singolo vaso giorno per giorno: quanta acqua entra (pioggia, irrigazione), quanta esce (evaporazione dal substrato, traspirazione della pianta), quanta resta disponibile alla pianta stessa, e come evolve la concentrazione di sali e il pH del substrato. Ti dà una stima quantitativa di quando il vaso si sta avvicinando alla soglia di stress idrico o chimico, in modo che tu possa pianificare gli interventi con un pizzico di anticipo invece di reagire al “lo vedo che soffre”.

Sotto il cofano fitosim implementa il modello FAO-56, lo standard agronomico internazionale per l’evapotraspirazione delle colture, con sei estensioni specifiche per il dominio dei vasi domestici che i modelli per il pieno campo non coprono. Tutta la matematica è dentro alla libreria — tu come utente vedi solo oggetti Python comodi: un Pot, una Species, un Substrate, un Garden che li orchestra, qualche metodo da chiamare, e dei numeri sensati che escono dall’altra parte.

## Per chi è questo manuale

Questo manuale è scritto pensando a tre tipi di utenti che si sovrappongono in modo naturale. Il primo è il giardiniere tecnologicamente curioso che ha già una stazione meteo Ecowitt sul balcone, dei sensori di umidità WH51 nei vasi, e si chiede se tutti quei dati possano servire a qualcosa di più che riempire una dashboard. Il secondo è lo sviluppatore che sta costruendo un sistema di monitoraggio o di automazione del giardino domestico e cerca un motore agronomico solido da integrare come libreria di backend. Il terzo è lo studioso del verde — bonsaista, coltivatore di succulente, orticoltore da balcone — che vuole capire quantitativamente come i parametri del proprio setup influenzino il fabbisogno idrico delle sue piante.

Quello che il manuale dà per scontato è una conoscenza di base di Python e una familiarità minima con il vocabolario agronomico (l’appendice C ha un glossario per rinfrescarti la memoria). Quello che NON dà per scontato è che tu sappia scrivere FAO-56 a memoria: tutto quello che serve sapere è spiegato man mano che serve, e le decisioni di design sono giustificate quando introducono qualche scelta non ovvia.

## Cosa fitosim NON fa

È utile mettere subito in chiaro i confini del dominio. fitosim non è un sostituto di modelli idrologici di pieno campo come HYDRUS o RZWQM, che gestiscono bilanci a scala di parcella con flussi orizzontali tra suoli adiacenti — il modello del singolo vaso ignora deliberatamente questi effetti perché in un contenitore isolato non esistono. Non è un sistema di controllo in tempo reale: le sue stime sono giornaliere, non al minuto. Non è infine un sostituto del giardiniere: ti dice “il vaso è sceso sotto la soglia di allerta”, non “irriga adesso 250 ml” senza che tu abbia la possibilità di valutare le condizioni reali del momento.

Il dominio in cui fitosim sa fare bene il suo lavoro è il vaso domestico singolo o un piccolo gruppo di vasi su un balcone, su scala di tempo giornaliera, per piante individualmente identificabili e con substrati di parametri noti. In questo dominio specifico fitosim copre molto: caratterizzazione fisica dei contenitori, modelli di sottovaso, ricette di substrato personalizzate, dinamica a due fasi dell’evaporazione, modello chimico completo, calibrazione dai sensori, orchestrazione di più vasi, persistenza della storia in database, previsioni a N giorni con eventi pianificati, e sistema di allerte. Tutto quello che vedrai vive dentro a questo perimetro.

## Filosofia: opt-in con default neutri

Una caratteristica importante di fitosim che incontrerai ripetutamente è che ogni capacità avanzata è “opt-in”: se non la vuoi, non la attivi, e il sistema continua a funzionare come se non esistesse. Vuoi modellare il sottovaso? Aggiungi un parametro al tuo Pot. Hai un sensore di umidità? Chiama il metodo che lo integra. Vuoi gestire più vasi insieme? Crea un Garden. Ti basta un vaso solo? Continua a usare il Pot direttamente. Questa scelta architetturale ti permette di partire semplice e aggiungere complessità solo quando ne vedi il bisogno.

## Mappa del manuale

Il manuale è organizzato per costruire la tua competenza progressivamente. Il capitolo 2 ti mette in piedi l’ambiente di lavoro e ti fa scrivere il tuo primo “hello basilico”. Il capitolo 3 spiega i concetti fondamentali (la trinità Pot-Species-Substrate, lo stato idrico, le soglie di allerta), che sono il vocabolario di base che ti porterai dietro per tutto il resto del manuale.

I capitoli da 4 a 8 sviluppano una a una le capacità avanzate del modello scientifico del singolo vaso: caratterizzazione del vaso, sottovaso, sostrati personalizzati, dual-Kc, calibrazione empirica e feedback dal sensore. Il capitolo 9 è un primo ricettario di quattro casi d’uso end-to-end del singolo vaso.

I capitoli da 10 a 15 sono il salto qualitativo verso il dashboard operativo del balcone: il Garden orchestra più vasi insieme (cap 10), la persistenza SQLite conserva la storia (cap 11), il backup JSON permette il trasporto (cap 12), i sensori vengono integrati in batch (cap 13), gli eventi pianificati e le previsioni a N giorni anticipano gli interventi (cap 14), e il sistema di allerte trasforma le previsioni in raccomandazioni concrete (cap 15).

Il capitolo 16 è una ricetta end-to-end del balcone completo che usa tutte le capacità viste nei capitoli 10-15 in uno scenario realistico di tre vasi monitorati per tre settimane. I capitoli 17 e 18 introducono le novità della tappa 5: il selettore di evapotraspirazione “best available” che sceglie automaticamente tra Penman-Monteith fisico, Penman-Monteith standard FAO-56 e Hargreaves-Samani in funzione dei dati disponibili (cap 17), e il modello completo dei vasi indoor con l’entità Room, il sensore ambientale WN31 e l’esposizione luminosa parametrizzata a tre livelli (cap 18). Il capitolo 19 raccoglie le domande frequenti. Le tre appendici contengono il catalogo delle specie pre-definite, dei substrati e materiali base disponibili, e un glossario dei termini agronomici.

Non devi leggere il manuale in ordine se hai fretta. Se vuoi subito vedere fitosim in azione, salta direttamente al capitolo 9 (singolo vaso) o al capitolo 16 (balcone completo). Se invece vuoi capire fitosim in profondità, leggi nell’ordine proposto.

# 2 — Installazione e primi passi

## Cosa ti serve

fitosim richiede Python 3.10 o superiore. La libreria è stata scritta in modo da non avere dipendenze esterne nel suo nucleo: tutto il codice agronomico, dal calcolo dell’ET₀ alla calibrazione empirica al Garden orchestratore alla persistenza SQLite, gira con la sola standard library di Python. Per il normale uso del motore agronomico, l’installazione è leggera e porta benissimo su ambienti vincolati come Termux su Android o Raspberry Pi 5.

## Installazione

Per ora fitosim è distribuito come repository sorgente. Una volta scaricato il progetto, posizionati nella sua directory principale e verifica che la suite di test giri correttamente. È il modo migliore per assicurarti che il tuo ambiente Python sia configurato bene:

$ cd fitosim/

$ python -m pytest tests/ --ignore=tests/test_demo_appartamento.py

================= 1366 passed, 428 subtests passed =================

Se vedi un risultato simile (al momento di questo aggiornamento la suite del core conta 1366 test verdi più 428 sub-test), tutto è a posto e puoi proseguire. Il core gira con la sola standard library: la sola demo end-to-end tappa5\_E usa matplotlib, per questo qui la escludiamo; se vuoi eseguirla installa gli extra con pip install -e '.[dev]'. I test coprono la fascia 1 e la fascia 2, più la fascia 3 (il layer di feedback, vedi il manuale di calibrazione). Se vedi errori di import, è possibile che la directory src/ non sia nel tuo path: ricorda di lanciare gli script con PYTHONPATH=src impostato, oppure di installare la libreria in modalità sviluppo con pip install -e .

__*Nota: *__*Se preferisci non manipolare PYTHONPATH ogni volta, l’installazione in modalità sviluppo (pip install -e .) crea un link simbolico nel tuo virtual environment che rende fitosim importabile da qualsiasi script senza configurazione aggiuntiva.*

## Hello basilico: il tuo primo vaso simulato

Per essere sicuro che fitosim funzioni nel tuo ambiente, scrivi questo piccolo script che crea un vaso di basilico, simula un giorno di evapotraspirazione, e stampa lo stato risultante:

from datetime import date

from fitosim.domain.pot import Location, Pot

from fitosim.domain.species import BASIL

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

vaso = Pot(

    label="Basilico balcone-1",

    species=BASIL,

    substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=2.0,

    pot\_diameter\_cm=18.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

)

print(f"Stato iniziale: {vaso.state\_mm:.1f} mm")\[continua…\]

print(f"Soglia di allerta: {vaso.alert\_mm:.1f} mm") \[continua…\]

vaso.apply\_balance\_step(

    et\_0\_mm=4.0, water\_input\_mm=0.0,

    current\_date=date(2026, 4, 2),

)

print(f"Dopo un giorno di sole: {vaso.state\_mm:.1f} mm")

Se l’output che vedi ha tre righe coi numeri delle soglie e dello stato dopo un giorno, fitosim è installato correttamente e tu hai appena scritto e fatto girare il tuo primo modello agronomico. Nel resto del manuale costruiremo sopra questo esempio sempre più sofisticatezza: aggiungeremo il modello chimico, il sensore reale, l’orchestrazione di più vasi, la persistenza, le previsioni e le allerte. Ma l’idea di base resta quella che hai appena visto.

# 3 — I concetti fondamentali

Prima di addentrarsi nelle capacità avanzate, vale la pena fissare il vocabolario di base di fitosim. Questo capitolo introduce le tre classi che incontrerai ovunque, lo stato idrico del vaso, le soglie operative, e il bilancio giornaliero che è il motore del modello.

## La trinità: Pot, Species, Substrate

fitosim modella ogni vaso come la composizione di tre concetti distinti. Il Pot è il vaso fisico: ha un volume, una geometria, un’esposizione, e contiene lo stato dinamico (acqua e sali correnti). La Species è la pianta che cresce dentro: ha i suoi coefficienti colturali (Kc), il suo depletion fraction, gli stadi fenologici, e opzionalmente i range chimici (EC e pH ottimali per il modello chimico). Il Substrate è il terriccio: ha i suoi parametri idrici (theta\_FC, theta\_PWP), la capacità di scambio cationico CEC, e il pH tipico.

La distinzione è significativa perché ti permette di combinare le tre classi in modo indipendente: lo stesso basilico (Species) può essere coltivato in vasi di tipi diversi (Pot) con substrati diversi (Substrate), e fitosim calcola le evoluzioni di ogni combinazione separatamente. Vedremo nei prossimi capitoli come si caratterizza il vaso, come si compongono substrati personalizzati, e come si scelgono le specie più adatte.

## Lo stato idrico: state\_mm e state\_theta

Lo stato idrico del Pot è memorizzato nel campo state\_mm, espresso in millimetri di lama d’acqua sull’area attiva del vaso. È la grandezza canonica usata internamente dal modello FAO-56. Per consultarlo in modo “umano” fitosim espone anche state\_theta, che è il contenuto idrico volumetrico (frazione 0..1), comparabile direttamente con le letture del sensore WH51 e con i parametri theta\_FC e theta\_PWP del substrato. Le due grandezze sono legate dalla profondità attiva del substrato: state\_theta = state\_mm / (active\_depth\_cm \* 10).

## Le tre soglie operative

fitosim espone tre soglie operative come property derivate dal Pot e dalla Species. fc\_mm è la capacità di campo: lo stato del vaso quando è completamente idratato dopo drenaggio. pwp\_mm è il punto di appassimento permanente: la soglia sotto la quale la pianta non riesce più ad estrarre acqua dal substrato. alert\_mm è la soglia operativa di irrigazione: il valore intermedio sotto al quale fitosim raccomanda di irrigare prima che la pianta entri in stress significativo. La sua posizione esatta dipende dal depletion\_fraction della Species (più alto è il depletion, più bassa è la soglia).

## Il bilancio giornaliero

Il cuore del modello è il metodo apply\_balance\_step del Pot, che evolve lo stato del vaso di un giorno. Riceve l’ET₀ del giorno (calcolata dal meteo), un eventuale input idrico (pioggia \+ irrigazione, in mm), e la data corrente. Aggiorna state\_mm, salt\_mass\_meq e ph\_substrate applicando il modello FAO-56 esteso. Tutto il manuale che segue è una sequenza di esempi che chiamano apply\_balance\_step in scenari diversi.

Per simulare più giorni di seguito basta un loop: per ogni giorno fornisci ET₀ e input idrico, chiama apply\_balance\_step, e leggi lo stato risultante. È esattamente il pattern che hai visto nell’hello basilico, esteso a una settimana di simulazione:

from datetime import date, timedelta

oggi = date(2026, 4, 1)

for i in range(7):

    giorno = oggi \+ timedelta(days=i)

    et\_0 = previsione\_et\_0\[i\]    \# dalla tua stazione meteo

    pioggia = previsione\_pioggia\[i\]

    vaso.apply\_balance\_step(

        et\_0\_mm=et\_0,

        water\_input\_mm=pioggia,

        current\_date=giorno,

    )

    print(f"{giorno}: {vaso.state\_mm:.1f} mm")

Questo è il motore che fa girare tutto il resto. Quando vedrai il Garden orchestrare più vasi, o le previsioni a 7 giorni, o le allerte, sotto sotto sarà sempre apply\_balance\_step a essere chiamato per ogni vaso e per ogni giorno.

# 4 — Caratterizzare il vaso

Nel capitolo 2 hai creato un Pot fornendo solo i parametri minimi: specie, substrato, volume, diametro. Quei parametri bastano per una simulazione di base, ma ignorano tre caratteristiche fisiche del contenitore che hanno un impatto significativo sul fabbisogno idrico reale: il materiale del vaso, il suo colore, e la sua esposizione solare. La differenza tra un vaso di plastica chiara in ombra parziale e un vaso di terracotta scura al pieno sole, a parità di tutto il resto, può essere di un fattore otto sulle irrigazioni richieste in un mese.

## Il coefficiente di vaso Kp

fitosim modula l’evapotraspirazione attraverso un coefficiente moltiplicativo chiamato Kp, prodotto di tre fattori: materiale, colore, esposizione. Tu li dichiari con tre enum:

from fitosim.domain.pot import (

    Location, Pot, PotMaterial, PotColor, SunExposure,

)

from fitosim.domain.species import BASIL

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

from datetime import date

vaso\_caldo = Pot(

    label="Basilico balcone-sud",

    species=BASIL,

    substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

    pot\_material=PotMaterial.TERRACOTTA,

    pot\_color=PotColor.DARK,

    sun\_exposure=SunExposure.FULL\_SUN,

)

print(f"Kp di questo vaso: {vaso\_caldo.kp:.2f}")

>>> Kp di questo vaso: 1.43

Il valore Kp di 1.43 dice che questo vaso consuma il 43% in più di acqua di un vaso “neutro” di plastica media in pieno sole. Lo stesso vaso di plastica chiara in ombra parziale avrebbe Kp di circa 0.77. fitosim applica Kp automaticamente in apply\_balance\_step: tu lo dichiari una volta nel costruttore del Pot e da quel momento in avanti tutto il resto del codice è invariato.

## La forma geometrica

Fitosim ti permette di dichiarare la forma geometrica del vaso. Le quattro forme supportate sono cilindrica (default), tronco di cono, rettangolare e ovale. Le geometrie diverse hanno proporzioni superficie/volume diverse e quindi comportamenti idrici diversi a parità di volume.

from fitosim.domain.pot import PotShape

\# Una cassetta rettangolare per insalate.

cassetta = Pot(

    label="Lattuga davanzale",

    species=LETTUCE, substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=4.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

    pot\_shape=PotShape.RECTANGULAR,

    pot\_length\_cm=40.0, pot\_width\_cm=18.0,

)

__*Nota: *__*Quando ometti pot\_shape, fitosim assume CYLINDRICAL e ti chiede solo pot\_diameter\_cm. Per le altre forme servono parametri aggiuntivi: la cassetta vuole lunghezza e larghezza, il tronco di cono vuole anche il diametro inferiore, l’ovale vuole entrambi gli assi.*

## La frazione attiva del substrato

Quando hai un vaso alto, l’acqua che si accumula in fondo tende a formare una zona satura che le radici evitano. Solo la frazione superiore del substrato — quella effettivamente colonizzata dalle radici — partecipa alla simulazione. fitosim ti permette di dichiarare questa frazione attiva con il parametro active\_depth\_fraction, che vale 1.0 di default e può essere ridotto a valori come 0.7 per vasi profondi e plantule giovani che non hanno ancora colonizzato il fondo.

# 5 — Il sottovaso

Il sottovaso è una capacità opt-in che modella esplicitamente la riserva d’acqua che si accumula nel sottovaso quando irrighi abbondantemente, e da cui il substrato può attingere per capillarità nei giorni successivi. È un comportamento importante per i vasi di piante delicate che il giardiniere irriga “con abbondanza” una volta a settimana invece che “giusto quanto basta” ogni giorno.

## Quando attivare il sottovaso nel modello

Per attivare il modello del sottovaso, dichiari la sua capacità in litri quando costruisci il Pot:

vaso = Pot(

    label="Basilico con sottovaso",

    species=BASIL, substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

    saucer\_capacity\_l=0.5,

)

Da quel momento il modello tiene traccia di un secondo stato (saucer\_state\_mm) che rappresenta l’acqua presente nel sottovaso. Quando irrighi e l’eccedenza supera la capacità di campo del substrato, l’eccesso scorre nel sottovaso. Nei giorni successivi, se il substrato si abbassa sotto la capacità di campo, l’acqua del sottovaso risale per capillarità riempiendo il deficit. Il sottovaso ha anche la sua evaporazione propria.

## Cosa succede dopo che hai dichiarato il sottovaso

Tutta la logica del sottovaso è gestita automaticamente da apply\_balance\_step: tu continui a chiamarlo come prima, e il modello si occupa dei trasferimenti capillari, delle evaporazioni separate, e del drenaggio del sottovaso quando l’acqua supera la sua capacità. Puoi consultare lo stato del sottovaso in saucer\_state\_mm e saucer\_state\_l.

# 6 — Sostrati personalizzati

Il catalogo di substrati pre-configurati di fitosim copre i tipi più comuni del giardinaggio domestico, ma se sei un coltivatore esperto vorrai certamente comporre il tuo mix personalizzato. Pensa al bonsaista che mescola akadama, pomice e lapillo in proporzioni precise, o al collezionista di succulente che preferisce un mix minerale ad alto drenaggio. fitosim ti dà gli strumenti per definire questi mix esplicitamente.

## Il catalogo dei nove materiali base

Il modulo fitosim.science.substrate espone nove materiali base pre-caratterizzati: TORBA\_BIONDA, COMPOST, PERLITE, VERMICULITE, AKADAMA, POMICE, LAPILLO, SABBIA, ARGILLA. Ognuno ha i suoi parametri idrici (theta\_FC, theta\_PWP), la sua densità apparente, e la sua CEC. Sono i mattoni con cui costruire mix personalizzati.

## Comporre un mix personalizzato

Per comporre un mix usi la factory function compose\_substrate, passando un dict con le frazioni di ogni materiale base (la somma deve essere 1.0):

from fitosim.science.substrate import (

    compose\_substrate, AKADAMA, POMICE, LAPILLO,

)

\# Mix bonsai classico: akadama 40%, pomice 30%, lapillo 30%.

mix\_bonsai = compose\_substrate(

    name="Mix bonsai personalizzato",

    components={

        AKADAMA: 0.40,

        POMICE: 0.30,

        LAPILLO: 0.30,

    },

)

print(f"theta\_FC del mix: {mix\_bonsai.theta\_fc:.3f}")

I parametri del mix sono calcolati come medie ponderate dei parametri dei componenti base. Il mix risultante è un Substrate ordinario che puoi usare come qualsiasi altro substrato del catalogo.

# 7 — Quando il single Kc non basta

Il modello FAO-56 “semplice” usa un singolo coefficiente colturale Kc che moltiplica l’ET₀ per ottenere l’ET effettiva del vaso. È un’approssimazione che funziona benissimo per la maggior parte dei casi, ma nasconde una dinamica importante: dopo un’irrigazione la superficie del substrato è bagnata e contribuisce molto all’evaporazione totale; dopo qualche giorno la superficie si asciuga e quasi tutta l’ET viene dalla traspirazione. Il dual-Kc separa esplicitamente queste due componenti.

## Il dual-Kc di FAO-56 capitolo 7

Per attivare il dual-Kc, devi avere Species e Substrate entrambi caratterizzati per il dual-Kc: la Species deve avere i Kcb (basal, traspirativi) oltre ai Kc, e il Substrate deve avere REW (readily evaporable water) e TEW (total evaporable water). Quando entrambi sono presenti, fitosim usa automaticamente il modello dual-Kc; altrimenti ricade sul single-Kc.

vaso = Pot(label="Basilico dual-Kc", species=BASIL, ...)

print(f"Dual-Kc attivo: {vaso.is\_dual\_kc\_active}")

## Quando ti serve davvero il dual-Kc

Il dual-Kc è particolarmente utile quando vuoi modellare con accuratezza i giorni immediatamente successivi a un’irrigazione abbondante (dove l’evaporazione superficiale domina) o quando hai dati di sensore che mostrano oscillazioni rapide post-irrigazione che il single-Kc non riproduce. Per la pianificazione settimanale del giardiniere medio, il single-Kc è adeguato e il dual-Kc è una raffinatezza.

# 8 — Imparare dal sensore

Il modello fitosim, fino al capitolo precedente, ha funzionato a “ciclo aperto”: prendi parametri, fornisci forzanti meteo, produci previsioni. Funziona bene se i parametri sono accurati. Nella realtà i parametri di letteratura possono differire del 10-30% dai parametri reali del tuo vaso specifico. Quando hai un sensore di umidità del suolo come il WH51, puoi chiudere il cerchio in due modi complementari: calibrare i parametri dalle letture storiche, e iniettare letture giornaliere per tenere il modello allineato.

Questo capitolo copre la calibrazione dal sensore, che è dove il ciclo chiuso è nato. La fascia 3 l’ha poi generalizzata in un **layer di feedback multi-fonte**: oltre alla pendenza del sensore per il Kc, ci sono il lisimetro (pesata del vaso come misura diretta e di riferimento), i gradi-giorno per la fenologia, e la calibrazione comportamentale per i vasi senza sensore, più una regola che le compone quando più fonti toccano lo stesso parametro. Se il sensore non c’è, insomma, non sei tagliato fuori dalla calibrazione. Il percorso operativo completo è nel *Manuale di calibrazione* (`docs/fitosim_calibration_manual.md`); il progetto del layer in `docs/fitosim_feedback_layer_design.md`.

## Calibrazione dei parametri dalle letture storiche

Se hai sei mesi di letture WH51 di un vaso, fitosim può ricavare i suoi parametri “veri” — theta\_FC e theta\_PWP effettivi del tuo vaso — analizzando la serie storica. Ogni irrigazione abbondante crea un picco che, dopo il drenaggio, si attesta intorno alla capacità di campo effettiva; ogni asciugamento crea una valle che è almeno un limite superiore del PWP.

from fitosim.science.calibration import calibrate\_substrate

from fitosim.science.substrate import Substrate

letture\_theta = \[0.42, 0.40, 0.36, ...\]  \# 60\+ giorni

risultato = calibrate\_substrate(

    theta\_series=letture\_theta,

    name="vaso-1 calibrato 2026-04",

)

print(f"theta\_FC stimato: {risultato.theta\_fc\_estimate:.3f}")

print(f"Confidenza FC: {risultato.confidence\_fc}")

__*Nota: *__*L’asimmetria FC-PWP è la lezione più sottile della calibrazione. La stima di theta\_FC è precisa: ogni irrigazione crea un picco e con molti picchi convergi sul valore vero. La stima di theta\_PWP è invece intrinsecamente un LIMITE SUPERIORE: il giardiniere attento irriga prima che la pianta soffra, quindi il sensore non vede mai il vero appassimento. Per FC fidati della calibrazione; per PWP usala come sanity check insieme al valore di letteratura.*

## Aggiornamento dal sensore in tempo reale

La calibrazione storica migliora i parametri ma non elimina il drift accumulato. Il metodo update\_from\_sensor ti permette di iniettare una lettura corrente nel modello, che si allinea immediatamente alla realtà osservata e ti restituisce un report diagnostico:

risultato = vaso.update\_from\_sensor(theta\_observed=0.31)

print(f"Modello prevedeva: {risultato.predicted\_theta:.4f}")

print(f"Sensore osserva:   {risultato.observed\_theta:.4f}")

print(f"Discrepanza:       {risultato.discrepancy\_theta:\+.4f}")

Una sequenza di SensorUpdateResult con discrepanze sistematiche di un certo segno è il segnale che i parametri del substrato hanno drift e meritano una nuova calibrazione completa. Per un sistema sempre attivo, una lettura al giorno dovrebbe essere il default; per il controllo manuale, una a settimana è sufficiente.

# 9 — Ricettario del singolo vaso

Questo capitolo raccoglie tre casi d’uso completi del singolo vaso, presentati come ricette di codice end-to-end. Le ricette sono ordinate per complessità crescente: pianificazione settimanale, confronto multi-specie, calibrazione da CSV. Per le ricette che usano più vasi insieme col Garden, vai al capitolo 16.

## Ricetta 1: pianificazione settimanale di un vaso

Hai un vaso di basilico sul balcone e vuoi sapere quale giorno della prossima settimana dovrai irrigare. Procurati la previsione meteo a 7 giorni da Open-Meteo, simula il vaso, e leggi quali giorni la previsione di stato scende sotto la soglia di allerta:

from datetime import date, timedelta

from fitosim.domain.pot import Location, Pot

from fitosim.domain.species import BASIL

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

vaso = Pot(

    label="Basilico balcone-1",

    species=BASIL, substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

)

previsione\_et0 = \[4.5, 5.0, 4.0, 6.0, 3.5, 4.0, 5.5\]

previsione\_pioggia = \[0, 0, 8.0, 0, 0, 0, 0\]

oggi = date.today()

consigli = \[\]

for i, (et0, p) in enumerate(zip(previsione\_et0, previsione\_pioggia)):

    giorno = oggi \+ timedelta(days=i\+1)

    if vaso.state\_mm < vaso.alert\_mm:

        dose = vaso.water\_to\_field\_capacity\_liters() \* 1.05

        consigli.append((giorno, dose))

    vaso.apply\_balance\_step(et\_0\_mm=et0, water\_input\_mm=p, current\_date=giorno)

for giorno, dose\_l in consigli:

    print(f"{giorno}: ~{dose\_l\*1000:.0f} ml")

## Ricetta 2: confronto di specie nello stesso scenario

Vuoi capire quale tra basilico, lattuga e rosmarino sia la specie più “facile da gestire” sul tuo balcone. Simula tre vasi gemelli con specie diverse e confronta i consumi totali e il numero di irrigazioni:

from fitosim.domain.species import BASIL, LETTUCE, ROSEMARY

specie\_da\_confrontare = \[BASIL, LETTUCE, ROSEMARY\]

risultati = {}

for specie in specie\_da\_confrontare:

    vaso = Pot(

        label=specie.common\_name,

        species=specie, substrate=UNIVERSAL\_POTTING\_SOIL,

        pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

        location=Location.OUTDOOR,

        planting\_date=date(2026, 4, 1),

    )

    irrigazioni = 0

    for i in range(30):

        if vaso.state\_mm < vaso.alert\_mm:

            irrigazioni \+= 1

            vaso.state\_mm = vaso.fc\_mm

        vaso.apply\_balance\_step(

            et\_0\_mm=4.5, water\_input\_mm=0.0,

            current\_date=date(2026, 4, 1) \+ timedelta(days=i),

        )

    risultati\[specie.common\_name\] = irrigazioni

print(risultati)

## Ricetta 3: calibrazione da CSV di letture WH51

Hai un file CSV con due mesi di letture orarie del sensore WH51 e vuoi calibrare il substrato del tuo vaso. Carica i dati, riduci a serie giornaliera, e applica calibrate\_substrate:

import csv

from collections import defaultdict

from datetime import datetime

from fitosim.science.calibration import calibrate\_substrate

letture\_giornaliere = defaultdict(list)

with open("wh51\_letture.csv") as f:

    for row in csv.DictReader(f):

        ts = datetime.fromisoformat(row\["timestamp"\])

        letture\_giornaliere\[ts.date()\].append(float(row\["theta"\]))

serie = \[sum(v)/len(v) for v in letture\_giornaliere.values()\]

risultato = calibrate\_substrate(theta\_series=serie, name="vaso-1")

print(f"theta\_FC: {risultato.theta\_fc\_estimate:.3f}")

print(f"theta\_PWP: {risultato.theta\_pwp\_estimate:.3f}")

# 10 — Il Garden: gestire più vasi insieme

Fino al capitolo 9 hai lavorato sempre con un singolo Pot alla volta. È un’astrazione che basta se hai due o tre vasi da seguire, ma diventa scomoda quando il tuo balcone ne ha sette o otto, ognuno con la sua specie, il suo sensore, il suo piano di fertirrigazioni. Il Garden è la classe che orchestra una collezione di vasi come un’unità coerente: li tiene insieme, propaga il meteo a tutti contemporaneamente, e ti permette di interrogare lo stato globale del tuo balcone con poche righe di codice.

L’aspetto importante da capire subito è che il Garden è un orchestratore puro: non aggiunge logica scientifica al modello del singolo vaso, semplicemente itera sui vasi applicando i metodi che già conosci. Conseguenza pratica: tutto quello che hai imparato nei capitoli da 3 a 8 sul Pot vale identico quando il Pot vive dentro a un Garden. Il Garden non è un livello di astrazione che nasconde il modello, è semplicemente una comodità di orchestrazione.

## Costruire il giardino

Il Garden si costruisce con un nome (per identificare il giardino quando ne hai più di uno) e una descrizione opzionale della posizione. I vasi si aggiungono uno per uno con add\_pot, ognuno con la sua label univoca:

from fitosim.domain.garden import Garden

from fitosim.domain.pot import Location, Pot

from fitosim.domain.species import BASIL, ROSEMARY

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

from datetime import date

balcone = Garden(

    name="balcone-milano",

    location\_description="Balcone esposto a sud, periferia di Milano",

)

balcone.add\_pot(Pot(

    label="basilico-1",

    species=BASIL, substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

    location=Location.OUTDOOR,

    planting\_date=date(2026, 4, 1),

))

balcone.add\_pot(Pot(

    label="rosmarino-1",

    species=ROSEMARY, substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=5.0, pot\_diameter\_cm=24.0,

    location=Location.OUTDOOR,

    planting\_date=date(2025, 4, 1),

))

print(f"Vasi nel giardino: {len(balcone)}")

print(f"Etichette: {balcone.pot\_labels}")

Le label dei vasi devono essere univoche all’interno del Garden: se cerchi di aggiungere due vasi con la stessa label, fitosim ti darà un errore esplicito. Le label sono il modo in cui ti riferisci ai singoli vasi nel resto del codice, quindi sceglile sensate: “basilico-balcone-sud” è meglio di “v1”.

## Iterare sui vasi

Il Garden si comporta come una collezione iterabile: puoi fare un loop sui vasi, controllare quanti ne hai con len(), verificare se contiene una label specifica con in. È un’API Python idiomatica:

for pot in balcone:

    print(f"{pot.label}: {pot.state\_mm:.1f} mm")

if "basilico-1" in balcone:

    pot = balcone.get\_pot("basilico-1")

    print(f"Stato: {pot.state\_mm:.1f} mm")

## Applicare un giorno a tutti i vasi

Il metodo apply\_step\_all è l’orchestratore del bilancio idrico giornaliero per tutti i vasi del giardino. Lo chiami una sola volta col meteo del giorno, e fitosim lo applica a tutti i vasi gestendo automaticamente la conversione “mm di pioggia → litri sul vaso” in base alla superficie e all’esposizione di ognuno:

balcone.apply\_step\_all(

    et\_0\_mm=4.5,

    current\_date=date(2026, 5, 15),

    rainfall\_mm=8.0,

)

Una proprietà importante che la suite di test ha inchiodato: apply\_step\_all su un Garden con un vaso solo produce stati identici a apply\_step chiamato direttamente sul Pot. Il Garden non aggiunge mai logica scientifica al modello; tutto quello che fa è iterare. Conseguenza concreta: se il tuo codice del singolo vaso era corretto al capitolo 9, lo stesso codice dentro a un Garden continua ad essere corretto. Niente sorprese.

## L’esposizione alla pioggia

Una caratteristica utile del Pot per chi lo usa nel Garden è il rainfall\_exposure: una frazione tra 0 e 1 che dice quanto della pioggia caduta sull’area aperta arriva effettivamente al vaso. Un vaso esposto in pieno cielo ha esposizione 1.0; un vaso sotto il balcone superiore ha esposizione magari 0.5; un vaso sotto la chioma di un albero ha esposizione 0.2. È il modo in cui il Garden modella la geometria reale del tuo balcone:

vaso\_aperto = Pot(label="aperto", rainfall\_exposure=1.0, ...)

vaso\_riparato = Pot(label="sotto-balcone", rainfall\_exposure=0.5, ...)

vaso\_albero = Pot(label="sotto-albero", rainfall\_exposure=0.2, ...)

Quando chiami apply\_step\_all con un certo rainfall\_mm, il Garden applica a ogni vaso una frazione diversa della pioggia in base al suo rainfall\_exposure. È un fenomeno con conseguenze importanti per il bilancio chimico di lungo periodo: il vaso aperto riceve molto lavaggio naturale e accumula meno sale dalle fertirrigazioni, mentre il vaso sotto-albero accumula sale progressivamente. Vedrai questo fenomeno in azione nel capitolo 16.

# 11 — Persistenza con SQLite

Il Garden in-memory del capitolo 10 è perfetto per la simulazione interattiva ma ha un limite ovvio: quando spegni Python, tutto sparisce. Per un dashboard operativo del tuo balcone reale ti serve una persistenza che vivrà sul tuo Raspberry Pi 5 o sul tuo Android in Termux, conservando lo stato e la storia dei tuoi vasi tra esecuzioni successive. fitosim usa SQLite come motore di persistenza per ragioni pratiche: zero configurazione, file singolo, dipendenze già nella standard library di Python.

## Il database e il catalogo

La persistenza vive in fitosim.io.persistence. La classe principale è GardenPersistence, che apre o crea un database SQLite in un file specificato. Lo schema attuale è alla versione 5 e gestisce, oltre alle otto tabelle di base (specie, materiali base, substrati, ricette delle misture, gardens, vasi, snapshot di stato, eventi), anche le stanze indoor (Room) e gli eventi pianificati. Le migrazioni si applicano automaticamente e in sequenza ai database esistenti (v1→v2 channel\_id dei vasi, v2→v3 eventi pianificati, v3→v4 stanze indoor, v4→v5 gradi-giorno accumulati dei vasi e configurazione fenologica delle specie della fascia 3), senza intervento da parte tua.

from fitosim.io.persistence import GardenPersistence

\# Apre o crea un database SQLite.

db = GardenPersistence("/home/utente/giardino.db")

Prima di salvare il giardino devi registrare nel catalogo le specie, i materiali base e i substrati che usi. Il catalogo è la fonte di verità del database: ogni vaso memorizza solo l’ID della sua specie e del suo substrato, e al caricamento il database ricostruisce gli oggetti completi dal catalogo.

from fitosim.domain.species import BASIL, ROSEMARY

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

db.register\_species(BASIL)

db.register\_species(ROSEMARY)

db.register\_substrate(UNIVERSAL\_POTTING\_SOIL)

__*Nota: *__*I metodi register\_\* sono idempotenti: chiamarli più volte sullo stesso oggetto aggiorna silenziosamente i parametri se sono cambiati, senza errori. Permette al tuo codice di essere lineare: registri tutto al boot dell’applicazione senza condizioni speciali per il primo avvio.*

## Salvare il giardino

Una volta registrato il catalogo, salvi il giardino con save\_garden. Il metodo accetta il Garden in-memory e un timestamp opzionale per lo snapshot dello stato (default: ora corrente UTC):

from datetime import datetime, timezone

db.save\_garden(balcone, snapshot\_timestamp=datetime.now(timezone.utc))

save\_garden fa due cose distinte: persiste la struttura del giardino (i vasi e le loro caratteristiche statiche) nelle tabelle gardens e pots, e aggiunge uno snapshot dello stato dinamico di ogni vaso (state\_mm, salt\_mass\_meq, ph\_substrate) alla tabella pot\_states con il timestamp specificato. La conseguenza pratica è che ogni save\_garden successiva preserva la storia: la tabella pot\_states accumula la sequenza degli snapshot e tu puoi ricostruire l’evoluzione del vaso nel tempo per produrre i grafici del dashboard.

## Caricare il giardino

Per caricare un giardino persistito ne richiami il nome, e il metodo load\_garden ricostruisce un Garden in-memory completo coi vasi nello stato dell’ultimo snapshot:

balcone\_caricato = db.load\_garden("balcone-milano")

print(f"Vasi caricati: {len(balcone\_caricato)}")

for pot in balcone\_caricato:

    print(f"  {pot.label}: {pot.state\_mm:.1f} mm")

Il caricamento ricostruisce anche le ricette dei substrati mistura: se hai modificato i parametri di un materiale base nel catalogo dopo aver salvato il giardino, al caricamento successivo i substrati mistura vedono i nuovi parametri automaticamente. Il database è “fonte di verità della ricetta”, non dei parametri derivati. È una scelta che ti permette di ricalibrare il catalogo dei materiali e propagare i nuovi valori a tutti i giardini senza migrazione manuale.

## Interrogare la storia

Per produrre i grafici di evoluzione di un vaso, il metodo query\_states ti restituisce tutti gli snapshot della tabella pot\_states ordinati per data:

history = db.query\_states("balcone-milano", "basilico-1")

for snap in history:

    print(f"{snap.timestamp.date()}: {snap.state\_mm:.2f} mm, 

          f"sale {snap.salt\_mass\_meq:.2f}, pH {snap.ph\_substrate:.2f}")

Puoi opzionalmente filtrare per intervallo di date passando i parametri start\_date e end\_date. Tipicamente ti servirà l’ultimo mese o l’ultima stagione per i grafici del dashboard.

# 12 — Backup e trasporto in JSON

La persistenza SQLite del capitolo precedente è perfetta come database operativo del tuo dashboard, ma ha un limite per gli scenari di trasporto: è un file binario legato alla tua macchina, e per spostare un giardino tra ambienti (per esempio dal Raspberry Pi al laptop, o per inviarlo via email a un amico per chiedergli un’opinione) il formato non è ideale. Per questi casi fitosim espone un secondo formato di serializzazione, completamente disaccoppiato dalla persistenza SQLite: il JSON.

L’aspetto importante da capire è che persistenza SQLite e serializzazione JSON sono due moduli distinti che non si conoscono tra loro. La SQLite è il database transazionale per il dashboard; il JSON è il formato di trasporto autocontenuto. Hanno scopi diversi, e usarli insieme è la scelta più potente.

## Esportare un giardino in JSON

Il modulo fitosim.io.serialization espone export\_garden\_json e import\_garden\_json. L’export prende un Garden in-memory e ritorna una stringa JSON autocontenuta:

from fitosim.io.serialization import export\_garden\_json

json\_str = export\_garden\_json(balcone)

with open("backup\_balcone\_2026-04-28.json", "w") as f:

    f.write(json\_str)

Il JSON prodotto è autocontenuto: include il catalogo minimale di tutte le specie e tutti i substrati referenziati dai vasi del giardino. Chi riceve il file può ricostruire l’intero giardino con una singola chiamata a import\_garden\_json, senza bisogno di pre-registrare niente nel suo catalogo locale. È esattamente la differenza tra “database” e “formato di trasporto”: il database vive nel suo ecosistema, il file JSON viaggia da solo.

## Importare un giardino da JSON

L’importazione è simmetrica:

from fitosim.io.serialization import import\_garden\_json

with open("backup\_balcone\_2026-04-28.json") as f:

    json\_str = f.read()

balcone = import\_garden\_json(json\_str)

print(f"Caricati {len(balcone)} vasi dal backup")

Il Garden ricostruito è equivalente all’originale: stessi vasi, stessi stati, stessi eventi pianificati, stessa mappa dei sensori. Puoi continuare a lavorarci come se non avessi mai serializzato niente.

## Casi d’uso del JSON

Il caso d’uso primario è il backup: una volta a settimana esporti il tuo giardino operativo in un file JSON e lo metti su un cloud o lo invii a te stesso via email. Se il Raspberry Pi si rompe, ricostruisci il giardino in pochi secondi dall’ultimo backup. Il secondo caso d’uso è la migrazione tra ambienti: il file JSON è indipendente dalla versione del database, dalla versione di Python, dal sistema operativo. Il terzo caso d’uso è la condivisione: puoi inviare il tuo giardino a un altro giardiniere per fare confronti, o pubblicarlo come configurazione di riferimento.

__*Nota: *__*Il formato JSON è alla versione 2 al momento della scrittura di questo manuale, e include la mappa dei sensori (channel\_id) e gli eventi pianificati. Le versioni future potranno aggiungere campi opzionali, ma fitosim manterrà la retrocompatibilità con i file vecchi: un JSON v1 potrà essere caricato sempre da una libreria nuova.*

# 13 — Sensori reali in batch

Nel capitolo 8 hai visto come integrare un sensore singolo con un singolo Pot tramite update\_from\_sensor. Quando passi al Garden con più vasi mappati a sensori diversi, il pattern “uno per uno” diventa scomodo, e soprattutto fragile: cosa succede se uno dei sensori ha la batteria scarica e fallisce la lettura? Il loop si interrompe a metà e gli altri vasi restano non aggiornati. Il Garden risolve questi due problemi con il metodo update\_all\_from\_sensors, che aggiorna in batch tutti i vasi mappati gestendo gli errori in modo strutturato.

## La mappa label → channel\_id

Per dire al Garden quale vaso è collegato a quale canale del sensore, usi il metodo set\_channel\_id. Il channel\_id è la stringa che identifica il canale sul gateway Ecowitt — tipicamente "1", "2", ..., "8" per i WH51. Solo i vasi mappati saranno aggiornati dal sensore; gli altri continueranno a girare in previsione pura, ed è esattamente quello che vuoi se hai un “giardino misto” dove alcuni vasi hanno il sensore e altri no:

balcone.set\_channel\_id("basilico-1", "1")

balcone.set\_channel\_id("rosmarino-1", "2")

\# "basilico-2" non è mappato: continuerà solo in previsione.

## L’aggiornamento in batch

Una volta mappati i vasi, una singola chiamata a update\_all\_from\_sensors esegue tutto il ciclo:

from fitosim.io.sensors import EcowittWH51SoilSensor

sensore = EcowittWH51SoilSensor(api\_key=..., application\_key=...)

risultati = balcone.update\_all\_from\_sensors(sensore)

for label, esito in risultati.items():

    if isinstance(esito, Exception):

        print(f"{label}: errore -- {esito}")

    else:

        print(f"{label}: theta osservato {esito.observed\_theta:.3f}")

Il dict risultati ha una chiave per ogni vaso mappato. Il valore è un SensorUpdateResult se la lettura ha avuto successo (con la diagnostica della discrepanza che hai visto al capitolo 8), oppure un’eccezione se la lettura è fallita. La chiave fondamentale qui è “ogni vaso ha il suo esito indipendente”: se il sensore del basilico-1 ha la batteria scarica, il rosmarino-1 viene aggiornato comunque.

## La gestione degli errori a tre livelli

fitosim distingue tre tipi di errore del sensore, ognuno con un comportamento diverso. Gli errori transitori (SensorTemporaryError) sono problemi che si risolvono da soli al prossimo ciclo: batteria scarica del WH51, timeout di rete, gateway momentaneamente irraggiungibile. Vengono catturati come oggetto nel dict dei risultati e non bloccano gli altri vasi. Gli errori permanenti (SensorPermanentError) sono problemi di configurazione: channel\_id sbagliato, sensore non esistente, credenziali scadute. Vengono propagati come eccezione perché richiedono il tuo intervento. Gli errori di qualità (SensorDataQualityError) sono letture impossibili (theta fuori da \[0, 1\], timestamp nel futuro): vengono propagati perché silenziarli contaminerebbe il modello.

Il pattern di chiamata in produzione è quindi:

try:

    risultati = balcone.update\_all\_from\_sensors(sensore)

except (SensorPermanentError, SensorDataQualityError) as e:

    \# Errore di configurazione: alza un’allerta al giardiniere.

    log.error(f"Errore di configurazione del sensore: {e}")

else:

    \# Tutti i vasi processati: alcuni magari con TemporaryError.

    for label, esito in risultati.items():

        if isinstance(esito, SensorTemporaryError):

            log.warn(f"{label}: lettura saltata -- {esito}")

Questo pattern ti dà la robustezza che ti serve in produzione: il dashboard funziona anche se uno dei sensori ha problemi, e tu vieni notificato solo quando c’è un problema vero da risolvere.

# 14 — Eventi pianificati e previsioni

Fino a questo punto fitosim ti ha aiutato a capire cosa è successo nei tuoi vasi e qual è il loro stato corrente. Il salto qualitativo della tappa 4 è la dimensione predittiva: il Garden può ora rispondere a domande come “come saranno i vasi tra una settimana se non intervengo?”, e applicare automaticamente eventi pianificati (fertirrigazioni, lavaggi) durante la simulazione futura. Questo capitolo introduce le due capacità che lavorano insieme: ScheduledEvent per pianificare gli interventi, e forecast per produrre la proiezione dello stato.

## Pianificare eventi futuri

Un ScheduledEvent è una dataclass frozen che descrive un’operazione futura: che tipo (fertigation, leaching, treatment), su quale vaso, in che data, con quali parametri. Il Garden mantiene una collezione di eventi pianificati che il forecast usa per simularli al momento giusto:

from fitosim.domain.scheduling import ScheduledEvent

evento = ScheduledEvent(

    event\_id="fert-basilico-1-week-20",

    pot\_label="basilico-1",

    event\_type="fertigation",

    scheduled\_date=date(2026, 5, 18),

    payload={

        "volume\_l": 0.3,

        "ec\_mscm": 2.0,

        "ph": 6.2,

    },

)

balcone.add\_scheduled\_event(evento)

Gli event\_id sono identificatori univoci che servono per cancellare un evento se cambi idea (remove\_scheduled\_event). Il payload è un dict con i parametri specifici del tipo di evento: per una fertirrigazione il volume in litri, l’EC della soluzione nutritiva, e il pH. Per un lavaggio (leaching) basta il volume, l’EC sarà bassa (acqua quasi pura) e il pH circa neutro.

Tipicamente costruisci un piano di eventi all’inizio della stagione: una fertirrigazione alla settimana per ogni vaso, un lavaggio a metà stagione per evitare salinizzazione cumulativa, eventuali trattamenti antiparassitari programmati. Il piano vive nel Garden e viene persistito col save\_garden, quindi sopravvive ai riavvii dell’applicazione.

## Il forecast a N giorni

Una volta pianificati gli eventi e raccolto il forecast meteo dei prossimi giorni, il metodo forecast del Garden produce una proiezione dello stato dei vasi giorno per giorno. Lavora su deep copy dei vasi (lo stato del Garden corrente non viene modificato) e applica automaticamente gli eventi pianificati di tipo fertigation e leaching. È esattamente il pezzo che permette al dashboard di mostrare “tra 4 giorni il vaso raggiungerà la soglia di allerta”:

from fitosim.domain.scheduling import WeatherDayForecast

forecast\_meteo = \[

    WeatherDayForecast(date\_=date(2026, 5, 15) \+ timedelta(days=i),

                       et\_0\_mm=4.5, rainfall\_mm=0.0)

    for i in range(7)

\]

risultato = balcone.forecast(forecast\_meteo)

traj\_basilico = risultato.trajectories\["basilico-1"\]

for punto in traj\_basilico.points:

    print(f"{punto.date\_}: {punto.state\_mm:.1f} mm, 

          f"EC {punto.ec\_substrate\_mscm:.2f} mS/cm")

Il ForecastResult ti restituisce una traiettoria per ogni vaso del giardino, con un PotForecastPoint per ogni giorno della previsione. Ogni punto contiene state\_mm, state\_theta, salt\_mass\_meq, ph\_substrate, ec\_substrate\_mscm — tutti i numeri che ti servono per produrre i grafici di previsione del dashboard. Lo stato del Garden corrente è invariato dopo la chiamata: puoi rieseguire forecast con scenari diversi (piani di fertirrigazione alternativi, ipotesi meteo diverse) per fare what-if analysis.

__*Nota: *__*Il forecast usa solo gli eventi di tipo fertigation e leaching, perché sono gli unici che hanno effetti scientifici modellati dal sistema. Eventi come treatment o repotting vengono ignorati dal forecast: per il modello agronomico sono “rumore” rispetto al bilancio idrico-chimico. Verranno presi in considerazione in futuro se aggiungeremo modelli specifici per quei tipi di intervento.*

# 15 — Il sistema di allerte

Le previsioni quantitative del capitolo 14 sono utili, ma il giardiniere medio non vuole leggere serie di numeri: vuole un cruscotto che gli dica “questo vaso ha bisogno di attenzione” con un’icona, una severità, e una raccomandazione concreta. Il sistema di allerte è il pezzo che trasforma le previsioni quantitative in raccomandazioni qualitative.

Un’allerta è una comunicazione strutturata dal sistema al giardiniere quando una condizione del giardino richiede (o richiederà) la sua attenzione. La differenza fondamentale rispetto a un evento (storico o pianificato) è che un’allerta è DERIVATA dallo stato: non è qualcosa che è successo o che farò, è qualcosa che il sistema deduce dallo stato corrente o proiettato. Conseguenza pratica: le allerte non si persistono. Sono il risultato dell’applicazione delle regole allo stato corrente del modello, ricalcolate ogni volta che le chiedi.

## Cinque categorie e tre severità

Le allerte sono classificate in cinque categorie semantiche e tre livelli di severità. Le categorie sono: irrigation\_needed (vaso prossimo al PWP, va annaffiato), fertilization\_due (EC sotto il range ottimale, sarebbe utile una fertirrigazione), ec\_too\_high (EC criticamente alta, va fatto un lavaggio), ec\_too\_low (EC molto bassa, carenza nutrizionale), ph\_out\_of\_range (pH fuori dal range della specie). Le severità sono info (informativa), warning (attenzione), critical (urgente).

## Allerte sullo stato corrente

Il metodo current\_alerts del Garden applica tutte le regole allo stato corrente di tutti i vasi e restituisce la lista delle allerte attive:

from fitosim.domain.alerts import AlertSeverity

alerte = balcone.current\_alerts(date.today())

for a in alerte:

    icon = {"info": "i", "warning": "!", "critical": "!!"}

    print(f"\[{icon\[a.severity.value\]}\] {a.pot\_label}: {a.message}")

    print(f"    Cosa fare: {a.recommended\_action}")

Ogni Alert ha un alert\_id (hash deterministico di pot\_label, category, triggered\_date), una severity, una category, un message descrittivo per il giardiniere, e una recommended\_action concreta da fare. Il dashboard può presentare queste allerte come notifiche con icone diverse per severità, e il giardiniere ha tutto quello che gli serve per decidere il prossimo intervento.

## Allerte previste nel forecast

Il metodo forecast\_alerts è la versione predittiva: applica le regole non allo stato corrente ma allo stato proiettato dei prossimi N giorni, producendo allerte previste. Le triggered\_date delle allerte sono i giorni futuri a cui si riferiscono:

alerte\_future = balcone.forecast\_alerts(forecast\_meteo)

\# Filtro solo le critical previste.

critical = \[a for a in alerte\_future if a.severity == AlertSeverity.CRITICAL\]

for a in critical:

    print(f"{a.triggered\_date}: \[{a.pot\_label}\] {a.message}")

Questo è il pezzo che porta valore proattivo: il dashboard può mostrare “tra 4 giorni il vaso albero raggiungerà EC critica, valuta un lavaggio reattivo prima di applicare la prossima fertirrigazione”. È il tipo di guida che trasforma fitosim da monitoraggio reattivo a gestione proattiva.

## Le regole come funzioni pure

Le regole di allerta vivono nel modulo fitosim.domain.alerts come funzioni pure (Pot, date) → Optional\[Alert\], dichiarative e indipendenti tra loro. Sono accessibili individualmente se ti serve applicarle a un singolo Pot fuori dal Garden:

from fitosim.domain.alerts import (

    check\_irrigation\_needed, check\_ec\_too\_high, ALL\_RULES,

)

vaso = balcone.get\_pot("basilico-1")

alerta = check\_irrigation\_needed(vaso, date.today())

if alerta:

    print(f"Allerta: {alerta.message}")

\# Oppure applica tutte le regole.

tutte = \[r(vaso, date.today()) for r in ALL\_RULES\]

attive = \[a for a in tutte if a is not None\]

__*Nota: *__*Le soglie delle regole sono definite a partire dai parametri della specie e del substrato del singolo vaso, non sono valori globali. Il vaso di basilico (range EC 1.0-1.6) e il vaso di rosmarino (range EC diverso) producono allerte ec\_too\_high con soglie diverse, perché ec\_too\_high scatta a max\+0.5 mS/cm sopra il massimo della specie. È la conseguenza naturale del modello chimico per-vaso.*

# 16 — Una ricetta end-to-end del balcone

Questo capitolo mette insieme tutte le capacità della tappa 4 in una ricetta unica che rappresenta il flusso giornaliero tipico del dashboard “Il Mio Giardino” in produzione. Lo scenario è realistico: tre vasi di basilico sul balcone milanese a esposizioni diverse, due collegati al sensore WH51, tre settimane di simulazione con fertirrigazioni settimanali, e a metà periodo una previsione a 7 giorni con allerte previste. Lo script completo del balcone in 60 righe.

Per uno script più articolato (con generazione meteo deterministica, fake sensor che simula errori transitori, output didattico tra blocchi di giorni), c’è la demo fitosim\_tappa4\_demo.zip che ti è stata consegnata e che gira completamente da sola. La ricetta che segue è la sua versione condensata, da usare come template per il tuo balcone reale.

## Setup del giardino e del database

Costruiamo il giardino con tre vasi a esposizioni diverse alla pioggia, registriamo il catalogo nel database, mappiamo i due sensori disponibili, e pianifichiamo le fertirrigazioni settimanali:

from datetime import date, datetime, timedelta, timezone

from fitosim.domain.garden import Garden

from fitosim.domain.pot import Location, Pot

from fitosim.domain.species import BASIL

from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast

from fitosim.io.persistence import GardenPersistence

from fitosim.io.serialization import export\_garden\_json

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

\# Costruzione del giardino con tre vasi a esposizioni diverse.

balcone = Garden(name="balcone-milano")

for label, exposure in \[("aperto", 1.0),

                        ("ringhiera", 0.5),

                        ("albero", 0.2)\]:

    balcone.add\_pot(Pot(

        label=label, species=BASIL,

        substrate=UNIVERSAL\_POTTING\_SOIL,

        pot\_volume\_l=2.0, pot\_diameter\_cm=18.0,

        location=Location.OUTDOOR,

        planting\_date=date(2026, 5, 1),

        rainfall\_exposure=exposure,

        state\_mm=28.0, salt\_mass\_meq=8.5,

    ))

balcone.set\_channel\_id("aperto", "1")

balcone.set\_channel\_id("ringhiera", "2")

\# "albero" non è mappato: continua solo in previsione.

## Database, catalogo, fertirrigazioni

db = GardenPersistence("/home/utente/giardino.db")

db.register\_species(BASIL)

db.register\_substrate(UNIVERSAL\_POTTING\_SOIL)

\# Tre fertirrigazioni settimanali per ogni vaso.

for week in range(3):

    fert\_date = date(2026, 5, 25) \+ timedelta(days=6 \+ 7\*week)

    for label in balcone.pot\_labels:

        balcone.add\_scheduled\_event(ScheduledEvent(

            event\_id=f"fert-{label}-w{week\+1}",

            pot\_label=label,

            event\_type="fertigation",

            scheduled\_date=fert\_date,

            payload={"volume\_l": 0.3, "ec\_mscm": 2.0, "ph": 6.2},

        ))

## Loop giornaliero

Il cuore del dashboard è il loop giornaliero che, una volta al giorno (tipicamente all’alba dopo la sincronizzazione del meteo), aggiorna i vasi dai sensori reali, applica gli eventi pianificati e il bilancio del giorno, e salva tutto nel database:

\# Sensore reale (sostituisci con la tua configurazione Ecowitt).

\# from fitosim.io.sensors import EcowittWH51SoilSensor

\# sensore = EcowittWH51SoilSensor(api\_key=..., application\_key=...)

def giornata\_tipo(balcone, db, sensore, et\_0\_mm, rainfall\_mm, current\_date):

    \# 1. Aggiorna i vasi mappati dai sensori reali.

    risultati = balcone.update\_all\_from\_sensors(sensore)

    for label, esito in risultati.items():

        if isinstance(esito, Exception):

            print(f"WARN: {label}: {esito}")

    \# 2. Applica gli eventi pianificati del giorno.

    for event in balcone.events\_due\_today(current\_date):

        if event.event\_type == "fertigation":

            pot = balcone.get\_pot(event.pot\_label)

            pot.apply\_fertigation\_step(\*\*event.payload,

                                       current\_date=current\_date)

    \# 3. Bilancio idrico giornaliero per tutti i vasi.

    balcone.apply\_step\_all(

        et\_0\_mm=et\_0\_mm, current\_date=current\_date,

        rainfall\_mm=rainfall\_mm,

    )

\[continua…\]

\[continua…\]

    \# 4. Snapshot al database.

    db.save\_garden(balcone, snapshot\_timestamp=datetime.now(timezone.utc))

## Forecast e allerte settimanali

Una volta a settimana (tipicamente la domenica) produci una previsione a 7 giorni con le allerte previste, esporti il backup JSON, e generi il report del dashboard:

def report\_settimanale(balcone, db, forecast\_meteo):

    \# Previsione a 7 giorni.

    risultato = balcone.forecast(forecast\_meteo)

    \# Allerte correnti e previste.

    correnti = balcone.current\_alerts(date.today())

    future = balcone.forecast\_alerts(forecast\_meteo)

    \# Backup JSON come trasporto di sicurezza.

    with open(f"backup-{date.today()}.json", "w") as f:

        f.write(export\_garden\_json(balcone))

    return {

        "trajectories": risultato.trajectories,

        "current\_alerts": correnti,

        "future\_alerts": future,

    }

Questo è il flusso operativo completo: il dashboard chiama giornata\_tipo una volta al giorno e report\_settimanale una volta a settimana. Il database SQLite preserva la storia per i grafici di evoluzione, il backup JSON è la rete di sicurezza in caso di guasto, le allerte correnti e previste guidano gli interventi del giardiniere. Tutto il modello scientifico — il bilancio idrico FAO-56, il modello chimico, la calibrazione dai sensori — è applicato correttamente sotto al cofano senza che tu debba pensarci.

## Cosa cambia dopo qualche settimana di dati reali

Quando il sistema avrà raccolto dati per qualche settimana sul tuo balcone reale, potrai cominciare le prime calibrazioni come visto al capitolo 8. La query\_states del database ti restituisce la storia completa di ogni vaso, che puoi usare come input a calibrate\_substrate per ricavare i parametri “veri” del tuo specifico vaso. La discrepanza sistematica tra forecast e realtà osservata sarà il segnale che alcuni parametri (Kc della specie, CEC del substrato, Kp del vaso) hanno bisogno di aggiustamento. È il passaggio dalla “libreria genericamente plausibile” alla “libreria calibrata per il TUO balcone milanese”.

# 17 — Il selettore di evapotraspirazione "best available"

Fino al capitolo 16 fitosim ha usato un solo modo di calcolare l'evapotraspirazione di riferimento ET₀: la formula di Hargreaves-Samani, scelta perché richiede solo la temperatura minima e massima della giornata ed è quindi sempre applicabile anche con dati meteo minimi. Hargreaves è robusto ma può sbagliare del 10-20% rispetto al "gold standard" della FAO che è Penman-Monteith, una formula fisica che combina temperatura, umidità relativa, velocità del vento e radiazione solare in un'equazione rigorosa. La tappa 5 della fascia 2 ha introdotto Penman-Monteith e un selettore automatico che sceglie tra le formule disponibili in funzione dei dati meteo che hai e dei parametri della specie che stai modellando.

Questo capitolo ti spiega come usare il selettore in pratica e quali decisioni prende internamente. Non entra nei dettagli matematici delle formule (per quelli vedi la pubblicazione FAO-56 nel repository, in docs/FAO-56.pdf): il taglio è operativo, mostra come passare dal modello Hargreaves-only del capitolo 8 al modello "best available" della tappa 5 senza dover capire l'equazione fisica nel dettaglio.

## Le tre formule e quando si applicano

Il selettore può scegliere tra tre formule, in ordine di preferenza:

Penman-Monteith fisico (PENMAN\_MONTEITH\_PHYSICAL nell'enum EtMethod) è la scelta migliore quando disponibile. Applica direttamente l'equazione di Penman-Monteith alla specie usando la sua resistenza stomatica e altezza colturale, e produce direttamente l'evapotraspirazione effettiva ET della specie (NON ET₀ di riferimento). Il chiamante che riceve un risultato PENMAN\_MONTEITH\_PHYSICAL non deve moltiplicare per il Kc: il risultato è già specifico per la pianta. Richiede tutti i dati meteo (T\_min, T\_max, umidità relativa, vento, radiazione solare) e i parametri specie (stomatal\_resistance\_s\_m, crop\_height\_m) popolati.

Penman-Monteith standard FAO-56 (PENMAN\_MONTEITH\_STANDARD) è il fallback quando la specie non ha la resistenza stomatica popolata ma i dati meteo sono completi. Applica l'equazione con i parametri della coltura di riferimento standard FAO-56 (rs=70 s/m, h=0.12 m) e produce ET₀ di riferimento, da moltiplicare per il Kc della specie come si fa con Hargreaves. Richiede tutti i dati meteo, ma niente sulla specie.

Hargreaves-Samani 1985 (HARGREAVES\_SAMANI) è il fallback finale quando mancano dati meteo (umidità, vento, radiazione). Richiede solo la temperatura minima e massima della giornata e produce ET₀, da moltiplicare per il Kc della specie. È la formula "di emergenza" che funziona sempre ma è meno precisa delle altre due.

## Usare il selettore: la funzione compute\_et

L'API del selettore vive nel modulo science/et0.py ed è la funzione compute\_et. Riceve i dati meteo disponibili come argomenti opzionali e restituisce un EtResult che contiene il valore numerico in mm/giorno e il metodo effettivamente usato. Esempio minimo di chiamata diretta:

from fitosim.science.et0 import compute\_et

result = compute\_et(

    t\_min=18.0, t\_max=28.0,

    latitude\_deg=45.46, j=200,  \# giorno dell'anno

    humidity\_relative=0.55,    \# opzionale

    wind\_speed\_m\_s=2.5,        \# opzionale

    solar\_radiation\_mj\_m2\_day=22.0,  \# opzionale

)

print(result.value\_mm)   \# es. 5.27

print(result.method)     \# EtMethod.PENMAN\_MONTEITH\_STANDARD

Se passi solo t\_min, t\_max, latitude\_deg e j, ricadi automaticamente su Hargreaves. Se passi anche umidità, vento e radiazione, il selettore salirà a Penman-Monteith standard. Se passi anche stomatal\_resistance\_s\_m e crop\_height\_m della specie, salirà a Penman-Monteith fisico. La tracciabilità del metodo nel risultato ti permette di fare diagnostica ("oggi quale formula è stata usata?") e calibrazione ("questi vasi girano sempre con Hargreaves perché manca la radiazione, dovrei configurare Open-Meteo come fonte di radiazione").

## Integrazione automatica nel Pot e nel Garden

Nella pratica del dashboard giornaliero non chiamerai compute\_et direttamente: la libreria offre due metodi di alto livello che invocano il selettore per te in modo trasparente. Sul Pot c'è apply\_balance\_step\_from\_weather(weather, current\_date), che riceve un WeatherDay (la dataclass meteo del giorno, definita in domain/weather.py) e applica internamente compute\_et con i dati appropriati e i parametri della specie. Sul Garden c'è apply\_step\_all\_from\_weather(weather, current\_date) che fa la stessa cosa per tutti i vasi outdoor del giardino in un colpo solo. Esempio:

from datetime import date

from fitosim.domain.weather import WeatherDay

meteo\_oggi = WeatherDay(

    date\_=date(2026, 7, 19),

    t\_min=18.0, t\_max=28.0,

    humidity\_relative=0.55,

    wind\_speed\_m\_s=2.5,

    solar\_radiation\_mj\_m2\_day=22.0,

    rainfall\_mm=0.0,

)

garden.apply\_step\_all\_from\_weather(meteo\_oggi, current\_date=date(2026, 7, 19))

Il vecchio metodo apply\_step\_all(et\_0\_mm, current\_date, rainfall\_mm) continua a funzionare invariato per retrocompatibilità: se hai già calcolato ET₀ da una fonte esterna (per esempio dall'API Ecowitt), puoi passarlo direttamente come prima. La differenza è che il nuovo metodo \_from\_weather sfrutta il selettore "best available" e produce un risultato più accurato quando hai i dati meteo completi.

## Quando ti serve il Penman-Monteith fisico

Il fisico è l'opzione più accurata in assoluto, ma richiede che la specie abbia popolati i campi stomatal\_resistance\_s\_m e crop\_height\_m. Nel catalogo predefinito di fitosim queste informazioni sono presenti per le specie principali (BASIL ha rs=200 s/m e h=0.40 m, TOMATO ha rs=120 s/m e h=1.50 m, ROSEMARY ha rs=300 s/m e h=0.60 m, CACTUS ha rs=600 s/m e h=0.30 m per riflettere la fisiologia CAM, ecc.); se stai costruendo una Species custom, puoi popolarli usando la letteratura agronomica o lasciarli a None per ricadere automaticamente sul Penman-Monteith standard.

La differenza tra fisico e standard è particolarmente significativa per specie con fisiologia atipica come succulente e cactacee a metabolismo CAM, dove la resistenza stomatica elevata produce un'evapotraspirazione molto più bassa di quanto Hargreaves o Penman-Monteith standard predirebbero. Per queste specie il fisico è quasi obbligatorio se vuoi previsioni realistiche; per specie a metabolismo C3 standard (basilico, rosmarino, pomodoro) lo standard è quasi altrettanto buono.

## Diagnostica della formula scelta

Quando vuoi sapere quale formula sta usando il selettore per un dato vaso in una data giornata, puoi chiamare compute\_et direttamente con gli stessi argomenti che il Pot userebbe, e ispezionare il campo method del risultato. Più operativamente, la demo dell'appartamento (sotto-tappa 5-E) produce una heatmap PNG che mostra giorno per giorno e vaso per vaso quale metodo è stato usato, ed è un buon punto di partenza per costruire la stessa visualizzazione nel tuo dashboard.

# 18 — Vasi indoor: Room, microclima e sensore WN31

Fino al capitolo 17 il manuale ha trattato implicitamente vasi outdoor: vasi che vivono sul balcone o in giardino, ricevono pioggia, sono esposti al sole e al vento, e il loro bilancio idrico è alimentato dai dati meteo esterni. Per i vasi indoor — quelli che vivono dentro casa, in salotto, in cucina, in camera da letto — il quadro è completamente diverso: non ricevono pioggia, il vento è quello eventualmente generato da un ventilatore, l'umidità relativa è quella della stanza non quella del balcone, la temperatura è quella della stanza, e la radiazione solare è una piccola frazione di quella outdoor che dipende dalla posizione del vaso rispetto alle finestre.

La tappa 5 della fascia 2 ha introdotto un modello dedicato per i vasi indoor, basato su una nuova entità di dominio chiamata Room che rappresenta lo spazio fisico (una stanza o una zona di una stanza) in cui vivono uno o più vasi indoor con il loro microclima condiviso. Questo capitolo ti spiega come modellare il tuo appartamento con fitosim: come creare le Room, come associarvi i vasi, come alimentare il modello dal sensore ambientale WN31 di Ecowitt, come parametrizzare l'esposizione luminosa di ogni vaso.

## Perché esiste l'entità Room

L'introduzione della Room non è una sofisticazione gratuita ma una conseguenza fisica del fatto che il sensore WN31 di Ecowitt (alias commerciale WH31, lo stesso prodotto con due nomi) non è una sonda dedicata al singolo vaso ma un trasmettitore ambientale che misura il microclima di una stanza intera. Cinque vasi che condividono il salotto condividono lo stesso microclima ambientale; un sesto vaso in camera da letto richiede un secondo WN31 per quella stanza.

Il modello rispecchia questa fisica esplicitamente attraverso l'entità Room invece di duplicare i dati meteo per ogni vaso. Ogni Room ha un room\_id univoco (una stringa scelta da te, per esempio "salotto"), un nome leggibile per UI e log, l'eventuale channel\_id del WN31 mappato, il microclima corrente come stato mutabile, e un default\_wind\_m\_s di 0.5 m/s per rappresentare il vento minimo convettivo della stanza. I Pot indoor si associano alla loro Room tramite il campo opzionale room\_id.

## Costruire le Room del tuo appartamento

Il punto di partenza è creare le Room corrispondenti alle stanze dell'appartamento e aggiungerle al Garden con add\_room. Esempio per un appartamento con vasi in salotto e in camera da letto:

from fitosim.domain.garden import Garden

from fitosim.domain.room import Room

appartamento = Garden(name="appartamento-milano")

salotto = Room(

    room\_id="salotto",

    name="Salotto",

    wn31\_channel\_id="1",  \# canale WN31 della stanza

)

camera = Room(

    room\_id="camera",

    name="Camera da letto",

    wn31\_channel\_id="2",

)

appartamento.add\_room(salotto)

appartamento.add\_room(camera)

Se non hai ancora il sensore WN31 collegato puoi lasciare wn31\_channel\_id=None e popolare manualmente il microclima della Room passando i dati che osservi. Se hai un ventilatore acceso costantemente in una stanza, puoi sovrascrivere il default\_wind\_m\_s con il valore stimato (per esempio 1.5 m/s per un ventilatore a velocità media a un metro dai vasi).

## Associare i vasi alle Room e parametrizzare la luce

Ogni vaso indoor si associa alla sua Room tramite il campo room\_id, e deve dichiarare il suo livello di esposizione luminosa tramite il campo light\_exposure (enum LightExposure con tre livelli). La scelta del livello è qualitativa e attribuibile per osservazione diretta: DARK per vasi lontani dalle finestre o in stanze poco luminose (Pothos in un angolo del salotto), INDIRECT\_BRIGHT per vasi vicini a una finestra ma senza sole diretto (basilico sul ripiano della cucina, lontano dalla finestra), DIRECT\_SUN per vasi sul davanzale di una finestra a sud o ovest con qualche ora di sole diretto al giorno (rosmarino sul davanzale del salotto).

from fitosim.domain.pot import Location, Pot

from fitosim.domain.room import LightExposure

from fitosim.domain.species import BASIL

from fitosim.science.substrate import UNIVERSAL\_POTTING\_SOIL

vaso\_basilico = Pot(

    label="basilico-cucina",

    species=BASIL,

    substrate=UNIVERSAL\_POTTING\_SOIL,

    pot\_volume\_l=1.5,

    pot\_diameter\_cm=14.0,

    location=Location.INDOOR,

    planting\_date=date(2026, 4, 1),

    room\_id="salotto",            \# appartiene al salotto

    light\_exposure=LightExposure.INDIRECT\_BRIGHT,

)

appartamento.add\_pot(vaso\_basilico)

I vasi outdoor continuano a vivere nel giardino senza room\_id e senza light\_exposure (entrambi sono opzionali e None per default). Puoi avere un Garden ibrido che mescola vasi outdoor sul balcone e vasi indoor in salotto, e il sistema gestisce correttamente ognuno con il suo modello.

## Aggiornare il microclima dal sensore WN31

Quando hai il sensore WN31 collegato, puoi alimentare il microclima delle Room dal sensore in modo automatico tramite l'adapter EcowittAmbientSensor. L'adapter espone due metodi: current\_state(channel\_id) per la lettura istantanea (kind=INSTANT, usata dal dashboard per mostrare lo stato corrente della stanza), e daily\_aggregate(channel\_id, target\_date) per l'aggregato giornaliero (kind=DAILY, con t\_min, t\_max e umidità media; usato dal bilancio idrico).

from datetime import date

from fitosim.io.sensors.ecowitt import EcowittAmbientSensor

sensor = EcowittAmbientSensor.from\_env()  \# legge le credenziali da .env

\# Microclima istantaneo per il dashboard

m\_now = sensor.current\_state(channel\_id="1")

salotto.update\_current\_microclimate(m\_now)

\# Aggregato giornaliero per il bilancio idrico

m\_daily = sensor.daily\_aggregate(

    channel\_id="1", target\_date=date(2026, 7, 19),

)

appartamento.apply\_step\_all\_from\_indoor(

    microclimate=m\_daily,

    room\_id="salotto",

    current\_date=date(2026, 7, 19),

)

Il metodo apply\_step\_all\_from\_indoor del Garden applica il bilancio idrico a tutti i vasi della Room specificata usando il microclima giornaliero passato come argomento. Internamente invoca il selettore compute\_et configurato per la Room (con il vento minimo convettivo della stanza al posto del vento outdoor, con la radiazione indoor stimata dal LightExposure del vaso al posto della radiazione globale outdoor) e produce un risultato realistico per ognuno dei vasi della stanza.

## La radiazione indoor: categoriale o continua

Il modulo science/indoor.py offre due modi per stimare la radiazione indoor di un vaso: il modo categoriale e il modo continuo. Sceglie il modo automaticamente in funzione dei dati che hai a disposizione, ma è utile sapere quale dei due sta usando.

Il modo categoriale associa al LightExposure tre valori fissi indipendenti dalla stagione: DARK = 1.5 MJ/m²/giorno, INDIRECT\_BRIGHT = 4.0, DIRECT\_SUN = 8.0. Sono valori medi annuali per una casa di latitudine padana, calibrati su letteratura agronomica generica. È il fallback semplice che funziona sempre, anche quando non hai dati outdoor.

Il modo continuo stima la radiazione indoor come una frazione della radiazione globale outdoor del giorno: DARK = 5% di outdoor, INDIRECT\_BRIGHT = 15%, DIRECT\_SUN = 40%. È più accurato del categoriale perché cattura naturalmente la stagionalità (un vaso DIRECT\_SUN riceve molto meno sole in inverno che in estate, perché la radiazione outdoor è stagionalmente più bassa) e anche le variazioni giornaliere (giorno nuvoloso vs sereno). Richiede però che tu abbia anche i dati di radiazione outdoor del giorno, tipicamente dal piranometro della tua stazione Ecowitt esterna.

Per usare il modo continuo, basta passare anche il dato outdoor al metodo apply\_step\_all\_from\_indoor tramite il parametro outdoor\_solar\_radiation\_mj\_m2\_day. Se lo lasci a None, il sistema usa automaticamente il modo categoriale.

## Il sensore di substrato WH52

La tappa 5 ha aggiunto anche il supporto al sensore di substrato WH52, che è l'upgrade del WH51 e misura non solo l'umidità volumetrica del substrato (come il WH51) ma anche la sua temperatura e l'EC. Per fitosim il WH52 è gestito dallo stesso adapter del WH51, EcowittWH51SoilSensor, parametrizzato col modello del sensore. Esempio:

from fitosim.io.sensors.ecowitt import EcowittWH51SoilSensor

\# Sensore WH51 (default)

sensor51 = EcowittWH51SoilSensor.from\_env()

\# Sensore WH52 (parametrizzato)

sensor52 = EcowittWH51SoilSensor.from\_env(model="WH52")

Le letture del WH52 popolano i campi temperature\_c ed ec\_mscm del SoilReading, mentre quelle del WH51 lasciano questi campi a None. Il Pot che riceve la lettura via update\_from\_sensor usa i campi popolati per raffinare la diagnostica del modello chimico (per esempio, una EC misurata dal WH52 può essere confrontata con la EC predetta dal modello interno del Pot, e la differenza è un indicatore di calibrazione del modello chimico). Il WH51 continua a essere supportato indefinitamente per chi ce l'ha già installato; il WH52 è un upgrade opzionale che fornisce più dati ai vasi che lo hanno.

## Una ricetta dell'appartamento

Per vedere il modello indoor in azione su uno scenario realistico, lancia lo script tappa5\_E\_appartamento\_demo.py nella cartella examples/ del repository. Simula un appartamento invernale con tre vasi indoor sparsi tra salotto (Room "salotto" con due vasi: un'orchidea su una finestra INDIRECT\_BRIGHT e un Pothos in posizione DARK) e camera da letto (Room "camera" con una sansevieria su davanzale DIRECT\_SUN, fisiologia CAM). Lo script mostra in azione la selezione automatica del metodo ET (diversa per ognuno dei tre vasi a seconda dei parametri specie), la persistenza completa delle Room nel database SQLite, e produce quattro grafici PNG che danno un'idea concreta del tipo di analisi che il modello indoor permette: andamento idrico per vaso, bilancio idrico per ambiente, heatmap dei metodi ET selezionati giorno per giorno, e confronto dei metodi su una settimana di scenario.

Lo script gira in pochi secondi senza hardware reale (usa fixture CSV per simulare il microclima delle due Room) ed è un buon punto di partenza per costruire la tua versione personalizzata sostituendo le fixture con EcowittAmbientSensor.daily\_aggregate quando avrai i tuoi WN31 collegati.

# 19 — Domande frequenti

Le domande che seguono sono quelle che probabilmente ti porrai nelle prime ore di utilizzo di fitosim. Le rispondo qui in modo concentrato per evitarti di doverle scoprire da solo.

## I numeri non corrispondono al mio vaso reale

È la situazione più comune ed è il punto in cui fitosim brilla davvero, perché ha gli strumenti per affrontarla. La causa più frequente è che i parametri di letteratura del substrato che stai usando non rispecchiano il tuo vaso specifico. La soluzione corretta è la calibrazione empirica del capitolo 8: con un sensore WH51 e qualche mese di letture storiche, puoi ricavare i parametri “veri” del tuo vaso e iniettarli nel modello. Se non hai un sensore, una soluzione più rudimentale ma comunque utile è di osservare quante irrigazioni reali fai in un mese, simulare lo stesso periodo con fitosim, e aggiustare manualmente theta\_FC del substrato finché il numero di irrigazioni simulate corrisponde al numero reale.

## Devo usare il Garden anche per un singolo vaso?

No, e ti consiglio di non farlo. Per un singolo vaso il Pot diretto è più semplice e più ergonomico. Il Garden ha senso quando ne hai almeno tre o quattro: a quel punto le sue capacità (apply\_step\_all, update\_all\_from\_sensors, current\_alerts) ti risparmiano davvero del codice ripetitivo. Per un vaso solo, il Garden aggiunge verbosità senza valore concreto.

## Le allerte si possono persistere?

No, e questa è una scelta architetturale deliberata. Le allerte sono una vista derivata dallo stato corrente del giardino, ricalcolate ogni volta che le chiedi. Se vuoi che il dashboard le “ricordi” tra esecuzioni, è il dashboard a doverlo fare: salva l’elenco di alert\_id che ha già notificato al giardiniere, e al prossimo ciclo confronta gli alert\_id correnti con quelli salvati per identificare le allerte nuove. fitosim non si fa carico di questa logica perché è policy del dashboard, non del modello agronomico.

## Posso usarlo per piante perenni come gli agrumi?

Sì, fitosim include gli agrumi nel suo catalogo (CITRUS) e gestisce le piante perenni correttamente. Per le perenni lascia il planting\_date a un valore qualunque del passato remoto, e fitosim userà i Kc del mid-season come coefficienti stabili per tutta la simulazione. La gestione dell’irrigazione segue le stesse regole degli annuali, ma con soglie di allerta più conservative perché le perenni hanno depletion\_fraction più alti.

## Non ho un sensore di umidità, fitosim mi serve comunque?

Sì. Il modello previsionale di base — caratterizzazione del vaso, geometria, sostrati personalizzati, dual-Kc, Garden, persistenza, eventi pianificati, allerte — funziona perfettamente con soli dati meteo. Le funzionalità di calibrazione e di feedback dal sensore restano dormienti, ma tutto il resto produce previsioni quantitativamente sensate basate sui parametri di letteratura.

## Quando dovrei aggiornare lo schema del database?

Mai manualmente: lo fa fitosim per te. Ogni volta che apri un GardenPersistence su un database esistente, fitosim verifica la versione dello schema (registrata nella tabella schema\_metadata) e applica automaticamente le migrazioni necessarie verso la versione corrente. Le migrazioni v1→v2 (channel\_id ai pot), v2→v3 (tabella eventi pianificati), v3→v4 (tabella stanze indoor) e v4→v5 (gradi-giorno accumulati e configurazione fenologica delle specie) sono già state applicate ai database creati con le versioni precedenti della libreria. Le future migrazioni manterranno la stessa policy: automatiche e senza perdita di dati.

## Le mie piante sono indoor, devo cambiare qualcosa?

Sì. Una pianta indoor vive un microclima completamente diverso da quello esterno, e la tappa 5 di fascia 2 ha introdotto un modello dedicato per questo caso. Il modello si basa sull’entità Room (vedi cap 18) che rappresenta lo spazio fisico in cui vivono uno o più vasi indoor con il loro microclima condiviso, alimentato dal sensore ambientale WN31 di Ecowitt. I vasi indoor si associano alla loro Room tramite il campo room\_id, e il bilancio idrico viene applicato con apply\_balance\_step\_from\_indoor (sul Pot) o apply\_step\_all\_from\_indoor (sul Garden), che alimentano il calcolo dal microclima della stanza invece che dal meteo esterno. Le novità aggiuntive della tappa 5 includono LightExposure a tre livelli per parametrizzare l’esposizione luminosa (DARK, INDIRECT\_BRIGHT, DIRECT\_SUN), il modulo science/indoor.py per la radiazione indoor (categoriale o continua come frazione dell’outdoor), e il sensore di substrato WH52 (upgrade del WH51 con temperatura ed EC del substrato).

## Ogni quanto devo ricalibrare il substrato?

La ricalibrazione completa via calibrate\_substrate ha senso una volta a stagione, perché i parametri “veri” del vaso evolvono lentamente nel tempo (il substrato si compatta, perde struttura, viene parzialmente sostituito al rinvaso). Una ricalibrazione settembre-ottobre con i dati raccolti durante l’estate è un’ottima cadenza pratica. Tra una ricalibrazione e l’altra, il feedback loop giornaliero (update\_all\_from\_sensors) corregge il drift di breve periodo.

# Appendice A — Catalogo delle specie pre-definite

fitosim include cinque specie pre-configurate, importabili da fitosim.domain.species. Ognuna ha i suoi coefficienti colturali, la sua frazione di esaurimento, le durate dei suoi stadi fenologici, e (per quelle abilitate al modello chimico) i range di EC e pH ottimali.

### BASIL — Basilico

Pianta annuale aromatica a ciclo breve. Kc tipici tra 0.6 e 1.05, depletion\_fraction di 0.4 che la rende sensibile allo stress. Stadi: 20 giorni iniziali, 30 giorni mid-season. Range EC ottimale 1.0-1.6 mS/cm, pH 6.0-7.0. Adatta a vasi piccoli (1-3 litri) sul balcone, in pieno sole o mezz’ombra. È la specie su cui sono stati sviluppati molti esempi di questo manuale.

### TOMATO — Pomodoro

Pianta annuale orticola a ciclo lungo. Kc tipici tra 0.6 e 1.15, depletion\_fraction di 0.4. Stadi: 30 giorni iniziali, 40 giorni mid-season. Pianta esigente in acqua, soprattutto durante la fase di fruttificazione. Adatta a vasi medi-grandi (10-15 litri) in pieno sole.

### LETTUCE — Lattuga

Pianta annuale orticola a ciclo molto breve. Kc tipici tra 0.7 e 1.0, depletion\_fraction bassa di 0.3. Stadi: 15 giorni iniziali, 20 giorni mid-season. Preferisce condizioni fresche e umide; soffre il caldo estivo.

### CITRUS — Agrumi

Pianta perenne sempreverde. Kc tipici tra 0.6 e 0.7 stabili, depletion\_fraction di 0.5 che la rende tollerante allo stress. Per le perenni il modello fenologico tripartito non è del tutto applicabile: usa i Kc mid-season come riferimento stabile.

### ROSEMARY — Rosmarino

Pianta perenne semi-mediterranea. Kc tipici intorno a 0.7-0.8, depletion\_fraction alta di 0.6 che la rende molto tollerante allo stress idrico. Le tue irrigazioni saranno meno frequenti di quelle del basilico anche con la stessa esposizione, perché la fisiologia della pianta accetta livelli idrici inferiori.

Se hai bisogno di una specie non inclusa nel catalogo, puoi costruire un nuovo oggetto Species seguendo lo schema di queste cinque, popolando i Kc, i Kcb (se vuoi attivare il dual-Kc), il depletion\_fraction, le durate degli stadi, e i range chimici (se vuoi attivare il modello chimico).

# Appendice B — Substrati e materiali base

## Substrati pre-configurati

Cinque substrati commerciali rappresentativi del giardinaggio domestico italiano, tutti importabili da fitosim.science.substrate.

### UNIVERSAL\_POTTING\_SOIL

Mix universale tipo “terriccio universale” da supermercato, tipicamente torba bionda \+ perlite \+ letame compostato in proporzioni circa 70/20/10. È il default per il giardinaggio generico. theta\_FC circa 0.42, theta\_PWP circa 0.13.

### ACIDOPHILE\_MIX

Mix per piante acidofile (azalee, rododendri, gardenie). pH naturale circa 5.0-5.5. Caratteristiche idriche simili al terriccio universale ma chimicamente più adatto a piante che soffrono nei substrati neutri.

### CACTUS\_MIX

Mix drenante per cactus e succulente. Maggior contenuto di sabbia e materiali minerali. theta\_FC più bassa (~0.25), drena rapidamente, va molto bene con specie xerofile che soffrono il ristagno.

### BONSAI\_AKADAMA

Akadama puro o quasi puro, il classico substrato giapponese per bonsai. Drena bene, ha buona ritenzione idrica nei micropori, struttura granulare stabile. Per i bonsai esperti.

### ORCHID\_BARK

Corteccia di pino in pezzi grossi, substrato specifico per le orchidee epifite. Quasi totalmente drenante, le radici devono ricevere aria e l’acqua deve passare rapidamente.

## Materiali base per mix personalizzati

Per comporre mix personalizzati, fitosim espone nove materiali base: TORBA\_BIONDA, COMPOST, PERLITE, VERMICULITE, AKADAMA, POMICE, LAPILLO, SABBIA, ARGILLA. Ognuno ha i suoi parametri idrici (theta\_FC, theta\_PWP), la sua densità apparente, e la sua CEC. Si combinano con compose\_substrate passando le frazioni in un dict che somma a 1.0.

# Appendice C — Glossario dei termini agronomici

Una raccolta dei termini tecnici che incontri nel manuale, con una definizione concisa per ognuno.

ET₀ (evapotraspirazione di riferimento): l’evapotraspirazione di una coltura ipotetica standardizzata (erba bassa, ben irrigata) nelle condizioni meteo del giorno. Espressa in mm. È la “forzante” meteo del modello FAO-56: si calcola dalle variabili meteo (temperatura, umidità, vento, radiazione) ed è uguale per tutte le piante della stessa zona climatica.

Kc (coefficiente colturale): fattore moltiplicativo specifico della specie e dello stadio fenologico, che converte ET₀ in ET effettiva della pianta. Una specie ad alto consumo come il pomodoro ha Kc fino a 1.15 in mid-season; una specie xerofila come il rosmarino ha Kc sotto 0.8.

theta\_FC (capacità di campo): contenuto idrico volumetrico del substrato dopo che l’eccesso d’acqua è drenato per gravità. È lo stato “ottimale” dopo un’irrigazione abbondante. Tipicamente tra 0.3 e 0.5 per i terricci da giardinaggio domestico.

theta\_PWP (punto di appassimento permanente): contenuto idrico volumetrico sotto al quale la pianta non riesce più ad estrarre acqua dal substrato e appassisce in modo irreversibile. Tipicamente tra 0.1 e 0.2.

TAW (total available water): differenza theta\_FC − theta\_PWP, l’acqua “usabile” dalla pianta tra i due estremi. Una grandezza più alta significa che la pianta ha più “riserva” tra una irrigazione e l’altra.

Kp (coefficiente di vaso): fattore moltiplicativo specifico del contenitore (materiale, colore, esposizione) che modula l’evapotraspirazione del singolo vaso. Estensione non standard di FAO-56, specifica del giardinaggio in vaso.

Kn (coefficiente nutrizionale): fattore moltiplicativo che modula l’evapotraspirazione effettiva in funzione dello stato chimico del substrato (EC fuori range, pH fuori range). Vaso in range chimico ottimale ha Kn=1; vaso in stress chimico totale ha Kn=0.30. Estensione di tappa 3 fascia 2.

EC (conducibilità elettrica): misura della concentrazione di sali disciolti nella soluzione del substrato, espressa in mS/cm. Indicatore della disponibilità di nutrienti e dello stress salino. Range tipici 1.0-2.0 mS/cm per la maggior parte delle specie domestiche.

CEC (capacità di scambio cationico): misura della capacità del substrato di trattenere e rilasciare ioni positivi (cationi nutritivi), espressa in meq/100g. Più alta la CEC, maggiore la capacità tampone del substrato contro le variazioni di fertilità.

Dual-Kc: variante avanzata del modello FAO-56 (capitolo 7 della pubblicazione FAO-56) che separa esplicitamente il coefficiente colturale in componente basale Kcb (traspirazione vegetale) e componente di evaporazione Ke (evaporazione superficiale dal substrato umido). Cattura la dinamica post-irrigazione che il single-Kc media.

Sottovaso (saucer): contenitore opzionale sotto al vaso che raccoglie l’acqua di drenaggio e la rende disponibile per riassorbimento capillare nei giorni successivi. Modellato come stato distinto in fitosim quando saucer\_capacity\_l > 0.

Forecast: proiezione dello stato dei vasi nei prossimi N giorni dato un forecast meteo, lavorando su deep copy senza side effects sul Garden corrente. Capacità della sotto-tappa D di tappa 4.

Allerta (Alert): comunicazione strutturata dal sistema al giardiniere quando una condizione del giardino richiede attenzione. Cinque categorie e tre severità. Capacità della sotto-tappa E di tappa 4. Non persistita: vista derivata dallo stato.

