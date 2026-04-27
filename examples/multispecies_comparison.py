"""
Confronto multi-specie sullo stesso scenario meteorologico.

Esegue la simulazione di 14 giorni a Milano in piena estate per tutte
e cinque le specie del catalogo `domain.species`, mantenendo
costanti tutti gli altri parametri (vaso, substrato, meteo, stadio
fenologico, condizione iniziale). L'unica variabile è la specie, così
che le differenze osservate siano attribuibili integralmente ai suoi
parametri agronomici (Kc, p).

Produce due figure:

  1. multispecies_water_trajectories.png
     Cinque curve di contenuto idrico sovrapposte. Le bande di zona
     non sono colorate (varierebbero per specie e renderebbero il
     grafico illeggibile); al loro posto, ogni curva ha un marker
     speciale nel giorno in cui ha attraversato la propria soglia di
     allerta personale.

  2. multispecies_ks_trajectories.png
     Cinque curve di Ks(t) per le cinque specie. Mostra la dinamica
     temporale dello stress idrico e fa emergere le differenze di
     comportamento meglio di qualunque tabella numerica.

Esegui con:
    python examples/multispecies_comparison.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.species import (
    ALL_SPECIES,
    PhenologicalStage,
    actual_et_c,
)
from fitosim.science.balance import (
    stress_coefficient_ks,
    water_balance_step_mm,
)
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import (
    UNIVERSAL_POTTING_SOIL,
    circular_pot_surface_area_m2,
    mm_to_theta,
    pot_substrate_depth_mm,
    readily_available_water,
)


# -----------------------------------------------------------------------
#  Parametri dello scenario (identici alle simulazioni precedenti)
# -----------------------------------------------------------------------
LATITUDE_DEG = 45.47
START_DATE = date(2025, 7, 15)
N_DAYS = 14
POT_VOLUME_L = 5.0
POT_DIAMETER_CM = 20.0
SUBSTRATE = UNIVERSAL_POTTING_SOIL
STAGE = PhenologicalStage.MID_SEASON

DAILY_TEMPERATURES = [
    (19.0, 31.0), (20.0, 32.0), (21.0, 33.0), (20.0, 31.0),
    (18.0, 28.0), (17.0, 26.0), (18.0, 28.0), (20.0, 30.0),
    (21.0, 32.0), (22.0, 33.0), (22.0, 34.0), (21.0, 32.0),
    (19.0, 29.0), (19.0, 28.0),
]

# Palette: cinque tinte distinguibili anche da chi ha daltonismo
# (tableau qualitative palette, ordinata in modo che colori adiacenti
# nel catalogo risultino visivamente lontani).
SPECIES_COLORS = {
    "Basilico":       "tab:blue",
    "Pomodoro":       "tab:red",
    "Lattuga":        "tab:green",
    "Limone in vaso": "tab:purple",
    "Rosmarino":      "tab:olive",
}

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =======================================================================
#  Esecuzione delle cinque simulazioni
# =======================================================================

def run_all_species() -> dict:
    """
    Lancia la simulazione di N_DAYS giorni per ciascuna specie del
    catalogo, restituendo un dizionario {nome_specie: {traiettorie, ...}}
    pronto per essere plottato.
    """
    surface_area = circular_pot_surface_area_m2(POT_DIAMETER_CM)
    depth_mm = pot_substrate_depth_mm(POT_VOLUME_L, surface_area)
    fc_mm = SUBSTRATE.theta_fc * depth_mm
    pwp_mm = SUBSTRATE.theta_pwp * depth_mm

    # Pre-calcoliamo l'ET₀ del giorno una sola volta: è meteo, comune
    # a tutte le specie. Risparmia 5N chiamate ridondanti al modulo et0.
    et0_per_day = []
    for day_index in range(N_DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        j = day_of_year(current_date)
        t_min, t_max = DAILY_TEMPERATURES[day_index]
        et0_per_day.append(
            et0_hargreaves_samani(t_min, t_max, LATITUDE_DEG, j)
        )

    results = {}
    for species in ALL_SPECIES:
        # Soglia di allerta in mm, specifica per questa specie via p.
        raw_fraction = readily_available_water(
            SUBSTRATE, species.depletion_fraction
        )
        alert_mm = (SUBSTRATE.theta_fc - raw_fraction) * depth_mm

        state_mm = fc_mm
        states = [state_mm]
        ks_values = []
        first_alert_day = None

        for day_index in range(N_DAYS):
            theta_now = mm_to_theta(state_mm, depth_mm)
            ks = stress_coefficient_ks(
                theta_now, SUBSTRATE, species.depletion_fraction
            )
            ks_values.append(ks)

            et_c_act = actual_et_c(
                species, STAGE, et0_per_day[day_index],
                current_theta=theta_now, substrate=SUBSTRATE,
            )
            result = water_balance_step_mm(
                current_mm=state_mm, water_input_mm=0.0,
                et_c_mm=et_c_act, substrate=SUBSTRATE,
                substrate_depth_mm=depth_mm,
                depletion_fraction=species.depletion_fraction,
            )
            state_mm = result.new_state
            states.append(state_mm)

            # Cattura del primo giorno di allerta: ci servirà come
            # marker speciale sul grafico delle traiettorie.
            if first_alert_day is None and result.under_alert:
                first_alert_day = day_index + 1  # +1 perché states[0]
                # è giorno 0, e l'allerta è valutata sullo stato post-step

        results[species.common_name] = {
            "species": species,
            "states": states,
            "ks_values": ks_values,
            "alert_mm": alert_mm,
            "first_alert_day": first_alert_day,
        }

    return {
        "per_species": results,
        "fc_mm": fc_mm,
        "pwp_mm": pwp_mm,
        "depth_mm": depth_mm,
    }


# =======================================================================
#  Grafico 1 — Traiettorie di contenuto idrico
# =======================================================================

def plot_water_trajectories(sim: dict) -> Path:
    """
    Cinque curve di contenuto idrico sovrapposte. Solo FC e PWP come
    riferimenti; il marker speciale 'X' indica il giorno della prima
    allerta per ciascuna specie.
    """
    days = np.arange(0, N_DAYS + 1)

    fig, ax = plt.subplots(figsize=(11.5, 6.5))

    # Soglie geometricamente comuni a tutte le specie.
    ax.axhline(sim["fc_mm"], linestyle="--", color="darkgreen",
               linewidth=1.0, alpha=0.6)
    ax.axhline(sim["pwp_mm"], linestyle="--", color="darkred",
               linewidth=1.0, alpha=0.6)
    ax.text(N_DAYS + 0.3, sim["fc_mm"], f"FC ({sim['fc_mm']:.1f})",
            verticalalignment="center", fontsize=9, color="darkgreen")
    ax.text(N_DAYS + 0.3, sim["pwp_mm"], f"PWP ({sim['pwp_mm']:.1f})",
            verticalalignment="center", fontsize=9, color="darkred")

    # Una traiettoria per specie, con marker di allerta dedicato.
    for name, data in sim["per_species"].items():
        color = SPECIES_COLORS[name]
        ax.plot(days, data["states"],
                color=color, linewidth=2.2, marker="o", markersize=5,
                label=f"{name} (p={data['species'].depletion_fraction})",
                zorder=4)

        # Marker dell'allerta: una "X" colorata sul giorno di trigger.
        if data["first_alert_day"] is not None:
            d = data["first_alert_day"]
            ax.scatter(
                [d], [data["states"][d]],
                marker="X", s=180, color=color,
                edgecolors="black", linewidths=1.4, zorder=6,
            )

    ax.set_xlabel("Giorno della simulazione")
    ax.set_ylabel("Contenuto idrico (mm)")
    ax.set_title(
        f"Cinque specie a confronto — stesso vaso ({POT_VOLUME_L:.0f} L "
        f"di {SUBSTRATE.name.lower()}), Milano, 14 giorni dal "
        f"{START_DATE.isoformat()}"
    )
    ax.set_xlim(-0.5, N_DAYS + 2.0)
    ax.set_ylim(sim["pwp_mm"] - 3, sim["fc_mm"] * 1.05)
    ax.grid(True, alpha=0.25)

    # Annotazione metodologica della "X": il marker non è ovvio,
    # un'etichetta esplicita evita ambiguità.
    ax.legend(loc="upper right", framealpha=0.92, fontsize=9, ncol=1)
    ax.text(
        0.5, sim["pwp_mm"] - 1.5,
        "Marker ✕ = primo giorno di allerta per ciascuna specie",
        fontsize=8.5, color="dimgray", style="italic",
    )

    path = OUTPUT_DIR / "multispecies_water_trajectories.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Grafico 2 — Traiettorie del coefficiente di stress Ks
# =======================================================================

def plot_ks_trajectories(sim: dict) -> Path:
    """
    Cinque curve di Ks(t). Mette in evidenza visivamente quando ogni
    specie inizia a "frenare" la traspirazione e con quale velocità.
    """
    # Asse temporale: Ks è valutato pre-step, quindi N_DAYS valori.
    days = np.arange(1, N_DAYS + 1)

    fig, ax = plt.subplots(figsize=(11.5, 5.5))

    # Linea di riferimento Ks=1 (zona di comfort).
    ax.axhline(1.0, linestyle=":", color="dimgray",
               linewidth=1.0, alpha=0.7)

    for name, data in sim["per_species"].items():
        color = SPECIES_COLORS[name]
        ax.plot(days, data["ks_values"],
                color=color, linewidth=2.2, marker="o", markersize=5,
                label=f"{name} (p={data['species'].depletion_fraction})")

    ax.set_xlabel("Giorno della simulazione")
    ax.set_ylabel("Coefficiente di stress Ks")
    ax.set_title(
        "Dinamica dello stress idrico Ks per ciascuna specie "
        "nello stesso scenario"
    )
    ax.set_xlim(0.5, N_DAYS + 0.5)
    ax.set_ylim(-0.05, 1.10)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower left", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "multispecies_ks_trajectories.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Stampa tabellare riassuntiva
# =======================================================================

def print_summary(sim: dict) -> None:
    """
    Tabella sintetica: per ogni specie, giorno di prima allerta, Ks
    finale e contenuto idrico finale. Aiuta a quantificare ciò che i
    grafici mostrano qualitativamente.
    """
    header = (
        f"{'Specie':<18} {'Kc_mid':>7} {'p':>5} "
        f"{'Allerta':>8} {'Ks fine':>8} {'Stato fine':>11}"
    )
    print(header)
    print("-" * len(header))

    for name, data in sim["per_species"].items():
        s = data["species"]
        alert_str = (
            f"giorno {data['first_alert_day']}"
            if data["first_alert_day"] is not None
            else "mai"
        )
        print(
            f"{name:<18} {s.kc_mid:>7.2f} {s.depletion_fraction:>5.2f} "
            f"{alert_str:>8} {data['ks_values'][-1]:>8.3f} "
            f"{data['states'][-1]:>9.1f} mm"
        )


# =======================================================================
#  Entry point
# =======================================================================

def main() -> None:
    sim = run_all_species()
    print_summary(sim)
    print()
    print("Generazione grafici...")
    p1 = plot_water_trajectories(sim)
    print(f"  [1/2] {p1.name}")
    p2 = plot_ks_trajectories(sim)
    print(f"  [2/2] {p2.name}")
    print(f"\nSalvati in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
