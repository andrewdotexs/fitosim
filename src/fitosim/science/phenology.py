"""
Gradi-giorno (GDD): sviluppo fenologico guidato dalla temperatura.

Il problema che risolvono
-------------------------

Il catalogo delle specie esprime la durata degli stadi in **giorni**:
il basilico sta 20 giorni nello stadio iniziale, poi 50 in piena
vegetazione. Ma un basilico seminato a maggio a Milano e uno seminato
a maggio a Palermo non si sviluppano alla stessa velocità, e nemmeno
lo stesso basilico seminato ad aprile o a luglio nello stesso posto.
Le durate in giorni sono valide solo per il clima in cui sono state
misurate.

Lo sviluppo di una pianta non è guidato dal calendario ma dal **calore
accumulato**. Sotto una temperatura di soglia (T_base) i processi
metabolici sono troppo lenti perché lo sviluppo proceda; sopra, la
pianta accumula "gradi-giorno" proporzionalmente a quanto la
temperatura supera quella soglia. Due piante della stessa specie
fioriscono dopo la stessa quantità di gradi-giorno accumulati, anche
se in un posto ci mettono 30 giorni e nell'altro 45.

È lo standard dell'agronomia per la previsione fenologica, ed è ciò
che rende il modello **trasferibile tra climi** invece che ancorato a
quello in cui è stato tarato.

Il metodo di calcolo
--------------------

Esistono diverse convenzioni. Qui usiamo la **media semplice
modificata**, la più diffusa nella pratica agronomica:

    T_min' = max(T_min, T_base)
    T_max' = max(T_max, T_base)
    GDD    = max(0, (T_max' + T_min') / 2 − T_base)

Il "modificata" sta nel clamp preliminare di T_min a T_base. Serve a
non far sottrarre sviluppo alle notti fredde: una notte a 2 °C non
manda la pianta *indietro*, semplicemente non contribuisce. Senza il
clamp, una giornata con minima 2 °C e massima 20 °C (media 11, con
T_base 10 darebbe 1 GDD) verrebbe penalizzata rispetto alla realtà,
in cui le ore diurne sopra soglia hanno comunque fatto sviluppo.

Il tetto opzionale (T_cap) modella il fatto che oltre una certa
temperatura lo sviluppo non accelera più, e anzi rallenta per stress
termico. È lasciato opzionale perché il valore giusto è
specie-specifico e meno consolidato in letteratura della T_base.

Perché solo per le annuali
--------------------------

Questo modulo è pensato per le specie a ciclo annuale, ancorate alla
semina. Le **perenni non seguono i GDD** per uscire dalla dormienza:
hanno bisogno prima di accumulare *freddo* invernale (chill units, e
solo dopo che il fabbisogno di freddo è soddisfatto il caldo le fa
ripartire). Modellarlo richiede i modelli di chill accumulation
(Utah, dynamic model), che sono un'altra famiglia. Applicare i GDD a
un agrume produrrebbe una fenologia sbagliata con l'apparenza della
scientificità.

Per le perenni fitosim continua quindi a usare il calendario
stagionale (vedi `PhenologyAnchor.PERENNIAL` in `domain/species.py`).

Riferimenti: McMaster & Wilhelm (1997), "Growing degree-days: one
equation, two interpretations", Agricultural and Forest Meteorology
87(4).
"""

from __future__ import annotations

from typing import Iterable, Optional


def growing_degree_days(
    t_min: float,
    t_max: float,
    t_base: float,
    t_cap: Optional[float] = None,
) -> float:
    """
    Gradi-giorno accumulati in una singola giornata.

    Applica la media semplice modificata descritta in testa al modulo.
    Il risultato è sempre ≥ 0: una giornata interamente sotto la
    soglia non fa sviluppo, ma non lo fa nemmeno regredire.

    Parametri
    ---------
    t_min, t_max : float
        Temperature minima e massima della giornata, in °C.
    t_base : float
        Temperatura di soglia sotto la quale lo sviluppo si ferma,
        in °C. Specifica della specie (tipicamente 10 °C per le
        solanacee e le aromatiche estive, 4 °C per le colture da
        foglia di stagione fresca).
    t_cap : float, opzionale
        Tetto superiore: le temperature oltre questo valore vengono
        troncate, perché oltre una certa soglia lo sviluppo non
        accelera più. `None` (default) significa nessun tetto.

    Ritorna
    -------
    float
        Gradi-giorno della giornata, in °C·giorno.

    Solleva
    -------
    ValueError
        Se t_max < t_min, o se t_cap è specificato e non è maggiore
        di t_base.
    """
    if t_max < t_min:
        raise ValueError(
            f"t_max ({t_max}) non può essere minore di t_min ({t_min})."
        )
    if t_cap is not None and t_cap <= t_base:
        raise ValueError(
            f"t_cap ({t_cap}) deve essere maggiore di t_base ({t_base})."
        )

    lo = t_min
    hi = t_max
    if t_cap is not None:
        lo = min(lo, t_cap)
        hi = min(hi, t_cap)

    # Clamp a T_base: le ore sotto soglia non contribuiscono, ma non
    # sottraggono sviluppo.
    lo = max(lo, t_base)
    hi = max(hi, t_base)

    return max(0.0, (hi + lo) / 2.0 - t_base)


def accumulate_gdd(
    daily_temperatures: Iterable[tuple[float, float]],
    t_base: float,
    t_cap: Optional[float] = None,
) -> float:
    """
    Gradi-giorno accumulati su una serie di giornate.

    Parametri
    ---------
    daily_temperatures : iterable di (t_min, t_max)
        Serie giornaliera di temperature, in ordine cronologico. Le
        giornate mancanti vanno semplicemente omesse: l'accumulo è
        una somma, quindi un buco nella serie sottostima lo sviluppo
        in modo proporzionale al buco (comportamento prudente e
        prevedibile, preferibile a un'interpolazione implicita).
    t_base, t_cap : float
        Come in `growing_degree_days`.

    Ritorna
    -------
    float
        Somma dei gradi-giorno, in °C·giorno.
    """
    return sum(
        growing_degree_days(t_min, t_max, t_base, t_cap)
        for t_min, t_max in daily_temperatures
    )
