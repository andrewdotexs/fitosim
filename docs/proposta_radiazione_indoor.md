# Proposta — la radiazione netta in casa, e la luce contata due volte

*24 novembre 2026. Scritta su fitosim 0.42.0 come proposta, da due
osservazioni della sessione di The Pot.*

**Decisa lo stesso giorno** (Andrew): **N2**, l'albedo soltanto, e **D2**, la
riga nella documentazione e lo stesso rimedio di The Pot nel passo in casa.
Sono in fitosim 0.43.0 (`indoor.net_indoor_radiation`,
`indoor.estimate_indoor_net_radiation`, `Pot.apply_balance_step_from_indoor`,
`tests/test_indoor.py`). Il testo sotto è quello della proposta, lasciato
com'era.

## 1. Le due osservazioni, verificate

**La globale passata come netta.** Il passo in casa
(`Pot.apply_balance_step_from_indoor`, `domain/pot.py:2515`) prende la
radiazione della stanza da `estimate_indoor_radiation` — una frazione della
radiazione **globale** di fuori, o un numero fisso per livello di luce — e
la passa a Penman-Monteith come `net_radiation_mj_m2_day`. È vero: fra le
due manca almeno la parte riflessa. The Pot fa lo stesso in
`idrica_service._et0_dall_aria`. All'aperto fitosim la conversione la fa
(`radiation.net_radiation`: albedo e onda lunga, FAO-56 eq. 38–40).

**La luce contata due volte.** In casa la luce del vaso decide la radiazione
della stanza (`light_exposure`: 0,40 / 0,15 / 0,05 di quella di fuori), e
poi l'ET passa per `Kp`, che la moltiplica per il fattore di esposizione
(`sun_exposure`: 1,00 / 0,70 / 0,45). In fitosim da solo il secondo vale 1,
perché un vaso in casa lascia `sun_exposure` al suo default; in The Pot no,
perché l'adattatore lo ricava dalla stessa luce del vaso. È vero anche
questo, ed è vero solo sul cammino in cui la radiazione è già quella al
vaso: un vaso in casa senza sensore d'aria usa l'ET₀ di fuori, e lì il
fattore di esposizione è l'unica riduzione.

## 2. Le fonti

| Fonte | Che cosa dice | Letta |
|---|---|---|
| FAO-56, cap. 3, «Albedo and net solar radiation» | Eq. 38: `R_ns = (1 − α) R_s`. «For the green grass reference crop, α is assumed to have a value of 0.23». Eq. 40: `R_n = R_ns − R_nl`, la netta è l'onda corta assorbita meno l'onda lunga netta uscente | alla fonte (fao.org), parola per parola |
| FAO-56, eq. 39 | L'onda lunga netta: Stefan-Boltzmann corretta per l'umidità e per la nuvolosità (`R_s/R_so`). È scritta per una superficie sotto il cielo | la formula è un'immagine nella pagina: è quella che fitosim ha già in `radiation.net_radiation` |
| Katsoulas & Stanghellini 2019, *Agronomy* 9(7):392, rassegna sui modelli di traspirazione in serra | Di giorno lo scambio termico netto in serra è spesso trascurato, e la netta della coltura si prende dalla sola onda corta; l'onda lunga, quando si calcola, è uno scambio fra la chioma e le superfici attorno, pesato coi fattori di vista | solo dal riassunto della ricerca: l'articolo rifiuta l'accesso automatico |
| Fernández et al. 2010, *Irrig. Sci.* 28:497–509 (con errata) | In serra Penman-Monteith funziona con una resistenza aerodinamica fissa; la stima della netta è un punto debole noto | solo l'abstract |

Quello che le fonti reggono: **l'albedo va tolto sempre** (eq. 38), e
**l'onda lunga dell'eq. 39 non vale al chiuso**, perché è scritta per il
cielo: in una stanza la chioma scambia con pareti, soffitto e vetri. Una
formula per le stanze di casa non l'ho trovata.

## 3. Le misure

Radiazione reale di Milano centro, 2025 (archivio Open-Meteo); stanza a
20 °C e 45 % d'inverno, 26 °C e 60 % d'estate (ipotesi di scenario, la
stessa della proposta sulla luce); vento 0,5 m/s. ET₀ di Penman-Monteith
standard, radiazione della stanza col sole vero.

| Luce al vaso | Trattamento | Anno (mm) | Dic–gen (mm/g) | Giu–lug (mm/g) | Rispetto a oggi |
|---|---|---:|---:|---:|---:|
| Sole diretto | oggi: globale come netta | 769 | 1,01 | 3,22 | 100 % |
| | albedo 0,23 | 638 | 0,91 | 2,59 | 83 % |
| | albedo, superfici 1 K più fredde | 587 | 0,78 | 2,44 | 76 % |
| | albedo, superfici 3 K più fredde | 485 | 0,52 | 2,15 | 63 % |
| Luminoso indiretto | oggi | 412 | 0,74 | 1,52 | 100 % |
| | albedo 0,23 | 363 | 0,71 | 1,28 | 88 % |
| | albedo, superfici 1 K più fredde | 312 | 0,58 | 1,13 | 76 % |
| | albedo, superfici 3 K più fredde | 210 | 0,32 | 0,84 | 51 % |
| Buio | oggi | 269 | 0,64 | 0,84 | 100 % |
| | albedo 0,23 | 253 | 0,62 | 0,76 | 94 % |
| | albedo, superfici 1 K più fredde | 202 | 0,49 | 0,61 | 75 % |
| | albedo, superfici 3 K più fredde | 100 | 0,23 | 0,31 | 37 % |

Col Penman-Monteith fisico (basilico: 100 s/m, 30 cm) le riduzioni per
l'albedo sono le stesse a un paio di punti: 85 / 90 / 95 %. Con la
radiazione fissa che The Pot usa oggi: 81 / 85 / 90 %.

Due letture.

- **L'albedo toglie fra il 6 e il 17 % dell'acqua dell'anno**, di più dove
  c'è più sole: l'ET in casa la guida soprattutto l'aria.
- **L'onda lunga pesa più dell'albedo, e non si conosce.** Ogni kelvin di
  differenza fra la chioma e le superfici della stanza vale 0,48
  MJ/m²/giorno; in un angolo luminoso d'inverno la radiazione a onda corta
  è 0,5. E il segno non è dato: accanto a un vetro freddo la chioma perde,
  ma una chioma che traspira è più fresca dell'aria e delle pareti, e
  allora guadagna. Servirebbe la temperatura media radiante della stanza,
  che nessun sensore di The Pot misura.

**Sui test.** Con l'albedo nel passo in casa, provato e poi tolto, i 1 642
test passano tutti: nessuno fissa un valore assoluto dell'ET in casa.

**Sui vasi veri.** Qui non si può misurare: i vasi con la sonda stanno nel
database di produzione di The Pot. La verifica è di là, col lettore della
calibrazione: `confronta` su un vaso in casa con la sonda, prima e dopo, e
lo scarto fra θ prevista e osservata dice se la correzione avvicina.

## 4. Le alternative

**N1 — Niente.** Le tre frazioni delle stanze (0,40 / 0,15 / 0,05) sono
medie di letteratura dichiarate da tarare: un errore del 6–17 % sta dentro
la loro incertezza, e una taratura sui vasi veri lo assorbirebbe. Ma resta
un errore di fisica scritto nel codice, in una direzione sola: troppa acqua.

**N2 — L'albedo soltanto (consigliata).** `R_n = (1 − 0,23) × R_s` della
stanza, e l'onda lunga a zero: è l'ipotesi neutra, superfici alla
temperatura della chioma, ed è quella che la rassegna sulle serre descrive
come pratica comune di giorno. Una funzione in `science/indoor.py` che dà
la netta, usata dal passo in casa di fitosim; The Pot chiama la stessa nel
suo `_et0_dall_aria`, così i due non si separano. L'incertezza dell'onda
lunga si dichiara nel codice coi suoi 0,48 MJ/m²/giorno per kelvin.

**N3 — La netta completa.** L'onda lunga fra chioma e superfici, coi
fattori di vista. È la fisica giusta, ma chiede la temperatura media
radiante e la temperatura della chioma: dati che non ci sono. Un numero
messo a caso peserebbe più di tutto il resto (tabella).

## 5. La luce contata due volte

The Pot ha già deciso la sua variante: divide l'ET₀ della stanza per il
fattore di esposizione, come fa per il Kc. Per fitosim le strade sono due.

**D1 — Solo la documentazione.** Una riga in `Pot.kp`, nel campo
`sun_exposure` e nel passo in casa: «in casa la luce entra una volta, nella
radiazione della stanza; `sun_exposure` resta al default, o chi chiama
divide l'ET₀ per il fattore». fitosim non cambia e The Pot non rischia di
correggere due volte.

**D2 — Lo stesso rimedio nel passo in casa di fitosim (consigliata).** Oltre
alla riga, `apply_balance_step_from_indoor` divide l'ET₀ per il fattore di
esposizione del vaso, come The Pot. Per un vaso col default non cambia
nulla (si divide per 1); cambia solo per chi chiama quel passo con un
`sun_exposure` diverso, e The Pot non lo chiama. I due motori fanno la
stessa cosa nello stesso punto, senza un interruttore nuovo.

Un interruttore generale («non applicare l'esposizione in Kp») non lo
propongo: Kp serve anche ai vasi in casa senza sensore d'aria, dove è
l'unica riduzione, e un secondo modo di dire la stessa cosa è il modo più
facile per correggere due volte.

## 6. Che cosa si decide

1. La radiazione netta in casa: N1, N2 o N3.
2. La luce contata due volte in fitosim: D1 o D2.

In tutti i casi The Pot non cambia niente da sé: quello che fa di là lo
decide di là, sui suoi vasi.
