"""
Demo: effetto delle caratteristiche del vaso sul fabbisogno idrico.

Prendiamo un singolo vaso di basilico "di riferimento" (5 litri, 22 cm
di diametro, plastica chiara, esposizione neutra) e creiamo otto
varianti che differiscono SOLO per una o più caratteristiche del
contenitore (materiale, colore, esposizione). Tutto il resto — specie,
substrato, dimensioni geometriche, meteo simulato, data di impianto,
stato iniziale — è identico in ogni variante.

Simuliamo trenta giorni con un meteo sintetico tipico di maggio a
Milano: ET₀ ~3-5 mm/giorno, qualche giorno di pioggia leggera. Per
ogni variante, ogni volta che il livello idrico scende sotto la soglia
di allerta (RAW), eseguiamo un'irrigazione che riporta il vaso a
capacità di campo.

Il grafico finale ha due pannelli sovrapposti:

  - Pannello superiore: le otto traiettorie idriche del vaso, con
    marker per ogni evento di irrigazione. Si vede a colpo d'occhio
    come le caratteristiche del vaso modulano la pendenza di
    asciugamento e la frequenza degli interventi.

  - Pannello inferiore: barra orizzontale per ogni variante che mostra
    quante irrigazioni il vaso ha richiesto in 30 giorni. È la
    sintesi operativa: il giardiniere vede subito che il vaso di
    terracotta nera al sole richiede 12 irrigazioni nel mese e quello
    di plastica chiara all'ombra ne richiede 4.

Esegui con:
    PYTHONPATH=src python examples/pot_characteristics_demo.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.pot_physics import (
    PotColor,
    PotMaterial,
    SunExposure,
)
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------
#  Definizione delle varianti
# -----------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    """Una configurazione di vaso da confrontare con le altre."""
    name: str
    color_hex: str  # colore della linea nel grafico
    material: PotMaterial
    color: PotColor
    exposure: SunExposure


# Otto varianti scelte per coprire i casi più rappresentativi: dai
# vasi più "assetati" (terracotta scura al sole) a quelli più
# "tranquilli" (plastica chiara all'ombra), con scenari intermedi.
VARIANTS = [
    Variant("Plastica chiara, sole",
            "#4682B4", PotMaterial.PLASTIC, PotColor.LIGHT,
            SunExposure.FULL_SUN),
    Variant("Plastica scura, sole",
            "#1F4E79", PotMaterial.PLASTIC, PotColor.DARK,
            SunExposure.FULL_SUN),
    Variant("Terracotta media, sole",
            "#D2691E", PotMaterial.TERRACOTTA, PotColor.MEDIUM,
            SunExposure.FULL_SUN),
    Variant("Terracotta scura, sole",
            "#8B0000", PotMaterial.TERRACOTTA, PotColor.DARK,
            SunExposure.FULL_SUN),
    Variant("Ceramica smaltata, sole",
            "#9370DB", PotMaterial.GLAZED_CERAMIC, PotColor.MEDIUM,
            SunExposure.FULL_SUN),
    Variant("Plastica scura, ombra parz.",
            "#2E8B57", PotMaterial.PLASTIC, PotColor.DARK,
            SunExposure.PARTIAL_SHADE),
    Variant("Terracotta media, ombra parz.",
            "#FF8C00", PotMaterial.TERRACOTTA, PotColor.MEDIUM,
            SunExposure.PARTIAL_SHADE),
    Variant("Plastica chiara, ombra",
            "#008080", PotMaterial.PLASTIC, PotColor.LIGHT,
            SunExposure.SHADE),
]


# -----------------------------------------------------------------------
#  Costruzione del vaso e meteo sintetico
# -----------------------------------------------------------------------

PLANTING_DATE = date(2026, 4, 15)
SIM_START = date(2026, 5, 1)         # piena fase mid-season
SIM_DAYS = 30


def make_pot(variant: Variant) -> Pot:
    """Crea un vaso configurato per la variante data."""
    return Pot(
        label=variant.name,
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0,
        pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=PLANTING_DATE,
        pot_material=variant.material,
        pot_color=variant.color,
        sun_exposure=variant.exposure,
    )


def synthetic_weather() -> tuple[list[float], list[float]]:
    """
    Genera un meteo sintetico tipico per maggio a Milano:
      - ET₀ oscillante fra 2.5 e 5.5 mm/giorno (tendenza crescente);
      - tre eventi di pioggia leggera distribuiti nel mese.
    Usato uniformemente per tutte le varianti, così che le differenze
    tra le traiettorie dipendano solo dal vaso.
    """
    et0_series = []
    rain_series = []
    rng = np.random.default_rng(seed=42)
    for d in range(SIM_DAYS):
        # Trend ascendente con rumore: 3.0 → 5.0 mm/giorno.
        base = 3.0 + 2.0 * (d / SIM_DAYS)
        noise = rng.normal(0, 0.4)
        et0_series.append(max(1.5, base + noise))
        rain_series.append(0.0)

    # Tre eventi di pioggia.
    for day, mm in [(7, 8.0), (15, 5.0), (22, 12.0)]:
        rain_series[day] = mm
    return et0_series, rain_series


# -----------------------------------------------------------------------
#  Simulazione
# -----------------------------------------------------------------------

@dataclass
class SimResult:
    """Esito di una simulazione singola: stati giornalieri ed eventi."""
    variant: Variant
    states_mm: list[float]
    irrigation_days: list[int]    # indici dei giorni in cui si è irrigato
    irrigation_amounts: list[float]  # mm aggiunti

    @property
    def num_irrigations(self) -> int:
        return len(self.irrigation_days)

    @property
    def total_water_mm(self) -> float:
        return sum(self.irrigation_amounts)


def simulate(
    variant: Variant,
    et0_series: list[float],
    rain_series: list[float],
) -> SimResult:
    """
    Simula la traiettoria idrica di un vaso per SIM_DAYS giorni,
    irrigando ogni volta che si scende sotto la soglia di allerta.

    L'irrigazione riporta il vaso a capacità di campo (water_to_field_capacity).
    """
    pot = make_pot(variant)
    states = [pot.state_mm]  # stato iniziale (= FC, dal __post_init__)
    irr_days: list[int] = []
    irr_amounts: list[float] = []

    for day_idx in range(SIM_DAYS):
        current_date = SIM_START + timedelta(days=day_idx)
        et_0 = et0_series[day_idx]
        rain = rain_series[day_idx]

        # Decisione: se il vaso è in allerta, irriga PRIMA del bilancio.
        if pot.state_mm < pot.alert_mm:
            irrigation = pot.water_to_field_capacity()
            irr_days.append(day_idx)
            irr_amounts.append(irrigation)
        else:
            irrigation = 0.0

        # Bilancio del giorno con pioggia + (eventuale) irrigazione.
        pot.apply_balance_step(
            et_0_mm=et_0,
            water_input_mm=rain + irrigation,
            current_date=current_date,
        )
        states.append(pot.state_mm)

    return SimResult(
        variant=variant,
        states_mm=states,
        irrigation_days=irr_days,
        irrigation_amounts=irr_amounts,
    )


# -----------------------------------------------------------------------
#  Plot
# -----------------------------------------------------------------------

def plot_comparison(
    results: list[SimResult],
    et0_series: list[float],
    rain_series: list[float],
) -> Path:
    """
    Due pannelli sovrapposti:
      1. Traiettorie idriche delle 8 varianti, con marker irrigazioni.
      2. Bar chart orizzontale del numero di irrigazioni per variante.
    """
    fig, (ax_traj, ax_bar) = plt.subplots(
        2, 1, figsize=(12, 10),
        gridspec_kw={"height_ratios": [2.5, 1.0]},
    )

    fig.suptitle(
        "Effetto delle caratteristiche del vaso sul fabbisogno idrico\n"
        f"Basilico, vaso 5 L cilindrico, {SIM_DAYS} giorni di simulazione "
        f"(maggio Milano)",
        fontsize=13, fontweight="bold", y=0.995,
    )

    # --- Pannello superiore: traiettorie ---
    days = list(range(SIM_DAYS + 1))

    # Soglie di riferimento (uguali per tutte le varianti).
    sample_pot = make_pot(VARIANTS[0])
    fc = sample_pot.fc_mm
    alert = sample_pot.alert_mm
    pwp = sample_pot.pwp_mm

    ax_traj.axhline(fc, color="#888", linestyle="-", linewidth=0.8,
                    alpha=0.5)
    ax_traj.text(SIM_DAYS, fc, " FC", color="#666",
                 fontsize=8, va="center")
    ax_traj.axhline(alert, color="#cc8800", linestyle="--", linewidth=0.8,
                    alpha=0.6)
    ax_traj.text(SIM_DAYS, alert, " soglia", color="#cc8800",
                 fontsize=8, va="center")
    ax_traj.axhline(pwp, color="#cc0000", linestyle=":", linewidth=0.8,
                    alpha=0.5)
    ax_traj.text(SIM_DAYS, pwp, " PWP", color="#cc0000",
                 fontsize=8, va="center")

    for r in results:
        ax_traj.plot(days, r.states_mm,
                     color=r.variant.color_hex,
                     linewidth=1.8,
                     label=f"{r.variant.name} (Kp={make_pot(r.variant).kp:.2f})")
        # Marker per ogni irrigazione.
        if r.irrigation_days:
            ax_traj.scatter(
                r.irrigation_days,
                [r.states_mm[d] for d in r.irrigation_days],
                color=r.variant.color_hex, marker="v",
                s=40, zorder=5, edgecolors="black", linewidth=0.5,
            )

    ax_traj.set_xlabel("Giorno della simulazione")
    ax_traj.set_ylabel("Acqua nel substrato (mm)")
    ax_traj.set_xlim(0, SIM_DAYS + 0.5)
    # Restringo al range significativo per leggibilità: poco sotto PWP
    # (per vedere chiaramente la soglia rossa) fino a poco sopra FC
    # (per vedere i picchi post-irrigazione).
    ax_traj.set_ylim(pwp - 4, fc + 3)
    ax_traj.grid(True, alpha=0.3)
    ax_traj.legend(loc="lower left", fontsize=8.5,
                   framealpha=0.95, ncol=2)

    # --- Pannello inferiore: bar chart numero irrigazioni ---
    # Ordino le varianti dal meno al più assetato per leggibilità.
    sorted_results = sorted(results, key=lambda r: r.num_irrigations)
    names = [r.variant.name for r in sorted_results]
    counts = [r.num_irrigations for r in sorted_results]
    colors = [r.variant.color_hex for r in sorted_results]
    kps = [make_pot(r.variant).kp for r in sorted_results]

    y_pos = np.arange(len(sorted_results))
    bars = ax_bar.barh(y_pos, counts, color=colors,
                       edgecolor="black", linewidth=0.4, alpha=0.85)
    ax_bar.set_yticks(y_pos)
    ax_bar.set_yticklabels(names, fontsize=9)
    ax_bar.set_xlabel("Numero di irrigazioni in 30 giorni")
    ax_bar.grid(True, alpha=0.3, axis="x")

    # Etichetta numerica + Kp accanto a ogni barra.
    for bar, count, kp in zip(bars, counts, kps):
        ax_bar.text(bar.get_width() + 0.15,
                    bar.get_y() + bar.get_height() / 2,
                    f"{count}  (Kp={kp:.2f})",
                    fontsize=9, va="center")

    # Spazio sulla destra per le etichette.
    ax_bar.set_xlim(0, max(counts) * 1.30)

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = OUTPUT_DIR / "pot_characteristics_comparison.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Report testuale
# -----------------------------------------------------------------------

def print_report(results: list[SimResult]) -> None:
    """Tabella ordinata: variante, Kp, irrigazioni, totale acqua."""
    print()
    print("=" * 78)
    print(f"{'Variante':<35} | {'Kp':>5} | {'Irr.':>5} | "
          f"{'Acqua tot':>10}")
    print("-" * 78)
    sorted_results = sorted(results, key=lambda r: r.num_irrigations)
    for r in sorted_results:
        kp = make_pot(r.variant).kp
        print(f"{r.variant.name:<35} | "
              f"{kp:>5.2f} | "
              f"{r.num_irrigations:>5d} | "
              f"{r.total_water_mm:>7.1f} mm")
    print("=" * 78)

    # Estremi.
    min_r = min(results, key=lambda r: r.num_irrigations)
    max_r = max(results, key=lambda r: r.num_irrigations)
    print()
    print(f"Vaso più «sereno»:    {min_r.variant.name}")
    print(f"   → {min_r.num_irrigations} irrigazioni, "
          f"{min_r.total_water_mm:.1f} mm totali in 30 giorni.")
    print(f"Vaso più «assetato»:  {max_r.variant.name}")
    print(f"   → {max_r.num_irrigations} irrigazioni, "
          f"{max_r.total_water_mm:.1f} mm totali in 30 giorni.")
    delta_irr = max_r.num_irrigations - min_r.num_irrigations
    delta_water = max_r.total_water_mm - min_r.total_water_mm
    print(f"\nDifferenza:           +{delta_irr} irrigazioni "
          f"(+{delta_water:.1f} mm) — pari a "
          f"{delta_water / min_r.total_water_mm * 100:.0f}% in più "
          f"rispetto al vaso più sereno.")


# -----------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("Demo: effetto delle caratteristiche del vaso")
    print("=" * 70)
    print(f"\nGenero meteo sintetico per {SIM_DAYS} giorni a partire da "
          f"{SIM_START.isoformat()}...")
    et0_series, rain_series = synthetic_weather()
    print(f"   ET₀ medio: {sum(et0_series) / len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm "
          f"(in {sum(1 for r in rain_series if r > 0)} eventi)")

    print(f"\nSimulo {len(VARIANTS)} varianti del vaso...")
    results = []
    for v in VARIANTS:
        r = simulate(v, et0_series, rain_series)
        results.append(r)
        kp = make_pot(v).kp
        print(f"   • {v.name:<36} Kp={kp:.2f}  →  "
              f"{r.num_irrigations} irrigazioni")

    print_report(results)

    print("\nGenerazione grafico di confronto...")
    p = plot_comparison(results, et0_series, rain_series)
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
