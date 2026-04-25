"""
Demo end-to-end: Open-Meteo + motore fitosim + inventario.

Questo è il primo esempio in cui fitosim consuma dati meteorologici
reali invece di scenari sintetici. Lo script fa tre cose in sequenza,
ciascuna documentata da una figura prodotta in `output/plots/`:

  1. Scarica la previsione a 7 giorni di Milano da Open-Meteo.
     Se la rete non è disponibile, ricade su un payload sintetico
     realistico — il demo funziona sempre, online e offline.

  2. Confronta la nostra ET₀ Hargreaves-Samani con la ET₀ FAO-56
     Penman-Monteith calcolata da Open-Meteo. Penman-Monteith è la
     formula completa "gold standard"; Hargreaves-Samani usa solo
     temperature + radiazione astronomica. Vedere quanto siamo in
     accordo con il PM è la validazione esterna più forte che
     possiamo fare del nostro motore.

  3. Applica la previsione meteo a un piccolo inventario di tre vasi
     (basilico, pomodoro, rosmarino) e simula 7 giorni di evoluzione
     idrica, producendo un grafico delle traiettorie.

Esegui con:
    python examples/openmeteo_milan_demo.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL, ROSEMARY, TOMATO
from fitosim.io.openmeteo import (
    DailyWeather,
    fetch_daily_forecast,
    parse_openmeteo_response,
)
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import (
    CACTUS_MIX,
    UNIVERSAL_POTTING_SOIL,
)


# -----------------------------------------------------------------------
#  Configurazione
# -----------------------------------------------------------------------
MILAN_LAT = 45.47
MILAN_LON = 9.19
N_DAYS = 7

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------------------
#  Fallback sintetico: usato quando la rete non è disponibile.
#  Numeri costruiti per essere realistici per Milano in luglio:
#  T_min sulla ventina di °C, T_max sui trenta, alcune giornate fresche
#  e un evento piovoso, ET₀ FAO compatibile con queste condizioni.
# -----------------------------------------------------------------------
def _build_synthetic_payload() -> dict:
    """Payload sintetico stile Open-Meteo per fallback offline."""
    today = date.today()
    days_iso = [
        (today + timedelta(days=i)).isoformat()
        for i in range(N_DAYS)
    ]
    return {
        "daily": {
            "time": days_iso,
            "temperature_2m_max": [31.5, 33.2, 30.1, 27.8, 26.4, 29.3, 31.0],
            "temperature_2m_min": [20.5, 21.8, 19.7, 18.0, 16.8, 18.5, 20.1],
            "precipitation_sum": [0.0, 0.0, 0.5, 6.4, 1.2, 0.0, 0.0],
            "et0_fao_evapotranspiration":
                [5.8, 6.4, 5.4, 4.0, 3.5, 4.6, 5.5],
        },
    }


def fetch_with_fallback() -> tuple[list[DailyWeather], bool]:
    """
    Prova a scaricare la previsione reale da Open-Meteo. Se la rete
    fallisce per qualunque ragione, ricade su un payload sintetico.

    Restituisce (lista_previsione, è_reale).
    """
    try:
        weather = fetch_daily_forecast(
            latitude=MILAN_LAT, longitude=MILAN_LON,
            days=N_DAYS, use_cache=True,
        )
        return weather, True
    except OSError as exc:
        print(f"⚠️  Connessione a Open-Meteo non disponibile: {exc}")
        print("   Fallback ai dati sintetici per il demo offline.\n")
        synthetic_payload = _build_synthetic_payload()
        return parse_openmeteo_response(synthetic_payload), False


# -----------------------------------------------------------------------
#  1. Stampa tabellare della previsione + nostra ET₀ Hargreaves-Samani
# -----------------------------------------------------------------------
def print_forecast_table(weather: list[DailyWeather]) -> None:
    """Tabella con previsione meteo e confronto ET₀ HS vs PM."""
    header = (
        f"{'Data':<12} {'T_min':>6} {'T_max':>6} "
        f"{'Pioggia':>8} {'ET₀ PM':>7} {'ET₀ HS':>7} {'Δ%':>6}"
    )
    print(header)
    print("-" * len(header))

    for w in weather:
        # ET₀ Hargreaves-Samani applicata alle stesse temperature.
        et0_hs = et0_hargreaves_samani(
            t_min=w.t_min, t_max=w.t_max,
            latitude_deg=MILAN_LAT, j=day_of_year(w.day),
        )
        # Differenza relativa rispetto a PM, se disponibile.
        if w.et0_mm is not None and w.et0_mm > 0:
            delta_pct = (et0_hs - w.et0_mm) / w.et0_mm * 100.0
            delta_str = f"{delta_pct:+5.1f}%"
            pm_str = f"{w.et0_mm:>5.2f}"
        else:
            delta_str = "  n/d"
            pm_str = "  n/d"

        print(
            f"{w.day.isoformat():<12} "
            f"{w.t_min:>5.1f}° {w.t_max:>5.1f}° "
            f"{w.precipitation_mm:>6.1f}mm "
            f"{pm_str:>7} {et0_hs:>5.2f} {delta_str:>6}"
        )

    print()
    print("Legenda:")
    print("  ET₀ PM = Penman-Monteith FAO-56 calcolata da Open-Meteo")
    print("  ET₀ HS = Hargreaves-Samani calcolata da fitosim")
    print("  Δ%     = differenza relativa di HS rispetto a PM")


# -----------------------------------------------------------------------
#  2. Grafico di validazione: HS vs PM
# -----------------------------------------------------------------------
def plot_et0_validation(weather: list[DailyWeather]) -> Path:
    """
    Grafico che confronta visivamente le due formule di ET₀: il nostro
    Hargreaves-Samani contro Open-Meteo Penman-Monteith. Aggiunge anche
    la differenza percentuale come barre per quantificare il bias.
    """
    days = [w.day for w in weather]
    et0_pm = np.array([w.et0_mm if w.et0_mm is not None else np.nan
                        for w in weather])
    et0_hs = np.array([
        et0_hargreaves_samani(
            t_min=w.t_min, t_max=w.t_max,
            latitude_deg=MILAN_LAT, j=day_of_year(w.day),
        )
        for w in weather
    ])

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(11, 7.5),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )

    # Pannello superiore: due curve di ET₀.
    ax_top.plot(
        days, et0_pm, "o-",
        color="tab:purple", linewidth=2.5, markersize=8,
        label="Penman-Monteith FAO-56 (Open-Meteo, gold standard)",
    )
    ax_top.plot(
        days, et0_hs, "s--",
        color="tab:orange", linewidth=2.0, markersize=7,
        label="Hargreaves-Samani (fitosim, approssimazione)",
    )
    ax_top.set_ylabel("ET₀ (mm/giorno)")
    ax_top.set_title(
        f"Confronto ET₀: Hargreaves-Samani vs Penman-Monteith — "
        f"Milano, previsione {days[0].isoformat()} → "
        f"{days[-1].isoformat()}"
    )
    ax_top.legend(loc="best", framealpha=0.92)
    ax_top.grid(True, alpha=0.3)
    ax_top.set_ylim(bottom=0)

    # Pannello inferiore: barre della differenza relativa.
    delta_pct = (et0_hs - et0_pm) / et0_pm * 100.0
    bar_colors = ["tab:green" if abs(d) < 10 else "tab:red"
                  for d in delta_pct]
    ax_bot.bar(days, delta_pct, color=bar_colors, alpha=0.7,
               edgecolor="black", linewidth=0.5)
    ax_bot.axhline(0, color="black", linewidth=0.8)
    ax_bot.axhline(10, color="gray", linewidth=0.5, linestyle=":",
                   alpha=0.6)
    ax_bot.axhline(-10, color="gray", linewidth=0.5, linestyle=":",
                   alpha=0.6)
    ax_bot.set_ylabel("HS − PM (%)")
    ax_bot.set_xlabel("Giorno")
    ax_bot.grid(True, alpha=0.3, axis="y")

    # Annotazione del bias medio: utile come metrica sintetica.
    mean_bias = float(np.nanmean(delta_pct))
    ax_bot.text(
        0.02, 0.95,
        f"Bias medio: {mean_bias:+.1f}%",
        transform=ax_bot.transAxes,
        fontsize=10, verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.4",
                  facecolor="white", edgecolor="gray", alpha=0.85),
    )

    fig.autofmt_xdate(rotation=30)
    path = OUTPUT_DIR / "openmeteo_et0_validation.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  3. Inventario: 7 giorni di simulazione su tre vasi reali
# -----------------------------------------------------------------------
def build_mini_inventory() -> list[Pot]:
    """Tre vasi rappresentativi, in stadi fenologici diversi."""
    today = date.today()
    return [
        Pot(
            label="Basilico",
            species=BASIL,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=4.0,
            pot_diameter_cm=18.0,
            location=Location.OUTDOOR,
            planting_date=today - timedelta(days=40),
        ),
        Pot(
            label="Pomodoro",
            species=TOMATO,
            substrate=UNIVERSAL_POTTING_SOIL,
            pot_volume_l=15.0,
            pot_diameter_cm=30.0,
            location=Location.OUTDOOR,
            planting_date=today - timedelta(days=70),
        ),
        Pot(
            label="Rosmarino",
            species=ROSEMARY,
            substrate=CACTUS_MIX,
            pot_volume_l=3.0,
            pot_diameter_cm=16.0,
            location=Location.OUTDOOR,
            planting_date=today - timedelta(days=300),
        ),
    ]


def simulate_inventory_with_forecast(
    inventory: list[Pot],
    weather: list[DailyWeather],
) -> dict[str, list[float]]:
    """
    Per ogni vaso simula 7 giorni usando direttamente la previsione
    Open-Meteo. Per l'ET₀ usiamo il nostro Hargreaves-Samani — è il
    motore validato di fitosim. La pioggia entra come water_input.
    Restituisce uno dizionario {label: [stati_giornalieri]} dove la
    lista contiene N_DAYS+1 valori (stato iniziale + N_DAYS aggiornati).
    """
    trajectories = {p.label: [p.state_mm] for p in inventory}

    for w in weather:
        et0_mm = et0_hargreaves_samani(
            t_min=w.t_min, t_max=w.t_max,
            latitude_deg=MILAN_LAT, j=day_of_year(w.day),
        )
        for pot in inventory:
            pot.apply_balance_step(
                et_0_mm=et0_mm,
                water_input_mm=w.precipitation_mm,
                current_date=w.day,
            )
            trajectories[pot.label].append(pot.state_mm)

    return trajectories


def plot_inventory_trajectories(
    inventory: list[Pot],
    weather: list[DailyWeather],
    trajectories: dict[str, list[float]],
) -> Path:
    """
    Tre traiettorie su pannello superiore, pioggia giornaliera come
    barre sul pannello inferiore. Ogni vaso ha la sua coppia di
    soglie FC e PWP, normalizzate visivamente come "% della FC del
    vaso" così che le tre traiettorie siano confrontabili nonostante
    geometrie e substrati diversi.
    """
    # Asse temporale: include il giorno 0 (stato iniziale, pre-meteo).
    day0 = weather[0].day - timedelta(days=1)
    days = [day0] + [w.day for w in weather]

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(11, 7.5),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )

    palette = {"Basilico": "tab:blue",
               "Pomodoro": "tab:red",
               "Rosmarino": "tab:olive"}

    for pot in inventory:
        color = palette[pot.label]
        states = np.array(trajectories[pot.label])
        # Normalizziamo come percentuale della capacità di campo del vaso.
        states_pct = states / pot.fc_mm * 100.0
        ax_top.plot(
            days, states_pct, "o-",
            color=color, linewidth=2.2, markersize=6,
            label=f"{pot.label} ({pot.species.common_name})",
        )
        # Soglia di allerta personale, come % della FC.
        alert_pct = pot.alert_mm / pot.fc_mm * 100.0
        ax_top.axhline(
            alert_pct, color=color, linestyle=":", alpha=0.4,
            linewidth=1.0,
        )

    ax_top.axhline(100, color="darkgreen", linestyle="--",
                   alpha=0.5, linewidth=1.0)
    ax_top.text(days[-1], 100.5, "Capacità di campo",
                color="darkgreen", fontsize=8.5,
                horizontalalignment="right")

    ax_top.set_ylabel("Stato idrico (% della FC del vaso)")
    is_real = "reale" if weather[0].et0_mm is not None else "sintetico"
    ax_top.set_title(
        f"Evoluzione idrica dell'inventario su 7 giorni — "
        f"meteo {is_real} di Milano"
    )
    ax_top.legend(loc="best", framealpha=0.92, fontsize=9)
    ax_top.grid(True, alpha=0.3)
    ax_top.set_ylim(0, 110)

    # Pannello pioggia.
    rain_days = [w.day for w in weather]
    rains = [w.precipitation_mm for w in weather]
    ax_bot.bar(rain_days, rains, color="tab:cyan", alpha=0.8,
               edgecolor="black", linewidth=0.5)
    ax_bot.set_ylabel("Pioggia (mm)")
    ax_bot.set_xlabel("Giorno")
    ax_bot.grid(True, alpha=0.3, axis="y")

    fig.autofmt_xdate(rotation=30)
    path = OUTPUT_DIR / "openmeteo_inventory_forecast.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("Demo Open-Meteo + fitosim per Milano")
    print("=" * 70)
    print()

    # Step 1: previsione (con fallback offline).
    weather, is_real = fetch_with_fallback()
    if is_real:
        print(f"✓ Previsione reale scaricata da Open-Meteo "
              f"({len(weather)} giorni).\n")
    else:
        print(f"○ Demo eseguito con dati sintetici "
              f"({len(weather)} giorni).\n")

    print_forecast_table(weather)
    print()

    # Step 2: validazione Hargreaves-Samani vs Penman-Monteith.
    print("Generazione grafico di validazione ET₀...")
    p1 = plot_et0_validation(weather)
    print(f"  → {p1.name}\n")

    # Step 3: simulazione dell'inventario.
    print("Simulazione dell'inventario sui 7 giorni di previsione...")
    inventory = build_mini_inventory()
    trajectories = simulate_inventory_with_forecast(inventory, weather)

    # Stampa stato finale dell'inventario.
    print()
    print("Stato finale dei vasi:")
    for pot in inventory:
        liters_to_fc = pot.water_to_field_capacity_liters()
        pct = pot.state_mm / pot.fc_mm * 100.0
        flag = " ⚠️ allerta" if pot.state_mm < pot.alert_mm else ""
        print(f"  {pot.label:<12} {pct:>5.1f}% FC, "
              f"da reintegrare {liters_to_fc:.2f} L{flag}")

    print()
    print("Generazione grafico delle traiettorie...")
    p2 = plot_inventory_trajectories(inventory, weather, trajectories)
    print(f"  → {p2.name}\n")

    print("=" * 70)
    print(f"Demo completato. Grafici salvati in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
