# Design: la pianta dentro il vaso — copertura della chioma e altezza

**Data:** 2026-09-05
**Status:** Implementato (fascia 3, su richiesta di The Pot, roadmap H.1-c). Tre campi facoltativi su `Pot`, un modulo puro `science/canopy.py`, formato JSON invariato nella forma (tre chiavi in più), schema SQLite v6.
**Autore della riflessione:** Andrea, con analisi tecnica in sessione.

## In una frase

Fino a oggi il vaso simulato non sapeva niente della pianta che aveva dentro, tranne la specie: un basilico di 10 cm e uno di 60 cm nello stesso vaso avevano la stessa curva idrica. The Pot da H.1 registra i rilievi della pianta — altezza, larghezza e altezza della chioma — e fitosim ora li riceve e li usa in due punti: **la copertura della chioma scala il coefficiente colturale** (FAO-56 cap. 9), **l'altezza della pianta entra in Penman-Monteith fisico** al posto dell'altezza colturale della specie.

## Il gap

FAO-56 dà i Kc per una coltura a pieno campo che copre il suolo come la sua tabella prevede. In vaso la chioma non copre "il suolo": copre la bocca del vaso, e il rapporto fra le due aree è quasi sempre lontano da uno, in tutte e due le direzioni:

- una piantina appena messa in un vaso grande copre un quarto della bocca, e la tabella la fa traspirare come se la coprisse tutta — sovrastima, e il consiglio è di bagnare troppo presto;
- un oleandro adulto in un vaso da trenta centimetri ha una chioma quattro volte la bocca del vaso: traspira per la sua superficie, e l'acqua la prende tutta dal vaso — sottostima, e il consiglio arriva tardi.

Il secondo caso è quello che The Pot vede tutti i giorni sul balcone, e finora aveva un solo rimedio: la taratura per vaso della fascia 3, che è un cerotto sul sintomo. Qui si cura la causa.

## Cosa dice FAO-56

Il capitolo 9 tratta le colture con copertura parziale o "non pristine" e propone (eq. 76) di scalare il Kcb con la frazione coperta `fc` e l'altezza della pianta `h` in metri:

```
Kcb = Kc_min + (Kcb_full − Kc_min) · min(1, 2·fc, fc^(1/(1+h)))
```

- `Kc_min` è il Kc del suolo nudo bagnato (0.15–0.20): il pavimento evaporativo, lo stesso di `species.KC_BARE_SOIL_FLOOR`.
- `2·fc` è il limite per le chiome molto rade.
- `fc^(1/(1+h))` dice che una pianta alta traspira più della sua frazione di copertura: gli effetti di bordo, la chioma investita dal vento anche di lato. Con `h = 1 m` e `fc = 0.5` il fattore è `0.5^0.5 = 0.71`, non `0.5`.

La formula è pensata per `fc ≤ 1`. **In vaso `fc` supera 1**, e lì FAO-56 non arriva.

## Le decisioni

### 1. Sotto la copertura piena: eq. 76. Sopra: il rapporto fra le aree, fino a un tetto

`science/canopy.py`:

```
cover_fraction(canopy_width_m, pot_area_m2) = π·(w/2)² / A_vaso
cover_factor(fc, h) = min(1, 2·fc, fc^(1/(1+h)))   se fc < 1
                    = min(fc, COVER_CAP)             se fc ≥ 1
```

`COVER_CAP = 2.5`: sopra due volte e mezza l'area del vaso una pianta è già root-bound o quasi, e il consumo lo governa lo stress idrico (`Ks`), non la chioma. Il tetto tiene il modello nel suo dominio; la calibrazione della fascia 3 potrà spostarlo. A `fc = 1` le due metà valgono 1: nessun salto.

### 2. Kcb senza pavimento, Kc con il pavimento

- **Dual-Kc**: `kcb_from_cover(kcb, fc, h) = kcb · cover_factor(fc, h)`. L'evaporazione dal substrato è di `Ke`, e il Kcb può scendere verso zero: è traspirazione pura. Il Kcb "della chioma" che limita `Ke` (l'ombreggiatura della superficie) è quello scalato: una chioma piccola ombreggia poco.
- **Single Kc**: `kc_from_cover(kc, fc, h, kc_min) = kc_min + (kc − kc_min) · cover_factor(fc, h)` sotto la copertura piena, `kc · cover_factor` sopra. Il pavimento è `min(kc_min, kc)`: una succulenta in riposo con Kc 0.15 non sale a 0.20 per un pavimento.

### 3. L'altezza nell'esponente: la chioma se c'è

In eq. 76 `h` è l'altezza della pianta. Su un albero o un bonsai con il tronco nudo è la chioma che traspira, quindi `Pot.cover_height_m` prende **l'altezza della chioma se misurata, altrimenti l'altezza della pianta, altrimenti l'altezza colturale della specie**.

### 4. L'altezza della pianta in Penman-Monteith fisico

`compute_et` riceve `crop_height_m = Pot.effective_crop_height_m`: **l'altezza misurata della pianta se c'è, altrimenti quella della specie**. Entra nella resistenza aerodinamica (`d = 0.667·h`, `z_om = 0.123·h`, `z_oh = 0.0123·h`): una pianta più alta ha meno resistenza e traspira di più, a parità di tutto il resto. Vale solo quando il selettore sceglie Penman-Monteith fisico (meteo completo e resistenza stomatica della specie); Hargreaves e Penman-Monteith standard non conoscono la pianta e continuano a passare dal Kc, che però è già scalato dalla copertura.

### 5. La «vela al vento» non è un fattore a parte

The Pot aveva promesso (C.7-a) un calcolo sulla vela che il vento investe, altezza per larghezza della chioma. Guardandolo da vicino: **Penman-Monteith fisico lo ha già dentro**. L'altezza della pianta entra nella resistenza aerodinamica, cioè in quanto vento "vede" la chioma; la larghezza entra nella copertura. Un terzo fattore moltiplicativo sul vento conterebbe due volte la stessa cosa. Il riparo (`shelter_wind_factor`) resta quello che è: una proprietà del posto, non della pianta. Decisione: **nessun fattore vela**; il tronco nudo entra solo nell'esponente della copertura (punto 3).

### 6. Tutto facoltativo, e senza misure niente cambia

I tre campi di `Pot` — `plant_height_m`, `canopy_width_m`, `canopy_height_m` — valgono `None` per default, e con `None` ogni funzione restituisce il coefficiente com'era. Il test `TestSenzaMisureNienteCambia` lo fissa: i 1366 test di prima passano invariati. Validazione: positivi se dati, chioma non più alta della pianta.

## Dove entra, nel codice

| Dove | Cosa |
|---|---|
| `science/canopy.py` | `cover_fraction`, `cover_factor`, `kcb_from_cover`, `kc_from_cover`, `COVER_CAP`, `KC_MIN_DEFAULT` |
| `domain/pot.py` | i tre campi; `canopy_cover_fraction`, `cover_height_m`, `effective_crop_height_m`; `_current_et_c_dual_kc` (Kcb e Kcb della chioma), `current_et_c` single Kc (ricalcolato in loco con il Kc scalato: `Ks × Kc × ET₀`), i due `compute_et` con `effective_crop_height_m` |
| `io/serialization.py` | le tre chiavi in `static_fields`, lette se presenti: i JSON di prima si rileggono |
| `io/persistence.py` | schema v6, migrazione difensiva `_migrate_v5_to_v6` (tre `ALTER TABLE`), salvataggio e ricarico |
| `tests/test_canopy.py`, `tests/test_canopy_in_pot.py` | eq. 76 sui numeri di FAO-56, continuità a `fc = 1`, il tetto, il pavimento, single e dual, l'altezza in PM fisico, JSON e SQLite avanti e indietro |

Lato The Pot: `fitosim_adapter.vaso` riceve le tre misure da `pot_plants` (centimetri → metri) e la linguetta «Dati tecnici» mostra la copertura della chioma fra i numeri del modello.

## Cosa resta fuori

- **La copertura come funzione del tempo.** Fra un rilievo e l'altro la chioma è quella dell'ultimo rilievo: una pianta che cresce in fretta va misurata spesso. Un'interpolazione fra rilievi, o una crescita attesa dalla fenologia, è un raffinamento della fascia 3.
- **Il tetto come parametro di calibrazione.** `COVER_CAP` è una costante ragionata, non misurata: la calibrazione contro i dati delle sonde dirà se 2.5 è giusto.
- **La frazione coperta effettiva** (`fc_eff = fc / sin β` di FAO-56, che tiene conto dell'angolo del sole): trascurata. Sul balcone, a mezzogiorno, `fc_eff ≈ fc`.
