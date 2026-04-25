"""
Esempio: previsione idrica del vaso con dati Open-Meteo reali.

Recupera la previsione meteo di 7 giorni per una posizione (Milano di
default) tramite Open-Meteo, esegue il bilancio idrico di un vaso di
basilico per quel periodo, e produce sia un report testuale sia un
grafico della traiettoria dello stato.

Questo è il primo esempio "operativo" di fitosim: i dati meteorologici
non sono inventati, ma vengono dalla rete reale. Il vaso simulato è
quello che potresti effettivamente avere sul balcone di casa.

Robustezza offline
------------------
Se la rete non è disponibile (ambiente sandboxed, test, viaggio),
lo script ricade su una fixture sintetica realistica calibrata su
clima padano luglio, così che l'esempio sia eseguibile ovunque.
Quando lo eseguirai con accesso a internet, vedrai i dati reali del
giorno corrente — e quel giorno è il banco di prova vero.

Esegui con:
    python examples/openmeteo_real_forecast.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.io.openmeteo import DailyWeather, fetch_daily_forecast
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


# -----------------------------------------------------------------------
#  Configurazione dello scenario
# -----------------------------------------------------------------------
LATITUDE_DEG = 45.47    # Milano, Lombardia
LONGITUDE_DEG = 9.19
N_DAYS = 7

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def synthetic_fallback() -> list[DailyWeather]:
    """
    Fixture meteorologica sintetica per ambienti senza rete.
    Calibrata su climatologia tipica di Milano in piena estate
    (terza decade di luglio), con piccole variazioni inter-giornaliere
    e un evento piovoso a metà periodo.
    """
    base = date.today()
    template = [
        # (T_min, T_max, pioggia_mm)
        (19.0, 31.0, 0.0),
        (20.0, 32.5, 0.0),
        (21.0, 33.0, 0.0),
        (19.5, 28.0, 5.0),  # giornata di pioggia
        (17.0, 26.0, 2.0),
        (18.5, 29.0, 0.0),
        (20.0, 31.0, 0.0),
    ]
    return [
        DailyWeather(
            day=base + timedelta(days=i),
            t_min=t_min, t_max=t_max,
            precipitation_mm=rain,
        )
        for i, (t_min, t_max, rain) in enumerate(template)
    ]


def get_forecast() -> tuple[list[DailyWeather], str]:
    """
    Tenta di recuperare la previsione reale; in caso di errore di rete
    ricade silenziosamente sulla fixture sintetica. Restituisce la
    lista di DailyWeather e una stringa che identifica la fonte usata,
    così che il grafico possa essere etichettato correttamente.
    """
    try:
        forecast = fetch_daily_forecast(
            latitude=LATITUDE_DEG,
            longitude=LONGITUDE_DEG,
            days=N_DAYS,
        )
        return forecast, "Open-Meteo (dati reali)"
    except OSError as exc:
        print(
            f"⚠️  Impossibile contattare Open-Meteo: {exc}\n"
            f"   Uso fixture sintetica per consentire l'esecuzione."
        )
        return synthetic_fallback(), "Fixture sintetica (no rete)"


# -----------------------------------------------------------------------
#  Simulazione e plot
# -----------------------------------------------------------------------

def simulate_pot_with_forecast(
    pot: Pot,
    forecast: list[DailyWeather],
) -> dict:
    """
    Esegue il bilancio idrico del vaso giorno per giorno, usando ogni
    DailyWeather come fonte di T_min/T_max (per ET₀) e di precipitazione
    (come water_input_mm). Ritorna i dati raccolti per il plot.
    """
    states = [pot.state_mm]
    et0_values = []
    et_c_values = []
    alerts = [False]

    for w in forecast:
        et0 = et0_hargreaves_samani(
            t_min=w.t_min, t_max=w.t_max,
            latitude_deg=LATITUDE_DEG,
            j=day_of_year(w.day),
        )
        et0_values.append(et0)
        # Calcoliamo ET_c effettiva (con Ks) prima del passo, perché ci
        # serve nel grafico delle barre.
        et_c = pot.current_et_c(et_0_mm=et0, current_date=w.day)
        et_c_values.append(et_c)

        result = pot.apply_balance_step(
            et_0_mm=et0,
            water_input_mm=w.precipitation_mm,
            current_date=w.day,
        )
        states.append(pot.state_mm)
        alerts.append(result.under_alert)

    return {
        "forecast": forecast,
        "states": states,
        "et0": et0_values,
        "et_c": et_c_values,
        "alerts": alerts,
    }


def print_table(sim: dict, source_label: str, pot: Pot) -> None:
    """Tabella testuale riassuntiva della previsione."""
    print(f"Previsione fitosim per {pot.label}")
    print(f"Specie: {pot.species.common_name}, vaso "
          f"{pot.pot_volume_l}L di {pot.substrate.name.lower()}")
    print(f"Fonte meteo: {source_label}")
    print(f"Posizione: ({LATITUDE_DEG}, {LONGITUDE_DEG})")
    print()
    header = (
        f"{'Data':<12} {'T_min':>5} {'T_max':>5} "
        f"{'Pioggia':>8} {'ET₀':>5} {'ET_c':>5} "
        f"{'Stato':>7} {'Allerta':>7}"
    )
    print(header)
    print("-" * len(header))
    for i, w in enumerate(sim["forecast"]):
        alert = "⚠️" if sim["alerts"][i + 1] else ""
        print(
            f"{w.day.isoformat():<12} "
            f"{w.t_min:>5.1f} {w.t_max:>5.1f} "
            f"{w.precipitation_mm:>6.1f}mm "
            f"{sim['et0'][i]:>5.2f} {sim['et_c'][i]:>5.2f} "
            f"{sim['states'][i + 1]:>5.1f}mm {alert:>7}"
        )


def plot_forecast(sim: dict, source_label: str, pot: Pot) -> Path:
    """
    Doppio grafico: traiettoria dello stato in alto, ET_c giornaliera
    e pioggia in basso. Serve a vedere d'un colpo "cosa succede"
    durante la finestra di previsione.
    """
    days = list(range(len(sim["states"])))
    dates = [pot.planting_date] + [w.day for w in sim["forecast"]]
    # Per le date sull'asse x usiamo l'index e mettiamo le date come
    # tick labels — è più leggibile che gestire date matplotlib direttamente.
    date_labels = ["Inizio"] + [
        w.day.strftime("%d/%m") for w in sim["forecast"]
    ]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 8), sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )

    # --- Pannello superiore: stato del vaso ---
    ax1.axhline(pot.fc_mm, linestyle="--", color="darkgreen",
                linewidth=1.0, alpha=0.7,
                label=f"FC ({pot.fc_mm:.1f}mm)")
    ax1.axhline(pot.alert_mm, linestyle="--", color="darkorange",
                linewidth=1.0, alpha=0.7,
                label=f"Allerta ({pot.alert_mm:.1f}mm)")
    ax1.axhline(pot.pwp_mm, linestyle="--", color="darkred",
                linewidth=1.0, alpha=0.7,
                label=f"PWP ({pot.pwp_mm:.1f}mm)")

    ax1.plot(days, sim["states"], color="tab:blue",
             linewidth=2.5, marker="o", markersize=7,
             label="Contenuto idrico", zorder=5)

    # Marker sui giorni di allerta.
    alert_days = [i for i, a in enumerate(sim["alerts"]) if a]
    if alert_days:
        ax1.scatter(
            alert_days, [sim["states"][i] for i in alert_days],
            marker="X", s=180, color="tab:red",
            edgecolors="black", linewidths=1.4, zorder=6,
            label="Giorni in allerta",
        )

    ax1.set_ylabel("Contenuto idrico (mm)")
    ax1.set_title(
        f"Previsione bilancio idrico — {pot.label}\n"
        f"Fonte meteo: {source_label}"
    )
    ax1.set_ylim(0, pot.fc_mm * 1.2)
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="upper right", fontsize=9, framealpha=0.92)

    # --- Pannello inferiore: ET_c e pioggia ---
    ax2.bar(
        days[1:], sim["et_c"], color="tab:purple", alpha=0.7,
        label="ET_c (consumo previsto)", width=0.6,
    )
    rain = [w.precipitation_mm for w in sim["forecast"]]
    if any(r > 0 for r in rain):
        ax2.bar(
            days[1:], rain, color="tab:cyan", alpha=0.7,
            label="Pioggia prevista", width=0.6, bottom=0,
        )

    ax2.set_xlabel("Giorno")
    ax2.set_ylabel("mm/giorno")
    ax2.set_xticks(days)
    ax2.set_xticklabels(date_labels, rotation=30, ha="right")
    ax2.grid(True, alpha=0.25, axis="y")
    ax2.legend(loc="upper right", fontsize=9, framealpha=0.92)

    path = OUTPUT_DIR / "openmeteo_forecast.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    forecast, source_label = get_forecast()

    # Vaso di basilico in piena vegetazione, partito a metà giugno.
    # Lo stato iniziale è settato a circa 75% di FC per simulare
    # "irrigato qualche giorno fa" — più realistico di "appena pieno".
    pot = Pot(
        label="Basilico-balcone",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=4.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date.today() - timedelta(days=40),
    )
    pot.state_mm = pot.fc_mm * 0.75

    sim = simulate_pot_with_forecast(pot, forecast)
    print_table(sim, source_label, pot)
    print()
    plot_path = plot_forecast(sim, source_label, pot)
    print(f"Grafico salvato in: {plot_path}")


if __name__ == "__main__":
    main()
