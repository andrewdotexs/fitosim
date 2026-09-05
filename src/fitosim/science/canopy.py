"""
La chioma nel vaso: quanto della superficie copre, e cosa fa al Kc.

FAO-56 dà i coefficienti colturali per una coltura a pieno campo che copre
il suolo come la sua tabella prevede. In un vaso la chioma non copre "il
suolo": copre la bocca del vaso, e può coprirla per metà (una piantina in
un vaso grande) o superarla di molte volte (un oleandro adulto in un vaso
da trenta centimetri). In tutti e due i casi il consumo per unità di
superficie del vaso non è quello della tabella.

Il capitolo 9 di FAO-56 tratta proprio questo — colture con copertura
parziale o "non pristine" — e propone (eq. 76) di scalare il Kcb con la
frazione coperta ``fc`` e l'altezza della pianta ``h``:

    Kcb = Kc_min + (Kcb_full − Kc_min) · min(1, 2·fc, fc^(1/(1+h)))

L'esponente ``1/(1+h)`` dice che una pianta alta traspira più della sua
frazione di copertura (gli effetti di bordo, la chioma investita dal vento
anche di lato); ``2·fc`` è il limite per le chiome molto rade.

Sopra la copertura piena la formula di FAO-56 non arriva: in campo ``fc``
non supera 1. In vaso sì, e la fisica è semplice — la chioma traspira per
la sua superficie, e l'acqua la prende tutta dal vaso — quindi il Kcb scala
con il rapporto fra le due aree, fino a un tetto: oltre un certo rapporto
la pianta è comunque limitata dalle radici, e il modello lo dice con lo
stress (Ks), non con un Kcb infinito.

Il modulo è puro: numeri dentro, numeri fuori. Chi lo usa è ``Pot``.
"""

from __future__ import annotations

import math

# Il tetto del rapporto chioma/vaso. Sopra 2.5 volte l'area del vaso una
# pianta è già root-bound o quasi, e il consumo lo governa lo stress idrico,
# non la chioma: il tetto tiene il modello dentro il suo dominio.
COVER_CAP = 2.5

# Kc minimo del suolo nudo bagnato (FAO-56 cap. 9 consiglia 0.15–0.20):
# è lo stesso pavimento evaporativo di `species.KC_BARE_SOIL_FLOOR`.
KC_MIN_DEFAULT = 0.20


def cover_fraction(canopy_width_m: float, pot_area_m2: float) -> float:
    """
    La frazione della bocca del vaso coperta dalla chioma, ``fc``.

    La chioma è presa per un cerchio del diametro dato — è la larghezza
    che si misura col metro, «da un'estremità all'altra» — e il rapporto
    è fra le due aree. Può superare 1: in vaso succede spesso.
    """
    if canopy_width_m <= 0:
        raise ValueError(
            f"canopy_width_m deve essere positivo (ricevuto {canopy_width_m})."
        )
    if pot_area_m2 <= 0:
        raise ValueError(
            f"pot_area_m2 deve essere positivo (ricevuto {pot_area_m2})."
        )
    return math.pi * (canopy_width_m / 2.0) ** 2 / pot_area_m2


def cover_factor(fc: float, height_m: float | None = None) -> float:
    """
    Il fattore che scala la traspirazione per la copertura ``fc``.

    Sotto la copertura piena è FAO-56 eq. 76, senza il termine Kc_min
    (che dipende da chi chiama: ``kcb_from_cover`` lo lascia a zero,
    ``kc_from_cover`` lo mette). Sopra, il rapporto fra le aree fino a
    ``COVER_CAP``. A ``fc = 1`` vale esattamente 1 da tutte e due le
    parti: nessun salto.

    ``height_m`` è l'altezza della chioma (o della pianta), che entra
    nell'esponente; senza, l'esponente vale 1 e il fattore è lineare in
    ``fc`` — il limite delle piante basse.
    """
    if fc < 0:
        raise ValueError(f"fc non può essere negativa (ricevuto {fc}).")
    if fc >= 1.0:
        return min(fc, COVER_CAP)
    h = max(height_m or 0.0, 0.0)
    return min(1.0, 2.0 * fc, fc ** (1.0 / (1.0 + h)))


def kcb_from_cover(
    kcb_full: float, fc: float | None, height_m: float | None = None,
) -> float:
    """
    Il Kcb (traspirazione basale, dual-Kc) per una chioma che copre ``fc``.

    Nel dual-Kc l'evaporazione dal substrato è di Ke: il Kcb può scendere
    verso zero senza pavimento. ``fc = None`` vuol dire «non misurata» e
    lascia il Kcb com'è — il comportamento di prima.
    """
    if fc is None:
        return kcb_full
    return kcb_full * cover_factor(fc, height_m)


def kc_from_cover(
    kc_full: float,
    fc: float | None,
    height_m: float | None = None,
    kc_min: float = KC_MIN_DEFAULT,
) -> float:
    """
    Il Kc (single Kc) per una chioma che copre ``fc``, con il pavimento.

    Nel single Kc l'evaporazione dal substrato sta dentro il Kc: sotto la
    copertura piena il Kc scende verso ``kc_min``, mai sotto, perché la
    superficie nuda evapora anche senza chioma (è la forma piena di eq.
    76). Sopra, scala con le aree come il Kcb.
    """
    if fc is None:
        return kc_full
    if fc >= 1.0:
        return kc_full * cover_factor(fc, height_m)
    floor = min(kc_min, kc_full)
    return floor + (kc_full - floor) * cover_factor(fc, height_m)
