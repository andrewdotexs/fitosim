"""
Demo: chiusura del feedback loop sensore-modello.

Il modello FAO-56 di fitosim, come ogni modello previsivo, accumula
errore nel tempo se i parametri non sono perfetti. Anche con la
calibrazione empirica della tappa precedente, restano sempre piccole
discrepanze tra la previsione e la realtà: il meteo previsto non è
quello osservato, il giardiniere ha innaffiato un po' più o un po'
meno della dose calcolata, una giornata di vento forte ha asciugato
il vaso più del previsto. Il drift accumula su orizzonti lunghi,
soprattutto quando i parametri sono leggermente sbagliati.

Il metodo Pot.update_from_sensor chiude il feedback loop iniettando
osservazioni reali del sensore WH51 nel modello: ogni volta che il
sensore produce una lettura, il modello la confronta con la propria
previsione, registra la discrepanza, e si allinea alla realtà. È
esattamente la differenza tra un GPS senza segnale satellitare (che
proietta dove pensa di essere) e un GPS con segnale (che si corregge
in tempo reale).

Questo demo mostra il valore operativo di questa correzione su un
esperimento controllato. Tre vasi gemelli simulati per 90 giorni:

  Vaso A (ground truth): parametri corretti del substrato
    (θ_FC=0.42, θ_PWP=0.12). Genera la "realtà" che gli altri
    vasi cercano di seguire e produce lo stream di letture del
    sensore (con rumore).

  Vaso B (modello sbagliato, ciclo aperto): parametri leggermente
    errati (θ_FC=0.50 invece di 0.42, sovrastima del 19%). Riceve
    le stesse irrigazioni del vaso A ma non riceve mai feedback dal
    sensore. Il drift accumula per 90 giorni.

  Vaso C (modello sbagliato + correzione): stessi parametri errati
    di B, stesse irrigazioni di A, ma ogni 7 giorni riceve un
    aggiornamento dal sensore di A (con rumore). La correzione
    settimanale resetta il drift accumulato.

Il grafico finale mostra le tre traiettorie sovrapposte e l'errore
di previsione nel tempo per B e C, dove si vede chiaramente che la
correzione settimanale tiene C vicino alla verità nonostante i
parametri sbagliati, mentre B drifta progressivamente.

Esegui con:
    PYTHONPATH=src python examples/sensor_update_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from random import Random

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot, SensorUpdateResult
from fitosim.domain.species import BASIL
from fitosim.science.substrate import Substrate


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Parametri del substrato "vero" (ground truth) e parametri "sbagliati"
# che il modello dei vasi B e C usa. La differenza simula una
# situazione realistica: il giardiniere ha preso il valore di
# letteratura del substrato senza calibrarlo, e i parametri reali del
# suo vaso specifico sono leggermente diversi.
TRUE_THETA_FC = 0.42
TRUE_THETA_PWP = 0.12
WRONG_THETA_FC = 0.50    # +19% rispetto al vero
WRONG_THETA_PWP = 0.12   # PWP corretto (questo è facile da stimare)

# Setup della simulazione.
PLANTING_DATE = date(2026, 4, 1)
SIM_START = date(2026, 4, 15)
SIM_DAYS = 90
SENSOR_UPDATE_INTERVAL_DAYS = 7  # aggiornamento settimanale del vaso C
SENSOR_NOISE_SIGMA = 0.010
IRRIGATION_EXCESS = 1.05


def make_pot(label: str, fc: float, pwp: float) -> Pot:
    """Crea un vaso con parametri specifici del substrato."""
    substrate = Substrate(
        name=f"sub-{label}",
        theta_fc=fc,
        theta_pwp=pwp,
    )
    return Pot(
        label=label,
        species=BASIL,
        substrate=substrate,
        pot_volume_l=5.0,
        pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=PLANTING_DATE,
    )


def synthetic_weather() -> tuple[list[float], list[float]]:
    """ET₀ stagionale e pioggia stocastica per 90 giorni."""
    rng = np.random.default_rng(seed=123)
    et0_series = []
    rain_series = []
    for d in range(SIM_DAYS):
        # ET₀ tra 3 e 6 mm/giorno con stagionalità leggera.
        season = 4.0 + 1.5 * np.sin(np.pi * d / SIM_DAYS)
        noise = rng.normal(0, 0.5)
        et0_series.append(max(2.0, season + noise))
        # Pioggia: 8% di probabilità per giorno.
        if rng.random() < 0.08:
            rain_series.append(float(rng.exponential(7.0)))
        else:
            rain_series.append(0.0)
    return et0_series, rain_series


@dataclass
class TrajectoryRecord:
    """Esito completo della simulazione di un vaso."""
    label: str
    state_mm_history: list[float]
    state_theta_history: list[float]
    irrigation_days: list[int]
    irrigation_amounts: list[float]
    # Solo per vaso C: storico delle correzioni applicate.
    sensor_updates: list[tuple[int, SensorUpdateResult]]


def simulate_three_pots(
    et0_series: list[float],
    rain_series: list[float],
    rng: Random,
) -> tuple[TrajectoryRecord, TrajectoryRecord, TrajectoryRecord]:
    """
    Simula i tre vasi in parallelo per 90 giorni.

    Strategia di accoppiamento:
      - A è autonomo: decide le proprie irrigazioni e produce la
        traiettoria di riferimento.
      - B e C ricevono le STESSE irrigazioni di A (per isolare l'effetto
        dei parametri sbagliati dall'effetto di decisioni di
        irrigazione diverse).
      - C riceve in più, ogni 7 giorni, un aggiornamento dal sensore
        di A (con rumore).
    """
    pot_A = make_pot("A (ground truth)", TRUE_THETA_FC, TRUE_THETA_PWP)
    pot_B = make_pot("B (parametri sbagliati, no feedback)",
                     WRONG_THETA_FC, WRONG_THETA_PWP)
    pot_C = make_pot("C (parametri sbagliati + sensore)",
                     WRONG_THETA_FC, WRONG_THETA_PWP)

    rec_A = TrajectoryRecord("A", [pot_A.state_mm], [pot_A.state_theta],
                             [], [], [])
    rec_B = TrajectoryRecord("B", [pot_B.state_mm], [pot_B.state_theta],
                             [], [], [])
    rec_C = TrajectoryRecord("C", [pot_C.state_mm], [pot_C.state_theta],
                             [], [], [])

    for day_idx in range(SIM_DAYS):
        current_date = SIM_START + timedelta(days=day_idx)
        et_0 = et0_series[day_idx]
        rain = rain_series[day_idx]

        # Decisione di irrigazione fatta dal vaso A (la realtà).
        # Calcoliamo l'irrigazione PRIMA del bilancio, perché è
        # quella che il giardiniere effettivamente versa.
        if pot_A.state_mm < pot_A.alert_mm:
            irrigation_A = pot_A.water_to_field_capacity() * IRRIGATION_EXCESS
            rec_A.irrigation_days.append(day_idx)
            rec_A.irrigation_amounts.append(irrigation_A)
            # B e C ricevono la stessa quantità reale di acqua.
            rec_B.irrigation_days.append(day_idx)
            rec_B.irrigation_amounts.append(irrigation_A)
            rec_C.irrigation_days.append(day_idx)
            rec_C.irrigation_amounts.append(irrigation_A)
        else:
            irrigation_A = 0.0

        # Bilancio idrico per tutti e tre i vasi con lo stesso
        # input idrico (rain + irrigazione di A).
        water_input = rain + irrigation_A
        pot_A.apply_balance_step(et_0, water_input, current_date)
        pot_B.apply_balance_step(et_0, water_input, current_date)
        pot_C.apply_balance_step(et_0, water_input, current_date)

        # Registrazione degli stati.
        rec_A.state_mm_history.append(pot_A.state_mm)
        rec_A.state_theta_history.append(pot_A.state_theta)
        rec_B.state_mm_history.append(pot_B.state_mm)
        rec_B.state_theta_history.append(pot_B.state_theta)
        rec_C.state_mm_history.append(pot_C.state_mm)
        rec_C.state_theta_history.append(pot_C.state_theta)

        # Aggiornamento dal sensore per il vaso C: ogni 7 giorni.
        # Il sensore è quello reale di A (con rumore aggiunto).
        if (day_idx + 1) % SENSOR_UPDATE_INTERVAL_DAYS == 0:
            theta_observed = max(0.0, min(1.0,
                pot_A.state_theta + rng.gauss(0, SENSOR_NOISE_SIGMA),
            ))
            update_result = pot_C.update_from_sensor(theta_observed)
            rec_C.sensor_updates.append((day_idx, update_result))
            # Aggiorniamo anche la traiettoria registrata per
            # riflettere la correzione applicata.
            rec_C.state_mm_history[-1] = pot_C.state_mm
            rec_C.state_theta_history[-1] = pot_C.state_theta

    return rec_A, rec_B, rec_C


def plot_comparison(
    rec_A: TrajectoryRecord,
    rec_B: TrajectoryRecord,
    rec_C: TrajectoryRecord,
    et0_series: list[float],
    rain_series: list[float],
) -> Path:
    """
    Tre pannelli con asse temporale condiviso:
      1. Traiettorie idriche dei tre vasi sovrapposte.
      2. Errore di previsione nel tempo per B (drift libero) e per
         C (con correzioni settimanali).
      3. Forzanti meteo.
    """
    fig = plt.figure(figsize=(13, 11), constrained_layout=True)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.5, 1.8, 1.0])
    ax_traj = fig.add_subplot(gs[0])
    ax_error = fig.add_subplot(gs[1], sharex=ax_traj)
    ax_meteo = fig.add_subplot(gs[2], sharex=ax_traj)

    fig.suptitle(
        "Chiusura del feedback loop sensore-modello\n"
        "Tre vasi gemelli, 90 giorni, parametri di B e C sbagliati del 19% "
        "su θ_FC",
        fontsize=13, fontweight="bold",
    )

    # --- Pannello 1: traiettorie idriche ---
    days = list(range(len(rec_A.state_mm_history)))

    ax_traj.plot(days, rec_A.state_mm_history,
                 color="#2ca02c", linewidth=2.5,
                 label=f"A — ground truth (FC={TRUE_THETA_FC:.2f})",
                 zorder=3)
    ax_traj.plot(days, rec_B.state_mm_history,
                 color="#d62728", linewidth=2.0, linestyle="--",
                 label=f"B — modello sbagliato, ciclo aperto "
                       f"(FC={WRONG_THETA_FC:.2f})",
                 zorder=2)
    ax_traj.plot(days, rec_C.state_mm_history,
                 color="#1f77b4", linewidth=2.0,
                 label=f"C — modello sbagliato + sensore settimanale",
                 zorder=2)

    # Marker per ogni aggiornamento sensore su C.
    if rec_C.sensor_updates:
        update_days = [day_idx + 1 for day_idx, _ in rec_C.sensor_updates]
        update_states = [rec_C.state_mm_history[d] for d in update_days]
        ax_traj.scatter(update_days, update_states,
                        color="#1f77b4", marker="o", s=100, zorder=5,
                        edgecolors="black", linewidth=1.5,
                        facecolors="white",
                        label="Correzione dal sensore (C)")

    ax_traj.set_ylabel("Acqua nel substrato (mm)")
    ax_traj.set_title(
        "Traiettorie idriche dei tre vasi",
        fontsize=11, color="tab:gray",
    )
    ax_traj.grid(True, alpha=0.3)
    ax_traj.legend(loc="lower left", fontsize=9.5, framealpha=0.95)

    # --- Pannello 2: errore di previsione (B − A e C − A) nel tempo ---
    error_B = [
        rec_B.state_mm_history[i] - rec_A.state_mm_history[i]
        for i in range(len(rec_A.state_mm_history))
    ]
    error_C = [
        rec_C.state_mm_history[i] - rec_A.state_mm_history[i]
        for i in range(len(rec_A.state_mm_history))
    ]

    ax_error.axhline(0, color="#2ca02c", linewidth=1.5, alpha=0.4,
                     linestyle="-")
    ax_error.text(0.5, 0, " errore zero (verità di A)",
                  color="#2ca02c", fontsize=9, va="center", alpha=0.6)

    ax_error.plot(days, error_B, color="#d62728", linewidth=2.0,
                  linestyle="--",
                  label="B (drift libero, sin correzione)")
    ax_error.plot(days, error_C, color="#1f77b4", linewidth=2.0,
                  label="C (con correzione settimanale)")

    # Marker degli aggiornamenti su C.
    if rec_C.sensor_updates:
        update_days = [day_idx + 1 for day_idx, _ in rec_C.sensor_updates]
        update_errors = [error_C[d] for d in update_days]
        ax_error.scatter(update_days, update_errors,
                         color="#1f77b4", marker="o", s=80, zorder=5,
                         edgecolors="black", linewidth=1.0,
                         facecolors="white")

    # Statistiche di drift.
    rmse_B = np.sqrt(np.mean(np.array(error_B) ** 2))
    rmse_C = np.sqrt(np.mean(np.array(error_C) ** 2))
    final_drift_B = abs(error_B[-1])
    final_drift_C = abs(error_C[-1])

    stats_text = (
        f"RMSE: B = {rmse_B:.1f} mm    C = {rmse_C:.1f} mm\n"
        f"Drift finale: B = {final_drift_B:.1f} mm    "
        f"C = {final_drift_C:.1f} mm"
    )
    ax_error.text(
        0.98, 0.95, stats_text,
        transform=ax_error.transAxes,
        fontsize=9.5, va="top", ha="right",
        family="monospace",
        bbox=dict(boxstyle="round,pad=0.4",
                  facecolor="white", edgecolor="#cccccc", alpha=0.9),
    )

    ax_error.set_ylabel("Errore di previsione (mm)")
    ax_error.set_title(
        "Errore = stato modello − stato reale (vaso A)",
        fontsize=11, color="tab:gray",
    )
    ax_error.grid(True, alpha=0.3)
    ax_error.legend(loc="lower left", fontsize=9.5, framealpha=0.95)

    # --- Pannello 3: meteo ---
    days_int = list(range(SIM_DAYS))
    color_et0 = "#d62728"
    color_rain = "#1f77b4"
    ax_meteo.bar(days_int, et0_series, color=color_et0, alpha=0.5,
                 edgecolor="none", width=0.8)
    ax_meteo.set_ylabel("ET₀ (mm/giorno)", color=color_et0)
    ax_meteo.tick_params(axis="y", labelcolor=color_et0)
    ax_meteo.set_xlabel("Giorno della simulazione")

    ax_rain = ax_meteo.twinx()
    ax_rain.bar([d + 0.4 for d in days_int], rain_series,
                color=color_rain, alpha=0.6, edgecolor="none", width=0.4)
    ax_rain.set_ylabel("Pioggia (mm)", color=color_rain)
    ax_rain.tick_params(axis="y", labelcolor=color_rain)

    ax_meteo.set_title("Forzanti meteo (90 giorni)",
                       fontsize=11, color="tab:gray")
    ax_meteo.grid(True, alpha=0.3, axis="y")

    path = OUTPUT_DIR / "sensor_update_demo.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def print_report(
    rec_A: TrajectoryRecord,
    rec_B: TrajectoryRecord,
    rec_C: TrajectoryRecord,
) -> None:
    """Statistiche di sintesi della simulazione."""
    error_B = [
        rec_B.state_mm_history[i] - rec_A.state_mm_history[i]
        for i in range(len(rec_A.state_mm_history))
    ]
    error_C = [
        rec_C.state_mm_history[i] - rec_A.state_mm_history[i]
        for i in range(len(rec_A.state_mm_history))
    ]

    rmse_B = np.sqrt(np.mean(np.array(error_B) ** 2))
    rmse_C = np.sqrt(np.mean(np.array(error_C) ** 2))
    max_error_B = max(abs(e) for e in error_B)
    max_error_C = max(abs(e) for e in error_C)

    print()
    print("=" * 72)
    print("Risultati della simulazione")
    print("=" * 72)
    print(f"\nIrrigazioni decise da A (ground truth): "
          f"{len(rec_A.irrigation_days)}")
    print(f"Aggiornamenti dal sensore applicati a C: "
          f"{len(rec_C.sensor_updates)}")

    print(f"\nDrift di B (modello errato, no feedback):")
    print(f"   RMSE: {rmse_B:.2f} mm")
    print(f"   Errore massimo: {max_error_B:.2f} mm")
    print(f"   Drift finale: {abs(error_B[-1]):.2f} mm")

    print(f"\nDrift di C (modello errato, con correzione settimanale):")
    print(f"   RMSE: {rmse_C:.2f} mm")
    print(f"   Errore massimo: {max_error_C:.2f} mm")
    print(f"   Drift finale: {abs(error_C[-1]):.2f} mm")

    if rmse_B > 0:
        improvement = (1 - rmse_C / rmse_B) * 100
        print(f"\nMiglioramento di C su B (RMSE): {improvement:.1f}%")

    print(f"\nDettaglio degli aggiornamenti applicati a C:")
    print(f"   {'Giorno':>7} | {'Predetto':>10} | {'Osservato':>10} | "
          f"{'Discrepanza':>12} | {'Significativa':>14}")
    print(f"   " + "-" * 65)
    for day_idx, upd in rec_C.sensor_updates:
        sig = "SI" if upd.is_significant else "no"
        print(f"   {day_idx + 1:>7d} | "
              f"{upd.predicted_theta:>10.4f} | "
              f"{upd.observed_theta:>10.4f} | "
              f"{upd.discrepancy_theta:>+12.4f} | "
              f"{sig:>14}")
    print("=" * 72)


def main() -> None:
    print("=" * 72)
    print("Demo: chiusura del feedback loop sensore-modello")
    print("=" * 72)

    print(f"\nGround truth: θ_FC={TRUE_THETA_FC}, θ_PWP={TRUE_THETA_PWP}")
    print(f"Modello sbagliato (vasi B e C): "
          f"θ_FC={WRONG_THETA_FC} (sovrastima del "
          f"{(WRONG_THETA_FC/TRUE_THETA_FC - 1)*100:.0f}%)")

    print(f"\nGenerazione meteo sintetico per {SIM_DAYS} giorni...")
    et0_series, rain_series = synthetic_weather()
    print(f"   ET₀ medio: {sum(et0_series)/len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm")

    print(f"\nSimulazione dei tre vasi con aggiornamenti del sensore "
          f"ogni {SENSOR_UPDATE_INTERVAL_DAYS} giorni per il vaso C...")
    rng = Random(42)
    rec_A, rec_B, rec_C = simulate_three_pots(
        et0_series, rain_series, rng,
    )

    print_report(rec_A, rec_B, rec_C)

    print(f"\nGenerazione grafico di confronto...")
    p = plot_comparison(rec_A, rec_B, rec_C, et0_series, rain_series)
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
