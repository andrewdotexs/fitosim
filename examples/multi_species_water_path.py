"""
Confronto multi-specie: cinque piante nello stesso scenario climatico.

Questo esempio mette le cinque specie del catalogo fitosim a confronto
sullo stesso identico scenario meteorologico (Milano, 14 giorni a metà
luglio, nessuna pioggia), con vasi fisicamente identici (5 L, diametro
20 cm, terriccio universale) tutti partiti dalla capacità di campo.
L'unica cosa che varia è la specie, e quindi il suo profilo di Kc e la
sua frazione di deplezione p.

Scopo pedagogico
----------------
Visualizzare come due parametri biologici — coefficiente colturale e
tolleranza allo stress — producano comportamenti idrici molto diversi
in condizioni ambientali identiche. Il grafico risultante è la
rappresentazione visiva del motivo per cui un algoritmo di irrigazione
intelligente *non può* usare le stesse regole per tutte le piante.

Nota metodologica
-----------------
I valori di Kc nel catalogo sono tratti da FAO-56 e si riferiscono a
colture in pieno campo con dimensioni mature. In un vaso domestico, le
specie "grandi" (pomodoro, limone) hanno un consumo effettivo più
contenuto di quello che suggerisce il loro Kc tabulato, perché la
pianta non raggiunge la stessa superficie fogliare. Il confronto che
segue resta tuttavia qualitativamente rappresentativo delle *relazioni*
tra le specie, che è ciò che vogliamo evidenziare. Una calibrazione
accurata per-vaso sarà oggetto di una versione futura di fitosim,
quando l'integrazione con i sensori WH51 fornirà feedback empirici.

Esegui dalla radice del progetto con:
    python examples/multi_species_comparison.py
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
from fitosim.science.balance import water_balance_step_mm
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
#  Parametri dello scenario (identici agli esempi precedenti per
#  consentire confronti trasversali).
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

# Palette scelta per massimizzare la distinguibilità delle cinque curve
# su stampa in bianco e nero e per lettori con diverse forme di
# daltonismo. L'ordine corrisponde all'ordine di ALL_SPECIES.
SPECIES_COLORS = {
    "Basilico": "tab:green",
    "Pomodoro": "tab:red",
    "Lattuga": "tab:olive",
    "Limone in vaso": "tab:orange",
    "Rosmarino": "tab:purple",
}

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# =======================================================================
#  Esecuzione della simulazione per una singola specie
# =======================================================================

def simulate_species(species) -> dict:
    """
    Esegue la simulazione di N_DAYS per una specie, restituendo la
    traiettoria completa dello stato idrico più i metadati necessari
    al grafico (soglia di allerta specifica della specie, giorno della
    prima allerta).

    La geometria del vaso è comune a tutte le specie, ma la soglia di
    allerta no: dipende dalla frazione di deplezione della specie. È
    proprio questa differenza che rende il confronto interessante.
    """
    surface_area = circular_pot_surface_area_m2(POT_DIAMETER_CM)
    depth_mm = pot_substrate_depth_mm(POT_VOLUME_L, surface_area)
    fc_mm = SUBSTRATE.theta_fc * depth_mm

    # La soglia di allerta è specifica per specie, perché dipende da p.
    raw_fraction = readily_available_water(
        SUBSTRATE, species.depletion_fraction
    )
    alert_mm = (SUBSTRATE.theta_fc - raw_fraction) * depth_mm

    state_mm = fc_mm
    states = [state_mm]
    first_alert_day = None  # registriamo il giorno della prima allerta

    for day_index in range(N_DAYS):
        current_date = START_DATE + timedelta(days=day_index)
        j = day_of_year(current_date)
        t_min, t_max = DAILY_TEMPERATURES[day_index]
        et0_mm = et0_hargreaves_samani(t_min, t_max, LATITUDE_DEG, j)

        # ET reale con Ks specifico di questa specie.
        theta_now = mm_to_theta(state_mm, depth_mm)
        et_c_mm = actual_et_c(
            species=species, stage=STAGE, et_0=et0_mm,
            current_theta=theta_now, substrate=SUBSTRATE,
        )

        result = water_balance_step_mm(
            current_mm=state_mm, water_input_mm=0.0,
            et_c_mm=et_c_mm, substrate=SUBSTRATE,
            substrate_depth_mm=depth_mm,
            depletion_fraction=species.depletion_fraction,
        )
        state_mm = result.new_state
        states.append(state_mm)

        # Prima volta che scatta l'allerta: salviamo il giorno.
        # Nota: "giorno" qui significa il giorno *dopo* l'aggiornamento,
        # cioè day_index + 1 in unità del grafico.
        if result.under_alert and first_alert_day is None:
            first_alert_day = day_index + 1

    return {
        "species": species,
        "states": np.array(states),
        "alert_mm": alert_mm,
        "fc_mm": fc_mm,
        "first_alert_day": first_alert_day,
    }


# =======================================================================
#  Grafico multi-specie
# =======================================================================

def plot_multi_species(results: list[dict]) -> Path:
    """
    Cinque curve sovrapposte, una per specie, con le rispettive soglie
    di allerta come linee orizzontali tratteggiate. Un marcatore
    particolare evidenzia il giorno in cui ciascuna specie attraversa
    per la prima volta la propria soglia di allerta: è il "momento
    operativo" che la notifica di fitosim comunicherebbe al giardiniere.
    """
    days = np.arange(0, N_DAYS + 1)

    fig, ax = plt.subplots(figsize=(12, 7))

    # Le capacità di campo coincidono per tutte (stesso substrato +
    # stesso vaso), quindi disegniamo una sola linea FC di riferimento.
    fc_common = results[0]["fc_mm"]
    ax.axhline(fc_common, linestyle=":", color="darkgreen",
               linewidth=1.0, alpha=0.5)
    ax.text(N_DAYS + 0.2, fc_common, "Capacità di campo (FC)",
            fontsize=9, color="darkgreen", verticalalignment="center")

    # PWP è anch'esso comune (dipende solo dal substrato).
    pwp = SUBSTRATE.theta_pwp * (
        results[0]["fc_mm"] / SUBSTRATE.theta_fc
    )
    ax.axhline(pwp, linestyle=":", color="darkred",
               linewidth=1.0, alpha=0.5)
    ax.text(N_DAYS + 0.2, pwp, "Appassimento (PWP)",
            fontsize=9, color="darkred", verticalalignment="center")

    # Per ogni specie: curva di stato + soglia di allerta colorata +
    # marcatore del primo giorno di allerta.
    for result in results:
        species = result["species"]
        color = SPECIES_COLORS[species.common_name]

        # Curva principale dello stato idrico.
        ax.plot(
            days, result["states"],
            color=color, linewidth=2.2, marker="o", markersize=5,
            label=(
                f"{species.common_name} "
                f"(Kc={species.kc_mid}, p={species.depletion_fraction})"
            ),
        )

        # Soglia di allerta, tratteggiata nello stesso colore della specie
        # ma con alpha più basso per non dominare il grafico.
        ax.axhline(
            result["alert_mm"], linestyle="--", color=color,
            linewidth=1.0, alpha=0.4,
        )

        # Marcatore del primo giorno di allerta: un triangolino che punta
        # verso il basso, nel colore della specie.
        if result["first_alert_day"] is not None:
            day = result["first_alert_day"]
            state_at_alert = result["states"][day]
            ax.plot(
                day, state_at_alert, marker="v",
                markersize=14, color=color, markeredgecolor="black",
                markeredgewidth=1.2, zorder=10,
            )

    ax.set_xlabel("Giorno della simulazione")
    ax.set_ylabel("Contenuto idrico (mm di colonna d'acqua)")
    ax.set_title(
        f"Confronto multi-specie — stesso vaso {POT_VOLUME_L:.0f} L "
        f"a Milano, {N_DAYS} giorni dal {START_DATE.isoformat()}, "
        f"senza pioggia\n"
        f"Il triangolo ▼ marca il giorno della prima allerta di "
        f"irrigazione per ciascuna specie"
    )
    ax.set_xlim(-0.5, N_DAYS + 3.5)
    ax.set_ylim(pwp - 3, fc_common * 1.08)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower left", framealpha=0.92, fontsize=9)

    path = OUTPUT_DIR / "multi_species_comparison.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


# =======================================================================
#  Tabella riassuntiva testuale
# =======================================================================

def print_summary_table(results: list[dict]) -> None:
    """
    Stampa una tabella compatta che riassume per ogni specie:
      - Kc_mid e p (i due parametri biologici chiave)
      - soglia di allerta in mm
      - giorno della prima allerta
      - stato finale dopo 14 giorni
      - consumo idrico totale nei 14 giorni
    """
    print()
    header = (
        f"{'Specie':<18} {'Kc':>5} {'p':>5} "
        f"{'Allerta':>8} {'1°all.':>7} "
        f"{'Finale':>7} {'Tot.consumo':>12}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        s = r["species"]
        first_alert = (
            f"g{r['first_alert_day']}" if r["first_alert_day"] is not None
            else "—"
        )
        consumed = r["states"][0] - r["states"][-1]
        print(
            f"{s.common_name:<18} {s.kc_mid:>5.2f} "
            f"{s.depletion_fraction:>5.2f} "
            f"{r['alert_mm']:>7.1f}mm {first_alert:>7} "
            f"{r['states'][-1]:>6.1f}mm {consumed:>11.1f}mm"
        )


# =======================================================================
#  Entry point
# =======================================================================

def main() -> None:
    print(f"Scenario: Milano, {N_DAYS} giorni dal {START_DATE.isoformat()}, "
          f"vaso {POT_VOLUME_L} L, terriccio universale, no pioggia")
    print(f"Tutte le specie allo stadio {STAGE.value}, partono a FC.")

    results = [simulate_species(s) for s in ALL_SPECIES]

    print_summary_table(results)

    print("\nGenerazione grafico...")
    path = plot_multi_species(results)
    print(f"  {path.name}")
    print(f"\nSalvato in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
