"""
Demo: composizione di substrati personalizzati dai materiali base.

La libreria espone un catalogo di nove materiali base (torba bionda
e bruna, perlite, vermiculite, fibra di cocco, pomice, sabbia,
akadama, lapillo) e una funzione `compose_substrate` che li mescola
con frazioni volumetriche personalizzate, calcolando le proprietà
idrauliche risultanti come media pesata.

Il demo confronta tre vasi gemelli di basilico, identici in tutto
(specie, dimensioni, meteo, data di impianto, posizione) tranne che
per il substrato, che viene costruito con tre ricette diverse:

  1. Mix professionale: 70% torba bionda + 30% perlite. È la ricetta
     standard per la coltivazione domestica e vivaistica, equilibrata
     tra ritenzione idrica e drenaggio.

  2. Mix bonsai italiano: 40% akadama + 30% pomice + 30% lapillo. È
     la ricetta classica per bonsai di latifoglie, drenaggio molto
     spinto e bassa ritenzione.

  3. Mix da balcone leggero: 50% torba bionda + 30% fibra di cocco
     + 20% perlite. È un mix con alta ritenzione idrica, pensato
     per ridurre la frequenza di irrigazione su balconi senza tempo
     per cure quotidiane.

Esegui con:
    PYTHONPATH=src python examples/substrate_mix_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.substrate import (
    AKADAMA,
    BIONDA_PEAT,
    COCO_FIBER,
    LAPILLO,
    PERLITE,
    POMICE,
    MixComponent,
    Substrate,
    compose_substrate,
)


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Setup della simulazione: stessi parametri usati negli altri demo
# di questa famiglia, per confrontabilità.
PLANTING_DATE = date(2026, 4, 15)
SIM_START = date(2026, 5, 1)
SIM_DAYS = 30
IRRIGATION_EXCESS = 1.0  # niente eccesso: vogliamo isolare l'effetto
                         # del substrato, non quello del sottovaso.


@dataclass(frozen=True)
class MixRecipe:
    """Una ricetta di mix con label per il grafico e colore."""
    name: str
    color_hex: str
    substrate: Substrate


def make_recipes() -> list[MixRecipe]:
    """Costruisce le tre ricette del demo."""
    professionale = compose_substrate(
        components=[
            MixComponent(BIONDA_PEAT, 0.70),
            MixComponent(PERLITE, 0.30),
        ],
        name="Professionale 70/30",
    )
    bonsai = compose_substrate(
        components=[
            MixComponent(AKADAMA, 0.40),
            MixComponent(POMICE, 0.30),
            MixComponent(LAPILLO, 0.30),
        ],
        name="Bonsai 40/30/30",
    )
    leggero = compose_substrate(
        components=[
            MixComponent(BIONDA_PEAT, 0.50),
            MixComponent(COCO_FIBER, 0.30),
            MixComponent(PERLITE, 0.20),
        ],
        name="Da balcone 50/30/20",
    )
    return [
        MixRecipe("Professionale (torba/perlite)", "#4682B4",
                  professionale),
        MixRecipe("Bonsai italiano (akadama/pomice/lapillo)", "#D2691E",
                  bonsai),
        MixRecipe("Da balcone (torba/cocco/perlite)", "#2E8B57",
                  leggero),
    ]


def make_pot(recipe: MixRecipe) -> Pot:
    """Crea un vaso configurato con il substrato della ricetta."""
    return Pot(
        label=recipe.name,
        species=BASIL,
        substrate=recipe.substrate,
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
    recipe: MixRecipe
    states_mm: list[float]
    irrigation_days: list[int]
    irrigation_amounts: list[float]

    @property
    def num_irrigations(self) -> int:
        return len(self.irrigation_days)

    @property
    def total_water_mm(self) -> float:
        return sum(self.irrigation_amounts)


def simulate(
    recipe: MixRecipe,
    et0_series: list[float],
    rain_series: list[float],
) -> SimResult:
    """Simula 30 giorni del vaso con la sua ricetta di substrato."""
    pot = make_pot(recipe)
    states = [pot.state_mm]
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

        pot.apply_balance_step(
            et_0_mm=et_0,
            water_input_mm=rain + irrigation,
            current_date=current_date,
        )
        states.append(pot.state_mm)

    return SimResult(
        recipe=recipe,
        states_mm=states,
        irrigation_days=irr_days,
        irrigation_amounts=irr_amounts,
    )


def plot_comparison(
    results: list[SimResult],
    et0_series: list[float],
    rain_series: list[float],
) -> Path:
    """
    Tre pannelli: caratterizzazione dei substrati, traiettorie idriche,
    forzanti meteo.
    """
    # constrained_layout gestisce meglio di tight_layout i casi con
    # gridspec complessa e assi twinx (come quello del meteo).
    fig = plt.figure(figsize=(12, 10), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[1.2, 3, 1.0])
    ax_props = fig.add_subplot(gs[0])
    ax_traj = fig.add_subplot(gs[1])
    ax_meteo = fig.add_subplot(gs[2])

    fig.suptitle(
        "Confronto di substrati composti: stesso vaso, ricette diverse\n"
        "Basilico in vaso 5 L, 30 giorni di simulazione (maggio Milano)",
        fontsize=13, fontweight="bold",
    )

    # --- Pannello 1: caratterizzazione delle ricette ---
    # Usiamo etichette brevi nel pannello (la legenda della traiettoria
    # ha quelle complete) per evitare problemi di troncamento orizzontale.
    short_labels = [
        "Professionale\n(torba/perlite)",
        "Bonsai italiano\n(akadama/pomice/lapillo)",
        "Da balcone\n(torba/cocco/perlite)",
    ]
    n_recipes = len(results)
    y_pos = np.arange(n_recipes)
    fc_values = [r.recipe.substrate.theta_fc for r in results]
    pwp_values = [r.recipe.substrate.theta_pwp for r in results]
    taw_values = [fc - pwp for fc, pwp in zip(fc_values, pwp_values)]

    bar_height = 0.35
    ax_props.barh(y_pos - bar_height / 2, fc_values,
                  height=bar_height, color="#4477aa", alpha=0.8,
                  label="θ_FC (capacità di campo)")
    ax_props.barh(y_pos + bar_height / 2, pwp_values,
                  height=bar_height, color="#cc4444", alpha=0.8,
                  label="θ_PWP (punto di appassimento)")

    # Etichetta numerica sulle barre.
    for i, (fc, pwp, taw) in enumerate(
        zip(fc_values, pwp_values, taw_values)
    ):
        ax_props.text(fc + 0.005, i - bar_height / 2,
                      f"{fc:.3f}", va="center", fontsize=9)
        ax_props.text(pwp + 0.005, i + bar_height / 2,
                      f"{pwp:.3f}", va="center", fontsize=9)
        # Annotazione TAW (acqua disponibile = FC - PWP).
        ax_props.text(0.68, i, f"TAW: {taw:.3f}",
                      va="center", fontsize=9, color="dimgray",
                      style="italic")

    ax_props.set_yticks(y_pos)
    ax_props.set_yticklabels(short_labels, fontsize=9)
    ax_props.set_xlabel("Contenuto idrico volumetrico θ")
    ax_props.set_xlim(0, 0.85)
    ax_props.set_title("Caratterizzazione dei substrati composti",
                       fontsize=11, color="tab:gray")
    ax_props.legend(loc="lower right", fontsize=9, framealpha=0.9)
    ax_props.grid(True, alpha=0.3, axis="x")
    ax_props.invert_yaxis()  # primo recipe in alto

    # --- Pannello 2: traiettorie idriche ---
    days = list(range(SIM_DAYS + 1))

    # Le soglie cambiano per ogni vaso (dipendono dal substrato), quindi
    # plot delle soglie del primo vaso solo come riferimento visivo
    # principale. Per chiarezza segniamo PWP del peggiore e FC del migliore.
    sample_pots = [make_pot(r.recipe) for r in results]

    # Plot delle traiettorie.
    for r, pot in zip(results, sample_pots):
        ax_traj.plot(days, r.states_mm,
                     color=r.recipe.color_hex, linewidth=2.2,
                     label=f"{r.recipe.name} ({r.num_irrigations} irrig.)")
        if r.irrigation_days:
            ax_traj.scatter(
                r.irrigation_days,
                [r.states_mm[d] for d in r.irrigation_days],
                color=r.recipe.color_hex, marker="v", s=50, zorder=5,
                edgecolors="black", linewidth=0.5,
            )

    # Soglie di riferimento per ciascuna ricetta, con testo accanto.
    for r, pot in zip(results, sample_pots):
        ax_traj.axhline(pot.fc_mm, color=r.recipe.color_hex,
                        linestyle=":", linewidth=0.6, alpha=0.5)

    ax_traj.set_xlabel("Giorno della simulazione")
    ax_traj.set_ylabel("Acqua nel substrato (mm)")
    ax_traj.set_title("Traiettorie idriche dei tre vasi",
                      fontsize=11, color="tab:gray")
    ax_traj.set_xlim(0, SIM_DAYS + 0.5)
    ax_traj.grid(True, alpha=0.3)
    ax_traj.legend(loc="upper right", fontsize=9, framealpha=0.95)

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

    # constrained_layout (impostato a True nel costruttore della figure)
    # gestisce automaticamente lo spaziamento tra i pannelli, anche con
    # gridspec complessa e assi twinx come quello del meteo. Nessuna
    # chiamata esplicita a tight_layout o subplots_adjust è necessaria.
    path = OUTPUT_DIR / "substrate_mix_comparison.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def print_report(results: list[SimResult]) -> None:
    """Tabella sintetica delle tre ricette e dei risultati."""
    print()
    print("=" * 78)
    print("Caratterizzazione dei substrati e risultati della simulazione")
    print("=" * 78)
    print(f"\n{'Ricetta':<42} | {'θ_FC':>5} | {'θ_PWP':>6} | "
          f"{'TAW':>5} | {'Irr.':>4}")
    print("-" * 78)
    for r in results:
        s = r.recipe.substrate
        taw = s.theta_fc - s.theta_pwp
        print(f"{r.recipe.name:<42} | "
              f"{s.theta_fc:>5.3f} | "
              f"{s.theta_pwp:>6.3f} | "
              f"{taw:>5.3f} | "
              f"{r.num_irrigations:>4d}")
    print("=" * 78)

    # Identifico il più ritentivo e il più drenante.
    most_retentive = max(
        results,
        key=lambda r: r.recipe.substrate.theta_fc - r.recipe.substrate.theta_pwp,
    )
    most_draining = min(
        results,
        key=lambda r: r.recipe.substrate.theta_fc - r.recipe.substrate.theta_pwp,
    )
    print()
    print(f"Più ritentivo: {most_retentive.recipe.name}")
    print(f"   TAW = {most_retentive.recipe.substrate.theta_fc - most_retentive.recipe.substrate.theta_pwp:.3f}, "
          f"{most_retentive.num_irrigations} irrigazioni in 30 giorni")
    print(f"Più drenante:  {most_draining.recipe.name}")
    print(f"   TAW = {most_draining.recipe.substrate.theta_fc - most_draining.recipe.substrate.theta_pwp:.3f}, "
          f"{most_draining.num_irrigations} irrigazioni in 30 giorni")


def main() -> None:
    print("=" * 70)
    print("Demo: composizione di substrati dai materiali base")
    print("=" * 70)

    print("\nCostruzione delle tre ricette tramite compose_substrate()...")
    recipes = make_recipes()
    for r in recipes:
        s = r.substrate
        print(f"   • {r.name}")
        print(f"     → θ_FC={s.theta_fc:.3f}, θ_PWP={s.theta_pwp:.3f}, "
              f"TAW={s.theta_fc - s.theta_pwp:.3f}")

    print("\nGenerazione meteo sintetico...")
    et0_series, rain_series = synthetic_weather()
    print(f"   ET₀ medio: {sum(et0_series) / len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm")

    print("\nSimulazione dei tre vasi gemelli...")
    results = []
    for r in recipes:
        res = simulate(r, et0_series, rain_series)
        results.append(res)
        print(f"   • {r.name:<45} → {res.num_irrigations} irrigazioni")

    print_report(results)

    print("\nGenerazione grafico di confronto...")
    p = plot_comparison(results, et0_series, rain_series)
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
