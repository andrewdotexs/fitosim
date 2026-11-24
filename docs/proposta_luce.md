# Proposta — la luce nel modello

*24 novembre 2026. Scritta su fitosim 0.40.0 come proposta.*

**Decisa lo stesso giorno** (Andrew): si fanno **L1 e L2**, L2 con la forma
**proporzionale**; **L0** passa a The Pot come proposta. L1 e L2 sono in
fitosim 0.41.0 (`science/light.py`, `nutrients.light_factor`,
`tests/test_light.py`). Il testo sotto è quello della proposta, lasciato
com'era.

## 1. La domanda

La luce conta nella traspirazione e nel consumo di nutrienti. Oggi fitosim
la tratta come **energia**: entra nell'ET₀ (radiazione netta di
Penman-Monteith), nel fattore di esposizione del vaso (1,00 / 0,70 / 0,45) e
nella radiazione delle stanze (0,40 / 0,15 / 0,05 di quella esterna). I
nutrienti la vedono solo di riflesso: l'assorbimento è `traspirazione ×
concentrazione del piano × frazione di alimentazione × cancello del freddo`.

Manca la luce come **motore di crescita**: nessuna grandezza dice quanta
luce utile arriva alla pianta, né se è quella che la specie vuole, e la
domanda di nutrienti non la conosce.

## 2. Che cosa dicono le fonti

Con la dichiarazione di che cosa ho letto e che cosa no.

| Fonte | Che cosa dice | Letta |
|---|---|---|
| Torres & Lopez, *Measuring Daily Light Integral in a Greenhouse*, Purdue Extension HO-238-W | La luce utile si misura come **integrale giornaliero** (DLI, mol di fotoni PAR per m² al giorno). All'aperto va da 5 a 60; in serra raramente oltre 25; sotto le ostruzioni scende a 1–5. Classi di coltura: **luce bassa 3–6, media 6–12, alta 12–18, molto alta oltre 18**. La tabella 2 (da Faust, *Ball RedBook*) dà per coltura il DLI di «qualità minima accettabile», «buona» e «alta»: felci e Spathiphyllum 2 / 4 / 6; Dracaena, Dieffenbachia, edera 4 / 6 / 8; Ficus benjamina, lavanda, timo, sedum 8–10 / 12–16 / 18; pomodoro e peperone 10–12 / 14–20 / 22 | per intero |
| Logan & Faust, mappe DLI degli Stati Uniti (poster ASHS 2017; Faust & Logan 2018, *HortScience* 53:1250–1257) | Conversione dalla radiazione globale: il 45 % è PAR, 4,48 µmol per joule di PAR, cioè 0,007265 mol/Wh = **2,02 mol per MJ** | solo l'estratto del poster; l'articolo no (accesso negato) |
| Langenfeld & Bugbee 2026, *Front. Plant Sci.* 17:1885837 (riprende Bugbee 2004, *Acta Hort.* 648:99–112) | La concentrazione della soluzione di rabbocco è `concentrazione nei tessuti × efficienza d'uso dell'acqua`: **i nutrienti escono con la crescita, l'acqua con la traspirazione**. WUE tipica 3 g di sostanza secca per litro traspirato (450 ppm di CO₂, 50 % di umidità) | in parte (PMC); Bugbee 2004 no |
| Gastal & Lemaire 2002, *J. Exp. Bot.* 53:789–799 | Con azoto disponibile, l'accumulo di N è strettamente legato alla velocità di crescita | solo l'abstract |
| Poorter et al. 2019, *New Phytol.* 223:1073–1105 | Meta-analisi di 500 esperimenti e 760 specie: molti tratti crescono col DLI in modo **saturante** | solo l'abstract: la forma della curva di crescita non l'ho potuta leggere |

Il punto che tiene insieme tutto è quello di Bugbee: il piano di
concimazione dà una concentrazione che è giusta **per un certo rapporto fra
acqua traspirata e crescita**. Quando quel rapporto cambia — una pianta con
poca luce in una stanza riscaldata traspira per l'aria secca ma cresce poco
— `traspirazione × concentrazione` sopravvaluta quello che la pianta mangia.

## 3. Le misure

Radiazione reale di Milano centro, 2025, 365 giorni (archivio Open-Meteo,
`shortwave_radiation_sum`), convertita a 2,02 mol/MJ.

### 3.1 Quanta luce arriva al vaso (mol/m²/giorno, medie mensili)

| Mese | Cielo aperto | In casa, sole diretto (0,40) | Luminoso indiretto (0,15) | Buio (0,05) |
|---|---:|---:|---:|---:|
| Gennaio | 8,5 | 3,4 | 1,3 | 0,4 |
| Marzo | 25,4 | 10,2 | 3,8 | 1,3 |
| Giugno | 47,7 | 19,1 | 7,2 | 2,4 |
| Settembre | 29,6 | 11,8 | 4,4 | 1,5 |
| Dicembre | 7,6 | 3,1 | 1,1 | 0,4 |

Letta con le classi di Purdue: una finestra al sole d'estate vale una
coltura da luce alta; un angolo luminoso senza sole diretto sta nella luce
bassa d'estate e **sotto il minimo di qualunque classe d'inverno**; un
angolo buio è sotto il minimo tutto l'anno.

### 3.2 Un difetto che c'è già: in casa la radiazione è fissa tutto l'anno

fitosim ha due modi per la radiazione indoor: fisso per livello (1,5 / 4 /
8 MJ/m²/giorno) e frazione di quella esterna. The Pot, nel passo indoor
(`_et0_dall_aria`), chiama `estimate_indoor_radiation` **senza la radiazione
esterna**: usa il fisso. In DLI sono 16,1 / 8,1 / 3,0 tutto l'anno, contro
i 3,1 / 1,1 / 0,4 veri di dicembre.

ET₀ della stanza (Penman-Monteith, stanza a 20 °C e 45 % d'inverno, 26 °C e
60 % d'estate: un'ipotesi di scenario):

| Luce | Radiazione | Anno (mm) | Dic–gen (mm/g) | Giu–lug (mm/g) |
|---|---|---:|---:|---:|
| Sole diretto | fissa (oggi) | 1 014 | 2,72 | 2,82 |
| Sole diretto | col sole vero | 769 | 1,01 | 3,22 |
| Luminoso indiretto | fissa (oggi) | 606 | 1,65 | 1,66 |
| Luminoso indiretto | col sole vero | 412 | 0,74 | 1,52 |
| Buio | fissa (oggi) | 351 | 0,99 | 0,93 |
| Buio | col sole vero | 269 | 0,64 | 0,84 |

D'inverno il modello fa bere a un vaso in casa da 1,5 a 2,7 volte quello
che berrebbe con la luce vera. Le sonde lo correggono dove ci sono; dove
non ci sono, l'avviso di sete arriva in anticipo.

### 3.3 Un anno in casa, con e senza la luce sull'assorbimento

Vaso da 4 litri, piano 100 / 40 / 80 mg/L da marzo a ottobre, concime ogni
14 giorni, acqua alla soglia di allerta. Azoto mangiato nell'anno, in
percentuale di quello che il modello calcola oggi:

| Luce al vaso | Oggi (mg di N) | Specie da luce bassa | Da luce media | Da luce alta |
|---|---:|---:|---:|---:|
| Sole diretto | 754 | 100 % | 99 % | 96 % |
| Luminoso indiretto | 602 | 94 % | 85 % | 43 % |
| Buio | 371 | 45 % | 29 % | 15 % |

(Forma «proporzionale» del §4, L2. Con la forma «a rampa» le riduzioni sono
più brusche: luminoso indiretto 90 / 70 / 8 %, buio 17 / 9 / 9 %.)

Due letture. **Oggi** il modello dice che un vaso al buio mangia la metà
(371 contro 754) di uno alla finestra al sole, mentre riceve un ottavo della
luce: la traspirazione in casa la guida l'aria, non il sole. **Con la
luce**, per una specie da luce media il rapporto diventa 109 contro 749,
cioè il 15 %: vicino al rapporto fra le luci, come vuole «i nutrienti
escono con la crescita». E il concime non mangiato resta nel vaso come
sale: è il caso reale della pianta d'appartamento concimata da calendario
che accumula sali.

All'aperto il termine pesa poco in stagione: un vaso in ombra riceve
ancora 9–21 mol/m²/giorno fra marzo e ottobre (col fattore 0,45 usato come
frazione di luce, in mancanza di meglio), e tocca solo le specie da luce
alta in primavera e autunno.

### 3.4 I test

La suite è di 1 618 test in 10,8 s. I passi L1 e L2 sono a consenso
esplicito (senza DLI o senza la soglia della specie il fattore vale 1):
per costruzione nessun test esistente cambia numero. Lo verifico
all'implementazione; i test nuovi sarebbero quelli del modulo della luce e
dei casi del §3.3.

## 4. La proposta, a passi

**L0 — La radiazione in casa segue il sole (The Pot).** Passare la
radiazione esterna del giorno a `estimate_indoor_radiation`: fitosim lo sa
già fare, non cambia una riga qui. Cambia il bilancio idrico dei vasi in
casa di The Pot (§3.2), quindi è una decisione sul modello, e il codice è
dell'altra sessione.

**L1 — La luce come grandezza (fitosim, nessun effetto sui bilanci).** Un
modulo `science/light.py`: la conversione MJ → mol, il DLI al vaso dalla
radiazione e dalla frazione, le quattro classi di Purdue, e un giudizio
(«sotto il minimo», «accettabile», «buona», «piena»). Il DLI compare nei
risultati del passo come dato. Serve a The Pot per dire «questa specie
vuole luce alta, il tuo vaso ne riceve 4» e alla console di calibrazione
per vedere i numeri prima di usarli.

**L2 — La luce sull'assorbimento (fitosim, cambia il modello).** Un
fattore accanto al cancello del freddo:

    assorbimento = traspirazione × concentrazione × alimentazione
                   × cancello del freddo × fattore di luce

    fattore di luce = min(1, DLI al vaso / DLI «buono» della specie),
                      con un pavimento a 0,1

Vale 1 quando manca il DLI o la soglia della specie. È riportato nel
risultato del passo, come il cancello del freddo.

- *Forma proporzionale* (consigliata): sotto la saturazione la crescita
  segue la luce. È la più semplice e dà il rapporto del §3.3.
- *Forma a rampa* fra «minimo accettabile» e «buono»: più severa, ma tratta
  il minimo di qualità commerciale come se fosse luce zero, e non lo è.

**L3 — Non ora.** La luce sulla fenologia e sulla chioma (tempo
fototermico al posto dei soli gradi-giorno) e un modello di crescita vero
(luce intercettata → biomassa → domanda di azoto). Sono la fisica giusta, ma
chiedono per specie parametri che il catalogo non ha e che una sonda di
umidità non sa calibrare, e toccano tutto il bilancio idrico.

## 5. I limiti, detti prima

- **La luce al vaso è l'anello debole.** Le frazioni 0,40 / 0,15 / 0,05
  sono medie di letteratura, e all'aperto una frazione di luce per
  esposizione non c'è: 0,70 e 0,45 sono fattori di traspirazione. Una
  misura col telefono al vaso e a cielo aperto dà la frazione vera (Purdue,
  tabella 1: per la luce solare 0,20 foot-candle per µmol/m²/s): è un campo
  in più per The Pot, non un numero da inventare qui.
- **Un po' di doppio conto.** La traspirazione cala già con la luce (in casa
  di metà fra finestra e buio, all'aperto col fattore di esposizione), e il
  fattore di luce le si moltiplica sopra. Con la forma proporzionale il
  risultato sta vicino al rapporto fra le luci (§3.3); con la rampa va
  oltre.
- **Il pavimento a 0,1 e la forma sono scelte di modello**, non numeri di
  una fonte: la curva di crescita di Poorter non l'ho potuta leggere. Vanno
  dichiarati nel codice come da tarare.
- **La soglia per specie** viene dal catalogo di The Pot: i quattro livelli
  di luce delle schede andrebbero legati alle quattro classi di Purdue. È
  una corrispondenza da decidere di là, non una tabella da scrivere qui.
- Non entrano: la qualità della luce, il fotoperiodo, la risposta degli
  stomi oltre quella che Penman-Monteith ha già.

## 6. Che cosa si decide

1. Quali passi fare in fitosim: L1 soltanto, L1 e L2, o nessuno.
2. Per L2, la forma: proporzionale o a rampa.
3. Se passare L0 all'altra sessione come proposta per The Pot.
