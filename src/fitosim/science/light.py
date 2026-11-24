"""
La luce utile alla pianta: l'integrale giornaliero di luce (DLI).

Il resto della libreria tratta la luce come **energia**: la radiazione
netta che fa evaporare l'acqua (`science/et0.py`), il fattore di
esposizione del vaso (`science/pot_physics.py`), la radiazione che entra
in una stanza (`science/indoor.py`). Qui la luce è quella che la pianta
**usa per crescere**: i fotoni fra 400 e 700 nm (PAR) che arrivano in un
giorno su un metro quadro, in moli — il *daily light integral*, la
grandezza con cui l'orticoltura dice quanta luce vuole una coltura
(Torres & Lopez, *Measuring Daily Light Integral in a Greenhouse*,
Purdue Extension HO-238-W).

Tre cose, tutte funzioni pure di numeri:

  1. **La conversione** dalla radiazione globale del piranometro
     (MJ/m²/giorno) al DLI (mol/m²/giorno): `dli_from_shortwave`.

  2. **Il DLI al vaso**: il piranometro misura il cielo aperto, e al vaso
     ne arriva una frazione — quella di una stanza
     (`science/indoor.light_fraction`) o quella misurata sul posto. Un
     sensore di luce al vaso la misura direttamente, in lux:
     `dli_from_illuminance` e `shortwave_from_illuminance` (2026-11-24,
     docs/proposta_luce_misurata.md).
     All'aperto una frazione per esposizione **non c'è**: i fattori di
     `pot_physics` (0,70 e 0,45) sono fattori di traspirazione, non di
     luce, e qui non si inventano. Chi ha la frazione la passa
     (`dli_at_pot`).

  3. **Il confronto con quello che la specie vuole**: un
     `LightRequirement` (il DLI «buono», e se si conoscono il «minimo
     accettabile» e l'«alto») e il giudizio `light_sufficiency`. Le
     quattro classi di coltura di Purdue (`LightClass`) dicono in che
     fascia cade un DLI.

Chi usa questi numeri sui bilanci è `science/nutrients.light_factor`: la
luce sull'assorbimento dei nutrienti. Sull'acqua il DLI non agisce: lì
la luce c'è già, come energia.

Decisa il 24 novembre 2026 (`docs/proposta_luce.md`, passi L1 e L2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

# =======================================================================
#  La conversione
# =======================================================================

# Che parte della radiazione globale è PAR, e quanti micromoli di fotoni
# porta un joule di PAR solare. Sono i due numeri delle mappe DLI degli
# Stati Uniti (Logan & Faust, ASHS 2017; Faust & Logan 2018, HortScience
# 53:1250–1257): 0,007265 mol di PAR per Wh di radiazione globale, cioè
# il 45 % in banda PAR a 4,48 µmol/J. Il prodotto, 2,02 mol per MJ, è la
# conversione di tutto il modulo.
PAR_FRACTION_OF_SHORTWAVE = 0.45
PAR_UMOL_PER_JOULE = 4.48
PAR_MOL_PER_MJ = PAR_FRACTION_OF_SHORTWAVE * PAR_UMOL_PER_JOULE


def dli_from_shortwave(radiation_mj_m2_day: float) -> float:
    """
    Il DLI, in mol di fotoni PAR per m² al giorno, dalla radiazione
    globale del giorno in MJ/m² — quella del piranometro o di
    Open-Meteo (`shortwave_radiation_sum`).
    """
    if radiation_mj_m2_day < 0:
        raise ValueError(
            f"radiation_mj_m2_day={radiation_mj_m2_day} non può essere negativa."
        )
    return radiation_mj_m2_day * PAR_MOL_PER_MJ


# Quanti lux fa un micromole di fotoni PAR al metro quadro al secondo,
# per la **luce del giorno**. Purdue HO-238-W, tabella 1: per la luce
# solare 0,20 µmol/m²/s per foot-candle, e un foot-candle sono 10,764
# lux. Con le due costanti qui sopra dà 108,5 lux per W/m² di radiazione
# globale: è l'efficacia luminosa che Littlefair misura per la luce del
# giorno (105 lm/W in rassegna, 107–109 in un anno a Garston; Lighting
# Res. Technol. 17:162–182, 1985).
#
# Il numero dipende dalla sorgente: il lux pesa la luce come l'occhio, i
# fotoni no. Sotto lampade al sodio sono 82,8 lux per µmol (la stessa
# tabella: 0,13), sotto un LED bianco circa 68. Chi misura sotto una
# lampada passa il suo fattore.
LUX_PER_UMOL_DAYLIGHT = 53.8


def dli_from_illuminance(
    lux_hours: float, lux_per_umol: float = LUX_PER_UMOL_DAYLIGHT,
) -> float:
    """
    Il DLI, in mol di fotoni PAR per m² al giorno, dall'integrale
    giornaliero di illuminamento in lux·ora — quello che dà un sensore
    di luce ambiente lasciato a campionare per un giorno. Per la luce
    del giorno: 1 000 lux·ora sono 0,067 mol/m².
    """
    if lux_hours < 0:
        raise ValueError(f"lux_hours={lux_hours} non può essere negativo.")
    if lux_per_umol <= 0:
        raise ValueError(f"lux_per_umol={lux_per_umol} deve essere positivo.")
    return lux_hours * 3600.0 / lux_per_umol / 1e6


def shortwave_from_illuminance(
    lux_hours: float, lux_per_umol: float = LUX_PER_UMOL_DAYLIGHT,
) -> float:
    """
    La radiazione globale del giorno, in MJ/m², dall'integrale di
    illuminamento in lux·ora: il DLI riportato all'energia con la stessa
    conversione di `dli_from_shortwave`, al contrario. Per la luce del
    giorno: 1 000 lux·ora sono 0,033 MJ/m².

    È la conversione più fragile delle due. Vale per la luce del giorno
    com'è fuori; dietro un vetro selettivo, che lascia passare il
    visibile e ferma il vicino infrarosso, ogni lux porta meno energia e
    questa stima è troppo alta (fino a due terzi). Sotto una lampada non
    vale: lì l'energia non segue la quota PAR della radiazione solare.
    """
    return dli_from_illuminance(lux_hours, lux_per_umol) / PAR_MOL_PER_MJ


def dli_at_pot(open_sky_radiation_mj_m2_day: float, light_fraction: float) -> float:
    """
    Il DLI che arriva al vaso: quello del cielo aperto per la frazione
    di luce che il posto lascia passare (0–1). La frazione è di chi
    chiama: quella di una stanza (`indoor.light_fraction`) o una misura
    fatta al vaso e a cielo aperto alla stessa ora.
    """
    if not 0.0 <= light_fraction <= 1.0:
        raise ValueError(f"light_fraction={light_fraction} deve stare fra 0 e 1.")
    return dli_from_shortwave(open_sky_radiation_mj_m2_day) * light_fraction


# =======================================================================
#  Le classi di coltura
# =======================================================================

class LightClass(Enum):
    """
    Le quattro classi di coltura per fabbisogno di luce (Purdue
    HO-238-W): luce bassa, media, alta, molto alta.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


# Il DLI che ogni classe richiede, in mol/m²/giorno, come lo scrive
# Purdue HO-238-W: «crops with a DLI requirement of 3 to 6 are
# considered low-light crops, 6 to 12 medium-light, 12 to 18 high-light,
# and those requiring more than 18 very high-light». L'estremo alto
# dell'ultima classe non c'è.
LIGHT_CLASS_DLI_RANGE: Mapping[LightClass, tuple[float, float | None]] = {
    LightClass.LOW: (3.0, 6.0),
    LightClass.MEDIUM: (6.0, 12.0),
    LightClass.HIGH: (12.0, 18.0),
    LightClass.VERY_HIGH: (18.0, None),
}


def light_class_of(dli_mol_m2_day: float) -> LightClass | None:
    """
    In che classe di coltura cade questo DLI: «la luce di questo posto è
    da coltura di luce media». None sotto i 3 mol/m²/giorno, dove
    nessuna classe ha il suo fabbisogno.
    """
    if dli_mol_m2_day < 0:
        raise ValueError(f"dli_mol_m2_day={dli_mol_m2_day} non può essere negativo.")
    found: LightClass | None = None
    for light_class, (low, _high) in LIGHT_CLASS_DLI_RANGE.items():
        if dli_mol_m2_day >= low:
            found = light_class
    return found


# =======================================================================
#  Quello che la specie vuole, e il giudizio
# =======================================================================

@dataclass(frozen=True)
class LightRequirement:
    """
    La luce che una specie vuole, in DLI (mol/m²/giorno). `dli_good` è
    quello della «buona qualità»: da lì in su la luce non limita la
    crescita. `dli_minimum` è la «qualità minima accettabile» e
    `dli_high` l'«alta qualità», quando si conoscono (sono le tre
    colonne della tabella 2 di Purdue HO-238-W, da Faust, *Ball
    RedBook*: per lo Spathiphyllum 2 / 4 / 6, per il pomodoro
    10–12 / 14–20 / 22).
    """

    dli_good: float
    dli_minimum: float | None = None
    dli_high: float | None = None

    def __post_init__(self) -> None:
        if self.dli_good <= 0:
            raise ValueError(f"dli_good={self.dli_good} deve essere positivo.")
        if self.dli_minimum is not None and not 0 < self.dli_minimum <= self.dli_good:
            raise ValueError(
                f"dli_minimum={self.dli_minimum} deve stare fra 0 e dli_good="
                f"{self.dli_good}."
            )
        if self.dli_high is not None and self.dli_high < self.dli_good:
            raise ValueError(
                f"dli_high={self.dli_high} non può stare sotto dli_good={self.dli_good}."
            )


class LightSufficiency(Enum):
    """Quanta luce riceve il vaso rispetto a quella che la specie vuole."""

    BELOW_MINIMUM = "below_minimum"
    """Sotto la qualità minima accettabile: la pianta sopravvive, non cresce bene."""

    BELOW_GOOD = "below_good"
    """Sotto il «buono»: la luce limita la crescita. È anche il giudizio
    di un DLI basso quando il minimo della specie non si conosce."""

    GOOD = "good"
    """Al «buono» o sopra: la luce non limita la crescita."""

    HIGH = "high"
    """All'«alto» o sopra, quando la specie lo dichiara."""


def light_sufficiency(
    dli_mol_m2_day: float, requirement: LightRequirement,
) -> LightSufficiency:
    """Il giudizio della luce al vaso contro il fabbisogno della specie."""
    if dli_mol_m2_day < 0:
        raise ValueError(f"dli_mol_m2_day={dli_mol_m2_day} non può essere negativo.")
    if requirement.dli_high is not None and dli_mol_m2_day >= requirement.dli_high:
        return LightSufficiency.HIGH
    if dli_mol_m2_day >= requirement.dli_good:
        return LightSufficiency.GOOD
    if requirement.dli_minimum is not None and dli_mol_m2_day < requirement.dli_minimum:
        return LightSufficiency.BELOW_MINIMUM
    return LightSufficiency.BELOW_GOOD
