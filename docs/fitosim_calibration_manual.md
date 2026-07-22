__fitosim — Manuale di calibrazione__

*Procedure operative per la calibrazione del modello sui vasi reali del balcone*

*Maggio 2026 — Fase iniziale della fascia 3. Aggiornato luglio 2026: la parte matematica della fascia 3 (fase A del layer di feedback) è ora implementata in fitosim; le note "Aggiornamento fascia 3" nei capitoli collegano le procedure manuali qui descritte ai moduli che le eseguono.*

# 1 — Premessa: cosa significa "calibrare" fitosim

Fino al manuale utente principale, fitosim ti è stato presentato come una libreria che descrive il bilancio idrico e chimico dei tuoi vasi a partire da un modello FAO-56 esteso. Questo modello arriva configurato di fabbrica con parametri di letteratura ragionevoli per le specie e i substrati più comuni, ma "ragionevole" non vuol dire "esatto per il tuo balcone". Le foglie del tuo rosmarino non sanno di essere descritte da un Kc di letteratura, e il tuo terriccio universale del vivaio sotto casa non ha esattamente le caratteristiche idriche del terriccio universale generico testato in laboratorio dieci anni fa. Il modello generico ti darà previsioni nell'ordine di grandezza giusto, magari sbagliate del trenta o del cinquanta per cento, e questo è abbastanza per cominciare ad avere un dashboard utile, ma non è abbastanza per fare gestione fine.

La calibrazione è il processo di trasformare fitosim da "libreria genericamente plausibile" a "libreria specifica per il tuo balcone milanese". Si fa raccogliendo dati di osservazione sui tuoi vasi reali per un periodo abbastanza lungo da catturare la variabilità stagionale, e poi confrontando le previsioni del modello con quei dati osservati per identificare i parametri che vanno aggiustati. Non è una procedura magica: è statistica applicata, con tutti i limiti e i rischi che la statistica comporta. Questo manuale ti accompagna passo-passo in modo che tu possa farlo bene, evitando le trappole più comuni e ottenendo un risultato di cui ti puoi fidare.

## I quattro livelli di calibrazione, in ordine

Calibrare fitosim significa in realtà calibrare quattro cose distinte, organizzate in una gerarchia che riflette la struttura del modello. Procedere nell'ordine giusto è fondamentale, perché ogni livello assume che i livelli precedenti siano già stati tarati e quindi affidabili. Saltare un livello o invertire l'ordine produce un effetto sgradevole: gli errori di un livello inferiore non calibrato vengono attribuiti al livello superiore, che viene quindi calibrato male compensando errori che non sono suoi.

Il primo livello è la calibrazione dei sensori. I tuoi sensori WH51 e WH52 leggono il theta volumetrico, la temperatura e l'EC del substrato a partire da segnali elettrici grezzi (capacità dielettrica, resistività), e li convertono in valori fisici tramite una funzione di trasferimento generica calibrata in fabbrica per "soil" generico. Nel tuo specifico substrato, in particolare nella corteccia delle orchidee che è molto diversa dal soil generico, questa funzione di trasferimento ha un offset sistematico che può arrivare al venti per cento. Calibrare il sensore significa misurare questo offset e correggerlo, e si fa confrontando la lettura del sensore con la massa d'acqua misurata dalla pesata del vaso.

Il secondo livello è la calibrazione dei substrati. Una volta che ti fidi del sensore, puoi usare le sue letture per stimare i parametri idrici fondamentali del tuo specifico substrato: il theta a capacità di campo (theta\_fc, lo stato di saturazione operativa subito dopo l'irrigazione e il drenaggio), il theta al punto di appassimento (theta\_pwp, lo stato di asciugatura massima oltre il quale la pianta non riesce più a estrarre acqua), e per i substrati che lavorano in regime dual-Kc anche REW e TEW (acqua di evaporazione rapida e totale dello strato superficiale). Fitosim ha già un modulo dedicato a questo (science/calibration.py) che esegue la stima automaticamente da serie temporali di theta osservato.

Il terzo livello è la calibrazione delle specie. Una volta che ti fidi del sensore E del substrato, puoi usare le serie temporali di theta calibrato per stimare quanto consuma la pianta giorno per giorno, e confrontare il consumo osservato con quello previsto dal modello. Le differenze sistematiche che emergono ti dicono come correggere i parametri della specie: i Kc per fase fenologica, le date di transizione tra fasi, la resistenza stomatica per il Penman-Monteith fisico, l'altezza colturale. Questa è la parte agronomicamente più ricca e quella che giustifica davvero un anno di osservazioni.

Il quarto livello è la calibrazione del modello chimico, possibile solo sui vasi strumentati con WH52 perché lì hai l'EC del substrato misurata. Sui vasi che fertirrighi attivamente puoi calibrare il coefficiente nutrizionale Kn (quanto la pianta riduce il consumo idrico in funzione dello stress chimico) e il coefficiente di accumulo dei sali nelle fertirrigazioni. Per il pH del substrato fitosim ha un modello separato, ma i sensori WH51 e WH52 non misurano il pH, quindi questa calibrazione si fa con misure manuali periodiche con pH-metro a stick.

## Aggiornamento (fascia 3, fase A): i moduli che automatizzano questi livelli

Da quando questo manuale è stato scritto, fitosim ha implementato la matematica di questi livelli come **funzioni pure** in `science/`, senza dipendenze esterne. Il livello 1 (la funzione di trasferimento della sonda, S\_sonda → theta\_vero) resta un'analisi tua, ma tutto il resto ha ora un'API:

| Livello / parametro | Modulo | Segnale |
|---|---|---|
| Livello 2 — theta\_fc, theta\_pwp | `science/calibration.py` (`calibrate_substrate`) | ancora ai picchi/valli di theta |
| Livello 3 — Kc | `science/calibration.py` (pendenza di asciugamento) | velocità di discesa della curva |
| Livello 3 — Kc (ground truth) | `science/lysimeter.py` | pesata del vaso |
| Livello 3 — Kc senza sensore | `science/behavioral_calibration.py` | scostamento delle irrigazioni |
| Livello 3 — date di transizione | `science/phenology.py` | gradi-giorno (GDD) |
| Più fonti sullo stesso Kc | `science/calibration_resolution.py` | precedenza tra le proposte |

Due principi che questi moduli condividono e che vale la pena tenere a mente leggendo le procedure manuali qui sotto. Primo: **propongono, non applicano**. Ogni funzione restituisce una *proposta* di correzione con confidenza e spiegazione; l'applicazione è un passo separato che lavora su una **copia** della specie, mai sul catalogo globale — così un errore di calibrazione non contamina gli altri vasi. Secondo: le procedure manuali descritte in questo manuale non sono state rese obsolete dai moduli — le spiegano. Capire come si pesa un vaso e come si estrae il consumo dalle serie di theta è il modo per interpretare (e non fidarsi ciecamente di) ciò che i moduli restituiscono. Il progetto completo del layer è in `docs/fitosim_feedback_layer_design.md`.

## Strumentazione che ti serve, oltre ai sensori

Per fare la calibrazione di livello 1 (sensori) ti serve una bilancia da cucina con risoluzione di un grammo per i vasi sotto i tre chili, e una bilancia da cucina con risoluzione di dieci grammi per i vasi tra i tre e i sei chili. La bilancia non deve essere di laboratorio, ma deve essere stabile (non quella a molla, ma quella elettronica a celle di carico) e deve avere il piano abbastanza grande da accogliere i vasi. Per il tuo setup di vasi tra duecento grammi e sei chili, una sola bilancia da cucina con portata sei o sette chili e risoluzione un grammo copre tutto il range con margine di sicurezza, ed è quella che ti consiglio di acquistare se non ne hai già una. Modelli a questo livello costano tra i venti e i quaranta euro.

Ti serve poi un pH-metro a stick per il livello 4 (calibrazione modello chimico). I modelli a sonda diretta da inserire nel substrato costano tra i quindici e i trenta euro e leggono direttamente il pH della soluzione del substrato. Verifica che il modello che acquisti abbia la possibilità di calibrazione a due punti (pH 4.00 e pH 7.00 con soluzioni di calibrazione standard, vendute in flaconcini sigillati per pochi euro) perché senza calibrazione iniziale anche il pH-metro più caro è impreciso del venti per cento. Se il pH-metro che hai legge anche l'EC è un bonus, ma non è essenziale visto che l'EC ce l'hai dai WH52.

Infine ti serve un termometro per il substrato, che può essere lo stesso del pH-metro se il modello lo prevede oppure un termometro a sonda separato (dieci euro), per le misure di controllo della temperatura del substrato sui vasi non strumentati con WH52. Non è strettamente necessario per la calibrazione che faremo in fascia 3 (il modello attuale non usa la temperatura del substrato come input), ma ti serve per il futuro quando estenderemo il modello in questa direzione.

## Il diario degli eventi: la cosa più importante di tutte

Prima ancora di parlare di sensori e di pesate e di formule, voglio insistere su un punto operativo che fa la differenza tra una calibrazione utile e una inutile: il diario degli eventi. La calibrazione è una procedura statistica, e la statistica è spietata con i dati anomali non documentati. Se durante l'anno di test capita un evento che invalida o altera l'interpretazione delle misure di un giorno o di una settimana (un acquazzone improvviso che ha bagnato i vasi outdoor che dovevano restare asciutti per il ciclo di asciugatura, un guasto del sensore che ha dato letture nulle, una concimazione fatta in un giorno diverso da quello pianificato, un vaso urtato e spostato in una posizione con esposizione diversa, un viaggio fuori casa di una settimana che ha alterato le irrigazioni, un trattamento antiparassitario che ha sporcato la sonda, una foglia caduta sopra il sensore che ha creato un microclima locale anomalo, un travaso di emergenza dopo che il vaso si è rotto), tu devi sapere a posteriori cosa è successo.

Senza diario, in un anno avrai accumulato tra le cinquanta e le cento situazioni del genere, ne ricorderai una piccola minoranza, e sui restanti farai congetture sbagliate che inquineranno la calibrazione. Il diario non deve essere sofisticato: una semplice tabella con data, ora approssimativa, vaso coinvolto (label tipo "oleandro-2"), descrizione dell'evento in una o due frasi, ed eventualmente flag di severità ("anomalia minore, escludere il dato del giorno" oppure "evento normale, da documentare ma il dato resta valido"). Può essere una colonna in un foglio di calcolo, una tabella notes nel database del logging, un file di testo gestito a mano. L'importante è che esista, che sia tenuto aggiornato in tempo reale (non a fine settimana cercando di ricordare cosa è successo), e che venga consultato sistematicamente in fase di analisi dei dati.

## Lo split dei dati: training e validation

L'altra protezione metodologica importante è la separazione dei dati in due gruppi distinti, da decidere prima di iniziare la calibrazione e non dopo. Il primo gruppo (training) viene usato per stimare i parametri del modello calibrato. Il secondo gruppo (validation) viene tenuto rigorosamente da parte e usato solo alla fine per verificare che il modello calibrato funzioni anche su dati che non ha visto durante la calibrazione. Senza questa separazione, ti convinceresti sempre che la calibrazione è andata bene perché stai valutando il modello sugli stessi dati con cui l'hai stimato, ed è circolarità.

Per la nostra fascia 3 ti propongo questa divisione: dei dodici mesi totali di osservazione, i primi otto vanno in training e gli ultimi quattro in validation. Lo split temporale è preferibile a uno split casuale perché riflette la situazione reale in cui userai il modello: lo userai per prevedere il futuro a partire dal passato, e quindi devi validarlo con la stessa logica. Se la calibrazione tarata su gennaio-agosto funziona anche su settembre-dicembre, allora il modello è genuinamente utile. Se funziona solo nel periodo di training e degrada in validation, allora hai un caso di overfitting (il modello ha memorizzato le idiosincrasie del training set invece di generalizzare).

Le metriche di successo da fissare in anticipo sono due: per il modello idrico, l'RMSE (root mean square error) della previsione di theta giorno per giorno rispetto alla lettura calibrata del sensore, espresso in unità di theta volumetrico (un valore di 0.02 significa errore tipico del due per cento volumetrico, che è un buon risultato; un valore di 0.05 è marginale; oltre 0.08 il modello calibrato non è significativamente migliore di quello generico). Per il modello chimico, la stessa metrica RMSE applicata alla previsione di EC rispetto alla lettura del WH52, espressa in mS/cm.

# 2 — Setup iniziale dei vasi prima di iniziare il logging

Prima di accendere il logging e iniziare a raccogliere dati, devi preparare ogni vaso in modo che le misure dei mesi successivi siano confrontabili tra loro e interpretabili. Questo capitolo descrive le operazioni preparatorie da fare una sola volta sui sedici vasi del setup definitivo, prima del giorno zero.

## Etichettatura dei vasi e mappatura nel database

Ogni vaso deve avere una label univoca, scelta da te, che resta invariata per tutto l'anno di calibrazione e oltre. Ti suggerisco una convenzione che mescola la specie e un numero progressivo, e che mantenga l'informazione della replica e dell'eventuale esposizione: "phalaenopsis-1-finestra", "phalaenopsis-2-media", "phalaenopsis-3-interna", "phalaenopsis-4", "phalaenopsis-5", "phalaenopsis-6", "sansevieria-1", "sansevieria-2", "pothos-1", "ficus-elastica-1", "aloe-1", "aloe-2", "oleandro-1-fertirrigato", "oleandro-2", "oleandro-3", "oleandro-4", "oleandro-5", "rosmarino-1-sole", "rosmarino-2-mezzombra". Sono diciassette label, una per ognuno dei vasi del tuo setup. Stampa un'etichetta adesiva resistente all'acqua e attaccala sul vaso, sotto il bordo dove il sole non la sbiadisce. La stessa label la userai come Pot.label nel codice fitosim.

Crea il garden in fitosim e aggiungi tutti i vasi. Per i vasi indoor associali alle rispettive Room (presumibilmente "salotto" e altre stanze a seconda di come hai distribuito i vasi). I vasi outdoor non hanno room\_id. Salva il garden nel database SQLite. Esempio di setup iniziale del codice:

from fitosim.domain.garden import Garden

from fitosim.domain.pot import Pot, Location, PotShape

from fitosim.domain.room import Room, LightExposure

giardino = Garden(name="balcone-milano-calibrazione")

salotto = Room(room\_id="salotto", name="Salotto",

               wn31\_channel\_id="1")

giardino.add\_room(salotto)

## Fotografia di stato iniziale di ogni vaso

Il giorno prima di iniziare il logging, fotografa ogni vaso da quattro angolazioni (fronte, dietro, vista dall'alto, vista del substrato dopo aver tolto leggermente la pianta dal fianco). Le foto servono come riferimento per il futuro: se a sei mesi il rosmarino-1 ha avuto una crescita anomala, vuoi poter confrontare visivamente lo stato attuale con quello iniziale per capire se è successo qualcosa. Salva le foto in una cartella per vaso, datate.

Fotografa anche il sottovaso vuoto e pesato, e annota il peso a vuoto del solo contenitore vaso più sottovaso, perché ti servirà per dedurre il peso netto del sistema substrato-pianta-acqua dalle pesate future. Annota anche il volume nominale del vaso (1.5 litri, 3 litri, 5 litri), il diametro, l'altezza, e la forma (cilindrica, tronco-conica, rettangolare). Tutti questi parametri vanno in Pot quando lo crei.

## Posizionamento del sensore

Il sensore WH51 e WH52 va inserito verticalmente nel substrato a circa due terzi della profondità del vaso, a metà distanza tra il bordo del vaso e la pianta (non vicino al tronco, non vicino al bordo). La parte sensibile dell'elettrodo è in punta, e la sua lettura rappresenta il theta del substrato in un raggio di circa cinque-sette centimetri attorno alla punta. Nei vasi piccoli (un litro, come le orchidee) questo raggio copre quasi tutto il volume; nei vasi grandi (cinque litri, come gli oleandri) copre solo una frazione del volume e la lettura è meno rappresentativa. Per i vasi grandi, accetta questo limite ma scegli con cura la posizione del sensore in modo che sia rappresentativa della zona radicale principale.

Per le orchidee in substrato di corteccia, il posizionamento richiede un'attenzione extra. La corteccia è discontinua e la sonda potrebbe trovarsi in un punto di vuoto d'aria che falsa la lettura. Spingi delicatamente la sonda finché non incontri resistenza meccanica della corteccia, poi controlla a mano che la punta sia in contatto fisico con almeno un pezzo di corteccia significativo. Se la sonda è troppo lasca, premi il substrato attorno con le dita per assestarlo. Una volta posizionata, la sonda non va più rimossa o spostata fino al rinvaso, perché ogni movimento cambierebbe il volume di substrato sensibile e creerebbe una discontinuità nella serie temporale.

Annota il channel\_id del trasmettitore Ecowitt che hai assegnato a quel vaso (uno specifico tra i diversi canali del tuo gateway), perché ti servirà per la mappatura channel\_id → label nel database. Aggiorna la mappa channel\_id\_map del Garden:

giardino.channel\_id\_map = {

    "soil\_ch1": "phalaenopsis-1-finestra",

    "soil\_ch2": "phalaenopsis-2-media",

    \# ... e così via per tutti gli altri vasi

}

# 3 — Calibrazione gravimetrica dei sensori (livello 1)

Questo è il primo livello operativo della calibrazione, ed è quello che fissa l'affidabilità di tutto quello che viene dopo. Lo scopo è costruire la funzione di trasferimento specifica della tua sonda nel tuo specifico substrato, sostituendo o correggendo la calibrazione generica fornita dal produttore. La procedura si chiama in letteratura "calibrazione gravimetrica" perché usa la pesata del vaso (gravimetria) come riferimento di verità contro cui confrontare la lettura della sonda.

## Il principio fisico

Il theta volumetrico è definito come il rapporto tra il volume di acqua e il volume totale del substrato, ed è una grandezza adimensionale espressa solitamente come frazione (theta = 0.30 significa che il trenta per cento del volume del substrato è occupato da acqua liquida) oppure come percentuale (30 per cento volumetrico, abbreviato 30 percento volumetrico o 30 percento). Il sensore non misura direttamente il theta volumetrico: misura la capacità dielettrica del substrato (per il WH51 e WH52) o la sua resistività, e poi applica una funzione di trasferimento per convertire il segnale elettrico in theta. La funzione di trasferimento è specifica del materiale, e quella che il produttore mette nel firmware è una media generica.

La pesata del vaso, invece, ti dà direttamente la massa d'acqua presente nel sistema pianta-substrato in un dato momento, perché tutti gli altri componenti (vaso vuoto, substrato secco, biomassa della pianta) hanno massa che cambia molto lentamente rispetto alla scala di tempo dell'acqua. Se conosci la massa d'acqua e il volume del substrato, puoi calcolare il theta volumetrico vero con un'aritmetica semplice. Confrontando il theta vero con la lettura della sonda nello stesso istante, ottieni un punto della curva di calibrazione.

Ripetendo questa coppia di misure su molti cicli di asciugatura e re-irrigazione, lungo l'arco di alcune settimane, accumuli decine di punti di calibrazione che ti permettono di stimare la funzione di trasferimento corretta per la tua sonda nel tuo substrato. Questa è la procedura standard usata dai ricercatori agronomici, e funziona altrettanto bene in casa con bilance da cucina.

## La procedura passo-passo

Per ognuno dei sedici vasi strumentati, durante i primi due o tre mesi di logging esegui la procedura seguente ogni volta che irrigi il vaso. La procedura aggiunge dieci minuti circa al normale rituale di irrigazione, ma è quei dieci minuti per dieci volte (su un trimestre con un'irrigazione settimanale tipica per vaso) che danno tutta la base di calibrazione che ti servirà.

Passo uno: poco prima dell'irrigazione pianificata, sposta delicatamente il vaso sulla bilancia senza muovere la sonda. Aspetta che la bilancia si stabilizzi (cinque secondi, il display smette di oscillare). Annota la massa lorda M\_pre in grammi. Annota anche l'orario esatto e la lettura della sonda S\_pre nel database del logging (o leggila manualmente se il logging è ancora in setup). Passo due: rimetti il vaso al suo posto e procedi con l'irrigazione normale, finché vedi acqua uscire dal foro di drenaggio. Se il vaso ha sottovaso, l'acqua finisce nel sottovaso. Passo tre: aspetta che il drenaggio si completi, tipicamente venti o trenta minuti per vasi piccoli e quaranta minuti per vasi grandi. Sai che il drenaggio è completo quando dal foro non escono più gocce per più di un minuto. Passo quattro: vuota il sottovaso (l'acqua che ci si è raccolta non fa più parte del sistema vaso-pianta perché non sarà più riassorbita capillarmente in quantità significativa, almeno nelle prime ore). Passo cinque: pesa di nuovo il vaso. Annota la massa lorda M\_post in grammi. Annota anche l'orario esatto e la lettura della sonda S\_post.

Hai ottenuto due punti di calibrazione: lo stato secco (M\_pre, S\_pre) e lo stato saturo (M\_post, S\_post). La differenza M\_post meno M\_pre è la quantità di acqua netta che il sistema ha trattenuto, espressa in grammi (e quindi in millilitri, perché la densità dell'acqua è circa uno alla temperatura ambiente). Se ripeti la procedura per ogni irrigazione di ogni vaso strumentato, dopo tre mesi avrai accumulato circa duecento coppie di misure totali (sedici vasi per circa dieci-quindici irrigazioni ognuno).

## Convertire le pesate in theta vero

La conversione da massa d'acqua a theta volumetrico richiede un passaggio aritmetico che conviene fare bene fin dall'inizio. Hai bisogno di tre quantità per ogni vaso: la massa a vuoto del contenitore (vaso più sottovaso vuoto, già pesato e annotato in fase di setup iniziale), la massa del substrato secco (la stimi una volta sola dal volume del vaso e dalla densità apparente del substrato secco, tipicamente 1.0 chilogrammi per litro per terriccio universale, 0.4-0.5 per la corteccia delle orchidee, 1.3-1.5 per substrati pesanti tipo argilla espansa), e il volume del vaso in litri.

La massa d'acqua presente nel vaso al momento della pesata è la massa totale meno la massa del vaso vuoto meno la massa del substrato secco meno la massa della biomassa della pianta. La biomassa della pianta è la quantità più scomoda da stimare, ma per fortuna cambia molto lentamente: per la calibrazione iniziale ti basta una stima grossolana fatta con bilancia (estrai la pianta dal vaso, scuoti via il substrato, pesa la pianta nuda) la prima volta, e poi assumi che resti costante per i primi tre mesi. Per orchidee e piccole erbacee la biomassa è di pochi grammi e il suo errore è trascurabile rispetto alle masse d'acqua in gioco; per oleandri e ficus elastica può essere rilevante e va aggiornata ogni due-tre mesi.

Una volta noto M\_acqua in grammi, il theta volumetrico vero è M\_acqua diviso per il volume del vaso in millilitri. Esempio numerico: vaso di tre litri (tremila millilitri), pesata pre-irrigazione 2800 grammi, vaso vuoto 350 grammi, substrato secco 1500 grammi, biomassa 50 grammi. La massa d'acqua è 2800 meno 350 meno 1500 meno 50 uguale 900 grammi. Il theta vero è 900 diviso 3000 uguale 0.30, cioè trenta per cento volumetrico. Se nello stesso istante la sonda ha letto 0.27, hai un punto di calibrazione che dice "quando la sonda legge 0.27 il vero theta è 0.30, offset positivo del tre per cento volumetrico".

## Stimare la funzione di trasferimento

Dopo tre mesi di pesate, per ogni vaso hai una nuvola di punti (S\_sonda, theta\_vero). Per i vasi che condividono lo stesso substrato (le sei phalaenopsis nella corteccia, gli oleandri nello stesso terriccio, eccetera), puoi mettere insieme le nuvole di punti dei vasi simili e ottenere una nuvola più ricca, ma fai attenzione: solo se i vasi strumentati con la stessa sonda hanno tutti lo stesso offset di sonda. Se due sensori hanno offset diversi (cosa possibile, anche tra esemplari della stessa marca), mettere insieme le loro letture introduce rumore. Per sicurezza, ti consiglio di fittare la funzione di trasferimento separatamente per ogni vaso il primo giro, e solo dopo aver verificato che gli offset sono simili tra vasi affratellati considerare di fonderli.

La forma più semplice di funzione di trasferimento è la regressione lineare theta\_vero uguale a per S\_sonda più b. Si stima coi minimi quadrati (in Python con numpy.polyfit di grado 1, oppure scipy.stats.linregress). Il coefficiente angolare a tipicamente è vicino a 1 (la sonda risponde con la pendenza giusta) e l'intercetta b è l'offset costante che ti interessa. Se il coefficiente angolare risulta significativamente diverso da 1, la sonda ha anche un errore di scala oltre che di offset, e questo è informazione utile per la diagnostica. Se la nuvola dei punti è molto rumorosa (varianza alta attorno alla retta) e l'R-quadro è basso (tipicamente sotto 0.7), c'è un problema: o la sonda ha letture molto rumorose nel tuo substrato, o le pesate sono fatte male, o il substrato non è abbastanza omogeneo. Investiga prima di fidarti del fit.

# 4 — Calibrazione dei substrati (livello 2)

Una volta che ti fidi delle letture della sonda calibrata, il livello successivo è stimare i parametri idrici del tuo specifico substrato. Fitosim ha già un modulo dedicato a questo lavoro nel file science/calibration.py, e l'API principale è la funzione calibrate\_substrate che riceve una serie temporale di theta osservato e restituisce un CalibrationResult con i parametri stimati.

## I parametri da stimare

I due parametri fondamentali sono theta\_fc (theta a capacità di campo) e theta\_pwp (theta al punto di appassimento permanente). Concettualmente, theta\_fc è il valore massimo che il theta raggiunge subito dopo un'irrigazione completa con drenaggio libero, e theta\_pwp è il valore minimo prima che la pianta inizi a soffrire stress idrico irreversibile. Operativamente, questi due valori si stimano analizzando i picchi e le valli della serie temporale di theta. Il modulo science/calibration.py di fitosim ha le funzioni find\_peaks (trova i picchi locali corrispondenti alle irrigazioni) e find\_valleys (trova le valli locali corrispondenti agli stati di massima asciugatura prima di un'irrigazione successiva), e poi usa una statistica robusta (percentile invece di media o massimo) per ridurre la sensibilità ai dati anomali.

Per i substrati che lavorano in regime dual-Kc (terriccio universale dei rosmarini e degli oleandri) ci sono altri due parametri: REW (readily evaporable water, l'acqua di evaporazione rapida dello strato superficiale, tipicamente 8-10 millimetri per terriccio fine) e TEW (totally evaporable water, l'acqua totale di evaporazione dello stesso strato, tipicamente 15-20 millimetri). Questi due parametri si stimano con metodi simili ma più complessi, e per la prima fase di calibrazione ti consiglio di lasciarli ai valori di letteratura e occupartene solo dopo aver chiuso bene theta\_fc e theta\_pwp.

## Esecuzione tecnica

Dopo i primi tre mesi di logging, hai accumulato per ogni vaso una serie temporale di theta osservato a frequenza alta (una lettura ogni quindici minuti o ogni ora, a seconda di come hai configurato il gateway). Questa serie passata a calibrate\_substrate ti restituisce le stime dei parametri:

from fitosim.science.calibration import calibrate\_substrate

\# theta\_observations è una list\[float\] o np.array delle letture

\# calibrate del sensore (dopo il livello 1).

result = calibrate\_substrate(

    theta\_observations=theta\_observations,

    sampling\_interval\_hours=1.0,

)

print(f"theta\_fc stimato: {result.theta\_fc\_estimated}")

print(f"theta\_pwp stimato: {result.theta\_pwp\_estimated}")

print(f"livello di confidenza: {result.confidence\_level}")

print(f"note: {result.notes}")

Il livello di confidenza ritornato (typicamente "low", "medium" o "high") riflette il numero di cicli osservati: pochi cicli (meno di cinque) producono confidenza bassa, molti cicli (più di venti) producono confidenza alta. Per la fascia 3 con un anno di osservazioni dovresti raggiungere confidenza alta su quasi tutti i vasi, con l'eccezione possibile delle aloe vera e delle sansevieria che irrighi raramente e che quindi accumulano pochi cicli osservati.

Una volta stimati theta\_fc e theta\_pwp per ogni substrato del tuo setup, registra i nuovi parametri nel catalogo Substrate di fitosim sostituendo quelli generici di partenza. I substrati distinti del tuo setup sono tipicamente quattro: terriccio universale per le piante mediterranee outdoor, corteccia di pino per le orchidee, substrato sabbioso-drenante per aloe e sansevieria (le succulente non amano il terriccio normale), terriccio per piante verdi indoor per pothos e ficus. Quattro substrati, quattro coppie (theta\_fc, theta\_pwp) calibrate.

# 5 — Calibrazione delle specie (livello 3)

Questo è il livello agronomicamente più interessante e quello che giustifica davvero un anno di osservazioni. L'idea è confrontare il consumo idrico osservato (quanto theta scende giorno per giorno) con il consumo idrico previsto dal modello (quanto il modello stima che dovrebbe scendere), e dalle differenze sistematiche dedurre come correggere i parametri della specie.

## Estrarre il consumo osservato dalle serie di theta

Per ogni giorno e per ogni vaso, il consumo idrico osservato è approssimativamente uguale al theta calibrato all'inizio del giorno meno il theta calibrato alla fine del giorno, moltiplicato per il volume del vaso, espresso in millimetri equivalenti (per ottenere mm dividi i millilitri per la superficie del vaso in centimetri quadrati e poi moltiplichi per dieci). Questa è la stima di ET reale del giorno per quel vaso, da cui si esclude qualsiasi giorno con eventi di irrigazione, pioggia, o fertirrigazione (che sposterebbero artificialmente theta verso l'alto e falserebbero la stima di ET).

Filtrare i giorni con eventi è quindi essenziale, ed è qui che il diario degli eventi paga i suoi dividendi. Tutti i giorni con un evento documentato vanno esclusi dal calcolo del consumo osservato. Restano i giorni "puliti" di sola asciugatura, e su questi puoi stimare il consumo medio giornaliero per vaso e per fase fenologica.

## Confronto con il modello e stima del Kc

Il modello fitosim, per ognuno di quei giorni puliti, ha calcolato un ET previsto usando il selettore best-available (Penman-Monteith fisico se possibile, altrimenti standard, altrimenti Hargreaves) e il Kc della specie nella fase fenologica corrente. Confrontando ET\_osservato con ET\_previsto giorno per giorno, ottieni una serie di rapporti ET\_osservato diviso ET\_previsto. Se questi rapporti sono sistematicamente diversi da uno per una specie in una specifica fase, hai trovato un errore di Kc da correggere.

Esempio: se per il rosmarino in fase di piena vegetazione il rapporto medio ET\_osservato diviso ET\_previsto è 0.85, significa che il modello sovrastima il consumo del quindici per cento, e il Kc da letteratura (tipicamente 0.7 per rosmarino in piena vegetazione) andrebbe corretto a 0.7 moltiplicato per 0.85 uguale 0.60 circa. Aggiorna la Species nel catalogo, ricalcola le previsioni con il nuovo Kc, verifica che il rapporto medio scenda a circa uno. Ripeti per ogni fase fenologica e per ogni specie.

**Aggiornamento (fascia 3, fase A).** Questo confronto è esattamente ciò che fanno tre moduli, ciascuno per una situazione diversa. Se hai il sensore, `science/calibration.py` (parte "pendenza") inverte il bilancio dalla velocità di asciugamento; nota che legge il coefficiente di stress Ks dalla theta osservata invece di stimarlo, così una finestra che finisce in stress non ti restituisce un Kc falsato al ribasso. Se hai una bilancia, `science/lysimeter.py` misura l'ET direttamente per pesata (nessuna inferenza: è il ground truth) — ma richiede il vaso nella zona di comfort, perché quello che vuoi misurare è Kc, non Ks·Kc. Se non hai né sensore né bilancia, `science/behavioral_calibration.py` deduce la correzione dallo scostamento tra quando il modello suggerisce di irrigare e quando lo fai davvero. Tutti restituiscono una stima con livello di confidenza e la mediana su più finestre, così un giorno anomalo non sposta il risultato — la stessa robustezza che il capitolo raccomanda di ottenere a mano.

## Calibrazione delle date di transizione tra fasi

Le date di transizione tra le fasi fenologiche (da iniziale a sviluppo, da sviluppo a piena vegetazione, eccetera) sono in fitosim parametri costanti per specie. Nella realtà variano leggermente di anno in anno con il clima, ma per una calibrazione di prima fase puoi accettare la semplificazione e fissare le date sui valori medi osservati nel tuo balcone. Il segnale per identificare una transizione è il cambiamento sistematico del rapporto ET\_osservato diviso ET\_previsto: se per una specie il rapporto è 0.95 in maggio-giugno e diventa 1.20 in luglio-agosto, hai identificato una transizione di fase che non è correttamente posizionata nel modello (oppure un Kc sbagliato per la fase di luglio-agosto, e devi disambiguare guardando la dinamica nel dettaglio).

**Aggiornamento (fascia 3, fase A).** La semplificazione "date costanti" non è più l'unica strada: fitosim ora modella lo sviluppo delle **annuali** con i gradi-giorno (`science/phenology.py`), cioè la temperatura accumulata sopra una soglia base, che è ciò che governa davvero lo sviluppo. È il modo di rendere una transizione **trasferibile tra climi** invece che fissata al calendario del tuo balcone: le date di fioritura che annoti nel diario, incrociate con lo storico meteo, tarano le soglie GDD. Le **perenni** restano invece ancorate al calendario stagionale (non ai GDD, perché il loro sviluppo dipende anche dal fabbisogno di freddo — chill units — che i gradi-giorno non catturano). Fitosim usa i 6 stadi botanici osservabili (gli stessi del diario e di The Pot) e li traduce internamente nei 3 stadi FAO-56 che pilotano il Kc.

## La resistenza stomatica per il Penman-Monteith fisico

Per le specie che hanno stomatal\_resistance\_s\_m popolato e usano quindi il Penman-Monteith fisico, la resistenza stomatica è un parametro calibrabile e di grande impatto. Lo stimi con la stessa logica del Kc: se il rapporto ET\_osservato diviso ET\_previsto è sistematicamente diverso da uno per una specie che usa il fisico, e hai già escluso che sia il sensore o il substrato, allora la resistenza stomatica è probabilmente sbagliata. La resistenza stomatica è inversamente proporzionale all'ET nel modello fisico, quindi se il modello sovrastima del venti per cento, la resistenza stomatica andrebbe aumentata del venti per cento.

Per le orchidee phalaenopsis questo è il parametro più importante in assoluto, perché il loro metabolismo CAM facoltativo significa che la resistenza stomatica effettiva varia tra fasi C3 (200-300 secondi per metro) e fasi CAM (600-800 secondi per metro). Le sei phalaenopsis con sei repliche ti danno la potenza statistica per stimare la resistenza stomatica media in regime di benessere e in regime di stress, e questo è uno dei contributi scientifici più interessanti che la tua calibrazione potrà produrre.

# 6 — Calibrazione del modello chimico (livello 4)

L'ultimo livello è la calibrazione del modello chimico di fitosim, possibile solo sui vasi strumentati con WH52 perché solo lì hai l'EC del substrato misurata. Nel tuo setup i WH52 sono distribuiti su due orchidee (per la calibrazione in substrato di corteccia atipico), un oleandro (per la calibrazione in substrato standard mediterraneo), un ficus elastica (per la calibrazione in substrato standard indoor). Sono quattro vasi WH52 in totale, che coprono i tre regimi più importanti del setup.

## Calibrazione del coefficiente di accumulo

Il modello chimico di fitosim descrive l'evoluzione della massa di sali nel substrato in risposta a fertirrigazioni e irrigazioni di lavaggio. Quando fertirrighi, aggiungi sali al sistema; quando irrighi con acqua pulita o quando piove, una frazione dei sali viene dilavata e drenata via. Il coefficiente di lavaggio è il parametro che regola questa frazione, e dipende dal substrato (substrati più drenanti come la corteccia delle orchidee dilavano più facilmente, substrati più trattenenti come il terriccio universale dilavano meno).

Lo stimi confrontando l'EC predetta dal modello dopo una serie di cicli di fertirrigazione e dilavamento con l'EC misurata dal WH52. Se il modello sottostima sistematicamente l'EC reale, il coefficiente di lavaggio è troppo alto e va abbassato. Se lo sovrastima, il contrario. La calibrazione richiede di osservare almeno cinque-dieci cicli completi di fertirrigazione, quindi tipicamente i mesi centrali della stagione di crescita sono quelli più informativi (maggio-settembre), periodo in cui fertirrighi più spesso.

## Calibrazione del coefficiente nutrizionale Kn

Il Kn è il coefficiente che modula l'evapotraspirazione effettiva in funzione dello stress chimico del substrato. Vaso con EC nel range ottimale per la specie ha Kn uguale a 1, vaso con EC fuori range ha Kn minore di 1 perché la pianta consuma meno. La forma funzionale del Kn in fitosim è triangolare lineare a tratti, definita da tre parametri per specie: il valore minimo del Kn in stress massimo (tipicamente 0.30, ma calibrabile), e gli estremi del range di EC ottimale (definiti nella Species come ec\_optimal\_min\_mscm e ec\_optimal\_max\_mscm).

Lo stimi osservando i giorni in cui l'EC misurata è significativamente fuori range (perché stai facendo un ciclo di salinizzazione progressiva tra una fertirrigazione e l'altra, oppure perché hai dimenticato di lavare il substrato per qualche settimana) e confrontando il consumo idrico osservato in quei giorni con quello previsto dal modello con Kn uguale a 1. Se il consumo reale è inferiore al previsto, la pianta sta effettivamente riducendo il suo ET in risposta allo stress, e il rapporto consumo\_osservato diviso consumo\_previsto ti dà il valore stimato di Kn per quel livello di EC fuori range. Ripetuto su molti giorni e molti vasi, ottieni la curva Kn(EC) calibrata per la tua specie.

## Calibrazione del modello del pH

Il modello del pH del substrato di fitosim è separato dal modello dell'EC, e i sensori WH52 non misurano il pH (è una grandezza chimicamente diversa che richiede una sonda dedicata). La calibrazione del pH si fa quindi con misure manuali periodiche, una ogni due settimane sui vasi WH52, usando il pH-metro a stick. La frequenza è bassa rispetto alle letture continue dei WH52, ma è sufficiente perché il pH evolve molto lentamente nel substrato (settimane o mesi tra una variazione significativa e l'altra) e non ha bisogno di alta risoluzione temporale.

Per ogni misura di pH, annota nel database la data, il vaso, il valore di pH letto, e il pH calibrato dal modello fitosim per lo stesso giorno. Confrontando le serie, identifichi gli errori sistematici e correggi i parametri del modello pH (densità CEC del substrato, alcalinità dell'acqua di irrigazione, eccetera). L'ortensia rosa-blu, se l'avessi inclusa nel setup, sarebbe stato un caso di validazione qualitativa del modello pH che ti consigliavo nei pre-test, ma con il setup attuale non c'è e accetti questa limitazione.

# 7 — Validazione finale e chiusura della fascia 3

Dopo dodici mesi di calibrazione articolata sui quattro livelli, hai un modello fitosim significativamente diverso da quello generico di partenza, con parametri specifici per il tuo balcone milanese. Prima di dichiarare chiusa la fascia 3 e considerare il modello "in produzione", devi fare una validazione finale rigorosa.

## Validazione su dati riservati

Recupera il gruppo di validation che avevi messo da parte al capitolo 1 (gli ultimi quattro mesi delle serie temporali, da settembre a dicembre se hai iniziato a maggio). Su questi dati il modello calibrato non è mai stato esposto durante la stima dei parametri. Calcola le metriche di errore: RMSE del theta previsto vs osservato per ogni vaso, RMSE dell'EC previsto vs misurato per i vasi WH52, errore tipico delle previsioni a sette giorni del modello.

Confronta queste metriche con quelle del modello generico di partenza (la stessa simulazione fatta con i parametri di letteratura non calibrati). Il modello calibrato deve essere significativamente migliore del generico su tutte le specie e su tutti i regimi, altrimenti la calibrazione non è valsa la pena. Tipicamente ti aspetti un miglioramento del trenta-cinquanta per cento sull'RMSE del theta, e del venti-trenta per cento sull'RMSE dell'EC. Se il miglioramento è inferiore al dieci per cento, qualcosa è andato storto nella calibrazione e vale la pena tornare indietro a investigare.

## Documentazione dei parametri calibrati

Una volta validato il modello, documenta in modo strutturato i parametri calibrati per ogni specie e ogni substrato, in modo da poterli rivedere e aggiornare nelle fasce successive di calibrazione. Una buona pratica è di mantenere un file di configurazione versionato (in YAML o JSON) che lista per ogni Species i parametri attuali, la data della calibrazione, il numero di vasi e di osservazioni su cui è stata fatta, e l'incertezza stimata di ogni parametro. Questo file di configurazione è il "knowledge artifact" più prezioso che la fascia 3 produce, ed è quello che andrà condiviso quando in futuro estenderai il modello ad altre specie o riproverai la calibrazione su altri balconi.

## Cosa viene dopo

Dopo la chiusura della fascia 3 hai un modello fitosim calibrato per il tuo balcone, con metriche di errore quantificate e un dashboard operativo che produce previsioni di cui ti puoi fidare. Le fasce successive di sviluppo del progetto possono andare in più direzioni: estensione del catalogo a specie nuove (le fascia 1 di calibrazione sulle perenni stagionali come melograno e limone, che richiedono il loro anno dedicato), raffinamento del modello scientifico (CAM facoltativo dinamico, temperatura del substrato come modulatore del Kn, modello del pH dinamico), integrazione di dati esterni (forecast meteo a sette giorni per allerte preventive, database di letteratura per validazione incrociata).

Quale di queste direzioni avrà la priorità dipende da cosa avrai imparato durante la fascia 3, e in particolare da dove gli errori residui del modello calibrato si concentreranno. Se i residui maggiori saranno sulle orchidee, vale la pena investire sul CAM facoltativo dinamico; se saranno sull'EC durante l'estate, vale la pena investire sulla temperatura del substrato come modulatore. La calibrazione non è solo un'attività di stima dei parametri ma anche una scoperta dei limiti del modello attuale, e i limiti che emergeranno saranno la guida per la fascia 4.

