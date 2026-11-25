__fitosim__

*Manuale utente*

Una guida pratica per usare fitosim nel tuo giardino domestico

*Dall’installazione al primo “hello basilico”, dai concetti fondamentali al vaso in casa. Il motore agronomico del singolo vaso: substrati, specie, evapotraspirazione, sensore, allerte.*

> **Dal 25 novembre 2026 (versione 0.46.0) fitosim è il motore, non più un'applicazione.** È nato per girare da solo — un giardino di vasi, un database, i sensori letti in rete, un'agenda — e dal settembre 2026 è il motore di **The Pot**, che ha il suo database, i suoi sensori e il suo calendario. Lo strato che faceva quelle cose (`Garden`, la persistenza SQLite, gli adapter dei sensori, gli eventi pianificati, il client Open-Meteo) è stato tolto. I capitoli 10–14 e 16, che lo descrivevano, sono ridotti a una nota; i capitoli 15, 17 e 18 dicono quello che resta. Chi vuole la versione di prima la trova nella storia git, fino alla 0.45.0.

*Maggio 2026 — Contenuti a fine fascia 2 (tappa 5). Numeri e riferimenti (test, schema DB, calibrazione) riallineati a luglio 2026, con la fascia 3 in corso.*

# 1 — Benvenuto in fitosim

fitosim è una libreria Python che ti aiuta a capire quanto e quando irrigare le piante nei tuoi vasi. Funziona modellando il bilancio idrico e chimico del singolo vaso giorno per giorno: quanta acqua entra (pioggia, irrigazione), quanta esce (evaporazione dal substrato, traspirazione della pianta), quanta resta disponibile alla pianta stessa, e come evolve la concentrazione di sali e il pH del substrato. Ti dà una stima quantitativa di quando il vaso si sta avvicinando alla soglia di stress idrico o chimico, in modo che tu possa pianificare gli interventi con un pizzico di anticipo invece di reagire al “lo vedo che soffre”.

Sotto il cofano fitosim implementa il modello FAO-56, lo standard agronomico internazionale per l’evapotraspirazione delle colture, con sei estensioni specifiche per il dominio dei vasi domestici che i modelli per il pieno campo non coprono. Tutta la matematica è dentro alla libreria — tu come utente vedi solo oggetti Python comodi: un Pot, una Species, un Substrate, qualche metodo da chiamare, e dei numeri sensati che escono dall’altra parte.

## Per chi è questo manuale

Questo manuale è scritto pensando a tre tipi di utenti che si sovrappongono in modo naturale. Il primo è il giardiniere tecnologicamente curioso che ha già una stazione meteo Ecowitt sul balcone, dei sensori di umidità WH51 nei vasi, e si chiede se tutti quei dati possano servire a qualcosa di più che riempire una dashboard. Il secondo è lo sviluppatore che sta costruendo un sistema di monitoraggio o di automazione del giardino domestico e cerca un motore agronomico solido da integrare come libreria di backend. Il terzo è lo studioso del verde — bonsaista, coltivatore di succulente, orticoltore da balcone — che vuole capire quantitativamente come i parametri del proprio setup influenzino il fabbisogno idrico delle sue piante.

Quello che il manuale dà per scontato è una conoscenza di base di Python e una familiarità minima con il vocabolario agronomico (l’appendice C ha un glossario per rinfrescarti la memoria). Quello che NON dà per scontato è che tu sappia scrivere FAO-56 a memoria: tutto quello che serve sapere è spiegato man mano che serve, e le decisioni di design sono giustificate quando introducono qualche scelta non ovvia.

## Cosa fitosim NON fa

È utile mettere subito in chiaro i confini del dominio. fitosim non è un sostituto di modelli idrologici di pieno campo come HYDRUS o RZWQM, che gestiscono bilanci a scala di parcella con flussi orizzontali tra suoli adiacenti — il modello del singolo vaso ignora deliberatamente questi effetti perché in un contenitore isolato non esistono. Non è un sistema di controllo in tempo reale: le sue stime sono giornaliere, non al minuto. Non è infine un sostituto del giardiniere: ti dice “il vaso è sceso sotto la soglia di allerta”, non “irriga adesso 250 ml” senza che tu abbia la possibilità di valutare le condizioni reali del momento.

Il dominio in cui fitosim sa fare bene il suo lavoro è il vaso domestico singolo o un piccolo gruppo di vasi su un balcone, su scala di tempo giornaliera, per piante individualmente identificabili e con substrati di parametri noti. In questo dominio specifico fitosim copre molto: caratterizzazione fisica dei contenitori, modelli di sottovaso, ricette di substrato personalizzate, dinamica a due fasi dell’evaporazione, modello chimico completo, calibrazione dai sensori, orchestrazione di più vasi, persistenza della storia in database, previsioni a N giorni con eventi pianificati, e sistema di allerte. Tutto quello che vedrai vive dentro a questo perimetro.

## Filosofia: opt-in con default neutri

Una caratteristica importante di fitosim che incontrerai ripetutamente è che ogni capacità avanzata è “opt-in”: se non la vuoi, non la attivi, e il sistema continua a funzionare come se non esistesse. Vuoi modellare il sottovaso? Aggiungi un parametro al tuo Pot. Hai un sensore di umidità? Chiama il metodo che lo integra. Ti basta un vaso solo? Continua a usare il Pot direttamente. Questa scelta architetturale ti permette di partire semplice e aggiungere complessità solo quando ne vedi il bisogno.

## Mappa del manuale

Il manuale è organizzato per costruire la tua competenza progressivamente. Il capitolo 2 ti mette in piedi l’ambiente di lavoro e ti fa scrivere il tuo primo “hello basilico”. Il capitolo 3 spiega i concetti fondamentali (la trinità Pot-Species-Substrate, lo stato idrico, le soglie di allerta), che sono il vocabolario di base che ti porterai dietro per tutto il resto del manuale.

I capitoli da 4 a 8 sviluppano una a una le capacità avanzate del modello scientifico del singolo vaso: caratterizzazione del vaso, sottovaso, sostrati personalizzati, dual-Kc, calibrazione empirica e feedback dal sensore. Il capitolo 9 è un primo ricettario di quattro casi d’uso end-to-end del singolo vaso.

I capitoli da 10 a 14 e il 16 descrivevano lo strato standalone — il giardino di più vasi, il database, i sensori in rete, gli eventi pianificati, la ricetta del balcone — e sono ridotti a una nota: quel lavoro oggi lo fa The Pot. Il capitolo 15 resta, col sistema di allerte applicato al singolo vaso.

I capitoli 17 e 18 sono il selettore di evapotraspirazione “best available”, che sceglie fra Penman-Monteith fisico, Penman-Monteith standard FAO-56 e Hargreaves-Samani secondo i dati disponibili (cap 17), e il modello dei vasi in casa, con la stanza, il suo microclima e la luce che arriva al vaso (cap 18).

Non devi leggere il manuale in ordine se hai fretta. Se vuoi subito vedere fitosim in azione, salta direttamente al capitolo 9 (singolo vaso). Se invece vuoi capire fitosim in profondità, leggi nell’ordine proposto.

# 2 — Installazione e primi passi

## Cosa ti serve

fitosim richiede Python 3.12 o superiore. La libreria è stata scritta in modo da non avere dipendenze esterne nel suo nucleo: tutto il codice agronomico, dal calcolo dell’ET₀ alla calibrazione empirica, gira con la sola standard library di Python. Per il normale uso del motore agronomico, l’installazione è leggera e porta benissimo su ambienti vincolati come Termux su Android o Raspberry Pi 5.

## Installazione

Per ora fitosim è distribuito come repository sorgente. Una volta scaricato il progetto, posizionati nella sua directory principale e verifica che la suite di test giri correttamente. È il modo migliore per assicurarti che il tuo ambiente Python sia configurato bene:

$ cd fitosim/

$ python -m pytest tests/

================= 1150 passed, 520 subtests passed =================

Se vedi un risultato simile (al momento di questo aggiornamento la suite conta 1150 test verdi più 520 sub-test), tutto è a posto e puoi proseguire. Il core gira con la sola standard library: le demo end-to-end, che usavano matplotlib, sono state tolte il 24 novembre 2026. I test coprono la fascia 1 e la fascia 2, più la fascia 3 (il layer di feedback, vedi il manuale di calibrazione). Se vedi errori di import, è possibile che la directory src/ non sia nel tuo path: ricorda di lanciare gli script con PYTHONPATH=src impostato, oppure di installare la libreria in modalità sviluppo con pip install -e .

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

Questo è il motore che fa girare tutto il resto. Le allerte, il passo dal meteo, il vaso in casa: sotto sotto è sempre apply\_balance\_step a essere chiamato, per quel vaso e per quel giorno.

## Il giorno fatto di blocchi

Dal 29 settembre 2026 (A7) il vaso sa anche avanzare *dentro* il giorno. `Pot.apply_blocks_from_weather` riceve i `WeatherBlock` di un giorno — un'ora l'uno con la stazione, una o tre con la previsione, in ora solare del sito — e per ogni blocco calcola l'ET₀ con la forma oraria di Penman-Monteith (FAO-56 eq. 53), valuta Ks sullo stato di quel momento e fa entrare pioggia e irrigazioni all'ora in cui accadono. Il giorno resta l'unità della contabilità (Kc, stadio, gradi-giorno, nutrienti), e il passo giornaliero di sempre è il caso di un solo blocco di 24 ore: gli stessi numeri. Quello che i blocchi aggiungono è l'*ora* dell'allerta (`alert_hour`) e il drenaggio giusto di un litro dato alle 20 invece che alle 8. Se ai blocchi manca umidità, vento o radiazione, l'ET₀ del giorno viene ripartita sul profilo del sole: la somma non cambia. Le decisioni e le ragioni sono in `domain/blocks.py`; l'esempio `examples/confronto_et0_risoluzione_temporale.py` (tolto con gli altri il 24-11-2026, nella storia git fino a `d310d17`) mette a confronto i due cammini su due settimane vere di Milano, una di luglio e una di gennaio, con lo stesso vaso.

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

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* `Garden` era l'orchestratore di più vasi: li teneva per etichetta, applicava un giorno a tutti, ne proiettava lo stato. Un giardino di vasi oggi è un elenco di `Pot` su cui chi chiama fa il suo ciclo; in The Pot è il database dell'app.

# 11 — Persistenza con SQLite

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* `GardenPersistence` salvava giardino, catalogo e storia in un file SQLite, con le migrazioni dallo schema v1 al v8. fitosim non persiste più niente: lo stato di un vaso è nei suoi campi, e chi lo vuole conservare lo scrive dove gli serve.

# 12 — Backup e trasporto in JSON

*Tolto il 24 novembre 2026 (fitosim 0.45.0).* Il modulo `fitosim.io.serialization`, con `export_garden_json` e `import_garden_json`, non c'è più: serviva agli esempi dello strato standalone.

# 13 — Sensori reali in batch

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* Gli adapter di `fitosim.io.sensors` (Ecowitt, Open-Meteo, HTTP-JSON, CSV) e l'aggiornamento in batch dal giardino non ci sono più. Resta il client grezzo del cloud Ecowitt, `fitosim.io.ecowitt`: `fetch_real_time` dà un'osservazione con, per canale, l'umidità, la temperatura e l'EC delle sonde nel substrato, e il vaso si aggiorna con `Pot.update_from_sensor` (capitolo 8).

# 14 — Eventi pianificati e previsioni

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* `ScheduledEvent`, `WeatherDayForecast` e il forecast a N giorni del giardino non ci sono più. Una previsione oggi si fa a mano: si copia il vaso (`copy.deepcopy`) e gli si applicano i giorni previsti con `apply_step` o `apply_balance_step_from_weather`, lasciando intatto l'originale.

# 15 — Il sistema di allerte

I numeri del bilancio sono utili, ma il giardiniere medio non vuole leggere serie di numeri: vuole un cruscotto che gli dica “questo vaso ha bisogno di attenzione” con un’icona, una severità, e una raccomandazione concreta. Il sistema di allerte è il pezzo che trasforma le previsioni quantitative in raccomandazioni qualitative.

Un’allerta è una comunicazione strutturata dal sistema al giardiniere quando una condizione del giardino richiede (o richiederà) la sua attenzione. La differenza fondamentale rispetto a un evento (storico o pianificato) è che un’allerta è DERIVATA dallo stato: non è qualcosa che è successo o che farò, è qualcosa che il sistema deduce dallo stato corrente o proiettato. Conseguenza pratica: le allerte non si persistono. Sono il risultato dell’applicazione delle regole allo stato corrente del modello, ricalcolate ogni volta che le chiedi.

## Cinque categorie e tre severità

Le allerte sono classificate in cinque categorie semantiche e tre livelli di severità. Le categorie sono: irrigation\_needed (vaso prossimo al PWP, va annaffiato), fertilization\_due (EC sotto il range ottimale, sarebbe utile una fertirrigazione), ec\_too\_high (EC criticamente alta, va fatto un lavaggio), ec\_too\_low (EC molto bassa, carenza nutrizionale), ph\_out\_of\_range (pH fuori dal range della specie). Le severità sono info (informativa), warning (attenzione), critical (urgente).

## Allerte sullo stato corrente

Le regole si applicano al vaso: ognuna guarda lo stato di oggi e torna un'allerta, o niente. Per averle tutte si itera sulla tupla `ALL_RULES`:

from datetime import date

from fitosim.domain.alerts import ALL\_RULES

oggi = date.today()

allerte = \[a for a in (regola(vaso, oggi) for regola in ALL\_RULES) if a is not None\]

for a in allerte:

    print(a.severity.value, a.message)

Per più vasi è lo stesso ciclo, vaso per vaso. Per le allerte *previste* si applicano le regole a una copia del vaso portata avanti coi giorni della previsione (capitolo 14).

## Le regole come funzioni pure

Le regole di allerta vivono nel modulo fitosim.domain.alerts come funzioni pure (Pot, date) → Optional\[Alert\], dichiarative e indipendenti tra loro. Sono accessibili individualmente, se te ne serve una sola:

from fitosim.domain.alerts import (

    check\_irrigation\_needed, check\_ec\_too\_high, ALL\_RULES,

)

alerta = check\_irrigation\_needed(vaso, date.today())

if alerta:

    print(f"Allerta: {alerta.message}")

\# Oppure applica tutte le regole.

tutte = \[r(vaso, date.today()) for r in ALL\_RULES\]

attive = \[a for a in tutte if a is not None\]

__*Nota: *__*Le soglie delle regole sono definite a partire dai parametri della specie e del substrato del singolo vaso, non sono valori globali. Il vaso di basilico (range EC 1.0-1.6) e il vaso di rosmarino (range EC diverso) producono allerte ec\_too\_high con soglie diverse, perché ec\_too\_high scatta a max\+0.5 mS/cm sopra il massimo della specie. È la conseguenza naturale del modello chimico per-vaso.*

# 16 — Una ricetta end-to-end del balcone

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* La ricetta metteva insieme giardino, database, sensori, eventi e allerte in tre settimane di balcone simulato. Per il singolo vaso valgono le ricette del capitolo 9.

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

## Integrazione automatica nel Pot

Nella pratica non chiamerai compute\_et direttamente: il vaso ha un metodo di alto livello che invoca il selettore per te. `apply_balance_step_from_weather(weather, water_input_mm, current_date)` riceve un WeatherDay (la dataclass meteo del giorno, in domain/weather.py) e applica compute\_et coi dati che ci sono e i parametri della specie:

from datetime import date

from fitosim.domain.weather import WeatherDay

meteo\_oggi = WeatherDay(

    date\_=date(2026, 7, 19),

    t\_min=18.0, t\_max=28.0,

    humidity\_relative=0.55,

    wind\_speed\_m\_s=2.5,

    solar\_radiation\_mj\_m2\_day=22.0,

)

vaso.apply\_balance\_step\_from\_weather(meteo\_oggi, 0.0, date(2026, 7, 19))

Chi ha già l'ET₀ calcolata da un'altra fonte la passa direttamente a `apply_step(et_0_mm, current_date, ...)`, come prima.

## Quando ti serve il Penman-Monteith fisico

Il fisico è l'opzione più accurata in assoluto, ma richiede che la specie abbia popolati i campi stomatal\_resistance\_s\_m e crop\_height\_m. Nel catalogo predefinito di fitosim queste informazioni sono presenti per le specie principali (BASIL ha rs=200 s/m e h=0.40 m, TOMATO ha rs=120 s/m e h=1.50 m, ROSEMARY ha rs=300 s/m e h=0.60 m, CACTUS ha rs=600 s/m e h=0.30 m per riflettere la fisiologia CAM, ecc.); se stai costruendo una Species custom, puoi popolarli usando la letteratura agronomica o lasciarli a None per ricadere automaticamente sul Penman-Monteith standard.

La differenza tra fisico e standard è particolarmente significativa per specie con fisiologia atipica come succulente e cactacee a metabolismo CAM, dove la resistenza stomatica elevata produce un'evapotraspirazione molto più bassa di quanto Hargreaves o Penman-Monteith standard predirebbero. Per queste specie il fisico è quasi obbligatorio se vuoi previsioni realistiche; per specie a metabolismo C3 standard (basilico, rosmarino, pomodoro) lo standard è quasi altrettanto buono.

## Diagnostica della formula scelta

Quando vuoi sapere quale formula sta usando il selettore per un dato vaso in una data giornata, puoi chiamare compute\_et direttamente con gli stessi argomenti che il Pot userebbe, e ispezionare il campo method del risultato. Più operativamente, la demo dell'appartamento (sotto-tappa 5-E) produce una heatmap PNG che mostra giorno per giorno e vaso per vaso quale metodo è stato usato, ed è un buon punto di partenza per costruire la stessa visualizzazione nel tuo dashboard.

## La forma oraria e i blocchi

Dal 29 settembre 2026 (A7) le due Penman-Monteith prendono un parametro `hours`: con 24 sono quelle di sempre, con 1 sono la forma oraria di FAO-56 (eq. 53), e la radiazione netta e il flusso nel suolo vanno dati sul blocco. Di norma non le chiami tu: `domain.blocks.et0_for_blocks` prende i `WeatherBlock` di un giorno e per ciascuno calcola l'ET₀ con la stessa gerarchia del selettore — Penman-Monteith fisico se la specie ha resistenza stomatica e altezza, standard altrimenti — con la R_a del blocco, la radiazione netta del blocco, G di giorno e di notte e il rapporto notturno R_s/R_so dalle 2–3 ore prima del tramonto; i blocchi notturni che escono negativi valgono zero. Se ai blocchi manca umidità, vento o radiazione, calcola l'ET₀ del giorno come farebbe il selettore e la ripartisce sui blocchi in proporzione alla R_a: il totale non cambia. Il Penman-Monteith fisico dà ET, non ET₀: il `Pot` la riporta a «ET₀ equivalente» dividendo per il Kc dello stadio, come fa il cammino giornaliero. Il capitolo 3 dice come il vaso usa questi blocchi.

Dal 21 ottobre 2026 (A9) le due Penman-Monteith giornaliere prendono anche gli estremi del giorno, `t_min` e `t_max`, e il selettore glieli passa sempre: la pressione di vapore a saturazione e_s è la media di e°(T_max) ed e°(T_min) (FAO-56 eq. 12) e non più e°(T_media), che e° essendo convessa sottostima — con un'escursione di sedici gradi l'11 % su e_s, il 3 % sull'ET₀ — mentre Δ resta alla temperatura media (eq. 13). La pressione di vapore attuale e_a segue l'eq. 17 quando il `WeatherDay` porta le umidità estreme, `humidity_min` e `humidity_max` (una stazione che campiona ogni quarto d'ora le ha, Open-Meteo le dà come aggregati del giorno), e l'eq. 19 dalla media altrimenti; la stessa e_a entra nella radiazione netta, così R_n e l'ET parlano la stessa lingua. La forma oraria dei blocchi non cambia: lavora su e°(T_ora), com'è giusto per l'ora. Sulle settimane vere dell'esempio delle stagioni l'ET₀ giornaliera di fitosim stava il 2–4 % sotto la FAO di riferimento; con A9 coincide al decimo di percento — quello che resta è il coefficiente aerodinamico, 900/(T+273) fisso nella FAO ed esplicito in fitosim — e l'esempio 18 del FAO-56, Bruxelles il 6 luglio, torna a un decimo di millimetro.

# 18 — Vasi indoor: Room, microclima e luce al vaso

Fino al capitolo 17 il manuale ha trattato implicitamente vasi outdoor: vasi che vivono sul balcone o in giardino, ricevono pioggia, sono esposti al sole e al vento, e il loro bilancio idrico è alimentato dai dati meteo esterni. Per i vasi indoor — quelli che vivono dentro casa, in salotto, in cucina, in camera da letto — il quadro è completamente diverso: non ricevono pioggia, il vento è quello eventualmente generato da un ventilatore, l'umidità relativa è quella della stanza non quella del balcone, la temperatura è quella della stanza, e la radiazione solare è una piccola frazione di quella outdoor che dipende dalla posizione del vaso rispetto alle finestre.

La tappa 5 della fascia 2 ha introdotto un modello dedicato per i vasi indoor, basato su una nuova entità di dominio chiamata Room che rappresenta lo spazio fisico (una stanza o una zona di una stanza) in cui vivono uno o più vasi indoor con il loro microclima condiviso. Questo capitolo ti spiega come modellare il tuo appartamento con fitosim: come creare le Room, come associarvi i vasi, come alimentare il modello dal sensore ambientale WN31 di Ecowitt, come parametrizzare l'esposizione luminosa di ogni vaso.

## Perché esiste l'entità Room

L'introduzione della Room non è una sofisticazione gratuita ma una conseguenza fisica del fatto che il sensore WN31 di Ecowitt (alias commerciale WH31, lo stesso prodotto con due nomi) non è una sonda dedicata al singolo vaso ma un trasmettitore ambientale che misura il microclima di una stanza intera. Cinque vasi che condividono il salotto condividono lo stesso microclima ambientale; un sesto vaso in camera da letto richiede un secondo WN31 per quella stanza.

Il modello rispecchia questa fisica esplicitamente attraverso l'entità Room invece di duplicare i dati meteo per ogni vaso. Ogni Room ha un room\_id univoco (una stringa scelta da te, per esempio "salotto"), un nome leggibile per UI e log, l'eventuale channel\_id del WN31 mappato, il microclima corrente come stato mutabile, e un default\_wind\_m\_s di 0.5 m/s per rappresentare il vento minimo convettivo della stanza. I Pot indoor si associano alla loro Room tramite il campo opzionale room\_id.

## Costruire le Room del tuo appartamento

Una Room è un oggetto che crei tu, una per stanza:

from fitosim.domain.room import Room

salotto = Room(room\_id="salotto", name="Salotto")

camera = Room(room\_id="camera", name="Camera da letto")

Se hai un ventilatore acceso costantemente in una stanza puoi cambiare il suo default\_wind\_m\_s. La Room non legge sensori: il microclima del giorno glielo dai tu, come nel paragrafo sul passo in casa.

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

I vasi all'aperto restano senza room\_id e senza light\_exposure (entrambi sono opzionali e None per default): ognuno segue il suo modello.

## Il passo in casa e il microclima della stanza

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* L'adapter `EcowittAmbientSensor`, che leggeva il sensore d'aria WN31 e ne faceva il microclima della stanza, non c'è più: l'aria della stanza si legge col client `fitosim.io.ecowitt` o da dove la tieni, e al vaso si passa come `IndoorMicroclimate` del giorno, con la minima e la massima:

from fitosim.domain.room import IndoorMicroclimate, MicroclimateKind

aria = IndoorMicroclimate(

    kind=MicroclimateKind.DAILY, temperature\_c=21.0, humidity\_relative=0.50,

    t\_min=19.0, t\_max=23.0,

)

vaso.apply\_balance\_step\_from\_indoor(aria, 0.0, date(2026, 12, 10), room=salotto)

Il passo prende la radiazione al vaso dal dato migliore che gli dai: la radiazione globale misurata al vaso (`global_radiation_at_pot_mj_m2_day`), poi la radiazione di fuori per una frazione misurata del posto (`light_fraction_override`), poi per la frazione del livello di luce, infine il numero fisso del livello. Da un sensore di luce in lux si passa per `fitosim.science.light.shortwave_from_illuminance`.

## La radiazione indoor: categoriale o continua

Il modulo science/indoor.py offre due modi per stimare la radiazione indoor di un vaso: il modo categoriale e il modo continuo. Sceglie il modo automaticamente in funzione dei dati che hai a disposizione, ma è utile sapere quale dei due sta usando.

Il modo categoriale associa al LightExposure tre valori fissi indipendenti dalla stagione: DARK = 1.5 MJ/m²/giorno, INDIRECT\_BRIGHT = 4.0, DIRECT\_SUN = 8.0. Sono valori medi annuali per una casa di latitudine padana, calibrati su letteratura agronomica generica. È il fallback semplice che funziona sempre, anche quando non hai dati outdoor.

Il modo continuo stima la radiazione indoor come una frazione della radiazione globale outdoor del giorno: DARK = 5% di outdoor, INDIRECT\_BRIGHT = 15%, DIRECT\_SUN = 40%. È più accurato del categoriale perché cattura naturalmente la stagionalità (un vaso DIRECT\_SUN riceve molto meno sole in inverno che in estate, perché la radiazione outdoor è stagionalmente più bassa) e anche le variazioni giornaliere (giorno nuvoloso vs sereno). Richiede però che tu abbia anche i dati di radiazione outdoor del giorno, tipicamente dal piranometro della tua stazione Ecowitt esterna.

Per usare il modo continuo, basta passare anche il dato outdoor al metodo apply\_step\_all\_from\_indoor tramite il parametro outdoor\_solar\_radiation\_mj\_m2\_day. Se lo lasci a None, il sistema usa automaticamente il modo categoriale.

## Il sensore di substrato WH52

*Tolto il 25 novembre 2026 (fitosim 0.46.0), con lo strato standalone.* L'adapter `EcowittWH51SoilSensor` non c'è più. Il WH52 misura l'umidità del substrato, la sua temperatura e l'EC; le letture arrivano dal client grezzo, `fitosim.io.ecowitt.fetch_real_time`, che le dà per canale (`soil_moisture_pct`, `soil_temperature_c`, `soil_ec_mscm`, e il grezzo `soil_ad`). La taratura della sonda e l'aggiornamento del vaso restano di chi chiama.

## Una ricetta dell'appartamento

Lo script dimostrativo `tappa5_E_appartamento_demo.py`, che simulava un appartamento invernale con tre vasi in due stanze, è stato tolto il 24 novembre 2026 con gli altri esempi; la storia git lo conserva.

# 19 — Domande frequenti

Le domande che seguono sono quelle che probabilmente ti porrai nelle prime ore di utilizzo di fitosim. Le rispondo qui in modo concentrato per evitarti di doverle scoprire da solo.

## I numeri non corrispondono al mio vaso reale

È la situazione più comune ed è il punto in cui fitosim brilla davvero, perché ha gli strumenti per affrontarla. La causa più frequente è che i parametri di letteratura del substrato che stai usando non rispecchiano il tuo vaso specifico. La soluzione corretta è la calibrazione empirica del capitolo 8: con un sensore WH51 e qualche mese di letture storiche, puoi ricavare i parametri “veri” del tuo vaso e iniettarli nel modello. Se non hai un sensore, una soluzione più rudimentale ma comunque utile è di osservare quante irrigazioni reali fai in un mese, simulare lo stesso periodo con fitosim, e aggiustare manualmente theta\_FC del substrato finché il numero di irrigazioni simulate corrisponde al numero reale.

## Le allerte si possono persistere?

No, e questa è una scelta architetturale deliberata. Le allerte sono una vista derivata dallo stato corrente del giardino, ricalcolate ogni volta che le chiedi. Se vuoi che il dashboard le “ricordi” tra esecuzioni, è il dashboard a doverlo fare: salva l’elenco di alert\_id che ha già notificato al giardiniere, e al prossimo ciclo confronta gli alert\_id correnti con quelli salvati per identificare le allerte nuove. fitosim non si fa carico di questa logica perché è policy del dashboard, non del modello agronomico.

## Posso usarlo per piante perenni come gli agrumi?

Sì, fitosim include gli agrumi nel suo catalogo (CITRUS) e gestisce le piante perenni correttamente. Per le perenni lascia il planting\_date a un valore qualunque del passato remoto, e fitosim userà i Kc del mid-season come coefficienti stabili per tutta la simulazione. La gestione dell’irrigazione segue le stesse regole degli annuali, ma con soglie di allerta più conservative perché le perenni hanno depletion\_fraction più alti.

## Non ho un sensore di umidità, fitosim mi serve comunque?

Sì. Il modello previsionale di base — caratterizzazione del vaso, geometria, sostrati personalizzati, dual-Kc, allerte — funziona perfettamente con soli dati meteo. Le funzionalità di calibrazione e di feedback dal sensore restano dormienti, ma tutto il resto produce previsioni quantitativamente sensate basate sui parametri di letteratura.

## Le mie piante sono indoor, devo cambiare qualcosa?

Sì. Una pianta indoor vive un microclima completamente diverso da quello esterno, e la tappa 5 di fascia 2 ha introdotto un modello dedicato per questo caso. Il modello si basa sull’entità Room (vedi cap 18) che rappresenta lo spazio fisico in cui vivono uno o più vasi indoor con il loro microclima condiviso, alimentato dal sensore ambientale WN31 di Ecowitt. I vasi indoor si associano alla loro Room tramite il campo room\_id, e il bilancio idrico viene applicato con apply\_balance\_step\_from\_indoor, che alimenta il calcolo dal microclima della stanza invece che dal meteo esterno. Le novità aggiuntive della tappa 5 includono LightExposure a tre livelli per parametrizzare l’esposizione luminosa (DARK, INDIRECT\_BRIGHT, DIRECT\_SUN), il modulo science/indoor.py per la radiazione indoor (categoriale o continua come frazione dell’outdoor), e il sensore di substrato WH52 (upgrade del WH51 con temperatura ed EC del substrato).

## Ogni quanto devo ricalibrare il substrato?

La ricalibrazione completa via calibrate\_substrate ha senso una volta a stagione, perché i parametri “veri” del vaso evolvono lentamente nel tempo (il substrato si compatta, perde struttura, viene parzialmente sostituito al rinvaso). Una ricalibrazione settembre-ottobre con i dati raccolti durante l’estate è un’ottima cadenza pratica. Tra una ricalibrazione e l’altra, il feedback loop giornaliero (update\_all\_from\_sensors) corregge il drift di breve periodo.

## Posso far girare il modello a ore invece che a giorni?

Sì, dal 29 settembre 2026 (A7), con `Pot.apply_blocks_from_weather`: gli passi i `WeatherBlock` di un giorno — un'ora l'uno dalla stazione, una o tre dalla previsione, in ora solare del sito — più la longitudine e il fuso standard, e il vaso avanza blocco per blocco. Quello che cambia: l'ET₀ è quella oraria di FAO-56, Ks è valutato sullo stato del momento, pioggia e irrigazioni entrano all'ora in cui accadono, e l'allerta ha un'ora (`alert_hour`). Quello che non cambia: Kc, stadio, gradi-giorno e nutrienti restano del giorno, e un solo blocco di 24 ore dà esattamente il passo giornaliero. Sui millimetri della settimana la differenza è di pochi punti percentuali; sull'ora dell'allerta e sul drenaggio di un litro dato la sera invece che la mattina, no. Il capitolo 3 e l'esempio `examples/confronto_et0_risoluzione_temporale.py` (tolto con gli altri il 24-11-2026, nella storia git fino a `d310d17`) (una settimana di luglio e una di gennaio) lo mostrano coi numeri.

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

Kn (coefficiente nutrizionale): fattore moltiplicativo che modula la traspirazione della pianta in funzione dello stato chimico del substrato. Vaso in range chimico ottimale ha Kn=1. Sopra il massimo di EC della specie il Kn perde il 12% per ogni mS/cm in più (la pendenza del coefficiente di stress salino di FAO-56, eq. 83), fino a un pavimento di 0.30. Il pH non entra nel Kn (dal 2026-09-20): agisce sulla nutrizione in settimane, non sulla traspirazione del giorno, e nel vaso è uno stato stimato, non misurato; resta un’allerta, oltre una tolleranza di ±0.3. L’EC sotto il range non riduce l’ET (una soluzione povera di sali non ostacola l’assorbimento d’acqua): è una carenza nutrizionale, segnalata dalle allerte fertilization\_due ed ec\_too\_low. Nel dual-Kc il Kn agisce sulla traspirazione (Kcb) e non sull’evaporazione dal substrato (Ke). Estensione di tappa 3 fascia 2.

Blocco (A7): una fetta del giorno, da un'ora a dodici, in ora solare del sito, con il suo meteo (`WeatherBlock`) o la sua ET₀ e la sua acqua in entrata (`BalanceBlock`). I blocchi di un giorno lo coprono tutto, contigui, da 0 a 24; il giorno intero è il blocco di 24 ore, e il passo giornaliero di sempre ne è il caso particolare.

Ora dell'allerta (alert\_hour): nel giorno a blocchi, la fine del primo blocco in cui l'acqua è scesa sotto la soglia della specie; 0 se il giorno è cominciato già sotto, None se non è successo. È l'informazione che il passo giornaliero non può dare.

EC (conducibilità elettrica): misura della concentrazione di sali disciolti nella soluzione del substrato, espressa in mS/cm. Indicatore della disponibilità di nutrienti e dello stress salino. Range tipici 1.0-2.0 mS/cm per la maggior parte delle specie domestiche.

CEC (capacità di scambio cationico): misura della capacità del substrato di trattenere e rilasciare ioni positivi (cationi nutritivi), espressa in meq/100g. Più alta la CEC, maggiore la capacità tampone del substrato contro le variazioni di fertilità.

Dual-Kc: variante avanzata del modello FAO-56 (capitolo 7 della pubblicazione FAO-56) che separa esplicitamente il coefficiente colturale in componente basale Kcb (traspirazione vegetale) e componente di evaporazione Ke (evaporazione superficiale dal substrato umido). Cattura la dinamica post-irrigazione che il single-Kc media.

Sottovaso (saucer): contenitore opzionale sotto al vaso che raccoglie l’acqua di drenaggio e la rende disponibile per riassorbimento capillare nei giorni successivi. Modellato come stato distinto in fitosim quando saucer\_capacity\_l > 0.
Allerta (Alert): comunicazione strutturata dal sistema al giardiniere quando una condizione del giardino richiede attenzione. Cinque categorie e tre severità. Capacità della sotto-tappa E di tappa 4. Non persistita: vista derivata dallo stato.

