"""
Demo: effetto del sottovaso e della risalita capillare.

Confronto di due vasi gemelli — stessa specie, stesso substrato, stesse
dimensioni, stesso meteo — di cui uno ha un sottovaso da 10 mm e
l'altro no. Mostriamo la traiettoria idrica giornaliera, gli eventi di
irrigazione consigliata, e l'evoluzione dell'acqua nel piattino.

Ipotesi: vaso da 5 L di basilico in fase mid-season, sottovaso che
trattiene fino a 10 mm-equivalenti. La logica di irrigazione è la
stessa per entrambi i vasi: ogni volta che si scende sotto la soglia
di allerta, si annaffia per riportare a capacità di campo.

Metrica chiave del demo: il **numero di irrigazioni richieste in 30
giorni**. Il vaso con sottovaso ne dovrebbe avere meno, perché il
piattino cattura il drenaggio e lo restituisce nei giorni successivi
prolungando l'autonomia.

Esegui con:
    PYTHONPATH=src python examples/saucer_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Setup della simulazione
PLANTING_DATE = date(2026, 4, 15)
SIM_START = date(2026, 5, 1)
SIM_DAYS = 30
SAUCER_CAPACITY_MM = 10.0

# Eccesso di irrigazione rispetto a FC. Il giardiniere domestico
# tipicamente annaffia "fino a vedere l'acqua uscire dal fondo", che
# corrisponde a un eccesso del 20-30% rispetto a capacità di campo.
# È esattamente questo gesto reale che rende il sottovaso utile:
# l'eccesso genera drenaggio, che il piattino cattura e restituisce
# nei giorni successivi. Modellando un'irrigazione "esatta a FC" il
# sottovaso non si riempirebbe mai e il modello non potrebbe mostrare
# il suo effetto.
IRRIGATION_EXCESS = 1.25


def make_pot(with_saucer: bool) -> Pot:
    """
    Crea un vaso gemello (basilico, 5L, plastica chiara, pieno sole).
    Se with_saucer=True, aggiunge il sottovaso da 10 mm.
    """
    return Pot(
        label=("con sottovaso" if with_saucer else "senza sottovaso"),
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0,
        pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=PLANTING_DATE,
        saucer_capacity_mm=SAUCER_CAPACITY_MM if with_saucer else None,
    )


def synthetic_weather() -> tuple[list[float], list[float]]:
    """
    Meteo sintetico per maggio a Milano: ET₀ medio 4 mm/giorno con
    rumore, tre eventi di pioggia distribuiti.
    """
    rng = np.random.default_rng(seed=42)
    et0_series = []
    rain_series = []
    for d in range(SIM_DAYS):
        base = 3.0 + 2.0 * (d / SIM_DAYS)
        noise = rng.normal(0, 0.4)
        et0_series.append(max(1.5, base + noise))
        rain_series.append(0.0)
    for day, mm in [(7, 8.0), (15, 5.0), (22, 12.0)]:
        rain_series[day] = mm
    return et0_series, rain_series


@dataclass
class SimResult:
    label: str
    states_mm: list[float]
    saucer_states_mm: list[float]
    irrigation_days: list[int]
    irrigation_amounts: list[float]

    @property
    def num_irrigations(self) -> int:
        return len(self.irrigation_days)

    @property
    def total_water_mm(self) -> float:
        return sum(self.irrigation_amounts)


def simulate(
    pot: Pot,
    et0_series: list[float],
    rain_series: list[float],
) -> SimResult:
    """
    Simula 30 giorni del vaso, registrando stato giornaliero e
    irrigazioni. La logica di irrigazione è: se lo stato cade sotto la
    soglia di allerta, si annaffia per tornare a FC.
    """
    states = [pot.state_mm]
    saucer_states = [pot.saucer_state_mm]
    irr_days: list[int] = []
    irr_amounts: list[float] = []

    for day_idx in range(SIM_DAYS):
        current_date = SIM_START + timedelta(days=day_idx)
        et_0 = et0_series[day_idx]
        rain = rain_series[day_idx]

        if pot.state_mm < pot.alert_mm:
            # Il giardiniere annaffia "abbondantemente" — fino a vedere
            # l'acqua uscire dal fondo. Modelliamo questa pratica con
            # un eccesso del 25% rispetto al rientro esatto a FC. Il
            # surplus produce drenaggio che, in presenza di sottovaso,
            # il piattino cattura.
            irrigation = pot.water_to_field_capacity() * IRRIGATION_EXCESS
            irr_days.append(day_idx)
            irr_amounts.append(irrigation)
        else:
            irrigation = 0.0

        pot.apply_balance_step(
            et_0_mm=et_0,
            water_input_mm=rain + irrigation,
            current_date=current_date,
        )
        states.append(pot.state_mm)
        saucer_states.append(pot.saucer_state_mm)

    return SimResult(
        label=pot.label,
        states_mm=states,
        saucer_states_mm=saucer_states,
        irrigation_days=irr_days,
        irrigation_amounts=irr_amounts,
    )


def plot_comparison(
    no_saucer: SimResult,
    with_saucer: SimResult,
    et0_series: list[float],
    rain_series: list[float],
) -> Path:
    """
    Tre pannelli sovrapposti con asse temporale condiviso:
      1. Traiettorie idriche dei due vasi, marker per le irrigazioni.
      2. Evoluzione dell'acqua nel sottovoto (solo del vaso che ce l'ha).
      3. Forzanti meteo: ET₀ giornaliero e pioggia.
    """
    fig, (ax_pot, ax_saucer, ax_meteo) = plt.subplots(
        3, 1, figsize=(12, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.2, 1.5]},
    )

    fig.suptitle(
        "Sottovaso e risalita capillare: confronto su 30 giorni\n"
        f"Basilico, vaso 5 L, sottovaso da {SAUCER_CAPACITY_MM:.0f} mm "
        "(quando presente)",
        fontsize=13, fontweight="bold", y=0.995,
    )

    days = list(range(SIM_DAYS + 1))
    days_int = list(range(SIM_DAYS))

    # Soglie di riferimento (uguali per entrambi i vasi).
    sample_pot = make_pot(with_saucer=False)
    fc = sample_pot.fc_mm
    alert = sample_pot.alert_mm
    pwp = sample_pot.pwp_mm

    # --- Pannello 1: traiettorie del vaso ---
    ax_pot.axhline(fc, color="#888", linestyle="-", linewidth=0.8,
                   alpha=0.5)
    ax_pot.text(SIM_DAYS, fc, " FC", color="#666",
                fontsize=8, va="center")
    ax_pot.axhline(alert, color="#cc8800", linestyle="--", linewidth=0.8,
                   alpha=0.6)
    ax_pot.text(SIM_DAYS, alert, " soglia", color="#cc8800",
                fontsize=8, va="center")
    ax_pot.axhline(pwp, color="#cc0000", linestyle=":", linewidth=0.8,
                   alpha=0.5)
    ax_pot.text(SIM_DAYS, pwp, " PWP", color="#cc0000",
                fontsize=8, va="center")

    # Vaso senza sottovaso
    ax_pot.plot(days, no_saucer.states_mm,
                color="#cc4444", linewidth=2.0,
                label=f"Senza sottovaso ({no_saucer.num_irrigations} irrig.)")
    if no_saucer.irrigation_days:
        ax_pot.scatter(
            no_saucer.irrigation_days,
            [no_saucer.states_mm[d] for d in no_saucer.irrigation_days],
            color="#cc4444", marker="v", s=50, zorder=5,
            edgecolors="black", linewidth=0.5,
        )

    # Vaso con sottovaso
    ax_pot.plot(days, with_saucer.states_mm,
                color="#4477aa", linewidth=2.0,
                label=f"Con sottovaso ({with_saucer.num_irrigations} irrig.)")
    if with_saucer.irrigation_days:
        ax_pot.scatter(
            with_saucer.irrigation_days,
            [with_saucer.states_mm[d] for d in with_saucer.irrigation_days],
            color="#4477aa", marker="v", s=50, zorder=5,
            edgecolors="black", linewidth=0.5,
        )

    ax_pot.set_ylabel("Acqua nel substrato (mm)")
    ax_pot.set_title("Traiettorie idriche del vaso (marker = irrigazione)",
                     fontsize=11, color="tab:gray")
    ax_pot.set_ylim(pwp - 4, fc + 3)
    ax_pot.grid(True, alpha=0.3)
    ax_pot.legend(loc="lower left", fontsize=10, framealpha=0.95)

    # --- Pannello 2: dinamica del sottovaso ---
    ax_saucer.axhline(SAUCER_CAPACITY_MM, color="#888",
                      linestyle="-", linewidth=0.8, alpha=0.5)
    ax_saucer.text(SIM_DAYS, SAUCER_CAPACITY_MM,
                   " capacità", color="#666",
                   fontsize=8, va="center")
    ax_saucer.fill_between(days, with_saucer.saucer_states_mm,
                           color="#4477aa", alpha=0.4)
    ax_saucer.plot(days, with_saucer.saucer_states_mm,
                   color="#4477aa", linewidth=1.8)
    ax_saucer.set_ylabel("Acqua nel piattino (mm)")
    ax_saucer.set_title("Evoluzione dell'acqua nel sottovaso "
                        "(solo del vaso che ce l'ha)",
                        fontsize=11, color="tab:gray")
    ax_saucer.set_ylim(0, SAUCER_CAPACITY_MM + 1)
    ax_saucer.grid(True, alpha=0.3)

    # --- Pannello 3: forzanti meteo ---
    color_et0 = "#d62728"
    color_rain = "#1f77b4"
    ax_meteo.bar(days_int, et0_series, color=color_et0, alpha=0.6,
                 label="ET₀", edgecolor="none", width=0.8)
    ax_meteo.set_ylabel("ET₀ (mm/giorno)", color=color_et0)
    ax_meteo.tick_params(axis="y", labelcolor=color_et0)
    ax_meteo.set_xlabel("Giorno della simulazione")

    ax_rain = ax_meteo.twinx()
    ax_rain.bar([d + 0.4 for d in days_int], rain_series,
                color=color_rain, alpha=0.6, edgecolor="none",
                width=0.4, label="Pioggia")
    ax_rain.set_ylabel("Pioggia (mm)", color=color_rain)
    ax_rain.tick_params(axis="y", labelcolor=color_rain)

    ax_meteo.set_title("Forzanti meteo giornaliere",
                       fontsize=11, color="tab:gray")
    ax_meteo.set_xlim(-0.5, SIM_DAYS + 0.5)
    ax_meteo.grid(True, alpha=0.3, axis="y")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = OUTPUT_DIR / "saucer_comparison.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def print_report(no_saucer: SimResult, with_saucer: SimResult) -> None:
    """Sintesi numerica del confronto."""
    print()
    print("=" * 70)
    print("Risultati del confronto su 30 giorni")
    print("=" * 70)
    print(f"\n{'':25} | {'Senza':>10} | {'Con':>10}")
    print(f"{'':25} | {'sottovoto':>10} | {'sottovoto':>10}")
    print("-" * 56)
    print(f"{'Numero irrigazioni':<25} | "
          f"{no_saucer.num_irrigations:>10d} | "
          f"{with_saucer.num_irrigations:>10d}")
    print(f"{'Acqua totale erogata':<25} | "
          f"{no_saucer.total_water_mm:>7.1f} mm | "
          f"{with_saucer.total_water_mm:>7.1f} mm")

    diff_irr = no_saucer.num_irrigations - with_saucer.num_irrigations
    diff_water = no_saucer.total_water_mm - with_saucer.total_water_mm
    if no_saucer.total_water_mm > 0:
        savings_pct = diff_water / no_saucer.total_water_mm * 100
    else:
        savings_pct = 0.0

    print()
    print("Risparmio del sottovaso:")
    print(f"  - {diff_irr} irrigazioni in meno in 30 giorni")
    print(f"  - {diff_water:.1f} mm di acqua risparmiata "
          f"({savings_pct:.1f}% del totale)")

    avg_saucer = sum(with_saucer.saucer_states_mm) / len(with_saucer.saucer_states_mm)
    max_saucer = max(with_saucer.saucer_states_mm)
    print()
    print("Dinamica del sottovaso:")
    print(f"  - Acqua media nel piattino: {avg_saucer:.1f} mm "
          f"({avg_saucer / SAUCER_CAPACITY_MM * 100:.0f}% della capacità)")
    print(f"  - Picco massimo nel piattino: {max_saucer:.1f} mm "
          f"({max_saucer / SAUCER_CAPACITY_MM * 100:.0f}% della capacità)")
    print("=" * 70)


def main() -> None:
    print("=" * 70)
    print("Demo: effetto del sottovaso e risalita capillare")
    print("=" * 70)

    print(f"\nGenero meteo sintetico per {SIM_DAYS} giorni a partire da "
          f"{SIM_START.isoformat()}...")
    et0_series, rain_series = synthetic_weather()
    print(f"   ET₀ medio: {sum(et0_series) / len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm")

    print("\nSimulazione vaso senza sottovaso...")
    pot_no = make_pot(with_saucer=False)
    res_no = simulate(pot_no, et0_series, rain_series)
    print(f"   → {res_no.num_irrigations} irrigazioni richieste")

    print("\nSimulazione vaso con sottovaso...")
    pot_yes = make_pot(with_saucer=True)
    res_yes = simulate(pot_yes, et0_series, rain_series)
    print(f"   → {res_yes.num_irrigations} irrigazioni richieste")

    print_report(res_no, res_yes)

    print("\nGenerazione grafico di confronto...")
    p = plot_comparison(res_no, res_yes, et0_series, rain_series)
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
