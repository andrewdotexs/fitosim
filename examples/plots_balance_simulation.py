"""
Grafici della simulazione del bilancio idrico a 14 giorni.

Produce due figure complementari dello stesso scenario già analizzato
numericamente in `vaso_milano_14giorni.py`:

    1. simulation_timeline.png
       Evoluzione temporale del contenuto idrico nel vaso, con soglie
       di riferimento (FC, allerta, PWP) e zone colorate per distinguere
       a colpo d'occhio regione di comfort, stress e morte.

    2. simulation_start_vs_end.png
       Confronto "prima e dopo" come grafico a barre stratificato: ogni
       barra rappresenta il contenuto idrico suddiviso in tre zone
       idrologiche, così che il lettore possa identificare non solo
       "quanto" ma "che tipo" di acqua è presente in ogni istante.

I due grafici insieme raccontano la dinamica (come arriva il vaso alla
fine) e la statica (qual è il saldo finale) della simulazione.

Esegui dalla radice del progetto con:
    python examples/plots_balance_simulation.py
"""

from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.science.balance import water_balance_step_mm
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import (
    UNIVERSAL_POTTING_SOIL,
    circular_pot_surface_area_m2,
    pot_substrate_depth_mm,
    readily_available_water,
)


# -----------------------------------------------------------------------
#  Parametri dello scenario (identici a vaso_milano_14giorni.py)
# -----------------------------------------------------------------------
LATITUDE_DEG = 45.47
START_DATE = date(2025, 7, 15)
N_DAYS = 14
POT_VOLUME_L = 5.0
POT_DIAMETER_CM = 20.0
SUBSTRATE = UNIVERSAL_POTTING_SOIL
KC = 1.0

DAILY_TEMPERATURES = [
    (19.0, 31.0), (20.0, 32.0), (21.0, 33.0), (20.0, 31.0),
    (18.0, 28.0), (17.0, 26.0), (18.0, 28.0), (20.0, 30.0),
    (21.0, 32.0), (22.0, 33.0), (22.0, 34.0), (21.0, 32.0),
    (19.0, 29.0), (19.0, 28.0),
]

# Palette coerente tra i due grafici: verde = comfort, arancio = stress,
# rosso = morte, grigio scuro = zona non disponibile (sotto PWP). I
# colori sono scelti intuitivamente (green-yellow-red = traffic-light
# semantic) e con trasparenze moderate per non sovrastare i dati.
COLOR_COMFORT = "tab:green"
COLOR_STRESS = "tab:orange"
COLOR_UNAVAILABLE = "dimgray"
COLOR_DEATH = "tab:red"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =======================================================================
#  Esecuzione della simulazione
# =======================================================================

def run_simulation() -> dict:
    """
    Esegue la simulazione di 14 giorni e restituisce un dizionario con
    tutti i dati necessari ai grafici: stati giornalieri, ET, flag di
    allerta, e soglie idrologiche di riferimento.
    """
    surface_area = circular_pot_surface_area_m2(POT_DIAMETER_CM)
    depth_mm = pot_substrate_depth_mm(POT_VOLUME_L, surface_area)

    # Soglie fisiche derivate da substrato e geometria del vaso.
    fc_mm = SUBSTRATE.theta_fc * depth_mm
    pwp_mm = SUBSTRATE.theta_pwp * depth_mm
    raw_fraction = readily_available_water(SUBSTRATE)
    alert_mm = (SUBSTRATE.theta_fc - raw_fraction) * depth_mm

    # Stato iniziale: appena irrigato fino a capacità di campo.
    state_mm = fc_mm
    # La lista include l'istante 0 (stato iniziale) e poi gli N_DAYS
    # stati successivi, per un totale di N_DAYS+1 punti sull'asse tempo.
    states = [state_mm]
    et_values = []
    alerts = [False]  # a giorno 0 lo stato è FC, non c'è allerta

    for day_index in range(N_DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        j = day_of_year(current_date)
        t_min, t_max = DAILY_TEMPERATURES[day_index]

        et0 = et0_hargreaves_samani(t_min, t_max, LATITUDE_DEG, j)
        et_c = KC * et0
        et_values.append(et_c)

        result = water_balance_step_mm(
            current_mm=state_mm,
            water_input_mm=0.0,
            et_c_mm=et_c,
            substrate=SUBSTRATE,
            substrate_depth_mm=depth_mm,
        )
        state_mm = result.new_state
        states.append(state_mm)
        alerts.append(result.under_alert)

    return {
        "states": states,
        "et_values": et_values,
        "alerts": alerts,
        "depth_mm": depth_mm,
        "fc_mm": fc_mm,
        "pwp_mm": pwp_mm,
        "alert_mm": alert_mm,
    }


# =======================================================================
#  Grafico 1 — Timeline del contenuto idrico
# =======================================================================

def plot_timeline(sim: dict) -> Path:
    """
    Curva temporale del contenuto idrico con soglie e zone colorate.

    La figura usa bande orizzontali colorate per marcare visivamente le
    tre zone idrologiche (comfort, stress, morte), una curva blu per lo
    stato giornaliero del vaso, e un'annotazione che evidenzia il
    giorno della prima allerta. I colori seguono la semantica del
    semaforo: verde = sicuro, arancio = attenzione, rosso = critico.
    """
    days = np.arange(0, N_DAYS + 1)
    states = np.array(sim["states"])

    fig, ax = plt.subplots(figsize=(11, 6))

    # Bande di zona: coprono l'intera estensione temporale e danno al
    # grafico un "sfondo semantico" contro cui leggere la curva.
    ax.axhspan(
        sim["alert_mm"], sim["fc_mm"],
        alpha=0.18, color=COLOR_COMFORT,
        label="Zona comfort (sopra soglia RAW)",
    )
    ax.axhspan(
        sim["pwp_mm"], sim["alert_mm"],
        alpha=0.20, color=COLOR_STRESS,
        label="Zona stress (sotto RAW, sopra PWP)",
    )
    ax.axhspan(
        0, sim["pwp_mm"],
        alpha=0.20, color=COLOR_DEATH,
        label="Zona non disponibile (sotto PWP)",
    )

    # Linee di soglia e relative etichette. Collocate a destra del
    # grafico fuori dall'area principale per non coprire la curva.
    for value, label, color in [
        (sim["fc_mm"], "FC", "darkgreen"),
        (sim["alert_mm"], "RAW", "darkorange"),
        (sim["pwp_mm"], "PWP", "darkred"),
    ]:
        ax.axhline(value, linestyle="--", color=color,
                   linewidth=1.2, alpha=0.8)
        ax.text(
            N_DAYS + 0.3, value,
            f"{label} ({value:.1f} mm)",
            verticalalignment="center", fontsize=9, color=color,
        )

    # Curva principale: stato giornaliero con marker su ogni punto.
    ax.plot(
        days, states,
        color="tab:blue", linewidth=2.5, marker="o", markersize=7,
        label="Contenuto idrico giornaliero", zorder=5,
    )

    # Annotazione del primo giorno di allerta: è l'evento più importante
    # da segnalare al lettore e giustifica una freccia dedicata.
    first_alert = next(
        (i for i, a in enumerate(sim["alerts"]) if a), None
    )
    if first_alert is not None:
        ax.axvline(
            first_alert, color="darkorange",
            linestyle=":", alpha=0.7, linewidth=1.5,
        )
        ax.annotate(
            f"Prima allerta\n(giorno {first_alert})",
            xy=(first_alert, states[first_alert]),
            xytext=(first_alert + 1.5, states[first_alert] + 12),
            fontsize=9.5,
            arrowprops=dict(arrowstyle="->", color="darkorange"),
        )

    ax.set_xlabel("Giorno della simulazione")
    ax.set_ylabel("Contenuto idrico (mm di colonna d'acqua)")
    ax.set_title(
        f"Evoluzione del contenuto idrico — Vaso {POT_VOLUME_L:.0f} L a "
        f"Milano, 14 giorni dal {START_DATE.isoformat()}, senza pioggia"
    )
    ax.set_xlim(-0.5, N_DAYS + 2.0)
    # Limite superiore appena sopra la capacità di campo: il contenuto
    # idrico non può fisicamente superare FC (il surplus drena via),
    # quindi stendere l'asse fino alla profondità totale del substrato
    # produrrebbe un grafico con tanto spazio vuoto inutile.
    ax.set_ylim(0, sim["fc_mm"] * 1.15)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper right", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "simulation_timeline.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Grafico 2 — Bilancio inizio vs fine (a barre stratificate)
# =======================================================================

def plot_start_vs_end(sim: dict) -> Path:
    """
    Grafico a barre stratificate: confronto inizio/fine decomposto per
    zona idrologica.

    Ogni barra rappresenta il contenuto idrico totale al momento scelto
    (in mm), scomposto in tre strati sovrapposti:
      - grigio: acqua sotto PWP, presente ma biologicamente inaccessibile;
      - arancione: acqua tra PWP e soglia di allerta (riserva stressante);
      - verde: acqua tra soglia di allerta e FC (riserva confortevole).

    Questa decomposizione permette di leggere non solo "quanta" acqua è
    presente, ma "di che qualità" nella terminologia agronomica.
    """
    initial_mm = sim["states"][0]
    final_mm = sim["states"][-1]

    # Funzione locale che, dato lo stato in mm, calcola quanta acqua
    # appartiene a ciascuna delle tre zone. La somma dei tre contributi
    # è sempre uguale allo stato complessivo (verificato sotto).
    def decompose(state_mm: float) -> tuple[float, float, float]:
        unavailable = min(state_mm, sim["pwp_mm"])
        stress = max(0.0, min(state_mm, sim["alert_mm"]) - sim["pwp_mm"])
        comfort = max(0.0, state_mm - sim["alert_mm"])
        return unavailable, stress, comfort

    init_u, init_s, init_c = decompose(initial_mm)
    fin_u, fin_s, fin_c = decompose(final_mm)

    # Sanity check interno: la decomposizione deve riprodurre lo stato
    # totale (utile come assert auto-documentante durante lo sviluppo).
    assert abs((init_u + init_s + init_c) - initial_mm) < 1e-9
    assert abs((fin_u + fin_s + fin_c) - final_mm) < 1e-9

    fig, ax = plt.subplots(figsize=(8.5, 7))
    x = np.arange(2)
    width = 0.55

    # Strato 1: acqua non disponibile. È la base di entrambe le barre.
    ax.bar(
        x, [init_u, fin_u], width,
        color=COLOR_UNAVAILABLE,
        label="Acqua non disponibile (sotto PWP)",
    )
    # Strato 2: riserva stressante. Impilato sopra lo strato 1.
    ax.bar(
        x, [init_s, fin_s], width,
        bottom=[init_u, fin_u],
        color=COLOR_STRESS, alpha=0.85,
        label="Riserva stressante (tra PWP e RAW)",
    )
    # Strato 3: riserva di comfort. In cima.
    ax.bar(
        x, [init_c, fin_c], width,
        bottom=[init_u + init_s, fin_u + fin_s],
        color=COLOR_COMFORT, alpha=0.85,
        label="Riserva di comfort (tra RAW e FC)",
    )

    # Etichette con il totale sopra ciascuna barra: è l'informazione
    # che il lettore cercherà per primo.
    for xi, total in zip(x, [initial_mm, final_mm]):
        ax.text(
            xi, total + 2.5, f"{total:.1f} mm",
            ha="center", fontsize=12, fontweight="bold",
        )

    # Linea di riferimento alla capacità di campo, così da dare una
    # scala visiva assoluta: mostra quanto spazio c'era al massimo.
    ax.axhline(
        sim["fc_mm"], linestyle=":", color="darkgreen",
        alpha=0.6, linewidth=1.2,
    )
    ax.text(
        1.42, sim["fc_mm"] + 1, "Capacità di campo (FC)",
        color="darkgreen", fontsize=9,
    )

    # Etichette dell'asse x con ulteriore contesto (giorno e stato θ).
    labels = [
        f"Inizio\n(giorno 0, θ=θ_FC={SUBSTRATE.theta_fc:.2f})",
        f"Fine\n(giorno {N_DAYS}, θ=θ_PWP={SUBSTRATE.theta_pwp:.2f})",
    ]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Contenuto idrico (mm)")
    ax.set_title("Bilancio del vaso: inizio vs fine simulazione")
    ax.set_ylim(0, sim["fc_mm"] * 1.20)
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(loc="upper right", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "simulation_start_vs_end.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Entry point
# =======================================================================

def main() -> None:
    sim = run_simulation()
    print(
        f"Simulazione completata: stato iniziale "
        f"{sim['states'][0]:.1f} mm, stato finale "
        f"{sim['states'][-1]:.1f} mm."
    )
    print()
    print("Generazione grafici...")
    p1 = plot_timeline(sim)
    print(f"  [1/2] {p1.name}")
    p2 = plot_start_vs_end(sim)
    print(f"  [2/2] {p2.name}")
    print()
    print(f"Salvati in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
