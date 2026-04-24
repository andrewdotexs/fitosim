"""
Confronto simulazione: ET_c potenziale vs ET_c reale (con Ks).

Ripete la simulazione di 14 giorni del vaso a Milano, ma questa volta
utilizzando il basilico come specie reale (Kc e p dal catalogo
`domain.species`). Produce due figure:

  1. simulation_potential_vs_actual.png
     Due traiettorie sovrapposte sullo stesso asse temporale: la
     simulazione "potenziale" (senza Ks, ET_c = Kc × ET_0) e la
     simulazione "reale" (con Ks, ET_c,act = Ks × Kc × ET_0). Mostra
     visivamente come Ks risolva il plateau terminale trasformando
     il clipping brusco a PWP in un avvicinamento asintotico.

  2. ks_function_shape.png
     La funzione Ks(θ) plottata in isolamento, per illustrarne la
     forma a tratti lineare con i tre regimi (comfort, stress, oltre
     PWP). È il diagramma classico di FAO-56 eq. 84.

Esegui dalla radice del progetto con:
    python examples/basil_with_stress_coefficient.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.species import (
    BASIL,
    PhenologicalStage,
    actual_et_c,
    kc_for_stage,
    potential_et_c,
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
    theta_to_mm,
)


# -----------------------------------------------------------------------
#  Parametri dello scenario
# -----------------------------------------------------------------------
LATITUDE_DEG = 45.47
START_DATE = date(2025, 7, 15)
N_DAYS = 14
POT_VOLUME_L = 5.0
POT_DIAMETER_CM = 20.0
SUBSTRATE = UNIVERSAL_POTTING_SOIL
SPECIES = BASIL
STAGE = PhenologicalStage.MID_SEASON

# Stesse temperature sintetiche dell'esempio precedente, per
# comparabilità diretta.
DAILY_TEMPERATURES = [
    (19.0, 31.0), (20.0, 32.0), (21.0, 33.0), (20.0, 31.0),
    (18.0, 28.0), (17.0, 26.0), (18.0, 28.0), (20.0, 30.0),
    (21.0, 32.0), (22.0, 33.0), (22.0, 34.0), (21.0, 32.0),
    (19.0, 29.0), (19.0, 28.0),
]

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =======================================================================
#  Esecuzione della simulazione in due regimi
# =======================================================================

def run_simulations() -> dict:
    """
    Esegue le due simulazioni (potenziale e reale) in parallelo sullo
    stesso scenario meteorologico, collezionando le traiettorie
    giornaliere di stato, ET applicata e coefficiente Ks.
    """
    surface_area = circular_pot_surface_area_m2(POT_DIAMETER_CM)
    depth_mm = pot_substrate_depth_mm(POT_VOLUME_L, surface_area)
    fc_mm = SUBSTRATE.theta_fc * depth_mm
    pwp_mm = SUBSTRATE.theta_pwp * depth_mm
    raw_fraction = readily_available_water(
        SUBSTRATE, SPECIES.depletion_fraction
    )
    alert_mm = (SUBSTRATE.theta_fc - raw_fraction) * depth_mm

    # Condizione iniziale comune: vaso appena irrigato.
    state_pot = fc_mm
    state_act = fc_mm
    states_pot = [state_pot]
    states_act = [state_act]
    et_pot_values = []
    et_act_values = []
    ks_values = []

    for day_index in range(N_DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        j = day_of_year(current_date)
        t_min, t_max = DAILY_TEMPERATURES[day_index]

        et0_mm = et0_hargreaves_samani(t_min, t_max, LATITUDE_DEG, j)

        # --- Simulazione potenziale: ET_c = Kc × ET_0, nessuna riduzione.
        et_c_pot = potential_et_c(SPECIES, STAGE, et0_mm)
        result_pot = water_balance_step_mm(
            current_mm=state_pot, water_input_mm=0.0,
            et_c_mm=et_c_pot, substrate=SUBSTRATE,
            substrate_depth_mm=depth_mm,
            depletion_fraction=SPECIES.depletion_fraction,
        )
        state_pot = result_pot.new_state
        states_pot.append(state_pot)
        et_pot_values.append(et_c_pot)

        # --- Simulazione reale: ET_c,act = Ks × Kc × ET_0.
        # Calcoliamo Ks usando lo stato corrente convertito in θ.
        theta_act = mm_to_theta(state_act, depth_mm)
        ks = stress_coefficient_ks(
            theta_act, SUBSTRATE, SPECIES.depletion_fraction
        )
        et_c_act = actual_et_c(
            SPECIES, STAGE, et0_mm,
            current_theta=theta_act, substrate=SUBSTRATE,
        )
        result_act = water_balance_step_mm(
            current_mm=state_act, water_input_mm=0.0,
            et_c_mm=et_c_act, substrate=SUBSTRATE,
            substrate_depth_mm=depth_mm,
            depletion_fraction=SPECIES.depletion_fraction,
        )
        state_act = result_act.new_state
        states_act.append(state_act)
        et_act_values.append(et_c_act)
        ks_values.append(ks)

    return {
        "states_pot": states_pot,
        "states_act": states_act,
        "et_pot": et_pot_values,
        "et_act": et_act_values,
        "ks_values": ks_values,
        "depth_mm": depth_mm,
        "fc_mm": fc_mm,
        "pwp_mm": pwp_mm,
        "alert_mm": alert_mm,
    }


# =======================================================================
#  Grafico 1 — Confronto delle due traiettorie
# =======================================================================

def plot_potential_vs_actual(sim: dict) -> Path:
    """
    Due traiettorie sullo stesso asse: rossa = ET potenziale (vecchio
    modello, con plateau), blu = ET reale con Ks (asintotica verso PWP).
    Le zone di comfort/stress sono indicate come nel primo timeline.
    """
    days = np.arange(0, N_DAYS + 1)

    fig, ax = plt.subplots(figsize=(11, 6))

    # Bande di zona, coerenti con le altre figure della libreria.
    ax.axhspan(sim["alert_mm"], sim["fc_mm"], alpha=0.18,
               color="tab:green", label="Zona comfort")
    ax.axhspan(sim["pwp_mm"], sim["alert_mm"], alpha=0.20,
               color="tab:orange", label="Zona stress")
    ax.axhspan(0, sim["pwp_mm"], alpha=0.20,
               color="tab:red", label="Sotto PWP")

    # Soglie di riferimento.
    for value, label, color in [
        (sim["fc_mm"], "FC", "darkgreen"),
        (sim["alert_mm"], "Allerta", "darkorange"),
        (sim["pwp_mm"], "PWP", "darkred"),
    ]:
        ax.axhline(value, linestyle="--", color=color,
                   linewidth=1.0, alpha=0.7)
        ax.text(N_DAYS + 0.3, value,
                f"{label} ({value:.1f} mm)",
                verticalalignment="center", fontsize=9, color=color)

    # Traiettoria potenziale: quella vecchia, clippa brutalmente a PWP.
    ax.plot(days, sim["states_pot"],
            color="tab:red", linewidth=2.2, marker="s",
            markersize=6, linestyle="--", alpha=0.85,
            label="Potenziale (senza Ks) — plateau brusco", zorder=4)

    # Traiettoria reale: con Ks, curva asintotica.
    ax.plot(days, sim["states_act"],
            color="tab:blue", linewidth=2.5, marker="o",
            markersize=6.5,
            label="Reale (con Ks) — asintotica", zorder=5)

    ax.set_xlabel("Giorno della simulazione")
    ax.set_ylabel("Contenuto idrico (mm)")
    ax.set_title(
        f"Bilancio idrico con e senza coefficiente di stress Ks — "
        f"{SPECIES.common_name}, "
        f"14 giorni dal {START_DATE.isoformat()}, senza pioggia"
    )
    ax.set_xlim(-0.5, N_DAYS + 2.0)
    ax.set_ylim(0, sim["fc_mm"] * 1.15)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "simulation_potential_vs_actual.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Grafico 2 — Forma della funzione Ks
# =======================================================================

def plot_ks_shape(sim: dict) -> Path:
    """
    Plot di Ks(θ) nell'intervallo [0, θ_FC], per mostrare i tre regimi:
    zero sotto PWP, rampa lineare nella zona di stress, plateau a 1 in
    zona di comfort. Una figura didattica che aiuta a leggere la forma
    della legge.
    """
    thetas = np.linspace(0.0, SUBSTRATE.theta_fc, 300)
    ks_values = np.array([
        stress_coefficient_ks(
            float(t), SUBSTRATE, SPECIES.depletion_fraction
        )
        for t in thetas
    ])

    raw_fraction = readily_available_water(
        SUBSTRATE, SPECIES.depletion_fraction
    )
    theta_alert = SUBSTRATE.theta_fc - raw_fraction
    theta_pwp = SUBSTRATE.theta_pwp
    theta_fc = SUBSTRATE.theta_fc

    fig, ax = plt.subplots(figsize=(10, 5.5))

    # Bande di zona sullo sfondo (orizzontali rispetto a θ sull'asse x).
    ax.axvspan(theta_alert, theta_fc, alpha=0.18,
               color="tab:green", label="Zona comfort (Ks=1)")
    ax.axvspan(theta_pwp, theta_alert, alpha=0.20,
               color="tab:orange", label="Zona stress (Ks lineare)")
    ax.axvspan(0, theta_pwp, alpha=0.20,
               color="tab:red", label="Sotto PWP (Ks=0)")

    # Curva Ks(θ).
    ax.plot(thetas, ks_values, color="tab:blue",
            linewidth=2.8, label="Ks(θ)")

    # Linee verticali di riferimento.
    for value, label, color in [
        (theta_pwp, "θ_PWP", "darkred"),
        (theta_alert, "θ_FC − RAW", "darkorange"),
        (theta_fc, "θ_FC", "darkgreen"),
    ]:
        ax.axvline(value, linestyle="--", color=color,
                   linewidth=1.0, alpha=0.7)
        ax.text(value, 1.10, label, rotation=0, fontsize=9,
                color=color, horizontalalignment="center")

    ax.set_xlabel("Contenuto idrico volumetrico θ (adimensionale)")
    ax.set_ylabel("Coefficiente di stress Ks")
    ax.set_title(
        f"Funzione Ks(θ) per {SPECIES.common_name} "
        f"(p = {SPECIES.depletion_fraction})"
    )
    ax.set_xlim(0, theta_fc * 1.02)
    ax.set_ylim(-0.05, 1.20)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="center right", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "ks_function_shape.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Entry point
# =======================================================================

def main() -> None:
    sim = run_simulations()

    # Confronto numerico sintetico dei risultati finali, utile per
    # confermare a occhio che la simulazione reale diverge dalla
    # potenziale al momento giusto.
    print(f"Specie simulata: {SPECIES.common_name} "
          f"(Kc_mid={SPECIES.kc_mid}, p={SPECIES.depletion_fraction})")
    print(f"Stato iniziale: {sim['states_pot'][0]:.1f} mm "
          f"(entrambe le traiettorie)")
    print(f"Stato finale potenziale (senza Ks): "
          f"{sim['states_pot'][-1]:.1f} mm")
    print(f"Stato finale reale (con Ks):      "
          f"{sim['states_act'][-1]:.1f} mm")
    print(f"Differenza finale: "
          f"{sim['states_act'][-1] - sim['states_pot'][-1]:+.1f} mm")
    print()
    print("Generazione grafici...")
    p1 = plot_potential_vs_actual(sim)
    print(f"  [1/2] {p1.name}")
    p2 = plot_ks_shape(sim)
    print(f"  [2/2] {p2.name}")
    print(f"\nSalvati in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
