"""
Coefficiente nutrizionale Kn per il modello evapotraspirativo esteso.

Il modulo introduce nella sotto-tappa D della tappa 3 della fascia 2
il fattore moltiplicativo che modula la traspirazione della pianta in
base allo stato chimico del substrato. È il pezzo che chiude l'anello
tra modello chimico (sotto-tappe A-C) e modello evapotraspirativo
(fascia 1): adesso le condizioni di EC e pH del substrato non sono
più solo grandezze "osservabili" nel dashboard del giardiniere, ma
influenzano effettivamente la dinamica idrica del vaso.

Il modello esteso del coefficiente colturale
--------------------------------------------

In FAO-56 standard il coefficiente colturale effettivo di un giorno è::

    Kc_eff = Kcb × Ks + Ke           (versione dual-Kc, FAO-56 cap. 7)
    Kc_eff = Kc × Ks                  (versione single-Kc, FAO-56 cap. 6)

dove `Kc` o `Kcb` sono i coefficienti dello stadio fenologico, `Ks` è
il fattore di stress idrico (riduce la traspirazione quando il
substrato è secco), e `Ke` è la componente di evaporazione superficiale
del dual-Kc. Con la sotto-tappa D introduciamo il fattore Kn::

    Kc_eff = (Kcb × Ks + Ke) × Kn    (dual-Kc esteso)
    Kc_eff = Kc × Ks × Kn             (single-Kc esteso)

Il Kn è applicato all'esterno del calcolo standard: quando vale 1.0
il modello si comporta esattamente come prima della sotto-tappa D, e
l'estensione è completamente retrocompatibile. Quando scende sotto
1.0 perché il substrato è troppo salino o il pH è fuori range, la
traspirazione predetta si riduce in modo coerente con la fisiologia
della pianta in stress.

Significato fisiologico
-----------------------

Una pianta con stress salino (EC del substrato troppo alta) fa fatica
ad assorbire acqua per via dell'effetto osmotico inverso: la
concentrazione esterna è simile a quella delle cellule, e la pianta
chiude parzialmente gli stomi per ridurre le perdite. Il risultato è
una traspirazione reale inferiore alla potenziale. Quanto inferiore lo
dice FAO-56 tab. 23 (Maas-Hoffman): per la maggior parte delle
colture il Ks salino perde l'8-17 % per ogni dS/m di ECe oltre la
soglia (pomodoro 9.9, lattuga 13, cipolla 16, fagiolo 19 %/(dS/m),
diviso Ky ≈ 1-1.15); la fragola, tra le più sensibili, 33. Le nostre
soglie sono EC della soluzione del substrato (PourThru), che legge
circa 1.5 volte l'ECe, quindi in queste unità la stessa pendenza vale
6-11 %/(mS/cm). La rampa di fitosim usa `EC_STRESS_SLOPE_PCT_PER_MSCM`
con quella scala: lo stress è un fenomeno di diversi mS/cm, non di
decimi. Fino al 2026-09 la rampa scendeva a 0.3 in una sola ampiezza
di range (47-140 %/(mS/cm) a seconda del gruppo): dopo ogni
fertirrigazione, l'EC che si concentra con l'asciugamento portava il
modello a tagliare l'ET fino al 70 % nella coda del ciclo.

Il pH del substrato fuori range non ostacola l'assorbimento d'acqua:
agisce sulla disponibilità dei nutrienti (ferro, manganese e fosforo
che precipitano a pH alto; manganese e alluminio tossici a pH basso,
poco rilevante in torba sopra 5.0) e quindi sulla salute e sulla
crescita, in settimane, non sul consumo idrico del giorno. FAO-56
non ha un coefficiente per il pH. Il fattore pH resta nel Kn come
modulatore **lieve** e bilaterale — entrambi i lati fanno male alla
pianta — con una banda di tolleranza di `PH_TOLERANCE` = ±0.3 unità
attorno al range, la stessa sotto la quale `ph_out_of_range` in
`domain/alerts.py` non emette allerte, e un pavimento `PH_KN_MIN` =
0.8: al massimo un quinto dell'ET, mai i due terzi. Il numero è una
scelta prudente, non una misura; è documentato perché sia
calibrabile. Conta anche perché il pH iniziale del Pot è quasi
sempre un default (il `ph_typical` del substrato, o 7.0) che nessuno
ha misurato: con una scheda a pH 5.8-6.2 il vecchio fattore tagliava
il 28 % dell'ET di un vaso appena invasato, il nuovo il 5 %.

Un'EC **bassa**, invece, non riduce la traspirazione. Una soluzione
povera di sali ha un potenziale osmotico vicino a zero: l'acqua è
più facile da assorbire, non più difficile. Quello che manca sono i
nutrienti, e la carenza agisce sulla crescita (meno foglie, meno
chioma) su una scala di settimane, non sul consumo idrico del giorno.
Per questo il fattore EC è **unilaterale**: penalizza solo l'eccesso
di sali, e sotto il range vale 1.0. È la stessa forma del
coefficiente di stress salino di FAO-56 (cap. 8, eq. 83, da
Maas-Hoffman): Ks = 1 fino alla soglia di EC, poi decrescita lineare.
FAO-56 tratta la fertilità ridotta per altra via, come chioma ridotta
(Kcb più basso), cioè come effetto di crescita e non come
moltiplicatore giornaliero. La carenza nutrizionale in fitosim è
quindi un **segnale per la fertirrigazione** — le allerte
`ec_too_low` e `fertilization_due` in `domain/alerts.py` — e non un
termine dell'evapotraspirazione. Un substrato fresco senza concime
(EC ≈ 0) traspira come uno in range: senza questo, un vaso appena
creato partirebbe con Kn = 0.3 e il 70 % di ET in meno finché non
arriva la prima fertirrigazione, falsando ogni calibrazione del Kc.

Forma matematica della funzione di stress
-----------------------------------------

Per il **pH** il fattore di stress è una **funzione triangolare**
della distanza dal range ottimale della specie, in entrambe le
direzioni: dentro il range, e nella banda di tolleranza `t` =
`PH_TOLERANCE` ai suoi lati, vale 1.0; oltre la banda scende
linearmente verso il pavimento `m` = `PH_KN_MIN` raggiunto a una
distanza `h` = `PH_STRESS_HALF_WIDTH` (la "semi-ampiezza" della
rampa), e oltre quella distanza è clampata al pavimento. La forma è
una "trapezia con plateau interno":

         1.0  ─┐    ┌──────────────┐    ┌───
                │    │              │    │
                │    │    Kn=1      │    │
                │    │ (range ± t)  │    │
                │    │              │    │
                ╱    │              │    ╲
       Kn_min ╱     │              │     ╲
              │     │              │      │
       ───── │      │              │      │ ─────
          a-t-h    a-t     a    b    b+t    b+t+h

Per l'**EC** il fattore è la stessa funzione **senza la rampa
sinistra** e senza banda: 1.0 fino al massimo del range compreso,
rampa lineare verso `KN_MIN_DEFAULT` sopra, clamp oltre
(`salinity_factor`). La semi-ampiezza `h` non viene dal range ma
dalla pendenza `EC_STRESS_SLOPE_PCT_PER_MSCM`: è la distanza sopra il
massimo alla quale la rampa, che perde quella percentuale per ogni
mS/cm, tocca il pavimento — `h = (1 − Kn_min) × 100 / pendenza`,
circa 5.8 mS/cm con i default. Il minimo del range non entra nel
fattore: serve alle allerte di fertirrigazione.

         1.0  ─────────────────────┐
                                   │
                    Kn=1           │
              (sotto e in range)   │
                                   │
                                    ╲
       Kn_min                        ╲
                                      │
                                      │ ─────
              0         a          b      b+h

Il Kn complessivo è il **prodotto dei due fattori** (EC e pH),
perché entrambi gli stress si combinano peggiorando la performance
della pianta: una pianta con sia EC alta sia pH fuori range soffre
più che una pianta con solo uno dei due problemi. Il pavimento
complessivo è `KN_MIN_DEFAULT × PH_KN_MIN` = 0.24.

Filosofia di disabilitazione
----------------------------

Quando la specie non ha configurato i quattro parametri chimici
(ec_optimal_min/max, ph_optimal_min/max), il modello chimico è
"silenzioso" e Kn vale 1.0 — il vaso si comporta esattamente come
prima della tappa 3. Questo rende l'estensione completamente
retrocompatibile per le specie del catalogo legacy della fascia 1.
"""

from __future__ import annotations


# Valore minimo del fattore EC, raggiunto in stress salino completo
# (EC molto sopra il range). Corrisponde al valore di letteratura per
# stress salino acuto: la pianta riduce la traspirazione del 70%
# rispetto alla condizione ottimale. È anche il default di `kn_min`
# per `triangular_factor`; il pH usa il suo pavimento, PH_KN_MIN.
#
# Quando in futuro la calibrazione contro i dati reali del sensore ATO
# mostrasse che un Kn_min specifico per specie produce simulazioni più
# accurate (per esempio, perché alcune specie sono più resistenti agli
# stress di altre), aggiungeremo un parametro opzionale `kn_min` a
# `Species` che ha la precedenza su questa costante. Per ora il valore
# globale è il default per tutte le specie.
KN_MIN_DEFAULT = 0.3


# Pendenza della rampa di stress salino: percentuale di ET persa per
# ogni mS/cm di EC della soluzione del substrato oltre il massimo del
# range ottimale della specie. È il `b / Ky` di FAO-56 eq. 83.
#
# FAO-56 tab. 23 (Maas-Hoffman) dà, in %/(dS/m) di ECe: pomodoro 9.9,
# lattuga 13, cipolla 16, fagiolo 19, fragola 33; con Ky ≈ 1-1.15 la
# perdita di ET è 8-17 %/(dS/m) per la maggior parte delle colture. Le
# soglie di fitosim sono EC PourThru, circa 1.5 volte l'ECe (e-GRO,
# cat. A: SME 0.9-1.3 contro PourThru 1.3-2.0), quindi in queste unità
# la stessa pendenza vale 6-11 %/(mS/cm). 12 è un default prudente,
# dalla parte delle specie sensibili: le ornamentali in vaso lo sono
# più delle ortive di pieno campo della tabella. Con KN_MIN_DEFAULT il
# pavimento si tocca a (1 − 0.3) × 100 / 12 ≈ 5.8 mS/cm sopra il
# massimo. Come per `kn_min`, la calibrazione potrà aggiungere una
# pendenza per specie (o per gruppo botanico in The Pot: orchidee,
# conifere e bonsai sensibili verso 25, ortive tolleranti verso 8).
EC_STRESS_SLOPE_PCT_PER_MSCM = 12.0


# Banda di tolleranza del pH attorno al range ottimale, in unità di pH:
# dentro `[min − t, max + t]` il fattore pH vale 1.0. È la stessa
# tolleranza sotto la quale `check_ph_out_of_range` (domain/alerts.py)
# non emette allerte: Kn e allerte devono cominciare a "vedere" il pH
# fuori range nello stesso punto.
PH_TOLERANCE = 0.3


# Pavimento del fattore pH in stress completo. Il pH agisce sulla
# nutrizione e sulla crescita in settimane, non sull'assorbimento
# d'acqua del giorno (FAO-56 non ha un coefficiente per il pH): resta
# nel Kn come modulatore lieve, al massimo un quinto dell'ET. Scelta
# prudente, non misura; da calibrare.
PH_KN_MIN = 0.8


# Semi-ampiezza della rampa di stress per il pH, in unità di pH. È la
# distanza oltre la banda di tolleranza alla quale il fattore pH
# raggiunge PH_KN_MIN: 10 % di ET per unità di pH.
#
# Per il basilico (range ottimale pH 6.0-7.0), questo significa che
# Kn_pH=1 tra pH 5.7 e 7.3, scende linearmente verso 0.8 fino a pH=3.7
# (= 5.7 - 2.0) e a pH=9.3 (= 7.3 + 2.0), e oltre quei limiti resta
# clampato a 0.8. Per acidofile estreme come il mirtillo potremmo voler
# stringere questa ampiezza in tappa di calibrazione.
PH_STRESS_HALF_WIDTH = 2.0


# =======================================================================
#  Funzione triangolare riusabile
# =======================================================================

def triangular_factor(
    *,
    current: float,
    optimal_min: float,
    optimal_max: float,
    half_width: float,
    kn_min: float = KN_MIN_DEFAULT,
) -> float:
    """
    Calcola un fattore di stress triangolare-trapezoidale.

    La funzione vale 1.0 dentro il range ottimale `[optimal_min,
    optimal_max]`, scende linearmente verso `kn_min` nelle due rampe
    di larghezza `half_width` ai lati del range, e resta clampata al
    minimo oltre quei limiti. È la forma giusta per grandezze che
    fanno male in entrambe le direzioni, come il pH; per l'EC, dove
    solo l'eccesso è uno stress, vedi `salinity_factor`.

    Forma matematica completa
    -------------------------

    Definendo `a = optimal_min`, `b = optimal_max`, `h = half_width`,
    `m = kn_min`::

        x ≤ a − h               →  m
        a − h < x < a           →  m + (1 − m) × (x − (a − h)) / h
        a ≤ x ≤ b               →  1
        b < x < b + h           →  1 − (1 − m) × (x − b) / h
        x ≥ b + h               →  m

    Le due rampe sono lineari per costruzione. Il plateau interno
    garantisce che dentro il range ottimale la funzione sia esattamente
    1.0, senza correzioni numeriche; i plateau esterni clampati
    impediscono che la funzione vada sotto il minimo per valori
    estremi.

    Parametri
    ---------
    current : float
        Valore corrente della grandezza chimica (EC in mS/cm o pH).
    optimal_min, optimal_max : float
        Estremi del range ottimale per la specie. Devono soddisfare
        `optimal_min < optimal_max`.
    half_width : float
        Distanza oltre il range alla quale il fattore raggiunge
        `kn_min`. Deve essere strettamente positiva.
    kn_min : float, opzionale
        Valore minimo del fattore in stress completo. Default
        `KN_MIN_DEFAULT = 0.3`. Deve stare in (0, 1].

    Ritorna
    -------
    float
        Fattore di stress in [kn_min, 1.0].

    Solleva
    -------
    ValueError
        Per parametri fisicamente impossibili (range invertito,
        half_width non positivo, kn_min fuori (0, 1]).

    Esempi
    --------
    Basilico, range pH 6.0-7.0, half_width `PH_STRESS_HALF_WIDTH`
    = 2.0, Kn_min default::

        >>> triangular_factor(current=6.5, optimal_min=6.0,
        ...                   optimal_max=7.0, half_width=2.0)
        1.0
        >>> triangular_factor(current=5.0, optimal_min=6.0,
        ...                   optimal_max=7.0, half_width=2.0)
        0.65         # rampa sinistra: -1.0 dal min, → 50% nella rampa
        >>> triangular_factor(current=4.0, optimal_min=6.0,
        ...                   optimal_max=7.0, half_width=2.0)
        0.3          # clampato al minimo (= optimal_min - half_width)
    """
    if optimal_min >= optimal_max:
        raise ValueError(
            f"triangular_factor: optimal_min ({optimal_min}) deve "
            f"essere strettamente minore di optimal_max ({optimal_max})."
        )
    if half_width <= 0:
        raise ValueError(
            f"triangular_factor: half_width deve essere positivo "
            f"(ricevuto {half_width})."
        )
    if not 0.0 < kn_min <= 1.0:
        raise ValueError(
            f"triangular_factor: kn_min deve stare in (0, 1] "
            f"(ricevuto {kn_min})."
        )

    # Caso 1: dentro il range ottimale — fattore pieno.
    if optimal_min <= current <= optimal_max:
        return 1.0

    # Caso 2: oltre il limite inferiore di stress completo.
    if current <= optimal_min - half_width:
        return kn_min

    # Caso 3: oltre il limite superiore di stress completo.
    if current >= optimal_max + half_width:
        return kn_min

    # Caso 4: rampa sinistra. Scala lineare da kn_min (a x = a-h) a
    # 1.0 (a x = a). La distanza relativa cresce con x.
    if current < optimal_min:
        ramp_position = (current - (optimal_min - half_width)) / half_width
        return kn_min + (1.0 - kn_min) * ramp_position

    # Caso 5: rampa destra. Scala lineare da 1.0 (a x = b) a kn_min
    # (a x = b+h). La distanza relativa cresce con x.
    # current > optimal_max
    ramp_position = (current - optimal_max) / half_width
    return 1.0 - (1.0 - kn_min) * ramp_position


# =======================================================================
#  Fattore di stress salino: unilaterale
# =======================================================================

def salinity_factor(
    *,
    current: float,
    optimal_max: float,
    half_width: float,
    kn_min: float = KN_MIN_DEFAULT,
) -> float:
    """
    Calcola il fattore di stress osmotico da eccesso di sali.

    È la metà destra di `triangular_factor`: vale 1.0 fino a
    `optimal_max` compreso, scende linearmente verso `kn_min` nella
    rampa di larghezza `half_width` sopra il massimo, e resta clampata
    al minimo oltre. Sotto il range non c'è penalità, perché una
    soluzione povera di sali non ostacola l'assorbimento d'acqua: la
    carenza nutrizionale è un segnale per la fertirrigazione (allerte
    `ec_too_low` e `fertilization_due`), non un termine dell'ET. Vedi
    la docstring del modulo per la motivazione e FAO-56 cap. 8, eq. 83
    per la forma.

    Forma matematica completa
    -------------------------

    Definendo `b = optimal_max`, `h = half_width`, `m = kn_min`::

        x ≤ b                   →  1
        b < x < b + h           →  1 − (1 − m) × (x − b) / h
        x ≥ b + h               →  m

    Parametri
    ---------
    current : float
        EC corrente della soluzione del substrato, in mS/cm.
    optimal_max : float
        Massimo del range ottimale della specie: la soglia sopra la
        quale comincia lo stress osmotico.
    half_width : float
        Distanza oltre il massimo alla quale il fattore raggiunge
        `kn_min`. Deve essere strettamente positiva.
    kn_min : float, opzionale
        Valore minimo del fattore in stress completo. Default
        `KN_MIN_DEFAULT = 0.3`. Deve stare in (0, 1].

    Ritorna
    -------
    float
        Fattore di stress in [kn_min, 1.0].

    Solleva
    -------
    ValueError
        Per half_width non positivo o kn_min fuori (0, 1].

    Esempi
    --------
    Massimo 1.6 mS/cm, half_width 0.6 (numeri tondi per l'esempio:
    `nutritional_factor` deriva la semi-ampiezza dalla pendenza
    `EC_STRESS_SLOPE_PCT_PER_MSCM`, circa 5.8 mS/cm), Kn_min default::

        >>> salinity_factor(current=0.0, optimal_max=1.6, half_width=0.6)
        1.0          # substrato fresco senza concime: nessuna penalità
        >>> salinity_factor(current=1.3, optimal_max=1.6, half_width=0.6)
        1.0
        >>> salinity_factor(current=1.9, optimal_max=1.6, half_width=0.6)
        0.65         # rampa: +0.3 dal max, → 50% nella rampa
        >>> salinity_factor(current=2.2, optimal_max=1.6, half_width=0.6)
        0.3          # clampato al minimo (= optimal_max + half_width)
    """
    if half_width <= 0:
        raise ValueError(
            f"salinity_factor: half_width deve essere positivo "
            f"(ricevuto {half_width})."
        )
    if not 0.0 < kn_min <= 1.0:
        raise ValueError(
            f"salinity_factor: kn_min deve stare in (0, 1] "
            f"(ricevuto {kn_min})."
        )

    # Caso 1: sotto il range o dentro — fattore pieno.
    if current <= optimal_max:
        return 1.0

    # Caso 2: oltre il limite di stress completo.
    if current >= optimal_max + half_width:
        return kn_min

    # Caso 3: rampa. Scala lineare da 1.0 (a x = b) a kn_min (a x = b+h).
    ramp_position = (current - optimal_max) / half_width
    return 1.0 - (1.0 - kn_min) * ramp_position


# =======================================================================
#  Funzione principale: Kn complessivo da specie e stato chimico
# =======================================================================

def nutritional_factor(
    *,
    species: "Species",
    ec_substrate_mscm: float,
    ph_substrate: float,
) -> float:
    """
    Calcola il coefficiente nutrizionale Kn complessivo per una specie
    nel suo stato chimico corrente.

    Il Kn è il **prodotto dei due fattori indipendenti** calcolati per
    EC e pH separatamente con i parametri della specie: l'EC tramite
    `salinity_factor` (unilaterale: penalizza solo l'eccesso di sali,
    sotto il range vale 1.0), il pH tramite `triangular_factor`
    (bilaterale, lieve). Quando la specie non ha configurato il modello
    chimico (`species.supports_chemistry_model == False`), la funzione
    restituisce silenziosamente 1.0 — comportamento "inerte" coerente
    con la filosofia di disabilitazione dell'estensione.

    La rampa dell'EC parte da `ec_optimal_max_mscm` e perde
    `EC_STRESS_SLOPE_PCT_PER_MSCM` per cento di ET per ogni mS/cm oltre
    (FAO-56 eq. 83, vedi la costante per la derivazione); la
    semi-ampiezza passata a `salinity_factor` è la distanza alla quale
    quella pendenza tocca `KN_MIN_DEFAULT`. Il minimo del range non
    entra nel calcolo. Per il pH il plateau è il range allargato di
    `PH_TOLERANCE` (la tolleranza delle allerte), la semi-ampiezza è
    `PH_STRESS_HALF_WIDTH` e il pavimento `PH_KN_MIN`.

    Parametri
    ---------
    species : Species
        Dataclass della specie. Solo i quattro parametri chimici sono
        usati; gli altri (Kc, fenologia, ecc.) sono ignorati. Quando
        non sono configurati, ritorniamo 1.0 senza errore.
    ec_substrate_mscm : float
        EC corrente del substrato, in mS/cm. Tipicamente ottenuto da
        `Pot.ec_substrate_mscm`. Non-negativo.
    ph_substrate : float
        pH corrente del substrato, scala 0-14. Tipicamente ottenuto
        da `Pot.ph_substrate`.

    Ritorna
    -------
    float
        Kn complessivo in [KN_MIN_DEFAULT × PH_KN_MIN, 1.0]. Il limite
        inferiore teorico è 0.3 × 0.8 = 0.24 nel caso degenere di stress
        massimo simultaneo su EC e pH; in pratica si vedono valori
        intorno a 0.8-0.95 per condizioni "subottimali ma non
        drammatiche" e 1.0 per condizioni ben gestite.

    Esempi
    --------
    Basilico (range EC 1.0-1.6, pH 6.0-7.0) in condizioni ottimali::

        >>> kn = nutritional_factor(
        ...     species=basil_with_chemistry,
        ...     ec_substrate_mscm=1.3,
        ...     ph_substrate=6.5,
        ... )
        >>> assert kn == 1.0

    Stesso basilico ma con EC moderatamente alta (stress lieve)
    e pH ottimale::

        >>> kn = nutritional_factor(
        ...     species=basil_with_chemistry,
        ...     ec_substrate_mscm=2.6,    # 1.0 sopra max=1.6
        ...     ph_substrate=6.5,
        ... )
        >>> # ec_factor: 1 mS/cm oltre × 12 %/(mS/cm) → 1 - 0.12 = 0.88
        >>> # ph_factor: 1.0
        >>> # kn = 0.88 × 1.0 = 0.88
        >>> assert abs(kn - 0.88) < 1e-9

    Stesso basilico con EC ottimale e pH 8.0 (1.0 sopra il massimo,
    0.7 oltre la banda di tolleranza di 0.3)::

        >>> kn = nutritional_factor(
        ...     species=basil_with_chemistry,
        ...     ec_substrate_mscm=1.3,
        ...     ph_substrate=8.0,
        ... )
        >>> # ph_factor: 0.7 / 2.0 della rampa → 1 - 0.2 × 0.35 = 0.93
        >>> assert abs(kn - 0.93) < 1e-9

    Stesso basilico in substrato fresco, senza concime (EC ≈ 0):
    nessuna penalità, perché l'EC bassa non è uno stress osmotico::

        >>> kn = nutritional_factor(
        ...     species=basil_with_chemistry,
        ...     ec_substrate_mscm=0.0,
        ...     ph_substrate=6.5,
        ... )
        >>> assert kn == 1.0

    Specie senza modello chimico configurato (es. specie del catalogo
    legacy della fascia 1)::

        >>> kn = nutritional_factor(
        ...     species=basil_legacy_no_chemistry,
        ...     ec_substrate_mscm=2.5,
        ...     ph_substrate=8.0,
        ... )
        >>> assert kn == 1.0   # disabilitazione silenziosa
    """
    # Disabilitazione silenziosa per specie del catalogo legacy.
    if not species.supports_chemistry_model:
        return 1.0

    # Validazione degli input numerici (la specie è già validata in
    # Species.__post_init__).
    if ec_substrate_mscm < 0:
        raise ValueError(
            f"nutritional_factor: ec_substrate_mscm deve essere "
            f"non-negativa (ricevuto {ec_substrate_mscm})."
        )
    if not 0.0 < ph_substrate <= 14.0:
        raise ValueError(
            f"nutritional_factor: ph_substrate deve stare in (0, 14] "
            f"(ricevuto {ph_substrate})."
        )

    # Fattore EC: unilaterale, sopra il massimo del range. La rampa
    # perde EC_STRESS_SLOPE_PCT_PER_MSCM per cento per mS/cm; la
    # semi-ampiezza è la distanza alla quale tocca il pavimento. Il
    # minimo del range non entra: sotto il massimo il fattore vale 1.0
    # e la carenza è affare delle allerte, non dell'ET.
    ec_half_width = (
        (1.0 - KN_MIN_DEFAULT) * 100.0 / EC_STRESS_SLOPE_PCT_PER_MSCM
    )
    ec_factor = salinity_factor(
        current=ec_substrate_mscm,
        optimal_max=species.ec_optimal_max_mscm,
        half_width=ec_half_width,
    )

    # Fattore pH: plateau sul range allargato della tolleranza delle
    # allerte, rampa lieve fino al suo pavimento (vedi le costanti).
    ph_factor = triangular_factor(
        current=ph_substrate,
        optimal_min=species.ph_optimal_min - PH_TOLERANCE,
        optimal_max=species.ph_optimal_max + PH_TOLERANCE,
        half_width=PH_STRESS_HALF_WIDTH,
        kn_min=PH_KN_MIN,
    )

    # Kn complessivo: prodotto dei due fattori.
    return ec_factor * ph_factor
