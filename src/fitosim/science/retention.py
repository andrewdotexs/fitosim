"""
La curva di ritenzione e la capacità di contenitore: quanta acqua tiene
una colonna di substrato alta h, a drenaggio finito.

Il fenomeno
-----------

Un vaso «a capacità di campo» non è bagnato uguale dappertutto. Quando
dai fori non esce più niente la colonna è in equilibrio idrostatico con
l'acqua che sta sul fondo: lì la tensione è zero — una falda sospesa, il
substrato saturo —, e salendo di un centimetro la tensione cresce di un
centimetro d'acqua. A ogni quota z il substrato trattiene la θ che la sua
**curva di ritenzione** gli assegna a quella tensione, ψ = −z. L'acqua
della colonna è la media di quella curva fra zero e h:

    θ_CC(h) = (1/h) · ∫₀ʰ θ(ψ = −z) dz

È la **capacità di contenitore** (container capacity: Bilderback &
Fonteno 1987; Milks, Fonteno & Larson 1989), e dipende dall'altezza
della colonna e non solo dal materiale: una ciotola da bonsai, una
cassetta da 13 cm o il terriccio sopra uno strato drenante tengono per
litro più acqua e meno aria di un vaso alto 30 cm riempito con lo stesso
sacco. La tensione media di una colonna alta h è h/2: a 20 cm fa 10 cm
d'acqua, −1 kPa, il punto che De Boodt & Verdonck (1972) hanno preso come
capacità di contenitore del vaso tipico e che il catalogo di The Pot
chiama θ_FC. Sotto i venti centimetri il vaso sta più bagnato di quel
numero, sopra più asciutto.

Cosa fa oggi il modello
-----------------------

`Pot.fc_mm` è θ_FC × profondità: la θ del substrato a −1 kPa, la stessa
per ogni altezza. Per una cassetta da 13 cm sottostima l'acqua dopo
un'annaffiatura — dice «sete» un po' prima del vero, mentre il fondo è
ancora zuppo — e per un vaso da 30 la sovrastima. Lo strato drenante entra
solo come profondità in meno (`active_depth_fraction`): il conto dei
litri è giusto, ma il terriccio che resta ha il θ_FC di una colonna di
venti centimetri.

Cosa questo modulo decide, e cosa no
------------------------------------

Decide la **matematica** (2026-10-21, «la colonna, solo la matematica»):
l'equilibrio idrostatico col fondo a tensione zero, la media sulla
colonna integrata con Simpson, due forme della curva — van Genuchten
(1980), che Milks, Fonteno & Larson (1989, parte II e III) hanno mostrato
adatta ai substrati orticoli e che da due punti del catalogo si ricava
quando si conoscono θ a saturazione e la residua, e una curva per punti
quando si misura — e lo spazio d'aria, che è il complemento.

Non decide tre cose, che aspettano i dati:

- **la forma della curva per il catalogo**: le 28 schede hanno θ a −1 e
  −10 kPa; per la colonna serve la θ a saturazione (la porosità totale, da
  densità apparente e densità delle particelle, o misurata) e, per la
  coda, il terzo punto a −1500 kPa rimandato con A2;
- **l'ingresso nel vaso**: `Pot.fc_mm` resta θ_FC × profondità finché la
  differenza non è misurata;
- **la verifica**: la θ_FC assoluta a due altezze non la dà la sonda, la
  cui taratura mappa la lettura bagnata sulla θ_FC del catalogo per
  costruzione. La misura che serve è l'acqua per litro di terriccio a
  drenaggio finito, cioè una pesata (il livello 1 del manuale di
  calibrazione, con la bilancia).

Le ipotesi, scritte
-------------------

Colonna omogenea; drenaggio libero dal fondo, quindi tensione zero alla
base — con uno **strato drenante** la barriera capillare porta la falda
sul confine, e h è l'altezza del terriccio sopra lo strato, quella che
The Pot conosce (C.9-bis); un **sottovaso** pieno sposta la falda sopra il
fondo e la colonna sta più bagnata, e non è modellato qui; nessuna
isteresi (la curva è quella di drenaggio, che è il verso giusto per la
capacità di contenitore); quote e tensioni in centimetri d'acqua, 1 kPa =
10,197 cm.

Fonti
-----

- De Boodt, M. & Verdonck, O. (1972). The physical properties of the
  substrates in horticulture. Acta Horticulturae 26, 37–44.
- Bilderback, T.E. & Fonteno, W.C. (1987). Effects of container geometry
  and media physical properties on air and water volumes in containers.
  J. Environ. Hort. 5(4), 180–182.
- Milks, R.R., Fonteno, W.C. & Larson, R.A. (1989). Hydrology of
  horticultural substrates: I. Mathematical models for moisture
  characteristics of horticultural container media; II. Predicting
  physical properties of media in containers; III. Predicting air and
  water content of limited and unlimited volume containers.
  J. Amer. Soc. Hort. Sci. 114(1), 48–61.
- van Genuchten, M.Th. (1980). A closed-form equation for predicting the
  hydraulic conductivity of unsaturated soils. Soil Sci. Soc. Am. J. 44,
  892–898.
- Raviv, M. & Lieth, J.H. (2008). Soilless Culture: Theory and Practice,
  cap. 3 (Wallach, R.: Physical characteristics of soilless media).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

# Un kilopascal è 10,197 cm di colonna d'acqua (ρ = 1000 kg/m³, g = 9,80665
# m/s²): le tensioni del catalogo, −1 e −10 kPa, sono 10,2 e 102 cm.
CM_H2O_PER_KPA = 10.1972

# Quanti intervalli di Simpson sulla colonna: duecento su venti centimetri
# è un millimetro, e l'errore del metodo è molto sotto la curva.
DEFAULT_INTERVALS = 200


def tension_cm_from_kpa(kpa: float) -> float:
    """Una tensione (o un potenziale matriciale in valore assoluto) da kPa
    a centimetri di colonna d'acqua."""
    if kpa < 0:
        raise ValueError(f"La tensione va data in valore assoluto, non {kpa} kPa.")
    return kpa * CM_H2O_PER_KPA


def kpa_from_tension_cm(tension_cm: float) -> float:
    if tension_cm < 0:
        raise ValueError(f"La tensione va data in valore assoluto, non {tension_cm} cm.")
    return tension_cm / CM_H2O_PER_KPA


class RetentionCurve(Protocol):
    """Una curva di ritenzione: la θ a una tensione, e la θ a saturazione."""

    @property
    def theta_s(self) -> float: ...

    def theta_at(self, tension_cm: float) -> float: ...


def _log_expm1(x: float) -> float:
    """ln(eˣ − 1), stabile anche per x grande (dove eˣ trabocca)."""
    if x > 30.0:
        return x + math.log1p(-math.exp(-x))
    return math.log(math.expm1(x))


@dataclass(frozen=True)
class VanGenuchten:
    """
    La curva di van Genuchten (1980):

        θ(ψ) = θ_r + (θ_s − θ_r) / [1 + (α·|ψ|)ⁿ]^m,   m = 1 − 1/n

    con |ψ| in centimetri d'acqua e α in 1/cm. θ_s è la θ a saturazione (la
    porosità totale, se tutta si riempie), θ_r la residua che non drena
    più; α è l'inverso della tensione a cui la curva comincia a scendere
    — l'ingresso d'aria, grosso modo —, n quanto scende ripida. Per i
    substrati orticoli Milks, Fonteno & Larson (1989) la trovano adatta
    fra zero e un metro di tensione, che è tutto quello che una colonna
    da vaso vede.
    """

    theta_r: float
    theta_s: float
    alpha_per_cm: float
    n: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.theta_r < self.theta_s <= 1.0:
            raise ValueError(
                f"VanGenuchten: serve 0 ≤ θ_r ({self.theta_r}) < θ_s ({self.theta_s}) ≤ 1."
            )
        if self.alpha_per_cm <= 0.0:
            raise ValueError(f"VanGenuchten: α deve essere positivo, non {self.alpha_per_cm}.")
        if self.n <= 1.0:
            raise ValueError(f"VanGenuchten: n deve superare 1, non {self.n} (m = 1 − 1/n).")

    @property
    def m(self) -> float:
        return 1.0 - 1.0 / self.n

    def theta_at(self, tension_cm: float) -> float:
        if tension_cm < 0.0:
            raise ValueError(f"La tensione va data in valore assoluto, non {tension_cm} cm.")
        if tension_cm == 0.0:
            return self.theta_s
        se = (1.0 + (self.alpha_per_cm * tension_cm) ** self.n) ** (-self.m)
        return self.theta_r + (self.theta_s - self.theta_r) * se

    def tension_at(self, theta: float) -> float:
        """La tensione, in cm, a cui la curva vale `theta`: zero a
        saturazione e oltre, infinito alla residua e sotto."""
        if theta >= self.theta_s:
            return 0.0
        if theta <= self.theta_r:
            return math.inf
        se = (theta - self.theta_r) / (self.theta_s - self.theta_r)
        return (se ** (-1.0 / self.m) - 1.0) ** (1.0 / self.n) / self.alpha_per_cm

    @classmethod
    def from_points(
        cls,
        *,
        theta_s: float,
        theta_r: float,
        wet: tuple[float, float],
        dry: tuple[float, float],
        n_max: float = 50.0,
    ) -> VanGenuchten:
        """
        La curva che passa per due punti (tensione in cm, θ), note la θ a
        saturazione e la residua: due incognite, α e n, due equazioni.
        Eliminato α, n è lo zero di una funzione monotona di cui si fa la
        bisezione; α viene poi dal punto bagnato. È la strada per il
        catalogo di The Pot, che di ogni componente ha θ a −1 e −10 kPa
        (`from_catalog`), quando si saprà θ_s.
        """
        (t_wet, theta_wet), (t_dry, theta_dry) = wet, dry
        if not 0.0 < t_wet < t_dry:
            raise ValueError(f"Le tensioni vanno in ordine: 0 < {t_wet} < {t_dry} cm.")
        if not theta_r < theta_dry < theta_wet < theta_s:
            raise ValueError(
                "I due punti devono stare fra la residua e la saturazione, in ordine: "
                f"θ_r {theta_r} < θ({t_dry} cm) {theta_dry} < θ({t_wet} cm) {theta_wet} < θ_s {theta_s}."
            )
        se_wet = (theta_wet - theta_r) / (theta_s - theta_r)
        se_dry = (theta_dry - theta_r) / (theta_s - theta_r)
        ln_ratio = math.log(t_wet / t_dry)  # negativo

        def residuo(n: float) -> float:
            m = 1.0 - 1.0 / n
            l_wet = _log_expm1(-math.log(se_wet) / m)
            l_dry = _log_expm1(-math.log(se_dry) / m)
            return (l_wet - l_dry) - n * ln_ratio

        lo, hi = 1.0 + 1e-6, n_max
        if residuo(hi) < 0.0:
            raise ValueError("I due punti non stanno su una curva di van Genuchten con n ≤ n_max.")
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if residuo(mid) < 0.0:
                lo = mid
            else:
                hi = mid
        n = 0.5 * (lo + hi)
        m = 1.0 - 1.0 / n
        alpha = math.exp(_log_expm1(-math.log(se_wet) / m) / n) / t_wet
        return cls(theta_r=theta_r, theta_s=theta_s, alpha_per_cm=alpha, n=n)

    @classmethod
    def from_catalog(
        cls,
        theta_fc_1kpa: float,
        theta_pwp_10kpa: float,
        *,
        theta_s: float,
        theta_r: float = 0.0,
    ) -> VanGenuchten:
        """La curva dai due punti del catalogo di The Pot — θ a −1 kPa e a
        −10 kPa, la convenzione dei substrati — con una θ_s da fuori (la
        porosità totale) e una residua che senza il punto a −1500 kPa vale
        zero: la scelta prudente, che tiene la coda più bassa."""
        return cls.from_points(
            theta_s=theta_s,
            theta_r=theta_r,
            wet=(tension_cm_from_kpa(1.0), theta_fc_1kpa),
            dry=(tension_cm_from_kpa(10.0), theta_pwp_10kpa),
        )


@dataclass(frozen=True)
class TabulatedCurve:
    """
    Una curva per punti (tensione in cm, θ), dal più bagnato al più
    asciutto, il primo a tensione zero: quello che esce da una misura, o
    da una scheda con più punti. Fra il primo punto e il secondo θ scende
    linearmente con la tensione — l'acqua esce prima dai pori grandi —,
    fra gli altri linearmente nel logaritmo della tensione, che è la
    scala su cui le curve si disegnano; oltre l'ultimo resta ferma.
    """

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("Una curva per punti ne vuole almeno due.")
        if self.points[0][0] != 0.0:
            raise ValueError("Il primo punto deve stare a tensione zero: la θ a saturazione.")
        for (t0, th0), (t1, th1) in zip(self.points, self.points[1:], strict=False):
            if t1 <= t0:
                raise ValueError(f"Le tensioni vanno in ordine crescente: {t0} poi {t1} cm.")
            if th1 > th0:
                raise ValueError(f"La θ non può salire con la tensione: {th0} poi {th1}.")
        for _t, th in self.points:
            if not 0.0 <= th <= 1.0:
                raise ValueError(f"θ deve stare fra 0 e 1, non {th}.")

    @property
    def theta_s(self) -> float:
        return self.points[0][1]

    def theta_at(self, tension_cm: float) -> float:
        if tension_cm < 0.0:
            raise ValueError(f"La tensione va data in valore assoluto, non {tension_cm} cm.")
        if tension_cm >= self.points[-1][0]:
            return self.points[-1][1]
        for (t0, th0), (t1, th1) in zip(self.points, self.points[1:], strict=False):
            if t0 <= tension_cm <= t1:
                if t0 == 0.0:
                    frazione = (tension_cm - t0) / (t1 - t0)
                else:
                    frazione = math.log(tension_cm / t0) / math.log(t1 / t0)
                return th0 + (th1 - th0) * frazione
        return self.points[-1][1]  # non si arriva qui


def _simpson(f: Callable[[float], float], a: float, b: float, intervals: int) -> float:
    if intervals < 2 or intervals % 2:
        raise ValueError(f"Simpson vuole un numero pari di intervalli, almeno due, non {intervals}.")
    passo = (b - a) / intervals
    somma = f(a) + f(b)
    for i in range(1, intervals):
        somma += (4.0 if i % 2 else 2.0) * f(a + i * passo)
    return somma * passo / 3.0


def container_capacity(
    curve: RetentionCurve, column_height_cm: float, *, intervals: int = DEFAULT_INTERVALS
) -> float:
    """
    La θ media di una colonna alta `column_height_cm` a drenaggio finito:
    la media della curva fra tensione zero (il fondo) e h (la superficie),
    integrata con Simpson. È la θ_FC *effettiva* di quel vaso, quella che
    moltiplicata per la profondità dà i millimetri che il vaso tiene
    davvero dopo un'annaffiatura a fondo.
    """
    if column_height_cm <= 0.0:
        raise ValueError(f"L'altezza della colonna deve essere positiva, non {column_height_cm} cm.")
    return _simpson(curve.theta_at, 0.0, column_height_cm, intervals) / column_height_cm


def air_space(
    curve: RetentionCurve, column_height_cm: float, *, intervals: int = DEFAULT_INTERVALS
) -> float:
    """Lo spazio d'aria a capacità di contenitore, frazione del volume:
    la porosità che l'acqua ha lasciato, θ_s − θ_CC(h). Milks, Fonteno &
    Larson (1989, III) lo prevedono così, ed è il numero che dice se le
    radici respirano in una ciotola bassa."""
    return curve.theta_s - container_capacity(curve, column_height_cm, intervals=intervals)


def theta_profile(
    curve: RetentionCurve, column_height_cm: float, *, steps: int = 10
) -> list[tuple[float, float]]:
    """La θ lungo la colonna, dal fondo (quota 0, saturo) alla superficie:
    `steps + 1` coppie (quota in cm, θ). Per disegnare la colonna, e per
    sapere che cosa legge una sonda infilata a una certa altezza."""
    if column_height_cm <= 0.0:
        raise ValueError(f"L'altezza della colonna deve essere positiva, non {column_height_cm} cm.")
    if steps < 1:
        raise ValueError("Servono almeno un passo.")
    return [
        (column_height_cm * i / steps, curve.theta_at(column_height_cm * i / steps))
        for i in range(steps + 1)
    ]


def mean_tension_cm(column_height_cm: float) -> float:
    """La tensione media di una colonna a drenaggio finito: h/2. A venti
    centimetri fa dieci, −1 kPa: il punto del catalogo."""
    if column_height_cm <= 0.0:
        raise ValueError(f"L'altezza della colonna deve essere positiva, non {column_height_cm} cm.")
    return column_height_cm / 2.0


def container_capacity_by_height(
    curve: RetentionCurve, heights_cm: Sequence[float], *, intervals: int = DEFAULT_INTERVALS
) -> list[tuple[float, float]]:
    """La capacità di contenitore per una lista di altezze: la tabella che
    mette in fila la ciotola, la cassetta e il vaso alto."""
    return [(h, container_capacity(curve, h, intervals=intervals)) for h in heights_cm]
