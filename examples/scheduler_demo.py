"""
Demo dello scheduler agronomico: dal forecast al piano di irrigazione.

Mette insieme tutti i livelli costruiti finora:
  - science/   per il bilancio idrico
  - domain/    per Pot, Species, e il pianificatore
  - io/        per Open-Meteo (con fallback offline)

Lo script orchestra una pipeline completa: scarica la previsione
meteorologica per Milano, crea un piccolo inventario di vasi, chiede
allo scheduler di pianificare le irrigazioni della settimana, e
produce tre output:

  1. Un report testuale "agenda settimanale" che elenca per ogni
     giorno dei prossimi sette quali vasi richiedono intervento e
     con che dose, più una sintesi dei totali del piano.

  2. Un grafico Gantt che dispone gli eventi su un piano (giorno,
     vaso). I marker sono dimensionati in funzione della dose in
     litri, e colorati per ragione (CURRENTLY_IN_ALERT vs
     PREDICTED_ALERT). Sotto, una stacked bar mostra i litri totali
     necessari per ogni giorno — utile per pianificare il numero
     di passaggi con l'innaffiatoio.

  3. Un grafico delle traiettorie idriche dei tre vasi, con marker
     verticali sui giorni di intervento schedulato. Mostra
     visivamente perché lo scheduler ha deciso quegli interventi:
     ogni marker è posizionato esattamente quando la curva di stato
     del vaso attraversa la sua soglia di allerta.

Esegui con:
    python examples/scheduler_demo.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.pot import Location, Pot
from fitosim.domain.scheduler import (
    IrrigationPlan,
    IrrigationReason,
    plan_irrigations,
)
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
#  Inventario di test
# -----------------------------------------------------------------------
def build_inventory() -> list[Pot]:
    """
    Tre vasi con caratteristiche volutamente diverse per produrre un
    piano di irrigazione interessante: uno sensibile (basilico), uno
    grosso e affamato (pomodoro), uno tollerante in substrato drenante
    (rosmarino). Ognuno reagirà al meteo della settimana in modo
    riconoscibile, e lo scheduler dovrà gestire le tre situazioni
    coerentemente.
    """
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


# -----------------------------------------------------------------------
#  Fetching meteo con fallback offline
# -----------------------------------------------------------------------
def _build_synthetic_payload() -> dict:
    """Payload sintetico realistico per Milano in luglio quando la
    rete non è disponibile. Replica la struttura di Open-Meteo."""
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
    """Tenta Open-Meteo; in caso di fallimento usa il payload sintetico."""
    try:
        weather = fetch_daily_forecast(
            latitude=MILAN_LAT, longitude=MILAN_LON,
            days=N_DAYS, use_cache=True,
        )
        return weather, True
    except OSError as exc:
        print(f"⚠️  Open-Meteo non raggiungibile: {exc}")
        print("   Demo eseguito con dati sintetici.\n")
        return parse_openmeteo_response(_build_synthetic_payload()), False


# -----------------------------------------------------------------------
#  Report testuale
# -----------------------------------------------------------------------
def print_weekly_agenda(plan: IrrigationPlan, weather: list[DailyWeather]) -> None:
    """
    Formatta il piano come "agenda settimanale": una riga per giorno,
    con elenco vasi/dosi se ci sono interventi, "—" se la giornata
    è di riposo. Aggiunge la temperatura massima del giorno come
    contesto, perché i picchi di calore spiegano i picchi di intervento.
    """
    print(f"AGENDA SETTIMANALE — Milano, dal "
          f"{plan.generated_at.isoformat()}")
    print(f"Orizzonte: {plan.horizon_days} giorni  •  "
          f"{plan.n_events if hasattr(plan, 'n_events') else len(plan.events)} interventi totali  •  "
          f"{plan.total_water_liters():.1f} L di acqua complessivi\n")

    weather_by_day = {w.day: w for w in weather}
    horizon_dates = sorted(weather_by_day.keys())

    for day in horizon_dates:
        events_today = plan.events_for_date(day)
        w = weather_by_day[day]
        weekday = day.strftime("%a")
        date_str = day.strftime("%d/%m")
        # Indicazione meteo concisa (T_max e pioggia se rilevante).
        rain_marker = (f", pioggia {w.precipitation_mm:.1f}mm"
                       if w.precipitation_mm >= 0.5 else "")
        weather_str = f"T_max {w.t_max:.1f}°{rain_marker}"

        if events_today:
            # Più eventi nello stesso giorno: prima il sommario, poi
            # il dettaglio per vaso.
            total_l = plan.total_liters_on_date(day)
            print(f"  {weekday} {date_str}  ({weather_str})  "
                  f"→  {len(events_today)} interventi, {total_l:.2f}L")
            for e in events_today:
                marker = ("⚠️" if e.reason == IrrigationReason.CURRENTLY_IN_ALERT
                          else "  ")
                print(f"      {marker} {e.pot_label:<12} "
                      f"{e.dose_liters:>5.2f}L "
                      f"({e.reason.value})")
        else:
            print(f"  {weekday} {date_str}  ({weather_str})  "
                  f"→  riposo")
    print()


# -----------------------------------------------------------------------
#  Grafico 1 — Gantt del piano + totali giornalieri
# -----------------------------------------------------------------------
def plot_schedule_gantt(
    plan: IrrigationPlan,
    inventory: list[Pot],
    weather: list[DailyWeather],
) -> Path:
    """
    Visualizzazione Gantt-style del piano. Ogni vaso ha la sua riga
    sull'asse y; i giorni dell'orizzonte sono sull'asse x. Un marker
    al punto (giorno, vaso) indica un evento di irrigazione, dimensionato
    proporzionalmente alla dose in litri e colorato per ragione.
    """
    pot_labels = [p.label for p in inventory]
    pot_colors = {"Basilico": "tab:blue",
                  "Pomodoro": "tab:red",
                  "Rosmarino": "tab:olive"}
    horizon_dates = sorted({w.day for w in weather})

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(11.5, 6.5),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )

    # ---- Pannello superiore: Gantt ----
    # Griglia verticale per i giorni: aiuta visivamente ad allineare
    # eventi con date.
    for d in horizon_dates:
        ax_top.axvline(d, color="lightgray", linewidth=0.5, alpha=0.6)

    # Per ogni evento, un marker sulla riga del vaso. La dimensione del
    # marker scala con la dose; il colore è per ragione (rosso più
    # scuro = già in allerta, arancione = previsto).
    for event in plan.events:
        pot_idx = pot_labels.index(event.pot_label)
        # Scala marker: 100 + 80*liters dà marker leggibili sia per
        # dosi piccole (~0.3L → ~125) sia grandi (~3L → ~340).
        size = 100 + 80 * event.dose_liters
        if event.reason == IrrigationReason.CURRENTLY_IN_ALERT:
            face = "darkred"
            edge = "black"
        else:
            face = "tab:orange"
            edge = "darkred"
        ax_top.scatter(
            event.event_date, pot_idx,
            s=size, color=face, edgecolor=edge,
            linewidths=1.5, alpha=0.85, zorder=5,
        )
        # Etichetta della dose, posizionata appena sopra il marker.
        ax_top.text(
            event.event_date, pot_idx + 0.18,
            f"{event.dose_liters:.2f}L",
            ha="center", fontsize=8.5, color="black",
        )

    # Etichette colorate sull'asse y per riconoscere i vasi.
    ax_top.set_yticks(range(len(pot_labels)))
    ax_top.set_yticklabels(pot_labels)
    for tick, label in zip(ax_top.get_yticklabels(), pot_labels):
        tick.set_color(pot_colors.get(label, "black"))
    ax_top.set_ylim(-0.6, len(pot_labels) - 0.4)
    ax_top.set_ylabel("Vaso")
    ax_top.grid(True, alpha=0.25, axis="x")

    # Legenda manuale per le due ragioni.
    legend_elements = [
        plt.scatter([], [], s=200, color="darkred", edgecolor="black",
                    linewidths=1.5, label="Già in allerta (urgente)"),
        plt.scatter([], [], s=200, color="tab:orange", edgecolor="darkred",
                    linewidths=1.5, label="Allerta prevista"),
    ]
    ax_top.legend(handles=legend_elements, loc="lower right",
                  framealpha=0.92, fontsize=9)
    ax_top.set_title(
        f"Piano di irrigazione — {plan.horizon_days} giorni dal "
        f"{plan.generated_at.isoformat()}"
    )

    # ---- Pannello inferiore: stacked bar dei litri totali per giorno ----
    # Ogni barra è la somma dei litri da somministrare quel giorno,
    # decomposta per vaso così che si veda chi contribuisce di più.
    bottom = np.zeros(len(horizon_dates))
    for label in pot_labels:
        events_for_pot = plan.events_for_pot(label)
        # Per ogni giorno della finestra, sommo i litri di questo vaso
        # (zero se non c'è evento per quel vaso quel giorno).
        per_day = []
        for d in horizon_dates:
            evs = [e for e in events_for_pot if e.event_date == d]
            per_day.append(sum(e.dose_liters for e in evs))
        per_day_arr = np.array(per_day)
        ax_bot.bar(
            horizon_dates, per_day_arr, bottom=bottom,
            color=pot_colors.get(label, "gray"),
            label=label, alpha=0.85,
            edgecolor="black", linewidth=0.4,
        )
        bottom += per_day_arr

    # Etichetta del totale sopra ciascuna barra (solo se > 0).
    for i, d in enumerate(horizon_dates):
        if bottom[i] > 0:
            ax_bot.text(
                d, bottom[i] + 0.08, f"{bottom[i]:.2f}L",
                ha="center", fontsize=8.5,
            )

    ax_bot.set_ylabel("Acqua totale (L)")
    ax_bot.set_xlabel("Giorno")
    ax_bot.grid(True, alpha=0.3, axis="y")
    ax_bot.legend(loc="upper right", framealpha=0.92, fontsize=8)

    fig.autofmt_xdate(rotation=30)
    path = OUTPUT_DIR / "scheduler_gantt.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Grafico 2 — Traiettorie con marker eventi
# -----------------------------------------------------------------------
def simulate_with_events(
    inventory: list[Pot],
    weather: list[DailyWeather],
    plan: IrrigationPlan,
) -> dict[str, list[float]]:
    """
    Simulazione "what-if con interventi": riproduce la traiettoria di
    ogni vaso assumendo che gli eventi schedulati siano effettivamente
    eseguiti. Le traiettorie risultanti sono ciò che vedremmo se il
    giardiniere seguisse il piano alla lettera.

    Lavora su copie (non muta gli originali). Restituisce per ogni
    vaso la lista degli stati giornalieri (lunghezza N_DAYS+1).
    """
    from dataclasses import replace
    sim_pots = {p.label: replace(p) for p in inventory}
    trajectories = {label: [p.state_mm] for label, p in sim_pots.items()}

    for w in weather:
        et0 = et0_hargreaves_samani(
            t_min=w.t_min, t_max=w.t_max,
            latitude_deg=MILAN_LAT, j=day_of_year(w.day),
        )
        for label, pot in sim_pots.items():
            # Applica il bilancio del giorno.
            pot.apply_balance_step(
                et_0_mm=et0,
                water_input_mm=w.precipitation_mm,
                current_date=w.day,
            )
            # Se il piano prevede un intervento per questo vaso oggi,
            # ricarichiamo a FC come farebbe il giardiniere.
            events_today = [
                e for e in plan.events_for_pot(label)
                if e.event_date == w.day
            ]
            if events_today:
                pot.state_mm = pot.fc_mm
            trajectories[label].append(pot.state_mm)

    return trajectories


def plot_trajectories_with_events(
    inventory: list[Pot],
    weather: list[DailyWeather],
    plan: IrrigationPlan,
    trajectories: dict[str, list[float]],
) -> Path:
    """
    Tre traiettorie sovrapposte normalizzate come % della FC del vaso.
    Su ogni traiettoria, marker a forma di goccia indicano gli eventi
    schedulati: si vede così come ogni intervento riporta il vaso al
    100% e perché lo scheduler ha deciso di intervenire proprio in
    quel giorno (è il punto in cui la curva incrocia la soglia di
    allerta personale).
    """
    pot_colors = {"Basilico": "tab:blue",
                  "Pomodoro": "tab:red",
                  "Rosmarino": "tab:olive"}
    day0 = weather[0].day - timedelta(days=1)
    days = [day0] + [w.day for w in weather]

    fig, ax = plt.subplots(figsize=(11.5, 6.5))

    # Linea della FC al 100% come riferimento universale.
    ax.axhline(100, linestyle="--", color="darkgreen",
               alpha=0.5, linewidth=1.0)
    ax.text(days[-1], 101, "Capacità di campo",
            color="darkgreen", fontsize=8.5, ha="right")

    for pot in inventory:
        color = pot_colors[pot.label]
        states = np.array(trajectories[pot.label])
        states_pct = states / pot.fc_mm * 100.0

        # Curva principale.
        ax.plot(days, states_pct, "o-",
                color=color, linewidth=2.2, markersize=5,
                label=f"{pot.label}", zorder=4)

        # Soglia di allerta personale del vaso, in % della sua FC.
        alert_pct = pot.alert_mm / pot.fc_mm * 100.0
        ax.axhline(alert_pct, color=color, linestyle=":",
                   alpha=0.35, linewidth=1.2)
        ax.text(days[0], alert_pct - 1.5,
                f"  soglia {pot.label}",
                color=color, fontsize=7.5, alpha=0.75)

        # Marker per ogni evento schedulato di questo vaso. Marker a
        # forma di "v" rovesciata posizionato sull'asse temporale,
        # sopra la curva, nel giorno dell'evento.
        for e in plan.events_for_pot(pot.label):
            # Trova l'indice corrispondente alla data dell'evento.
            day_index = days.index(e.event_date)
            ax.annotate(
                "",
                xy=(e.event_date, states_pct[day_index]),
                xytext=(e.event_date, states_pct[day_index] + 12),
                arrowprops=dict(
                    arrowstyle="-|>", color=color,
                    lw=1.5, alpha=0.9,
                ),
            )
            ax.text(
                e.event_date, states_pct[day_index] + 14,
                f"{e.dose_liters:.1f}L",
                color=color, fontsize=8.5, ha="center", fontweight="bold",
            )

    ax.set_xlabel("Giorno")
    ax.set_ylabel("Stato idrico (% della FC del vaso)")
    ax.set_title(
        "Traiettorie idriche con interventi schedulati — "
        "se segui il piano, le curve restano sopra le soglie"
    )
    ax.set_ylim(0, 130)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", framealpha=0.92, fontsize=9)

    fig.autofmt_xdate(rotation=30)
    path = OUTPUT_DIR / "scheduler_trajectories_with_events.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# -----------------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------------
def main() -> None:
    print("=" * 72)
    print("Demo dello scheduler agronomico — pianificazione settimanale")
    print("=" * 72)
    print()

    weather, is_real = fetch_with_fallback()
    if is_real:
        print(f"✓ Previsione reale Open-Meteo per Milano "
              f"({len(weather)} giorni).\n")

    inventory = build_inventory()
    today = weather[0].day

    # IL CUORE DELLA TAPPA: una sola chiamata produce il piano.
    plan = plan_irrigations(
        inventory=inventory,
        forecast=weather,
        latitude_deg=MILAN_LAT,
        today=today,
    )

    if plan.is_empty():
        print("Nessun intervento necessario nei prossimi "
              f"{plan.horizon_days} giorni: tutti i vasi attraversano "
              "la settimana sopra le proprie soglie di allerta.\n")
        return

    print_weekly_agenda(plan, weather)

    print("Generazione visualizzazioni...")
    p1 = plot_schedule_gantt(plan, inventory, weather)
    print(f"  [1/2] {p1.name}")

    trajectories = simulate_with_events(inventory, weather, plan)
    p2 = plot_trajectories_with_events(
        inventory, weather, plan, trajectories,
    )
    print(f"  [2/2] {p2.name}")
    print(f"\nSalvati in: {OUTPUT_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
