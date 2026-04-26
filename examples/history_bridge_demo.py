"""
Demo end-to-end: bridge sensor-modello via endpoint history.

Scarica lo stesso periodo storico da due fonti complementari — la
stazione Ecowitt installata sul balcone dell'utente e l'archivio
grigliato di Open-Meteo — aggrega entrambe a livello giornaliero,
calcola l'ET₀ Hargreaves-Samani con i dati di ciascuna, e produce un
grafico di confronto.

Perché questo esempio è importante
----------------------------------
È il primo demo in cui fitosim usa **letture reali** della stazione
locale come input al motore agronomico, invece dei dati climatologici
grigliati di Open-Meteo. Open-Meteo modella un quadrato di ~9 km
centrato sulle tue coordinate; la stazione Ecowitt è installata sul
TUO balcone. Le differenze sistematiche (effetto isola di calore
urbana, esposizione, microclima locale) sono ciò che il confronto
mette in luce.

Strategia di acquisizione
-------------------------
Tenta di scaricare i dati reali da entrambe le fonti. Se le credenziali
Ecowitt non sono configurate o la rete non è disponibile, ricade
sulle fixture salvate per i test, mantenendo il demo eseguibile in
qualunque ambiente.

Esegui con:
    # Modalità reale:
    export ECOWITT_APPLICATION_KEY="..."
    export ECOWITT_API_KEY="..."
    export ECOWITT_MAC="88:13:BF:CB:5A:AF"
    python examples/history_bridge_demo.py

    # Modalità offline (con fixture):
    python examples/history_bridge_demo.py
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.io.ecowitt import (
    aggregate_to_daily_weather,
    credentials_from_env,
    fetch_history,
    parse_ecowitt_history_response,
)
from fitosim.io.openmeteo import (
    DailyWeather,
    fetch_daily_archive,
    parse_openmeteo_response,
)
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year


MILAN_LAT = 45.47
MILAN_LON = 9.19

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ECOWITT_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests" / "fixtures" / "ecowitt_history_week.json"
)


# -----------------------------------------------------------------------
#  Acquisizione dati Ecowitt (con fallback)
# -----------------------------------------------------------------------

def acquire_ecowitt_daily(
    start: datetime, end: datetime,
) -> tuple[list[DailyWeather], str]:
    """
    Recupera la serie history dalla stazione e la aggrega a livello
    giornaliero. Se non riesce, usa la fixture.
    """
    try:
        app_key, api_key, mac = credentials_from_env()
        series = fetch_history(
            application_key=app_key, api_key=api_key, mac=mac,
            start_date=start, end_date=end,
        )
        daily = aggregate_to_daily_weather(series, min_points_per_day=4)
        if daily:
            return daily, f"stazione live {mac}"
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"○ Acquisizione Ecowitt fallita: {exc}")

    # Fallback: parsing della fixture compatta.
    print("   Fallback alla fixture history compatta.")
    with ECOWITT_FIXTURE.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    series = parse_ecowitt_history_response(payload)
    daily = aggregate_to_daily_weather(series, min_points_per_day=2)
    return daily, "fixture (offline)"


def acquire_openmeteo_daily(
    start: date, end: date,
) -> tuple[list[DailyWeather], str]:
    """
    Recupera l'archivio giornaliero Open-Meteo per la stessa finestra.
    In caso di fallimento di rete, usa un payload sintetico costruito
    sui valori climatologici tipici della stagione corrispondente.
    """
    try:
        daily = fetch_daily_archive(
            latitude=MILAN_LAT, longitude=MILAN_LON,
            start_date=start, end_date=end,
        )
        return daily, "archivio Open-Meteo"
    except OSError as exc:
        print(f"○ Acquisizione Open-Meteo fallita: {exc}")
        print("   Fallback a payload sintetico.")

    # Costruiamo un payload sintetico realistico per inizio aprile a
    # Milano: temperature tipiche 7-18 °C, qualche evento di pioggia
    # leggera, ET₀ FAO compatibile.
    n = (end - start).days + 1
    payload = {
        "daily": {
            "time": [(start + timedelta(days=i)).isoformat() for i in range(n)],
            "temperature_2m_max": [16.5 + (i % 3) for i in range(n)],
            "temperature_2m_min": [6.0 + (i % 4) * 0.5 for i in range(n)],
            "precipitation_sum": [0.0] * n,
            "et0_fao_evapotranspiration": [2.8 + (i % 3) * 0.4 for i in range(n)],
        },
    }
    return parse_openmeteo_response(payload), "sintetico (Open-Meteo offline)"


# -----------------------------------------------------------------------
#  Calcolo ET₀ con Hargreaves-Samani
# -----------------------------------------------------------------------

def compute_et0_hs(daily: list[DailyWeather]) -> list[float]:
    """ET₀ HS (mm/giorno) per ogni entry, applicato alle T_min/T_max."""
    return [
        et0_hargreaves_samani(
            t_min=d.t_min, t_max=d.t_max,
            latitude_deg=MILAN_LAT, j=day_of_year(d.day),
        )
        for d in daily
    ]


# -----------------------------------------------------------------------
#  Plot di confronto: 3 pannelli
# -----------------------------------------------------------------------

def plot_comparison(
    eco_daily: list[DailyWeather],
    eco_et0_hs: list[float],
    om_daily: list[DailyWeather],
    om_et0_hs: list[float],
    eco_source: str,
    om_source: str,
) -> Path:
    """
    Tre pannelli verticali sovrapposti, con asse temporale condiviso:
      1. Temperature: T_min e T_max di entrambe le fonti
      2. Precipitazione: barre giornaliere
      3. ET₀ HS calcolato dalle due fonti, con barra del bias
    """
    eco_days = [d.day for d in eco_daily]
    om_days = [d.day for d in om_daily]

    # Limitiamoci all'intersezione delle date così il confronto giorno-
    # per-giorno ha senso.
    common_days = sorted(set(eco_days) & set(om_days))
    if not common_days:
        # Niente sovrapposizione: usiamo entrambe ma non potremo
        # calcolare il bias.
        common_days = sorted(set(eco_days) | set(om_days))

    # Mappa di accesso indicizzato per data.
    eco_by_day = {d.day: (d, et0)
                  for d, et0 in zip(eco_daily, eco_et0_hs)}
    om_by_day = {d.day: (d, et0)
                 for d, et0 in zip(om_daily, om_et0_hs)}

    fig, (ax_t, ax_r, ax_e) = plt.subplots(
        3, 1, figsize=(11, 9.5),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.2, 2.5]},
    )

    fig.suptitle(
        f"Bridge sensore-modello: stazione Ecowitt vs archivio Open-Meteo\n"
        f"{common_days[0]} → {common_days[-1]}",
        fontsize=13, fontweight="bold", y=0.995,
    )

    # Asse x indicizzato: tutti e tre i pannelli usano lo stesso array
    # numerico così che `sharex=True` lavori correttamente. Le etichette
    # con le date vengono applicate solo all'ultimo pannello.
    x = np.arange(len(common_days))

    # ---- Pannello 1: temperature ----
    eco_tmin = [eco_by_day[d][0].t_min if d in eco_by_day else np.nan
                for d in common_days]
    eco_tmax = [eco_by_day[d][0].t_max if d in eco_by_day else np.nan
                for d in common_days]
    om_tmin = [om_by_day[d][0].t_min if d in om_by_day else np.nan
               for d in common_days]
    om_tmax = [om_by_day[d][0].t_max if d in om_by_day else np.nan
               for d in common_days]

    ax_t.plot(x, eco_tmax, "o-",
              color="tab:red", linewidth=2.0, markersize=6,
              label="Ecowitt T_max")
    ax_t.plot(x, eco_tmin, "o-",
              color="tab:blue", linewidth=2.0, markersize=6,
              label="Ecowitt T_min")
    ax_t.plot(x, om_tmax, "s--",
              color="tab:red", linewidth=1.5, markersize=6,
              alpha=0.65, label="Open-Meteo T_max")
    ax_t.plot(x, om_tmin, "s--",
              color="tab:blue", linewidth=1.5, markersize=6,
              alpha=0.65, label="Open-Meteo T_min")
    ax_t.set_ylabel("Temperatura (°C)")
    ax_t.set_title("Temperature giornaliere — locale vs grigliato",
                   fontsize=11, color="tab:gray")
    ax_t.grid(True, alpha=0.3)
    ax_t.legend(loc="best", framealpha=0.9, fontsize=8.5, ncol=2)

    # ---- Pannello 2: precipitazioni ----
    eco_rain = [eco_by_day[d][0].precipitation_mm
                if d in eco_by_day else np.nan
                for d in common_days]
    om_rain = [om_by_day[d][0].precipitation_mm
               if d in om_by_day else np.nan
               for d in common_days]
    width = 0.4
    ax_r.bar(x - width / 2, eco_rain, width=width,
             color="tab:cyan", alpha=0.85, edgecolor="black",
             linewidth=0.4, label="Ecowitt")
    ax_r.bar(x + width / 2, om_rain, width=width,
             color="tab:purple", alpha=0.65, edgecolor="black",
             linewidth=0.4, label="Open-Meteo")
    ax_r.set_ylabel("Pioggia (mm)")
    ax_r.set_title("Pioggia giornaliera",
                   fontsize=11, color="tab:gray")
    ax_r.legend(loc="best", framealpha=0.9, fontsize=8.5)
    ax_r.grid(True, alpha=0.3, axis="y")

    # ---- Pannello 3: ET₀ HS confronto + bias ----
    eco_et0 = [eco_by_day[d][1] if d in eco_by_day else np.nan
               for d in common_days]
    om_et0 = [om_by_day[d][1] if d in om_by_day else np.nan
              for d in common_days]

    ax_e.plot(x, eco_et0, "o-",
              color="tab:green", linewidth=2.2, markersize=7,
              label="ET₀ HS dalla stazione locale")
    ax_e.plot(x, om_et0, "s--",
              color="tab:orange", linewidth=2.0, markersize=7,
              label="ET₀ HS dall'archivio grigliato")
    ax_e.set_ylabel("ET₀ HS (mm/giorno)")
    ax_e.set_xlabel("Giorno")
    ax_e.set_title("ET₀ Hargreaves-Samani calcolato sui due dataset",
                   fontsize=11, color="tab:gray")
    ax_e.grid(True, alpha=0.3)
    ax_e.legend(loc="best", framealpha=0.9, fontsize=9)
    ax_e.set_ylim(bottom=0)

    # Etichette delle date solo sull'ultimo pannello (gli altri le
    # ereditano via sharex). Una etichetta ogni quanti giorni se la
    # finestra è lunga.
    n_labels = len(common_days)
    stride = max(1, n_labels // 10)
    label_idx = list(range(0, n_labels, stride))
    ax_e.set_xticks([x[i] for i in label_idx])
    ax_e.set_xticklabels(
        [common_days[i].strftime("%d/%m") for i in label_idx],
        rotation=30, ha="right",
    )

    # Calcoliamo e annotiamo il bias medio (locale - grigliato) come
    # metrica sintetica del microclima.
    valid = [(e, o) for e, o in zip(eco_et0, om_et0)
             if not (np.isnan(e) or np.isnan(o))]
    if valid:
        bias = np.mean([(e - o) / o * 100 for e, o in valid])
        ax_e.text(
            0.02, 0.95,
            f"Bias medio Ecowitt − Open-Meteo: {bias:+.1f}%",
            transform=ax_e.transAxes,
            fontsize=10, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.4",
                      facecolor="white", edgecolor="gray",
                      alpha=0.92),
        )

    fig.text(
        0.5, 0.005,
        f"Sensore: {eco_source}  |  Grigliato: {om_source}",
        ha="center", fontsize=8.5, color="gray", style="italic",
    )

    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    path = OUTPUT_DIR / "history_bridge_comparison.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Report testuale
# -----------------------------------------------------------------------

def print_summary(
    eco_daily: list[DailyWeather],
    eco_et0_hs: list[float],
    om_daily: list[DailyWeather],
    om_et0_hs: list[float],
) -> None:
    """Tabella giornaliera con confronto T_min, T_max, ET₀ delle due fonti."""
    print()
    print("=" * 78)
    print(f"{'Giorno':<12} | {'Ecowitt (locale)':<26} | "
          f"{'Open-Meteo (grigliato)':<26}")
    print(f"{'':<12} | {'T_min':>6} {'T_max':>6} {'ET₀':>7} | "
          f"{'T_min':>6} {'T_max':>6} {'ET₀':>7}")
    print("-" * 78)

    eco_by_day = {d.day: (d, et0)
                  for d, et0 in zip(eco_daily, eco_et0_hs)}
    om_by_day = {d.day: (d, et0)
                 for d, et0 in zip(om_daily, om_et0_hs)}
    all_days = sorted(set(eco_by_day.keys()) | set(om_by_day.keys()))

    for day in all_days:
        eco_part = "—"
        if day in eco_by_day:
            d, et0 = eco_by_day[day]
            eco_part = (f"{d.t_min:>5.1f}° {d.t_max:>5.1f}° "
                        f"{et0:>5.2f}mm")
        om_part = "—"
        if day in om_by_day:
            d, et0 = om_by_day[day]
            om_part = (f"{d.t_min:>5.1f}° {d.t_max:>5.1f}° "
                       f"{et0:>5.2f}mm")
        print(f"{day.isoformat():<12} | {eco_part:<26} | {om_part:<26}")

    print("=" * 78)


# -----------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("Bridge sensore-modello: confronto Ecowitt history vs Open-Meteo")
    print("=" * 70)
    print()

    # Finestra di analisi: una settimana di inizio aprile 2026. In
    # modalità reale questa stessa finestra viene richiesta a entrambe
    # le API. La fixture offline copre esattamente questo intervallo.
    start = datetime(2026, 4, 1, 0, 0, 0)
    end = datetime(2026, 4, 7, 23, 59, 59)
    print(f"Finestra: {start.date()} → {end.date()}\n")

    eco_daily, eco_source = acquire_ecowitt_daily(start, end)
    om_daily, om_source = acquire_openmeteo_daily(start.date(), end.date())

    print(f"\n• Ecowitt: {len(eco_daily)} giorni aggregati ({eco_source})")
    print(f"• Open-Meteo: {len(om_daily)} giorni ({om_source})\n")

    if not eco_daily:
        print("⚠️  Nessun giorno valido dalla stazione Ecowitt; "
              "demo non eseguibile.")
        return

    eco_et0 = compute_et0_hs(eco_daily)
    om_et0 = compute_et0_hs(om_daily)

    print_summary(eco_daily, eco_et0, om_daily, om_et0)

    print("\nGenerazione grafico di confronto...")
    p = plot_comparison(
        eco_daily, eco_et0, om_daily, om_et0,
        eco_source, om_source,
    )
    print(f"  → {p.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
