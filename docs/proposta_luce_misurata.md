# Proposta — la luce misurata al vaso

*24 novembre 2026. Scritta su fitosim 0.43.0 come proposta. Nasce dal
lisimetro (`fitosim-calibration`), che misura la luce con un sensore suo e
vuole che entri nel calcolo al posto della stima per categoria.*

**Decisa lo stesso giorno** (Andrew): si fanno **i tre pezzi in fitosim** del
§4.2. Sono in fitosim 0.44.0: `light.dli_from_illuminance` e
`light.shortwave_from_illuminance`; `indoor.resolve_indoor_radiation` con la
cascata a quattro gradini; `Pot.apply_balance_step_from_indoor` con
`global_radiation_at_pot_mj_m2_day` e `light_fraction_override`, e il
gradino usato in `Pot.last_indoor_radiation`. Restano da decidere il
contratto col backend del lisimetro, il parametro canonico da chiedere a
The Pot, e nel lisimetro la posizione e il guadagno del sensore. Il testo
sotto è quello della proposta, lasciato com'era.

## 1. Il verdetto

**Con le funzioni di oggi la misura può entrare, ma non dal passo in casa.**

Quello che hai visto in fitosim 0.43.0 è esatto, punto per punto.

- `Pot.apply_balance_step_from_indoor` prende la radiazione solo da
  `LightExposure`, con o senza la radiazione di fuori.
  `light_exposure_override` accetta soltanto l'enum: un ingresso per una
  radiazione misurata al vaso non c'è.
- `Pot.dli_at_pot` accetta `light_fraction_override`, ma il passo in casa
  calcola il DLI con `light_fraction(effective_exposure)` e non lo propaga.
- In `io/sensors/measurement.py` non c'è un parametro di illuminamento
  (c'è `solar_radiation_mj_m2`).
- Lo status report elenca la frazione di luce misurata fra le cose aperte.

La strada che oggi funziona è quella che usa The Pot: non chiamare il passo
in casa, ma i suoi mattoni.

    netta = indoor.net_indoor_radiation(globale_al_vaso_mj)      # × 0,77
    et0   = et0.compute_et(..., net_radiation_mj_m2_day=netta)
    et0  /= pot_physics.exposure_correction_factor(pot.sun_exposure)
    dli   = light.dli_from_shortwave(globale_al_vaso_mj)         # × 2,02
    pot.apply_step(et_0_mm=et0, current_date=..., dli_mol_m2_day=dli)

Mancano due cose: **la conversione dal lux**, che in fitosim non esiste, e
**un ingresso nel passo in casa**, per chi non vuole rifare a mano quattro
righe che devono restare uguali a quelle del motore.

## 2. Le fonti

| Fonte | Che cosa dice | Letta |
|---|---|---|
| Torres & Lopez, Purdue Extension HO-238-W, tabella 1 | Per la luce solare 0,20 µmol/m²/s per foot-candle, cioè **53,8 lux per µmol/m²/s**; per le lampade al sodio 0,13, cioè 82,8. «The conversion factor depends on the light source» | per intero |
| Guida Apogee/Cycloptics sui sensori di luce | Luce solare: 0,0185 µmol/m²/s per lux, 54 lux per µmol | solo dal riassunto della ricerca |
| AGi32, concetti di PPFD | LED bianco a 5000 K: 14,6 µmol/m²/s per kilolux, cioè 68 lux per µmol | solo dal riassunto |
| Littlefair 1985, «The luminous efficacy of daylight: a review», *Lighting Res. Technol.* 17(4):162–182; Littlefair 1988, stessa rivista | Radiazione globale: circa 105 lm/W a cielo sereno e in media (rassegna); 107 e 109 misurati in un anno a Garston. Sole diretto 70–105, cielo diffuso 110–130 | gli abstract |
| Penn State EGEE 102, tabella dei vetri; soglia del DOE | Doppio vetro chiaro: trasmittanza visibile 0,57 e guadagno solare 0,58, rapporto luce/sole circa 1. Doppio vetro selettivo: 0,51 e 0,31, rapporto 1,65. Il DOE chiama selettivo un vetro sopra 1,25 | solo dal riassunto della ricerca |
| Logan & Faust, mappe DLI | 45 % della globale è PAR, 4,48 µmol/J: già in `science/light.py` | estratto del poster |
| Vishay, «Designing the VEML7700 Into an Application», doc. 84323, rev. 06-Mar-2025 | Tabella di risoluzione e fondo scala: **guadagno 1 e 100 ms danno 0,0672 lx/conteggio e 4 404 lux al massimo** (le revisioni precedenti dicevano 0,0576 e 3 775); il massimo assoluto è 140 926 lux a guadagno 1/8 e 25 ms. «At lux levels above 100 lux GAIN level 1 and 2 should not be used as the sensor becomes non-linear»: si usano 1/4 e 1/8, e sopra 1 000 lux il polinomio di correzione (a = 6,0135e-13, b = −9,3924e-9, c = 8,1488e-5, d = 1,0023). LED, fluorescenti e luce del giorno leggono uguale entro ±10 %; le alogene di più. La nota descrive anche la scelta automatica del guadagno, partendo da 1/8 | alla fonte, le prime dieci pagine |

**La catena torna.** Coi numeri già in fitosim, 1 W/m² di globale sono
2,016 µmol/m²/s di PAR, e a 53,8 lux per µmol fanno 108,5 lux: l'efficacia
luminosa che ne esce è dentro i 105–110 lm/W delle rassegne. Una sola
costante nuova, coerente con le altre due:

    1 klux·h = 0,0669 mol/m² di PAR = 0,0332 MJ/m² di globale
    1 MJ/m²  = 30,1 klux·h

Il limite è lo **spettro**. Il lux pesa la luce come l'occhio; i fotoni e
l'energia no. Per la luce del giorno la conversione in fotoni è solida
(±10 % fra le fonti). Sotto una lampada cambia del 25–50 %. La conversione
in **energia** è la più fragile: un vetro selettivo lascia passare il
visibile e ferma il vicino infrarosso, quindi dietro quel vetro ogni lux
porta meno watt di quanto dica la costante. Con un doppio vetro chiaro il
rapporto fra luce e sole è circa 1 e la costante regge; con un vetro
selettivo è 1,65, e l'energia stimata dal lux sarebbe troppa di due terzi.
Va dichiarata come stima, e il tipo di vetro è un dato del posto.

## 3. Le misure

Milano 2025 (archivio Open-Meteo), luce media nelle ore di giorno al vaso,
e il DLI più alto che il sensore può leggere col fondo scala di oggi
(4 404 lux, guadagno 1 e 100 ms, dalla tabella della nota Vishay).

| Mese | Ore di luce | Cielo aperto (lux) | Finestra al sole | Luminoso indiretto | Buio | DLI massimo leggibile | DLI vero: finestra / indiretto / buio |
|---|---:|---:|---:|---:|---:|---:|---|
| Gennaio | 8,9 | 14 300 | 5 700 | 2 100 | 700 | 2,6 | 3,4 / 1,3 / 0,4 |
| Marzo | 11,6 | 32 700 | 13 100 | 4 900 | 1 600 | 3,4 | 10,2 / 3,8 / 1,3 |
| Giugno | 15,5 | 46 100 | 18 400 | 6 900 | 2 300 | 4,6 | 19,1 / 7,2 / 2,4 |
| Settembre | 12,3 | 36 000 | 14 400 | 5 400 | 1 800 | 3,6 | 11,8 / 4,4 / 1,5 |
| Dicembre | 8,5 | 13 400 | 5 300 | 2 000 | 700 | 2,5 | 3,1 / 1,1 / 0,4 |

- **Col firmware di oggi il sensore non misura, per due motivi.** Il primo
  è il fondo scala: già la media di un angolo luminoso senza sole diretto lo
  supera da marzo a settembre, e una finestra al sole lo supera tutto
  l'anno. Il DLI massimo leggibile, 2,5–4,6 mol/m²/giorno, arriva appena al
  «buono» di una pianta da luce bassa (4). Il secondo è peggiore, perché non
  si vede: a guadagno 1 il sensore è **non lineare sopra i 100 lux**, e la
  nota Vishay dice di non usarlo. Nel suo grafico di confronto con un
  luxmetro di riferimento la lettura si stacca verso il basso da qualche
  centinaio di lux, e a 4 000 lux veri ne segna meno della metà. Il dato
  quindi sbaglia per difetto molto prima di fermarsi.
- **Sotto la chioma si legge la pianta, non la luce.** Con la legge di Beer
  (`I/I₀ = e^(−k·LAI)`, k = 0,7) resta il 50 % a LAI 1, il 25 % a LAI 2, il
  12 % a LAI 3: un numero che cala mentre la pianta cresce, a luce uguale.

## 4. Le risposte alle sei domande

**1. Può entrare oggi?** Sì coi mattoni del §1, no dal passo in casa. Manca
la conversione dal lux.

**2. La modifica.** Tre pezzi, tutti a consenso esplicito.

- *La conversione*, in `science/light.py`: una costante
  `LUX_PER_UMOL_DAYLIGHT = 53.8` e due funzioni,
  `dli_from_illuminance(lux_hours)` in mol/m²/giorno e
  `shortwave_from_illuminance(lux_hours)` in MJ/m²/giorno, con il fattore
  per sorgente come argomento (il default è la luce del giorno).
- *L'ingresso*, nel passo in casa: un argomento facoltativo
  `global_radiation_at_pot_mj_m2_day`. Quando c'è, sostituisce la stima: la
  netta è `net_indoor_radiation` di quel numero e il DLI è
  `dli_from_shortwave` di quel numero. Tutti e due dalla stessa grandezza,
  come oggi li si ricava entrambi da `LightExposure`.
- *La convivenza*, una cascata a quattro gradini, dal più misurato al meno:
  1. la radiazione misurata al vaso quel giorno;
  2. una **frazione misurata** del posto per la radiazione di fuori
     (`light_fraction_override`, un numero fra 0 e 1), per i giorni in cui
     il sensore manca;
  3. la frazione di `LightExposure` per la radiazione di fuori;
  4. il numero fisso di `LightExposure`.
  Con la misura `light_exposure` non serve più, e il passo non lo pretende.
  Il risultato dice quale gradino ha usato.

**3. Il contratto col backend del lisimetro.** Scelgo la terza strada per
il contratto e la seconda per la firma.

- Il backend manda la grandezza che **misura**: l'integrale giornaliero di
  illuminamento, `daily_light_integral_lux_h`, che DL-002 già prevede. Con
  due campi di qualità, perché il contratto non dipenda dal firmware: le
  ore coperte da campioni validi, e la frazione di campioni a fondo scala.
- La conversione sta **in fitosim**: è scienza, ha una fonte, deve restare
  coerente con le altre due costanti della luce, e cambia con la sorgente.
- La firma del vaso prende la **radiazione globale al vaso in MJ/m²/giorno**:
  è la grandezza fisica, e vale anche per un piranometro o un sensore PAR.
- La **frazione misurata** la scarto come dato giornaliero: mescola due
  sorgenti e cambia col tempo di ogni giorno. La tengo come prodotto
  derivato (la mediana su molti giorni di «al vaso / fuori»), per il
  gradino 2.

**4. Dove deve stare il sensore.** All'altezza della cima della chioma, in
piano e rivolto in alto, non ombreggiato dalla pianta, alla stessa distanza
dalla finestra. **Sotto la chioma è inutilizzabile**, per l'ET e per il DLI
(§3). Può servire a un'altra cosa, se un giorno ce ne sono due: il rapporto
sotto/sopra dà la luce intercettata, cioè la copertura della chioma che
fitosim usa per il Kc.

**5. Il parametro canonico.** Sì, va chiesto a The Pot: un illuminamento in
lux nel vocabolario dei sensori (la spec ha `solar_radiation_mj_m2` e
lascia la luce a `custom:*`). In fitosim non lo aggiungo:
`io/sensors/measurement.py` è nello strato congelato che se ne va.

**6. All'aperto.** Sì, la stessa misura lo sblocca: un sensore al vaso dà la
luce al vaso, e il DLI si passa al passo senza bisogno di una frazione. E
dopo qualche settimana dà la frazione misurata del posto. Non propongo di
usarla per l'ET all'aperto: lì la luce entra con Kp, e sostituirlo è un
altro cambio al modello. Col fondo scala di oggi all'aperto il sensore è
sempre saturo.

## 5. I limiti

- **Il firmware.** Con guadagno 1 fisso la misura non vale come misura:
  sottostima sopra i 100 lux e si ferma a 4 404. Il rimedio è quello della
  nota Vishay: guadagno 1/8 o 1/4, scelta automatica partendo dal più
  basso, e il polinomio di correzione sopra i 1 000 lux. È un lavoro del
  lisimetro, non di fitosim. I dati raccolti finora col guadagno 1 non si
  recuperano con una formula: la nota dà la correzione solo per 1/4 e 1/8.
  Il contratto porta la frazione di campioni a fondo scala proprio per
  poter scartare il giorno.
- **Lo spettro.** La costante è della luce del giorno. Sotto lampade serve
  un altro fattore, e l'energia dietro un vetro selettivo è sovrastimata.
- **Il campionamento.** Una lettura istantanea ogni cinque minuti integra
  bene la luce diffusa, peggio una macchia di sole che passa.
- **L'onda lunga** resta a zero come in tutto il passo in casa.
- Delle rassegne sull'efficacia luminosa ho letto gli abstract; la tabella
  dei vetri e i fattori per le lampade vengono dal riassunto della ricerca.
  La risposta angolare del sensore non l'ho verificata: conta, perché una
  misura in piano vuole una risposta a coseno.

## 6. Che cosa si decide

1. Se fare i tre pezzi del §4.2 in fitosim, o solo la conversione.
2. Il contratto: lux·ora al giorno con ore valide e frazione satura, e la
   conversione in fitosim.
3. Se chiedere a The Pot il parametro canonico di illuminamento.
4. Per il lisimetro, prima di usare il dato: spostare il sensore sopra la
   chioma, e passare dal guadagno 1 fisso al guadagno basso con scelta
   automatica e correzione.
