"""
Il colore dei sali: i serbatoi N, P, K del vaso.

Il bilancio dei sali (`science/fertigation.py`) tiene una massa salina
sola, in milliequivalenti: cresce con le fertirrigazioni, si concentra
con l'asciugamento, esce dal foro col drenaggio. Sa *quanto* sale c'è,
non *che cosa*. Questo modulo gli dà un colore: accanto alla massa
salina, tre serbatoi — azoto (N), fosforo (come P₂O₅) e potassio (come
K₂O), in milligrammi per vaso, le unità delle etichette — che **seguono
la massa salina** e in più conoscono la pianta.

Tre regole, tutte funzioni pure di numeri:

  1. **Entrano con l'etichetta.** Una fertirrigazione a `C` mg/L porta
     `volume × C` in ogni serbatoio; un concime secco versa la sua
     quota giornaliera (`daily_release_fraction`).

  2. **Escono col drenaggio, nella stessa proporzione dei sali** — il
     bilancio dei sali dice che frazione della massa è uscita dal foro,
     e i serbatoi perdono quella frazione (`leached`). Il nitrato, che
     il substrato non trattiene, un po' di più (`NITRATE_LEACHING_BONUS`).

  3. **Escono con la pianta**, ogni giorno (`daily_uptake`): l'assorbimento
     è il flusso di massa della traspirazione alla concentrazione che il
     piano vuole per quel mese — `T [L] × C_bersaglio [mg/L]` — per una
     **frazione di alimentazione** che dice quanto di quel flusso è
     davvero concime e non acqua: chi fertirriga a ogni annaffiatura
     («constant feed», le serre) sta a 1; chi dà un liquido ogni due
     settimane e annaffia ogni tre giorni sta a circa 0,2, e il resto lo
     mette il substrato che non modelliamo. Il freddo chiude il cancello:
     sotto i 10 °C le radici assorbono poco anche se la pianta traspira
     (`temperature_gate`). L'assorbimento toglie anche dalla massa
     salina i milliequivalenti corrispondenti — il concime è sale, e la
     pianta se lo mangia — che è la «metà mangiata» di The Pot fatta
     giorno per giorno.

La coerenza è per costruzione: la somma dei serbatoi in
milliequivalenti non può superare la massa salina, e il vaso la
ristringe quando qualcosa la farebbe superare (`clamp_to_salts`).

**La riserva** per il giardiniere è un numero solo, come quella
idrica: la frazione di una **carica piena** occupata dal serbatoio più
vuoto fra quelli che il piano oggi chiede. La carica piena è l'acqua
del vaso a capacità di campo alla concentrazione del piano, per la
frazione che una concimazione rimpiazza (`FULL_CHARGE_FRACTION`: si
concima quando il vaso ha bevuto metà della sua riserva idrica, e
quella metà torna alla concentrazione giusta). Con la riserva viene il
*quale*: «al 40 %, manca soprattutto azoto».

**Il vincolo di taratura** (nutrizione-spec di The Pot §4): in un anno
tipico un vaso di profilo medio concimato secondo il suo piano deve
finire l'anno con la riserva dove l'ha iniziata — né accumulo né fame.
Con `feed_fraction = intervallo fra le annaffiature / cadenza delle
concimazioni` il bilancio chiude per costruzione: la pianta mangia
quello che il piano le dà, e la riserva oscilla fra la concimazione e
la successiva scendendo più in fretta quando fa caldo e traspira di
più. `tests/test_nutrients.py` lo prova su un anno simulato.

Le fonti dei numeri sono nei commenti delle costanti; dove il numero è
una stima da tarare, lo dice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional


# =======================================================================
#  Costanti
# =======================================================================

# I tre nutrienti, nell'ordine delle etichette: N, P₂O₅, K₂O.
NUTRIENTS: tuple[str, str, str] = ("n", "p", "k")

# Milligrammi per milliequivalente, per portare i serbatoi nella scala
# della massa salina. L'azoto come nitrato (NO₃⁻: 14 mg di N per meq);
# il fosforo come P₂O₅ che in soluzione è H₂PO₄⁻ monovalente (142 g/mol
# per due P: 71 mg di P₂O₅ per meq); il potassio come K₂O (94 g/mol per
# due K⁺: 47 mg di K₂O per meq). Un 20-20-20 a 1 g/L fa così 200/14 +
# 200/71 + 200/47 ≈ 21 meq/L: la parte nutritiva dei 13 meq/L che la
# scheda tecnica misura in EC (1,3 mS/cm) è già più della massa — segno
# che i cationi ammoniacali e le forme non dissociate contano meno di
# un equivalente pieno. Si tiene la scala come ordine di grandezza; il
# `clamp_to_salts` fa il resto.
MG_PER_MEQ: Mapping[str, float] = {"n": 14.0, "p": 71.0, "k": 47.0}

# Che parte dell'acqua del vaso una concimazione rimpiazza: si concima
# quando il vaso ha bevuto la sua riserva utile, circa metà dell'acqua a
# capacità di campo (FAO-56, p ≈ 0,5). È la carica piena della riserva.
FULL_CHARGE_FRACTION = 0.5

# Il nitrato non si lega al substrato e esce col drenaggio più dei sali
# medi (che comprendono cationi trattenuti dalla CEC): un quinto in più,
# stima da tarare — l'ordine di grandezza è quello dei lisimetri in
# torba (Argo & Fisher 2002, cap. sull'azoto).
NITRATE_LEACHING_BONUS = 1.2

# Il cancello della temperatura sull'assorbimento: le radici assorbono
# poco sotto i 10 °C (l'attività dei trasportatori e la permeabilità
# delle membrane calano; Marschner, *Mineral Nutrition of Higher
# Plants*, cap. 2). Una rampa fra 8 e 12 °C, con un pavimento del 10 %
# — non zero: anche d'inverno qualcosa entra.
UPTAKE_T_GATE_LOW_C = 8.0
UPTAKE_T_GATE_HIGH_C = 12.0
UPTAKE_COLD_FLOOR = 0.1

# Nel cammino single-Kc l'ET non è divisa fra pianta e superficie: la
# traspirazione è una quota dell'ET della coltura. In pieno sviluppo il
# Ke è piccolo (FAO-56 cap. 7: E ≈ 10–20 % dell'ET con chioma piena).
TRANSPIRATION_SHARE_SINGLE_KC = 0.85

# I rilasci dei concimi secchi. Il Q10 di 2 è la regola generale della
# cinetica biologica e vale sia per i rivestiti (Osmocote: la durata
# nominale è a 21 °C e dimezza a 31 °C, scheda tecnica ICL) sia per la
# mineralizzazione degli organici (Hartz et al. 2000, riferita a 20 °C).
RELEASE_Q10 = 2.0
RELEASE_T_REF_CONTROLLED_C = 21.0
RELEASE_T_REF_ORGANIC_C = 20.0
# Sotto questo θ relativo (0 al punto di appassimento, 1 a capacità di
# campo) la mineralizzazione si ferma: i microrganismi vogliono acqua.
RELEASE_MOISTURE_FLOOR = 0.2


class ReleaseClass(Enum):
    """
    Come un concime cede i suoi sali, il vocabolario di The Pot
    (`FertilizerReleaseClass`).

      - QUICK («pronto»): tutto subito, con l'acqua in cui è sciolto.
      - GRANULAR («granulare»): un solubile dato a secco, che si scioglie
        con le annaffiature nei suoi giorni, senza altra dipendenza.
      - CONTROLLED («controllato»): il rivestito, che cede per diffusione
        attraverso la membrana: la temperatura comanda, l'acqua no.
      - ORGANIC («organico»): mineralizza per opera dei microrganismi:
        temperatura e umidità comandano tutte e due.
    """

    QUICK = "pronto"
    GRANULAR = "granulare"
    CONTROLLED = "controllato"
    ORGANIC = "organico"


# =======================================================================
#  Le quantità
# =======================================================================

@dataclass(frozen=True)
class NutrientAmounts:
    """Tre quantità di N, P₂O₅ e K₂O, in milligrammi (o in mg/L: dipende
    da chi le usa). Immutabile: le operazioni tornano una copia."""

    n_mg: float = 0.0
    p_mg: float = 0.0
    k_mg: float = 0.0

    def __post_init__(self) -> None:
        for name in ("n_mg", "p_mg", "k_mg"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"NutrientAmounts.{name}={value} non può essere negativo.")

    @property
    def as_tuple(self) -> tuple[float, float, float]:
        return (self.n_mg, self.p_mg, self.k_mg)

    def get(self, nutrient: str) -> float:
        return {"n": self.n_mg, "p": self.p_mg, "k": self.k_mg}[nutrient]

    @property
    def total_mg(self) -> float:
        return self.n_mg + self.p_mg + self.k_mg

    @property
    def total_meq(self) -> float:
        """La somma dei tre serbatoi nella scala della massa salina."""
        return sum(self.get(x) / MG_PER_MEQ[x] for x in NUTRIENTS)

    def scaled(self, factor: float) -> "NutrientAmounts":
        return NutrientAmounts(self.n_mg * factor, self.p_mg * factor, self.k_mg * factor)

    def plus(self, other: "NutrientAmounts") -> "NutrientAmounts":
        return NutrientAmounts(
            self.n_mg + other.n_mg, self.p_mg + other.p_mg, self.k_mg + other.k_mg,
        )

    def minus(self, other: "NutrientAmounts") -> "NutrientAmounts":
        """La differenza, mai sotto zero: un serbatoio non va in debito."""
        return NutrientAmounts(
            max(0.0, self.n_mg - other.n_mg),
            max(0.0, self.p_mg - other.p_mg),
            max(0.0, self.k_mg - other.k_mg),
        )

    @classmethod
    def from_tuple(cls, values: tuple[float, float, float]) -> "NutrientAmounts":
        return cls(float(values[0]), float(values[1]), float(values[2]))


ZERO = NutrientAmounts()


# =======================================================================
#  L'assorbimento
# =======================================================================

def temperature_gate(t_mean_c: Optional[float]) -> float:
    """
    Quanto le radici assorbono a questa temperatura, 0–1: 1 sopra i
    12 °C, il pavimento sotto gli 8, la rampa in mezzo. Senza una
    temperatura (None) il cancello è aperto: non si inventa il freddo.
    """
    if t_mean_c is None:
        return 1.0
    if t_mean_c >= UPTAKE_T_GATE_HIGH_C:
        return 1.0
    if t_mean_c <= UPTAKE_T_GATE_LOW_C:
        return UPTAKE_COLD_FLOOR
    span = UPTAKE_T_GATE_HIGH_C - UPTAKE_T_GATE_LOW_C
    return UPTAKE_COLD_FLOOR + (1.0 - UPTAKE_COLD_FLOOR) * (t_mean_c - UPTAKE_T_GATE_LOW_C) / span


def daily_uptake(
    transpiration_l: float,
    targets_mg_per_l: NutrientAmounts,
    *,
    feed_fraction: float = 1.0,
    t_mean_c: Optional[float] = None,
    available: Optional[NutrientAmounts] = None,
) -> NutrientAmounts:
    """
    Quanto la pianta mangia oggi: il flusso di massa della traspirazione
    alla concentrazione del piano, per la frazione di alimentazione e il
    cancello della temperatura — e mai più di quello che c'è.

    Parametri
    ---------
    transpiration_l : float
        La traspirazione della pianta del giorno, in litri (mm × m²):
        solo la pianta, non l'evaporazione della superficie.
    targets_mg_per_l : NutrientAmounts
        La concentrazione che il piano vuole oggi per N, P₂O₅, K₂O.
    feed_fraction : float
        Che parte del flusso è concime (vedi in testa al modulo).
    t_mean_c : float, opzionale
        La temperatura media del giorno, per il cancello.
    available : NutrientAmounts, opzionale
        Quello che c'è nei serbatoi: l'assorbimento non lo supera.
    """
    if transpiration_l < 0:
        raise ValueError(f"transpiration_l={transpiration_l} non può essere negativa.")
    if not 0.0 <= feed_fraction <= 1.0:
        raise ValueError(f"feed_fraction={feed_fraction} deve stare fra 0 e 1.")
    factor = transpiration_l * feed_fraction * temperature_gate(t_mean_c)
    wanted = targets_mg_per_l.scaled(factor)
    if available is None:
        return wanted
    return NutrientAmounts(
        min(wanted.n_mg, available.n_mg),
        min(wanted.p_mg, available.p_mg),
        min(wanted.k_mg, available.k_mg),
    )


# =======================================================================
#  Il drenaggio e la coerenza coi sali
# =======================================================================

def leached(pools: NutrientAmounts, drained_fraction: float) -> NutrientAmounts:
    """
    Quello che il drenaggio porta via dai serbatoi, data la frazione
    della massa salina uscita dal foro; il nitrato un po' di più.
    """
    if not 0.0 <= drained_fraction <= 1.0:
        raise ValueError(f"drained_fraction={drained_fraction} deve stare fra 0 e 1.")
    nitrate = min(1.0, drained_fraction * NITRATE_LEACHING_BONUS)
    return NutrientAmounts(
        pools.n_mg * nitrate, pools.p_mg * drained_fraction, pools.k_mg * drained_fraction,
    )


def clamp_to_salts(pools: NutrientAmounts, salt_mass_meq: float) -> NutrientAmounts:
    """
    I serbatoi non possono valere più della massa salina: se la loro
    somma in milliequivalenti la supera, si ristringono in proporzione.
    Succede quando lo stato dei sali viene corretto dal basso (una
    lettura di sonda, una partenza stimata) e i serbatoi no.
    """
    total = pools.total_meq
    if total <= 0 or total <= salt_mass_meq:
        return pools
    if salt_mass_meq <= 0:
        return ZERO
    return pools.scaled(salt_mass_meq / total)


# =======================================================================
#  La riserva
# =======================================================================

@dataclass(frozen=True)
class NutrientReserve:
    """
    La riserva nutritiva del vaso: la frazione della carica piena
    occupata dal serbatoio più vuoto fra quelli che il piano chiede
    (`fraction`, 0 in su: sopra 1 c'è più del bersaglio), quale sia
    (`limiting`), e la frazione di ognuno (`per_nutrient`, solo i
    nutrienti col bersaglio sopra zero).
    """

    fraction: float
    limiting: str
    per_nutrient: Mapping[str, float]


def full_charge_mg(targets_mg_per_l: NutrientAmounts, fc_water_l: float) -> NutrientAmounts:
    """La carica piena: l'acqua del vaso a capacità di campo alla
    concentrazione del piano, per la frazione che una concimazione
    rimpiazza."""
    if fc_water_l < 0:
        raise ValueError(f"fc_water_l={fc_water_l} non può essere negativo.")
    return targets_mg_per_l.scaled(fc_water_l * FULL_CHARGE_FRACTION)


def reserve(
    pools: NutrientAmounts,
    targets_mg_per_l: NutrientAmounts,
    fc_water_l: float,
) -> Optional[NutrientReserve]:
    """
    La riserva rispetto al piano di oggi, o None se il piano oggi non
    chiede niente (riposo): senza un bersaglio non c'è una mancanza.
    """
    charge = full_charge_mg(targets_mg_per_l, fc_water_l)
    per_nutrient = {
        x: pools.get(x) / charge.get(x) for x in NUTRIENTS if charge.get(x) > 0
    }
    if not per_nutrient:
        return None
    limiting = min(per_nutrient, key=lambda x: per_nutrient[x])
    return NutrientReserve(
        fraction=per_nutrient[limiting], limiting=limiting, per_nutrient=per_nutrient,
    )


# =======================================================================
#  I rilasci dei concimi secchi
# =======================================================================

def daily_release_fraction(
    release_class: ReleaseClass,
    nominal_days: int,
    *,
    t_mean_c: Optional[float] = None,
    theta_relative: Optional[float] = None,
) -> float:
    """
    Che frazione del totale un concime secco cede oggi.

    Il pronto cede tutto il primo giorno. Gli altri cedono `1 /
    nominal_days` al giorno nelle condizioni di riferimento — è la
    durata dell'etichetta — e poi: il rivestito segue la temperatura
    (Q10 = 2 intorno a 21 °C); l'organico segue la temperatura (intorno
    a 20 °C) e l'umidità del substrato, e sotto `RELEASE_MOISTURE_FLOOR`
    si ferma; il granulare solubile segue solo l'umidità, perché senza
    acqua non si scioglie. Senza temperatura o umidità (None) si resta
    al riferimento. Il chiamante somma le frazioni e smette quando
    arrivano a 1: un rivestito in un'estate calda finisce prima della
    sua etichetta, in un inverno dopo.
    """
    if nominal_days <= 0:
        raise ValueError(f"nominal_days={nominal_days} deve essere positivo.")
    if release_class is ReleaseClass.QUICK:
        return 1.0
    base = 1.0 / nominal_days
    moisture = 1.0
    if theta_relative is not None:
        theta_relative = min(1.0, max(0.0, theta_relative))
        if theta_relative <= RELEASE_MOISTURE_FLOOR:
            moisture = 0.0
        else:
            moisture = (theta_relative - RELEASE_MOISTURE_FLOOR) / (1.0 - RELEASE_MOISTURE_FLOOR)
    if release_class is ReleaseClass.GRANULAR:
        return base * moisture
    reference = (
        RELEASE_T_REF_CONTROLLED_C
        if release_class is ReleaseClass.CONTROLLED
        else RELEASE_T_REF_ORGANIC_C
    )
    thermal = 1.0 if t_mean_c is None else RELEASE_Q10 ** ((t_mean_c - reference) / 10.0)
    if release_class is ReleaseClass.CONTROLLED:
        return base * thermal
    return base * thermal * moisture
