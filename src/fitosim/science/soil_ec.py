"""
La conducibilità letta nel substrato, e quella della soluzione.

Una sonda nel vaso (la WH52 di Ecowitt, un sensore TDR o capacitivo con
l'elettrodo per l'EC) misura la **conducibilità apparente** del substrato,
σ_b: quella dell'insieme di solido, aria e acqua che le sta intorno. Le
soglie di fitosim (`Species.ec_optimal_*`) e l'EC che il bilancio dei
sali tiene (`Pot.ec_substrate_mscm`) sono invece la conducibilità della
**soluzione interstiziale**, σ_p — quella che si misura estraendola
(PourThru, SME) e che le radici sentono. Le due stanno fra loro come
l'acqua sta nel vaso: a parità di sali, un substrato secco legge poco
perché la corrente non trova acqua in cui passare; uno a capacità di
campo legge di più. Confondere le due scale vorrebbe dire dire «pochi
sali» a un vaso asciutto e «troppi» a uno appena bagnato.

**Il modello di Hilhorst** (2000, *A pore water conductivity sensor*,
Soil Sci. Soc. Am. J. 64) lega le due grandezze attraverso la
permittività del substrato, che cresce con l'acqua:

    σ_p = ε_p · σ_b / (ε_b − ε_σb=0)

dove ε_p è la permittività dell'acqua (80,3 a 20 °C, meno 0,37 per grado
in più), ε_b quella apparente del substrato, ε_σb=0 l'intercetta — la
permittività a conducibilità zero, 4,1 nei suoli di Hilhorst; nei
substrati organici sta più su (i torbosi 6–7), e il fattore per vaso ne
tiene conto. La permittività apparente da una sonda che dà solo l'acqua
si ricava con **Topp** (1980), la relazione empirica fra ε_b e θ che i
sensori usano nell'altro verso:

    θ = −5,3·10⁻² + 2,92·10⁻² ε_b − 5,5·10⁻⁴ ε_b² + 4,3·10⁻⁶ ε_b³

invertita per bisezione. È la scala giusta ma non il numero giusto per
ogni substrato: **un fattore per vaso**, tarato a capacità di campo —
dopo un'annaffiata a fondo, quando l'EC della soluzione è quella della
vasca che si è appena versata — chiude il conto (`factor_at_field_capacity`).
Senza taratura il fattore vale uno e il modello di Hilhorst è quello
che è: una stima dichiarata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# La permittività dell'acqua a 20 °C e la sua pendenza con la temperatura
# (Hilhorst 2000, eq. 3: ε_p = 80,3 − 0,37 (T − 20)).
WATER_PERMITTIVITY_20C = 80.3
WATER_PERMITTIVITY_SLOPE_PER_C = 0.37
# L'intercetta ε_σb=0 di Hilhorst per i suoli: la permittività apparente
# «a conducibilità zero». Nei substrati organici sta più su, e lo assorbe
# il fattore per vaso.
EPSILON_OFFSET = 4.1
# I coefficienti di Topp (1980), θ in funzione di ε_b.
TOPP = (-5.3e-2, 2.92e-2, -5.5e-4, 4.3e-6)
# La permittività apparente sta fra quella dell'aria e quella dell'acqua.
PERMITTIVITY_MIN = 1.0
PERMITTIVITY_MAX = 80.0


def theta_from_permittivity(epsilon: float) -> float:
    """Topp (1980): il contenuto idrico dalla permittività apparente."""
    a, b, c, d = TOPP
    return a + b * epsilon + c * epsilon**2 + d * epsilon**3


def permittivity_from_theta(theta: float) -> float:
    """
    Topp al contrario: la permittività apparente da θ, per bisezione (la
    cubica è crescente nell'intervallo dei sensori). θ sotto lo zero di
    Topp (≈ 0,0 a ε = 1,8) dà la permittività minima; sopra il massimo
    dà quella dell'acqua.
    """
    if theta < 0:
        raise ValueError(f"theta={theta} non può essere negativo.")
    lo, hi = PERMITTIVITY_MIN, PERMITTIVITY_MAX
    if theta <= theta_from_permittivity(lo):
        return lo
    if theta >= theta_from_permittivity(hi):
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if theta_from_permittivity(mid) < theta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def water_permittivity(temperature_c: float) -> float:
    return WATER_PERMITTIVITY_20C - WATER_PERMITTIVITY_SLOPE_PER_C * (temperature_c - 20.0)


def pore_water_ec(
    bulk_ec_mscm: float,
    theta: float,
    *,
    temperature_c: float = 25.0,
    factor: float = 1.0,
    epsilon_offset: float = EPSILON_OFFSET,
) -> Optional[float]:
    """
    L'EC della soluzione interstiziale (mS/cm) dall'EC apparente letta
    dalla sonda e dal contenuto idrico, con Hilhorst su Topp, per il
    fattore del vaso. None quando il substrato è troppo asciutto perché
    la lettura dica qualcosa (ε_b sotto l'intercetta): lì la corrente
    non passa, e dividere per zero non è una misura.
    """
    if bulk_ec_mscm < 0:
        raise ValueError(f"bulk_ec_mscm={bulk_ec_mscm} non può essere negativa.")
    if factor <= 0:
        raise ValueError(f"factor={factor} deve essere positivo.")
    epsilon_b = permittivity_from_theta(theta)
    if epsilon_b - epsilon_offset <= 0.5:
        return None
    return water_permittivity(temperature_c) * bulk_ec_mscm / (epsilon_b - epsilon_offset) * factor


def factor_at_field_capacity(
    *,
    bulk_ec_mscm: float,
    theta: float,
    solution_ec_mscm: float,
    temperature_c: float = 25.0,
    epsilon_offset: float = EPSILON_OFFSET,
) -> Optional[float]:
    """
    Il fattore che fa combaciare Hilhorst con quello che si sa: a
    capacità di campo, subito dopo un'annaffiata a fondo, la soluzione
    del vaso è quella della vasca appena versata (o quella che il bilancio
    dice), e la sonda legge σ_b. Torna `solution / hilhorst(σ_b, θ)`, o
    None se la lettura non dice niente.
    """
    if solution_ec_mscm <= 0:
        raise ValueError(f"solution_ec_mscm={solution_ec_mscm} deve essere positiva.")
    stimata = pore_water_ec(
        bulk_ec_mscm, theta, temperature_c=temperature_c, epsilon_offset=epsilon_offset
    )
    if stimata is None or stimata <= 0:
        return None
    return solution_ec_mscm / stimata


@dataclass(frozen=True)
class EcUpdateResult:
    """
    Quello che una lettura EC ha fatto al vaso: l'EC della soluzione che
    il modello prevedeva e quella che la sonda dice (dopo Hilhorst e il
    fattore), la massa salina prima e dopo, e il rapporto con cui i
    serbatoi nutritivi sono stati scalati.
    """

    observed_bulk_ec_mscm: float
    theta: float
    predicted_solution_ec_mscm: float
    observed_solution_ec_mscm: float
    salt_mass_before_meq: float
    salt_mass_after_meq: float
    ratio: float

    @property
    def discrepancy_mscm(self) -> float:
        """Osservata meno prevista: positiva se c'erano più sali di quanto il
        modello pensasse."""
        return self.observed_solution_ec_mscm - self.predicted_solution_ec_mscm
