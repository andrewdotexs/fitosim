# Design: modellazione del pane radicale (fascia 3)

**Data:** 2026-06-01
**Status:** Decisione di design registrata, NON implementata. Candidata alla fascia 3 (calibrazione). Il livello "minimo" (regime come stato) è anticipabile alla fase 1 di The Pot.
**Autore della riflessione:** Andrea, con analisi tecnica in sessione.

## In una frase

Fitosim oggi assume implicitamente che le radici riempiano l'intero vaso (`Zr = profondità del vaso`). Questa assunzione è valida per una pianta matura in regime stazionario — il dominio dichiarato della libreria — ma si rompe nei due casi estremi del ciclo di vita in vaso: la **talea/semina senza radici** e la **pianta root-bound**. Questo documento registra il fenomeno fisico, le opzioni di modellazione e la decisione di rimandarlo alla fascia 3.

## Il gap attuale

### Cosa fa FAO-56 in pieno campo

Il FAO-56 originale modella esplicitamente la **profondità radicale** `Zr`, che determina il serbatoio idrico accessibile:

```
TAW = 1000 · (θ_FC − θ_PWP) · Zr
```

`Zr` cresce nel tempo (initial → mid) ed è il **secondo** meccanismo, oltre al coefficiente colturale `Kc`, con cui FAO-56 cattura lo sviluppo della pianta: una pianta giovane ha radici poco profonde e accede a meno acqua, anche a parità di domanda atmosferica.

### Cosa ha fatto fitosim

Fitosim ha **collassato `Zr` nella geometria del vaso**:

```
taw_mm = (θ_FC − θ_PWP) · profondità_substrato_mm
```

cioè assume sempre `Zr = profondità del substrato`, ovvero **radici che riempiono tutto il volume**. Questo è coerente con il dominio dichiarato (vaso domestico maturo, regime stazionario) ma introduce un errore sistematico ai due estremi.

## I due casi estremi

### Caso 1 — Talea / semina (radici ≈ 0)

Fenomeno fisico:
- La **traspirazione è quasi nulla**: senza apparato radicale funzionante la pianta non assorbe acqua, quindi manca il "motore" che svuota il substrato per traspirazione.
- L'unica uscita reale è l'**evaporazione superficiale** + drenaggio. Il substrato resta umido a lungo.
- Applicare il Kc normale (per il basilico Kc_initial ≈ 0.5–0.7) **sovrastima enormemente il consumo** → consiglio di irrigare → **marciume**, la causa di morte n°1 delle talee.

Modello corretto: **`Kcb ≈ 0` con `Ke` (evaporazione) dominante**. Fitosim ha già il dual-Kc che separa `Kcb` (traspirazione basale) da `Ke` (evaporazione superficiale); manca solo il modo di forzare `Kcb → 0` durante l'attecchimento.

Nota di onestà modellistica: per una talea senza radici, **FAO-56 non è lo strumento giusto**. Lì conta l'umidità ambientale (mini-serra, nebulizzazione), non il bilancio idrico del substrato. Il regime è "sopravvivenza fino all'attecchimento", non "consumo evapotraspirativo".

### Caso 2 — Vaso pieno di radici (root-bound)

Due effetti distinti che si sommano:
1. **Spiazzamento del substrato**: le radici occupano volume fisico. Il substrato che trattiene acqua si riduce → `TAW` effettivo cala anche se θ_FC/θ_PWP del materiale non cambiano. Un vaso da 2 L root-bound può avere l'equivalente idraulico di ~1 L di substrato.
2. **Consumo massimo**: chioma piena → Kcb al massimo, evaporazione ridotta (superficie coperta dal fogliame).

Risultato: cicli di asciugatura molto più rapidi, RAW esaurito in 1–2 giorni invece di 4–5. È il segnale agronomico classico "questa pianta va rinvasata".

## I due fenomeni da non confondere

| Fenomeno | Quando | Variabile concettuale | Effetto |
|---|---|---|---|
| **A. Esplorazione radicale** | Attecchimento, crescita giovanile, post-rinvaso | `root_fraction ∈ [0,1]` = frazione di serbatoio raggiunta | Riduce TAW accessibile e Kcb |
| **B. Spiazzamento del substrato** | Fine vita nel vaso (root-bound) | `root_volume_fraction` = frazione di volume occupata da biomassa | Riduce il volume idraulico effettivo |

Mappatura sui casi estremi:
- Talea/semina: A → 0 (B irrilevante, nessuna biomassa)
- Root-bound: A = 1, B alto

## Il concetto proposto: frazione di esplorazione radicale

Variabile di stato `root_fraction ∈ [0, 1]`:

| `root_fraction` | Significato | Effetto sul modello |
|---|---|---|
| → 0 | Talea/semina appena fatta | `Kcb → 0` (no traspirazione), `TAW_eff → 0`; domina `Ke` |
| 0.3–0.7 | Pianta in attecchimento/crescita | `TAW_eff = root_fraction · TAW`; Kcb cresce verso il valore di catalogo |
| 1.0 | Vaso pienamente esplorato | Comportamento attuale di fitosim (caso di riferimento) |
| 1.0 + spiazzamento | Root-bound | `TAW_eff < TAW` per riduzione del volume idraulico |

Modula due quantità del modello esistente:
1. **Serbatoio accessibile**: `TAW_eff = root_fraction · TAW` (analogo diretto di `Zr/Zr_max` in FAO-56)
2. **Partizione traspirazione/evaporazione**: `Kcb_eff = root_fraction · Kcb`

## Il collegamento con post-rinvaso e lineage (The Pot)

Questo fenomeno è **lo stesso meccanismo fisico** dietro la finestra post-rinvaso già discussa per The Pot (vedi `the-pot/docs/the_pot_fitosim_integration.md` §8.6 e `the_pot_vision.md` cap. 16).

Quando si rinvasa:
- Le radici occupano ancora il vecchio volume, non il nuovo → `root_fraction` rispetto al **nuovo** vaso crolla.
- La pianta consuma meno per qualche settimana (shock da trapianto) → meno acqua, più rischio marciume.
- Poi le radici colonizzano il nuovo substrato → `root_fraction` risale a 1.

È lo stesso identico fenomeno della talea, a partire da un punto più alto. Avevamo già deciso "il post-rinvaso non blocca i consigli idrici di fitosim ma li rende più conservativi" — `root_fraction` è il **meccanismo fisico** dietro quell'intuizione, e `post_rinvaso_until` ne è la finestra temporale.

## Come inferire `root_fraction` (è non osservabile)

L'utente domestico non sa quantificare lo stato radicale, e il WH51 misura θ senza distinguere zona radicale da inerte. Tre strade di inferenza, in ordine di sofisticazione:

1. **Curva temporale per specie**: `root_fraction(giorni_da_semina)` come sigmoide tarata per specie (basilico colonizza in ~3 settimane, un agrume in mesi). Semplice ma cieca rispetto alla realtà.
2. **Reset al rinvaso**: integrazione con il lineage di The Pot — `root_fraction` riparte da un valore basso ad ogni evento di rinvaso e risale secondo la curva.
3. **Inferenza dal sensore** (fascia 3): se il substrato resta umido nonostante l'ET prevista alta → poche radici → calibra `root_fraction` verso il basso. È la calibrazione passiva descritta nel manuale utente.

## Livelli di ambizione

| Livello | Cosa | Tocca le equazioni FAO-56? | Fase consigliata |
|---|---|---|---|
| **Minimo** | Flag di regime `{ATTECCHIMENTO, NORMALE, DA_RINVASARE}` che cambia consigli e allerte | No | Fase 1 di The Pot |
| **Medio** | `root_fraction(t)` come curva per specie, resettata dal rinvaso, che modula `TAW_eff` e `Kcb_eff` | Sì (moltiplicatori) | Fascia 3 di fitosim |
| **Massimo** | Modello a due serbatoi (zona radicale + zona inerte con scambio idrico) | Sì (riscrittura del bilancio) | **Sconsigliato** (over-engineering per il dominio domestico) |

### Decisione

- **Target: livello medio**, con il **livello minimo come primo passo** già utilizzabile in fase 1 di The Pot.
- **Scope temporale: fascia 3** per il livello medio, perché ha senso tarare le curve `root_fraction(t)` solo con i dati reali del balcone.
- Il **caso talea** va trattato come **regime speciale** (un modo, non un numero): fitosim dovrebbe riconoscere lo stato e dire "sei in attecchimento, non sto simulando il bilancio, mantieni umido e non fertilizzare" piuttosto che fingere di calcolare un Kc.
- Il **caso root-bound** è più utile come **allerta** ("consumo anomalmente rapido + vaso vecchio → considera il rinvaso") che come simulazione precisa del TAW spiazzato. L'utente vuole sapere *che deve rinvasare*, non il valore esatto.
- Il **livello massimo è escluso**: il modello a due serbatoi è sproporzionato rispetto al valore aggiunto per il giardinaggio domestico.

## Punti aperti (da affrontare in fascia 3)

1. **Forma della curva `root_fraction(t)`** — sigmoide? Per quali specie tarata? Parametri (tempo di colonizzazione `τ` per gruppo di specie).
2. **Soglie del regime** — quando `ATTECCHIMENTO → NORMALE` (giorni? `root_fraction` > soglia?) e `NORMALE → DA_RINVASARE` (età del vaso? consumo anomalo rilevato?).
3. **Dove vive `root_fraction`** — campo di stato su `Pot` in fitosim, o derivato dal backend di The Pot e passato come input al calcolo? Coerenza con la decisione "lo stato dinamico vive in fitosim".
4. **Integrazione con il dual-Kc esistente** — il `Kcb_eff = root_fraction · Kcb` si innesta naturalmente nel modulo `science/dual_kc.py`, ma va verificato l'effetto sul limite energetico `Kcmax`.
5. **Reset al rinvaso** — il contratto tra il lineage di The Pot e fitosim: chi resetta `root_fraction`, con quale valore iniziale, e come lo comunica.

## Riferimenti

- Modello fisico attuale: `src/fitosim/science/balance.py` (TAW/RAW), `src/fitosim/science/dual_kc.py` (Kcb/Ke), `src/fitosim/science/substrate.py` (θ_FC/θ_PWP, geometria).
- Variabili del modello: vedi inventario completo discusso in sessione (8 tipologie di input).
- Collegamento post-rinvaso: `the-pot/docs/the_pot_fitosim_integration.md` §8.6, `the-pot/docs/the_pot_vision.md` cap. 16.
- Calibrazione passiva: `docs/fitosim_calibration_manual.md`.
