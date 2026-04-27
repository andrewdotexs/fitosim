"""
Demo: calibrazione empirica dei parametri del substrato dalle letture
del sensore WH51 (esperimento sintetico).

Questo demo costruisce un esperimento controllato dove conosciamo i
parametri "veri" del substrato e poi facciamo finta di non saperli,
lanciando la calibrazione sulla serie temporale rumorosa che il
sensore produrrebbe nel mondo reale. Il test è il recupero: la
calibrazione deve ricavare valori molto vicini ai parametri originali,
senza che il modulo abbia mai visto la verità.

Lo schema dell'esperimento è il seguente:

  1. Definiamo un substrato "ground truth" con θ_FC e θ_PWP noti.

  2. Eseguiamo una simulazione forward di sei mesi di vita del vaso,
     con un'algoritmo di irrigazione realistica (irrigare quando lo
     stato scende sotto la soglia di allerta).

  3. Convertiamo la serie state_mm in serie θ usando la profondità
     del substrato, e aggiungiamo rumore gaussiano per simulare
     l'imperfezione del sensore reale.

  4. Lanciamo la calibrazione sulla serie rumorosa SENZA dirle quali
     sono i parametri veri.

  5. Confrontiamo le stime con i valori originali e visualizziamo il
     risultato.

L'utilità pratica del demo è duplice. Da una parte valida la pipeline
sul dataset più favorevole possibile (rumore controllato, dinamica
ben definita), il che ci dà una baseline di prestazioni. Dall'altra
mostra al giardiniere quale "shape" di dati produce buone calibrazioni
e quali no — informazione utile per chi vorrà calibrare il proprio
vaso reale e capire se i suoi dati sono adeguati.

Esegui con:
    PYTHONPATH=src python examples/calibration_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from random import Random

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.science.calibration import (
    calibrate_substrate,
    find_peaks,
    find_valleys,
)
from fitosim.science.substrate import Substrate


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Parametri "ground truth" del substrato. Sono i valori che la
# calibrazione dovrà recuperare senza che li conosca esplicitamente.
TRUE_THETA_FC = 0.42
TRUE_THETA_PWP = 0.12

# Setup della simulazione forward.
PLANTING_DATE = date(2026, 4, 1)
SIM_START = date(2026, 4, 15)
SIM_DAYS = 180  # sei mesi di osservazione
IRRIGATION_EXCESS = 1.05  # leggero eccesso, gesto del giardiniere

# Parametri del sensore WH51. Il sensore reale produce dati orari, ma
# qui simuliamo direttamente la serie giornaliera (max o medio
# giornaliero, equivalente). Sigma del rumore tipico per WH51
# aggregato giornaliero: ~0.005-0.015 in θ.
SENSOR_NOISE_SIGMA = 0.010


def make_ground_truth_pot() -> Pot:
    """Crea il vaso con il substrato 'ground truth' che genererà i dati."""
    truth_substrate = Substrate(
        name="Ground truth",
        theta_fc=TRUE_THETA_FC,
        theta_pwp=TRUE_THETA_PWP,
    )
    return Pot(
        label="vaso-test",
        species=BASIL,
        substrate=truth_substrate,
        pot_volume_l=5.0,
        pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=PLANTING_DATE,
    )


def synthetic_weather() -> tuple[list[float], list[float]]:
    """
    Genera meteo sintetico per sei mesi: ET₀ con stagionalità (basso
    in primavera/autunno, alto in estate) e pioggia stocastica.
    """
    rng = np.random.default_rng(seed=42)
    et0_series = []
    rain_series = []
    for d in range(SIM_DAYS):
        # ET₀ stagionale: sinusoide con massimo a metà periodo.
        season_factor = np.sin(np.pi * d / SIM_DAYS)  # 0 → 1 → 0
        base = 2.5 + 4.0 * season_factor
        noise = rng.normal(0, 0.5)
        et0_series.append(max(1.5, base + noise))
        # Pioggia: 10% di probabilità per giorno, con intensità random
        # se piove.
        if rng.random() < 0.10:
            rain_series.append(float(rng.exponential(8.0)))
        else:
            rain_series.append(0.0)
    return et0_series, rain_series


@dataclass
class SimResult:
    """Esito della simulazione forward + acquisizione del sensore."""
    state_mm_history: list[float]
    theta_clean_history: list[float]   # serie pulita (senza rumore)
    theta_noisy_history: list[float]   # serie come il sensore la vede
    et0_series: list[float]
    rain_series: list[float]
    irrigation_days: list[int]


def simulate_and_observe(
    pot: Pot,
    et0_series: list[float],
    rain_series: list[float],
    rng: Random,
) -> SimResult:
    """
    Simula sei mesi di vita del vaso e produce la serie del sensore.

    A ogni passo:
      - Decide se irrigare (stato sotto soglia di allerta).
      - Applica il bilancio idrico FAO-56.
      - Registra lo stato in mm e la corrispondente lettura θ.
      - Aggiunge rumore gaussiano alla lettura per simulare il sensore.
    """
    state_mm: list[float] = [pot.state_mm]
    theta_clean: list[float] = [pot.state_theta]
    theta_noisy: list[float] = [
        max(0.0, min(1.0, pot.state_theta + rng.gauss(0, SENSOR_NOISE_SIGMA)))
    ]
    irr_days: list[int] = []

    for day_idx in range(SIM_DAYS):
        current_date = SIM_START + timedelta(days=day_idx)
        et_0 = et0_series[day_idx]
        rain = rain_series[day_idx]

        # Decisione di irrigazione: gesto del giardiniere.
        if pot.state_mm < pot.alert_mm:
            irrigation = pot.water_to_field_capacity() * IRRIGATION_EXCESS
            irr_days.append(day_idx)
        else:
            irrigation = 0.0

        pot.apply_balance_step(
            et_0_mm=et_0,
            water_input_mm=rain + irrigation,
            current_date=current_date,
        )

        state_mm.append(pot.state_mm)
        theta_clean.append(pot.state_theta)
        # Il sensore vede lo stato + rumore, saturato in [0, 1].
        noisy = pot.state_theta + rng.gauss(0, SENSOR_NOISE_SIGMA)
        theta_noisy.append(max(0.0, min(1.0, noisy)))

    return SimResult(
        state_mm_history=state_mm,
        theta_clean_history=theta_clean,
        theta_noisy_history=theta_noisy,
        et0_series=et0_series,
        rain_series=rain_series,
        irrigation_days=irr_days,
    )


def plot_calibration(
    sim: SimResult,
    result,  # CalibrationResult
    peak_indices: list[int],
    valley_indices: list[int],
) -> Path:
    """
    Tre pannelli con asse temporale condiviso:
      1. Serie del sensore con picchi e valli evidenziati e linee
         orizzontali per i parametri stimati e veri.
      2. Distribuzione dei valori di picchi e valli (istogramma).
      3. Forzanti meteo.
    """
    fig = plt.figure(figsize=(13, 11), constrained_layout=True)
    gs = fig.add_gridspec(3, 2, height_ratios=[3.0, 1.5, 1.0],
                          width_ratios=[3, 1])
    ax_series = fig.add_subplot(gs[0, :])
    ax_hist = fig.add_subplot(gs[1, 1])
    ax_summary = fig.add_subplot(gs[1, 0])
    ax_meteo = fig.add_subplot(gs[2, :], sharex=ax_series)

    fig.suptitle(
        "Calibrazione empirica dei parametri del substrato dai dati WH51\n"
        "Esperimento sintetico: 6 mesi di basilico, "
        f"σ_rumore={SENSOR_NOISE_SIGMA} in θ",
        fontsize=13, fontweight="bold",
    )

    # --- Pannello 1: serie del sensore + picchi/valli + linee θ ---
    days = list(range(len(sim.theta_noisy_history)))

    # Serie pulita (ground truth della simulazione, senza rumore) come
    # riferimento di confronto, in grigio chiaro.
    ax_series.plot(days, sim.theta_clean_history,
                   color="#aaaaaa", linewidth=0.8, alpha=0.6,
                   label="Ground truth (simulazione)", zorder=1)
    # Serie del sensore (con rumore): è quello che la calibrazione vede.
    ax_series.plot(days, sim.theta_noisy_history,
                   color="#1f77b4", linewidth=1.2, alpha=0.9,
                   label="Sensore WH51 (rumoroso)", zorder=2)

    # Picchi rilevati: marker triangolo in alto.
    if peak_indices:
        ax_series.scatter(
            peak_indices,
            [sim.theta_noisy_history[i] for i in peak_indices],
            color="#d62728", marker="^", s=80, zorder=5,
            edgecolors="black", linewidth=0.8,
            label=f"Picchi rilevati ({len(peak_indices)})",
        )
    # Valli rilevate: marker triangolo in basso.
    if valley_indices:
        ax_series.scatter(
            valley_indices,
            [sim.theta_noisy_history[i] for i in valley_indices],
            color="#2ca02c", marker="v", s=80, zorder=5,
            edgecolors="black", linewidth=0.8,
            label=f"Valli rilevate ({len(valley_indices)})",
        )

    # Linee orizzontali: parametri veri vs stimati.
    ax_series.axhline(TRUE_THETA_FC, color="#d62728", linestyle="--",
                      linewidth=1.2, alpha=0.7)
    ax_series.text(SIM_DAYS + 1, TRUE_THETA_FC,
                   f" θ_FC vero={TRUE_THETA_FC:.3f}",
                   color="#d62728", fontsize=9, va="center")
    ax_series.axhline(result.theta_fc_estimate, color="#d62728",
                      linestyle=":", linewidth=1.2, alpha=0.7)
    ax_series.text(SIM_DAYS + 1, result.theta_fc_estimate - 0.018,
                   f" θ_FC stimato={result.theta_fc_estimate:.3f}",
                   color="#d62728", fontsize=9, va="center", style="italic")

    ax_series.axhline(TRUE_THETA_PWP, color="#2ca02c", linestyle="--",
                      linewidth=1.2, alpha=0.7)
    ax_series.text(SIM_DAYS + 1, TRUE_THETA_PWP,
                   f" θ_PWP vero={TRUE_THETA_PWP:.3f}",
                   color="#2ca02c", fontsize=9, va="center")
    if result.theta_pwp_estimate is not None:
        ax_series.axhline(result.theta_pwp_estimate, color="#2ca02c",
                          linestyle=":", linewidth=1.2, alpha=0.7)
        ax_series.text(SIM_DAYS + 1,
                       result.theta_pwp_estimate + 0.018,
                       f" θ_PWP stimato={result.theta_pwp_estimate:.3f}",
                       color="#2ca02c", fontsize=9, va="center",
                       style="italic")

    ax_series.set_ylabel("Contenuto idrico volumetrico θ")
    ax_series.set_title(
        "Serie storica del sensore con picchi e valli identificati",
        fontsize=11, color="tab:gray",
    )
    ax_series.grid(True, alpha=0.3)
    ax_series.legend(loc="lower left", fontsize=9, framealpha=0.95,
                     ncol=2)
    ax_series.set_xlim(-1, SIM_DAYS + 32)
    # Estendiamo l'asse Y abbastanza in basso da includere la vera PWP
    # (0.12), che è molto più bassa di quanto il sensore abbia mai
    # visto (~0.25). Questo gap visivo è la sintesi grafica
    # dell'asimmetria FC-PWP.
    y_min = min(TRUE_THETA_PWP - 0.02, min(sim.theta_noisy_history) - 0.02)
    y_max = min(1.0, max(sim.theta_noisy_history) + 0.04)
    ax_series.set_ylim(y_min, y_max)
    # Sfondatura visiva della "zona invisibile al sensore": tra la
    # valle più bassa osservata e la vera PWP. È la regione che il
    # giardiniere virtuale ha sempre evitato irrigando in tempo.
    sensor_floor = min(sim.theta_noisy_history)
    ax_series.axhspan(
        TRUE_THETA_PWP, sensor_floor,
        facecolor="#2ca02c", alpha=0.06, zorder=0,
    )
    ax_series.text(
        SIM_DAYS / 2, (TRUE_THETA_PWP + sensor_floor) / 2,
        "Zona mai osservata dal sensore\n(il giardiniere irriga prima)",
        ha="center", va="center", fontsize=9,
        color="#226622", style="italic", alpha=0.8,
    )

    # --- Pannello 2 sinistro: riquadro riassuntivo testuale ---
    fc_error = result.theta_fc_estimate - TRUE_THETA_FC
    fc_error_pct = (fc_error / TRUE_THETA_FC * 100) if TRUE_THETA_FC else 0
    pwp_diff = (
        (result.theta_pwp_estimate - TRUE_THETA_PWP)
        if result.theta_pwp_estimate is not None
        else None
    )

    summary_lines = [
        "RISULTATO DELLA CALIBRAZIONE",
        "",
        f"Picchi usati: {result.n_peaks}    "
        f"Valli usate: {result.n_valleys}",
        "",
        f"θ_FC stimato:  {result.theta_fc_estimate:.4f}    "
        f"(vero: {TRUE_THETA_FC:.4f},  errore: "
        f"{fc_error:+.4f} = {fc_error_pct:+.1f}%)",
        f"θ_PWP stimato: " +
        (f"{result.theta_pwp_estimate:.4f}    "
         f"(vero: {TRUE_THETA_PWP:.4f},  diff: {pwp_diff:+.4f})"
         if result.theta_pwp_estimate is not None else "non stimabile"),
        "",
        f"Confidenza FC:  {result.confidence_fc.upper()}",
        f"Confidenza PWP: {result.confidence_pwp.upper()}",
    ]
    ax_summary.text(
        0.02, 0.95, "\n".join(summary_lines),
        transform=ax_summary.transAxes,
        fontsize=10, va="top", ha="left",
        family="monospace",
    )
    ax_summary.set_xticks([])
    ax_summary.set_yticks([])
    for spine in ax_summary.spines.values():
        spine.set_edgecolor("#cccccc")

    # --- Pannello 2 destro: distribuzione di picchi e valli ---
    if peak_indices and valley_indices:
        peak_values = [sim.theta_noisy_history[i] for i in peak_indices]
        valley_values = [sim.theta_noisy_history[i] for i in valley_indices]
        bins = np.linspace(0.0, 0.5, 26)
        ax_hist.hist(peak_values, bins=bins, color="#d62728",
                     alpha=0.6, label="Picchi", edgecolor="white",
                     linewidth=0.5, orientation="horizontal")
        ax_hist.hist(valley_values, bins=bins, color="#2ca02c",
                     alpha=0.6, label="Valli", edgecolor="white",
                     linewidth=0.5, orientation="horizontal")
        ax_hist.axhline(TRUE_THETA_FC, color="#d62728", linestyle="--",
                        linewidth=1.0, alpha=0.7)
        ax_hist.axhline(TRUE_THETA_PWP, color="#2ca02c", linestyle="--",
                        linewidth=1.0, alpha=0.7)
        ax_hist.set_xlabel("Frequenza")
        ax_hist.set_title("Distribuzione",
                          fontsize=10, color="tab:gray")
        ax_hist.legend(loc="center right", fontsize=8)
        ax_hist.grid(True, alpha=0.3)

    # --- Pannello 3: meteo ---
    days_int = list(range(SIM_DAYS))
    color_et0 = "#d62728"
    color_rain = "#1f77b4"
    ax_meteo.bar(days_int, sim.et0_series, color=color_et0, alpha=0.5,
                 label="ET₀", edgecolor="none", width=0.8)
    ax_meteo.set_ylabel("ET₀ (mm/giorno)", color=color_et0)
    ax_meteo.tick_params(axis="y", labelcolor=color_et0)
    ax_meteo.set_xlabel("Giorno della simulazione")

    ax_rain = ax_meteo.twinx()
    ax_rain.bar([d + 0.4 for d in days_int], sim.rain_series,
                color=color_rain, alpha=0.6, edgecolor="none",
                width=0.4)
    ax_rain.set_ylabel("Pioggia (mm)", color=color_rain)
    ax_rain.tick_params(axis="y", labelcolor=color_rain)

    ax_meteo.set_title("Forzanti meteo (sei mesi)",
                       fontsize=11, color="tab:gray")
    ax_meteo.grid(True, alpha=0.3, axis="y")

    path = OUTPUT_DIR / "calibration_demo.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    print("=" * 72)
    print("Demo: calibrazione empirica del substrato dai dati del sensore")
    print("=" * 72)

    print(f"\nGround truth (parametri 'veri' del substrato):")
    print(f"   θ_FC  = {TRUE_THETA_FC}")
    print(f"   θ_PWP = {TRUE_THETA_PWP}")

    print(f"\nSimulazione di {SIM_DAYS} giorni con il vaso ground truth...")
    pot = make_ground_truth_pot()
    et0_series, rain_series = synthetic_weather()
    rng = Random(42)
    sim = simulate_and_observe(pot, et0_series, rain_series, rng)
    print(f"   Irrigazioni decise: {len(sim.irrigation_days)}")
    print(f"   ET₀ medio: {sum(et0_series)/len(et0_series):.2f} mm/giorno")
    print(f"   Pioggia totale: {sum(rain_series):.1f} mm")
    print(f"   Range θ del sensore: [{min(sim.theta_noisy_history):.3f}, "
          f"{max(sim.theta_noisy_history):.3f}]")

    print(f"\nCalibrazione (il modulo NON conosce i parametri veri)...")
    result = calibrate_substrate(
        theta_series=sim.theta_noisy_history,
        name="vaso-test calibrato",
    )

    # Recupero indici di picchi e valli per la visualizzazione (la
    # funzione di calibrazione li trova internamente ma non li
    # restituisce; li ricalcoliamo qui per il grafico).
    peak_idx = find_peaks(sim.theta_noisy_history)
    valley_idx = find_valleys(sim.theta_noisy_history)

    print()
    print(f"   θ_FC stimato:  {result.theta_fc_estimate:.4f} "
          f"(vero: {TRUE_THETA_FC:.4f}, "
          f"errore: {result.theta_fc_estimate - TRUE_THETA_FC:+.4f})")
    if result.theta_pwp_estimate is not None:
        print(f"   θ_PWP stimato: {result.theta_pwp_estimate:.4f} "
              f"(vero: {TRUE_THETA_PWP:.4f}, "
              f"diff: {result.theta_pwp_estimate - TRUE_THETA_PWP:+.4f})")
    else:
        print(f"   θ_PWP stimato: NON STIMABILE")
    print(f"   Picchi usati: {result.n_peaks}, "
          f"valli usate: {result.n_valleys}")
    print(f"   Confidenza FC:  {result.confidence_fc}")
    print(f"   Confidenza PWP: {result.confidence_pwp}")
    print(f"\n   Note: {result.notes}")

    print(f"\nGenerazione grafico di confronto...")
    p = plot_calibration(sim, result, peak_idx, valley_idx)
    print(f"   → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
