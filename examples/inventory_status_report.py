"""
Esempio: report di stato di un piccolo inventario di vasi.

Simula un balcone con quattro vasi reali, ciascuno con specie,
substrato, dimensioni e data di impianto diverse. Esegue 30 giorni di
simulazione con meteo sintetico tipico estivo a Milano, poi produce
un report di stato finale ordinato per priorità di intervento.

L'esempio è dimostrativo del valore dell'astrazione `Pot`: il codice
del loop di simulazione è breve e leggibile, e ciò che rende ogni
vaso "diverso" è incapsulato dentro l'oggetto Pot stesso, non in
parametri sparsi nel ciclo.

Esegui con:
    python examples/inventory_status_report.py
"""

from datetime import date, timedelta

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL, CITRUS, ROSEMARY, TOMATO
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import (
    CACTUS_MIX,
    PERLITE_RICH,
    UNIVERSAL_POTTING_SOIL,
)


# -----------------------------------------------------------------------
#  Definizione dell'inventario
# -----------------------------------------------------------------------

LATITUDE_DEG = 45.47
START_DATE = date(2025, 7, 1)
N_DAYS = 30


def build_inventory() -> list[Pot]:
    """
    Quattro vasi di test, scelti per coprire scenari biologicamente
    diversi. Le date di impianto sono scelte in modo che, alla data
    finale della simulazione, i vasi si trovino in stadi fenologici
    diversi — utile per vedere il sistema gestire vasi "freschi" e
    "maturi" insieme.
    """
    return [
        Pot(
            label="Basilico-balcone",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=4.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=date(2025, 6, 5),  # inizio MID a fine luglio
        ),
        Pot(
            label="Pomodoro-grande",
            species=TOMATO,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=15.0,
            pot_diameter_cm=30.0,
            location=Location.OUTDOOR,
            planting_date=date(2025, 5, 1),  # MID-SEASON a luglio
        ),
        Pot(
            label="Limone-d-angolo",
            species=CITRUS,
            substrate=PERLITE_RICH,
            pot_volume_l=25.0,
            pot_diameter_cm=40.0,
            location=Location.OUTDOOR,
            planting_date=date(2023, 4, 1),  # perenne, anni di impianto
        ),
        Pot(
            label="Rosmarino-pietraia",
            species=ROSEMARY,
            substrate=CACTUS_MIX,
            pot_volume_l=3.0,
            pot_diameter_cm=16.0,
            location=Location.OUTDOOR,
            planting_date=date(2024, 9, 15),  # perenne, ~1 anno
        ),
    ]


# -----------------------------------------------------------------------
#  Meteo sintetico per 30 giorni di luglio
# -----------------------------------------------------------------------

def synthetic_milan_july(day_index: int) -> tuple[float, float, float]:
    """
    Restituisce (T_min, T_max, pioggia_mm) per il giorno `day_index`
    del periodo simulato.

    Pattern deterministico: alterniamo periodi caldi e freschi, con
    due eventi piovosi piazzati a ~1/3 e ~2/3 del periodo. È ridotto
    in volume (3-8 mm a evento) per non azzerare la deplezione.
    """
    base_min, base_max = 19.0, 30.0
    # Onda termica lenta ±3°C, periodo 10 giorni.
    import math
    wave = math.sin(2 * math.pi * day_index / 10.0)
    t_min = base_min + 2.0 * wave
    t_max = base_max + 3.0 * wave

    rain_mm = 0.0
    if day_index == 11:
        rain_mm = 5.0
    elif day_index == 22:
        rain_mm = 8.0

    return t_min, t_max, rain_mm


# -----------------------------------------------------------------------
#  Simulazione e reportistica
# -----------------------------------------------------------------------

def run_inventory_simulation(inventory: list[Pot]) -> None:
    """
    Loop principale: per ogni giorno calcola ET₀ una volta, poi applica
    il bilancio a ogni vaso. Si vede chiaramente che il codice del
    loop non sa nulla di Kc, p, substrati: tutto è dentro il Pot.
    """
    for day_index in range(N_DAYS):
        current = START_DATE + timedelta(days=day_index)
        t_min, t_max, rain_mm = synthetic_milan_july(day_index)

        # ET₀ del giorno: è meteo, comune a tutti i vasi outdoor.
        et0 = et0_hargreaves_samani(
            t_min=t_min, t_max=t_max,
            latitude_deg=LATITUDE_DEG,
            j=day_of_year(current),
        )

        # Aggiornamento di tutti i vasi del balcone con la stessa ET₀
        # e la stessa pioggia. Ogni Pot poi calcola da sé il proprio
        # ET_c interno e il suo aggiornamento.
        for pot in inventory:
            pot.apply_balance_step(
                et_0_mm=et0,
                water_input_mm=rain_mm,
                current_date=current,
            )


def print_status_report(inventory: list[Pot], report_date: date) -> None:
    """
    Stampa un report finale ordinato per "urgenza di intervento".
    L'urgenza è proporzionale a quanto lo stato è sotto la soglia di
    allerta (deficit relativo).
    """
    # Calcoliamo per ogni vaso un "urgency score" come deficit relativo:
    # zero se sopra soglia, altrimenti (alert - state) / (alert - PWP).
    # Così tutti gli score sono in [0, 1] indipendentemente dalla
    # geometria del vaso.
    def urgency(pot: Pot) -> float:
        if pot.state_mm >= pot.alert_mm:
            return 0.0
        return (pot.alert_mm - pot.state_mm) / (
            pot.alert_mm - pot.pwp_mm
        )

    sorted_inv = sorted(inventory, key=urgency, reverse=True)

    print(f"Report di stato dell'inventario al {report_date.isoformat()}")
    print(f"Dopo {N_DAYS} giorni di simulazione iniziati "
          f"il {START_DATE.isoformat()}\n")

    header = (
        f"{'Vaso':<22} {'Specie':<16} {'Stadio':<12} "
        f"{'Stato':>7} {'Soglia':>7} {'Da dare':>8} {'Urgenza':>8}"
    )
    print(header)
    print("-" * len(header))

    for pot in sorted_inv:
        stage = pot.current_stage(report_date)
        # "Da dare": litri necessari per riportare a FC.
        liters = pot.water_to_field_capacity_liters()
        urg = urgency(pot) * 100  # in percentuale
        urg_str = f"{urg:.0f}%" if urg > 0 else "—"
        print(
            f"{pot.label:<22} "
            f"{pot.species.common_name:<16} "
            f"{stage.value:<12} "
            f"{pot.state_mm:>5.1f}mm "
            f"{pot.alert_mm:>5.1f}mm "
            f"{liters:>6.2f}L "
            f"{urg_str:>8}"
        )

    print()
    print("Legenda colonne:")
    print("  Stato    = contenuto idrico corrente del vaso")
    print("  Soglia   = soglia di allerta specifica della specie")
    print("  Da dare  = litri d'acqua per riportare a capacità di campo")
    print("  Urgenza  = deficit relativo, da 0% (sopra soglia) "
          "a 100% (a PWP)")


def main() -> None:
    inventory = build_inventory()
    run_inventory_simulation(inventory)
    final_date = START_DATE + timedelta(days=N_DAYS)
    print_status_report(inventory, final_date)


if __name__ == "__main__":
    main()
