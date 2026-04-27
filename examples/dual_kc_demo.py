"""
Demo: confronto fra single Kc e dual-Kc di FAO-56 cap. 7.

Il modello single Kc tradizionale tratta l'evapotraspirazione come un
unico coefficiente moltiplicativo costante per stadio fenologico:
ETc = Kc × ET₀. Cattura bene il consumo idrico medio ma sbaglia nei
giorni di transizione, dove la traspirazione fogliare e l'evaporazione
superficiale del substrato hanno dinamiche molto diverse.

Il modello dual-Kc separa esplicitamente le due componenti:
ETc = (Kcb + Ke) × ET₀, dove Kcb è il coefficiente basale (solo
traspirazione) e Ke è il coefficiente di evaporazione superficiale,
dinamico nel tempo: massimo subito dopo un'irrigazione/pioggia
(quando il substrato superficiale è bagnato), poi decresce verso
zero man mano che la superficie si asciuga.

Questo demo confronta due vasi gemelli di basilico, identici in tutto
tranne che per il modello di evapotraspirazione applicato:

  - Vaso A: motore single Kc tradizionale (default del progetto).
  - Vaso B: motore dual-Kc (specie con Kcb, substrato con REW/TEW).

Mostriamo tre pannelli sovrapposti:

  1. Traiettorie idriche dei due vasi, con marker per ogni
     irrigazione decisa dall'algoritmo.

  2. Evoluzione del De (cumulative depletion superficiale) e del Ke
     (coefficiente di evaporazione superficiale) per il vaso B.
     Si vede chiaramente la dinamica a due fasi del modello.

  3. Forzanti meteo (ET₀, pioggia).

Esegui con:
    PYTHONPATH=src python examples/dual_kc_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL, Species
from fitosim.science.dual_kc import (
    evaporation_reduction_coefficient,
    soil_evaporation_coefficient,
)
from fitosim.science.substrate import Substrate


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Setup della simulazione: stessi parametri degli altri demo per
# confrontabilità.
PLANTING_DATE = date(2026, 4, 15)
SIM_START = date(2026, 5, 1)
SIM_DAYS = 30
IRRIGATION_EXCESS = 1.0  # niente eccesso, isoliamo l'effetto del modello


# Specie basilico con i Kcb FAO-56 cap. 7 (valori tipici per ortive
# da foglia in vaso). I Kcb sono ~0.10-0.15 più bassi dei Kc perché
# tolgono la componente di evaporazione media.
BASIL_DUAL_KC = Species(
    common_name="basilico-dualKc",
    scientific_name="Ocimum basilicum",
    kc_initial=0.50, kc_mid=1.10, kc_late=0.85,
    kcb_initial=0.35, kcb_mid=1.00, kcb_late=0.75,
    depletion_fraction=0.40,
    notes="Versione con Kcb FAO-56 cap.7, valori per ortive in vaso.",
)


# Substrato torba commerciale con REW e TEW per dual-Kc. Valori
# rappresentativi per torba di sfagno + perlite (mix universale).
TORBA_DUAL_KC = Substrate(
    name="Torba commerciale (dual-Kc)",
    theta_fc=0.40,
    theta_pwp=0.10,
    rew_mm=9.0,    # readily evaporable: ~9 mm per torba domestica
    tew_mm=22.0,   # total evaporable: ~22 mm per Ze=15 cm
    description=(
        "Torba di sfagno + perlite, parametri estesi con REW=9 mm "
        "e TEW=22 mm per supportare il modello dual-Kc."
    ),
)


# Substrato single Kc equivalente per il vaso di confronto.
TORBA_SINGLE_KC = Substrate(
    name="Torba commerciale (single Kc)",
    theta_fc=0.40,
    theta_pwp=0.10,
)


def make_pot(use_dual_kc: bool) -> Pot:
    """
    Crea un vaso di basilico con o senza supporto dual-Kc.

    Vaso A (single Kc): specie BASIL standard del catalogo (senza Kcb)
        e substrato torba senza REW/TEW. Comportamento tradizionale.
    Vaso B (dual-Kc): specie BASIL_DUAL_KC con Kcb e substrato
        TORBA_DUAL_KC con REW/TEW. Il motore attiva automaticamente
        il modello dual-Kc.
    """
    return Pot(
        label=("dual-Kc" if use_dual_kc else "single Kc"),
        species=BASIL_DUAL_KC if use_dual_kc else BASIL,
        substrate=TORBA_DUAL_KC if use_dual_kc else TORBA_SINGLE_KC,
        pot_volume_l=5.0,
        pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=PLANTING_DATE,
    )


def synthetic_weather() -> tuple[list[float], list[float]]:
    """Stesso meteo sintetico degli altri demo (maggio Milano)."""
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
    """Esito di una simulazione con tracking dei dettagli dual-Kc."""
    label: str
    states_mm: list[float]
    de_mm_history: list[float]
    ke_history: list[float]
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
    Simula 30 giorni del vaso, registrando per ogni giorno:
      - stato idrico del bulk substrato (state_mm);
      - cumulative depletion (de_mm) — solo per dual-Kc;
      - Ke effettivo del giorno — solo per dual-Kc.
    """
    states = [pot.state_mm]
    de_history = [pot.de_mm]
    ke_history: list[float] = []
    irr_days: list[int] = []
    irr_amounts: list[float] = []

    for day_idx in range(SIM_DAYS):
        current_date = SIM_START + timedelta(days=day_idx)
        et_0 = et0_series[day_idx]
        rain = rain_series[day_idx]

        if pot.state_mm < pot.alert_mm:
            irrigation = pot.water_to_field_capacity() * IRRIGATION_EXCESS
            irr_days.append(day_idx)
            irr_amounts.append(irrigation)
        else:
            irrigation = 0.0

        # Per il dual-Kc, calcoliamo Ke come "snapshot" del giorno
        # PRIMA di applicare il bilancio (riflette lo stato di De
        # entrante).
        if pot.supports_dual_kc:
            kr = evaporation_reduction_coefficient(
                de_mm=pot.de_mm,
                rew_mm=pot.substrate.rew_mm,
                tew_mm=pot.substrate.tew_mm,
            )
            stage = pot.current_stage(current_date)
            from fitosim.domain.species import PhenologicalStage
            kcb_map = {
                PhenologicalStage.INITIAL: pot.species.kcb_initial,
                PhenologicalStage.MID_SEASON: pot.species.kcb_mid,
                PhenologicalStage.LATE_SEASON: pot.species.kcb_late,
            }
            ke = soil_evaporation_coefficient(kr=kr, kcb=kcb_map[stage])
            ke_history.append(ke)
        else:
            ke_history.append(0.0)

        pot.apply_balance_step(
            et_0_mm=et_0,
            water_input_mm=rain + irrigation,
            current_date=current_date,
        )
        states.append(pot.state_mm)
        de_history.append(pot.de_mm)

    return SimResult(
        label=pot.label,
        states_mm=states,
        de_mm_history=de_history,
        ke_history=ke_history,
        irrigation_days=irr_days,
        irrigation_amounts=irr_amounts,
    )


def plot_comparison(
    single_kc: SimResult,
    dual_kc: SimResult,
    et0_series: list[float],
    rain_series: list[float],
    rew_mm: float,
    tew_mm: float,
) -> Path:
    """
    Tre pannelli con asse temporale condiviso:
      1. Traiettorie idriche dei due vasi.
      2. Dinamica di De e Ke per il vaso dual-Kc.
      3. Forzanti meteo.
    """
    fig = plt.figure(figsize=(12, 11), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.5, 1.8, 1.0])
    ax_traj = fig.add_subplot(gs[0])
    ax_de_ke = fig.add_subplot(gs[1], sharex=ax_traj)
    ax_meteo = fig.add_subplot(gs[2], sharex=ax_traj)

    fig.suptitle(
        "Confronto fra single Kc e dual-Kc (FAO-56 cap. 7)\n"
        "Basilico in vaso 5 L, 30 giorni di simulazione (maggio Milano)",
        fontsize=13, fontweight="bold",
    )

    # --- Pannello 1: traiettorie idriche ---
    days = list(range(SIM_DAYS + 1))

    # Soglie di riferimento (uguali per entrambi i vasi).
    sample_pot_single = make_pot(use_dual_kc=False)
    fc = sample_pot_single.fc_mm
    alert = sample_pot_single.alert_mm
    pwp = sample_pot_single.pwp_mm

    ax_traj.axhline(fc, color="#888", linestyle="-", linewidth=0.8,
                    alpha=0.5)
    ax_traj.text(SIM_DAYS, fc, " FC", color="#666",
                 fontsize=8, va="center")
    ax_traj.axhline(alert, color="#cc8800", linestyle="--",
                    linewidth=0.8, alpha=0.6)
    ax_traj.text(SIM_DAYS, alert, " soglia", color="#cc8800",
                 fontsize=8, va="center")
    ax_traj.axhline(pwp, color="#cc0000", linestyle=":", linewidth=0.8,
                    alpha=0.5)
    ax_traj.text(SIM_DAYS, pwp, " PWP", color="#cc0000",
                 fontsize=8, va="center")

    # Vaso single Kc.
    ax_traj.plot(days, single_kc.states_mm,
                 color="#4682B4", linewidth=2.0,
                 label=f"Single Kc ({single_kc.num_irrigations} irrig., "
                       f"{single_kc.total_water_mm:.0f} mm)")
    if single_kc.irrigation_days:
        ax_traj.scatter(
            single_kc.irrigation_days,
            [single_kc.states_mm[d] for d in single_kc.irrigation_days],
            color="#4682B4", marker="v", s=50, zorder=5,
            edgecolors="black", linewidth=0.5,
        )

    # Vaso dual-Kc.
    ax_traj.plot(days, dual_kc.states_mm,
                 color="#D2691E", linewidth=2.0,
                 label=f"Dual-Kc ({dual_kc.num_irrigations} irrig., "
                       f"{dual_kc.total_water_mm:.0f} mm)")
    if dual_kc.irrigation_days:
        ax_traj.scatter(
            dual_kc.irrigation_days,
            [dual_kc.states_mm[d] for d in dual_kc.irrigation_days],
            color="#D2691E", marker="v", s=50, zorder=5,
            edgecolors="black", linewidth=0.5,
        )

    ax_traj.set_ylabel("Acqua nel substrato (mm)")
    ax_traj.set_title("Traiettorie idriche (marker = irrigazione)",
                      fontsize=11, color="tab:gray")
    ax_traj.set_ylim(pwp - 4, fc + 3)
    ax_traj.grid(True, alpha=0.3)
    ax_traj.legend(loc="lower left", fontsize=10, framealpha=0.95)

    # --- Pannello 2: De e Ke per il vaso dual-Kc ---
    color_de = "#8B4513"
    color_ke = "#228B22"

    # De (asse sinistro).
    ax_de_ke.fill_between(days, dual_kc.de_mm_history,
                          color=color_de, alpha=0.2)
    ax_de_ke.plot(days, dual_kc.de_mm_history, color=color_de,
                  linewidth=2.0, label="De (cumulative depletion)")
    ax_de_ke.axhline(rew_mm, color=color_de, linestyle="--",
                     linewidth=0.8, alpha=0.6)
    ax_de_ke.text(SIM_DAYS, rew_mm, f" REW={rew_mm:.0f}",
                  color=color_de, fontsize=8, va="center")
    ax_de_ke.axhline(tew_mm, color=color_de, linestyle=":",
                     linewidth=0.8, alpha=0.6)
    ax_de_ke.text(SIM_DAYS, tew_mm, f" TEW={tew_mm:.0f}",
                  color=color_de, fontsize=8, va="center")
    ax_de_ke.set_ylabel("De (mm)", color=color_de)
    ax_de_ke.tick_params(axis="y", labelcolor=color_de)
    ax_de_ke.set_ylim(0, tew_mm + 2)

    # Ke (asse destro).
    ax_ke = ax_de_ke.twinx()
    days_for_ke = list(range(SIM_DAYS))
    ax_ke.plot(days_for_ke, dual_kc.ke_history,
               color=color_ke, linewidth=2.0, marker="o", markersize=3,
               label="Ke (coeff. evap. superficiale)")
    ax_ke.set_ylabel("Ke", color=color_ke)
    ax_ke.tick_params(axis="y", labelcolor=color_ke)
    ax_ke.set_ylim(0, max(dual_kc.ke_history) * 1.2 + 0.01)

    ax_de_ke.set_title(
        "Dinamica del dual-Kc: De cresce con l'asciugamento, "
        "Ke segue la fase di Kr",
        fontsize=11, color="tab:gray",
    )
    ax_de_ke.grid(True, alpha=0.3, axis="x")

    # --- Pannello 3: forzanti meteo ---
    days_int = list(range(SIM_DAYS))
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

    path = OUTPUT_DIR / "dual_kc_comparison.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def print_report(
    single_kc: SimResult,
    dual_kc: SimResult,
) -> None:
    """Tabella sintetica dei risultati."""
    print()
    print("=" * 70)
    print("Risultati del confronto su 30 giorni")
    print("=" * 70)
    print(f"\n{'':25} | {'Single Kc':>10} | {'Dual-Kc':>10}")
    print("-" * 56)
    print(f"{'Numero irrigazioni':<25} | "
          f"{single_kc.num_irrigations:>10d} | "
          f"{dual_kc.num_irrigations:>10d}")
    print(f"{'Acqua totale erogata':<25} | "
          f"{single_kc.total_water_mm:>7.1f} mm | "
          f"{dual_kc.total_water_mm:>7.1f} mm")

    # Per il dual-Kc, statistiche su De e Ke.
    avg_de = sum(dual_kc.de_mm_history) / len(dual_kc.de_mm_history)
    max_de = max(dual_kc.de_mm_history)
    avg_ke = sum(dual_kc.ke_history) / len(dual_kc.ke_history)
    max_ke = max(dual_kc.ke_history)

    print()
    print("Dinamica del dual-Kc:")
    print(f"  - De medio: {avg_de:.1f} mm  (massimo: {max_de:.1f} mm)")
    print(f"  - Ke medio: {avg_ke:.3f}  (massimo: {max_ke:.3f})")

    # Differenza tra i due modelli.
    diff_water = dual_kc.total_water_mm - single_kc.total_water_mm
    if single_kc.total_water_mm > 0:
        diff_pct = diff_water / single_kc.total_water_mm * 100
    else:
        diff_pct = 0.0

    print()
    print("Differenza dual-Kc vs single Kc:")
    sign = "+" if diff_water >= 0 else ""
    print(f"  - Acqua: {sign}{diff_water:.1f} mm "
          f"({sign}{diff_pct:.1f}%)")
    diff_irr = dual_kc.num_irrigations - single_kc.num_irrigations
    print(f"  - Irrigazioni: {sign if diff_irr >= 0 else ''}{diff_irr}")
    print("=" * 70)


def main() -> None:
    print("=" * 70)
    print("Demo: confronto fra single Kc e dual-Kc (FAO-56 cap. 7)")
    print("=" * 70)

    print(f"\nGenero meteo sintetico per {SIM_DAYS} giorni a partire da "
          f"{SIM_START.isoformat()}...")
    et0_series, rain_series = synthetic_weather()
    print(f"   ET₀ medio: {sum(et0_series) / len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm")

    print("\nCreazione dei due vasi gemelli...")
    pot_single = make_pot(use_dual_kc=False)
    pot_dual = make_pot(use_dual_kc=True)
    print(f"   • {pot_single.label}: supports_dual_kc = "
          f"{pot_single.supports_dual_kc}")
    print(f"   • {pot_dual.label}: supports_dual_kc = "
          f"{pot_dual.supports_dual_kc}")

    print("\nSimulazione del vaso single Kc...")
    res_single = simulate(pot_single, et0_series, rain_series)
    print(f"   → {res_single.num_irrigations} irrigazioni richieste")

    print("\nSimulazione del vaso dual-Kc...")
    res_dual = simulate(pot_dual, et0_series, rain_series)
    print(f"   → {res_dual.num_irrigations} irrigazioni richieste")

    print_report(res_single, res_dual)

    print("\nGenerazione grafico di confronto...")
    p = plot_comparison(
        res_single, res_dual, et0_series, rain_series,
        rew_mm=TORBA_DUAL_KC.rew_mm,
        tew_mm=TORBA_DUAL_KC.tew_mm,
    )
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
