"""Effetto del pane radicale sulla curva idrica del vaso.

Cosa dimostra questo esempio
----------------------------

A PARITA' di vaso e di pianta (stessa chioma, stesso Kc), confronta due
stati dell'apparato radicale e mostra come divergono le curve di
umidita' del substrato nei 7 giorni dopo un'unica irrigazione a
capacita' di campo:

  - MATURO      root_fraction = 0.90  (radici che occupano quasi tutto)
  - IN SVILUPPO root_fraction = 0.35  (radici ancora poco estese:
                                       talea attecchita, semina, o
                                       pianta appena rinvasata)

Lo fa per tutte e 5 le specie del catalogo e nelle 4 stagioni, cosi'
da mostrare come l'effetto radicale interagisce col "temperamento"
della specie (Kc = quanto consuma, p = quanto tollera l'asciutto).

IMPORTANTE — questo e' un OVERLAY, non una feature di fitosim
--------------------------------------------------------------

Il concetto di `root_fraction` NON e' (ancora) implementato in fitosim:
e' una decisione di design registrata per la fascia 3 in
`docs/fitosim_root_modeling_design.md`. Questo script lo applica come
overlay sopra la fisica REALE della libreria (livello "medio" del
design doc):

  - Kcb_eff = root_fraction * Kcb        traspirazione modulata dalle
                                          radici (il serbatoio idrico
                                          passa attraverso le radici)
  - evaporazione Ke: IDENTICA per i due stati, perche' dipende dalla
    CHIOMA (ombreggiatura della superficie), non dalle radici. Con la
    stessa chioma la superficie e' ombreggiata uguale, quindi evapora
    uguale. Usiamo la Kcb piena della chioma nel limite energetico del
    dual-Kc, NON la Kcb ridotta dalle radici.
  - Ks (stress idrico): funzione di theta, quindi identica per i due a
    parita' di umidita' locale (lo stress dipende dal potenziale
    matriciale, non dalla dimensione del serbatoio).

Le funzioni di fisica sono quelle REALI di fitosim (ET0 Hargreaves,
stress_coefficient_ks, dual-Kc dell'evaporazione): l'overlay tocca
solo la partizione traspirazione/evaporazione.

Esecuzione
----------

    cd fitosim/
    PYTHONPATH=src python examples/root_ball_water_curve.py

Produce due grafici PNG in output/plots/ e una tabella comparativa a
console (giorno del primo bisogno d'acqua per specie/stagione/stato).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fitosim.domain.species import (
    BASIL, TOMATO, LETTUCE, CITRUS, ROSEMARY, Species,
)
from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.dual_kc import (
    evaporation_reduction_coefficient,
    soil_evaporation_coefficient,
    update_de,
)
from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year
from fitosim.science.substrate import Substrate


# =========================================================================
#  Setup fisico (identico per tutti i confronti)
# =========================================================================

LATITUDE_MILANO = 45.47

# Vaso: 5 L, diametro 22 cm -> profondita' del substrato.
POT_VOLUME_L = 5.0
POT_DIAMETER_CM = 22.0
_AREA_CM2 = 3.141592653589793 * (POT_DIAMETER_CM / 2.0) ** 2
DEPTH_MM = (POT_VOLUME_L * 1000.0 / _AREA_CM2) * 10.0

# Substrato universale (valori reali del catalogo) + REW/TEW plausibili
# per abilitare il dual-Kc dell'evaporazione superficiale.
SUBSTRATE = Substrate(
    name="Terriccio universale (demo)",
    theta_fc=0.40,
    theta_pwp=0.15,
    rew_mm=8.0,
    tew_mm=18.0,
)
FC_MM = SUBSTRATE.theta_fc * DEPTH_MM
PWP_MM = SUBSTRATE.theta_pwp * DEPTH_MM
TAW_MM = FC_MM - PWP_MM

KP = 1.0    # vaso neutro (plastica, colore medio, pieno sole)
FEW = 1.0   # frazione di suolo esposto/bagnato (vaso omogeneo)
DAYS = 7

# Quota evaporativa residua sottratta a Kc_mid per stimare Kcb (la
# traspirazione basale). Il residuo ~0.15 e' l'evaporazione a copertura,
# gestita dinamicamente dal dual-Kc. Regola coerente per tutte le specie.
KCB_EVAP_MARGIN = 0.15

ROOT_STATES = {
    "Radici mature (f=0.90)": 0.90,
    "Radici in sviluppo (f=0.35)": 0.35,
}

# Stagioni: giorno rappresentativo di Milano + (tmin, tmax) tipici.
SEASONS = {
    "Inverno": (date(2026, 1, 15), -1.0, 7.0),
    "Primavera": (date(2026, 4, 15), 8.0, 19.0),
    "Estate": (date(2026, 7, 15), 19.0, 31.0),
    "Autunno": (date(2026, 10, 15), 9.0, 18.0),
}

# Le 5 specie del catalogo, ordinate per Kc decrescente (dalla piu'
# assetata alla piu' rustica).
SPECIES_CATALOG = [TOMATO, BASIL, LETTUCE, CITRUS, ROSEMARY]

COLOR_MATURE = "#2A6FB8"
COLOR_DEVELOPING = "#C8324A"


# =========================================================================
#  Il modello overlay
# =========================================================================

def simulate_root_overlay(
    species: Species, root_fraction: float, et0_mm: float,
) -> dict:
    """Simula 7 giorni post-irrigazione per uno stato radicale dato.

    Applica l'overlay `root_fraction` sopra la fisica FAO-56 di fitosim.
    La chioma (e quindi l'evaporazione) e' quella piena della specie;
    root_fraction modula solo la traspirazione basale.

    Ritorna: serie giornaliera di theta, giorno di allerta (deplezione
    p raggiunta) o None, e i totali di traspirazione ed evaporazione.
    """
    kcb_canopy = max(0.05, species.kc_mid - KCB_EVAP_MARGIN)
    kcb_eff = root_fraction * kcb_canopy
    p = species.depletion_fraction

    water_mm = FC_MM          # irrigato a capacita' di campo al giorno 0
    de_mm = 0.0               # superficie appena bagnata
    alert_threshold_mm = FC_MM - p * TAW_MM

    theta_series = [water_mm / DEPTH_MM]
    alert_day = None
    total_transp = 0.0
    total_evap = 0.0

    for day in range(1, DAYS + 1):
        theta = water_mm / DEPTH_MM

        # Stress idrico Ks: funzione di theta (uguale per i due stati
        # radicali a parita' di umidita').
        ks = stress_coefficient_ks(theta, SUBSTRATE, depletion_fraction=p)

        # Traspirazione: modulata da root_fraction via kcb_eff.
        et_transp = ks * kcb_eff * KP * et0_mm

        # Evaporazione superficiale via dual-Kc reale. Il limite
        # energetico usa la Kcb della CHIOMA (root-independent): stessa
        # chioma -> stessa ombreggiatura -> stessa evaporazione.
        kr = evaporation_reduction_coefficient(
            de_mm, SUBSTRATE.rew_mm, SUBSTRATE.tew_mm,
        )
        ke = soil_evaporation_coefficient(kr, kcb=kcb_canopy, few=FEW)
        et_evap = ke * KP * et0_mm

        water_mm = max(PWP_MM, min(FC_MM, water_mm - et_transp - et_evap))
        de_mm = update_de(
            de_mm, et_evap, water_input_mm=0.0, tew_mm=SUBSTRATE.tew_mm,
        )

        if alert_day is None and water_mm <= alert_threshold_mm:
            alert_day = day

        theta_series.append(water_mm / DEPTH_MM)
        total_transp += et_transp
        total_evap += et_evap

    return {
        "theta": theta_series,
        "alert_day": alert_day,
        "total_transp": total_transp,
        "total_evap": total_evap,
        "alert_theta": alert_threshold_mm / DEPTH_MM,
    }


# =========================================================================
#  Tabella comparativa a console
# =========================================================================

def print_comparison_table() -> None:
    """Stampa il giorno del primo bisogno d'acqua per specie/stagione/stato."""
    print("=" * 72)
    print("Giorno del primo bisogno d'acqua (allerta) - '-' = mai in 7 giorni")
    print("=" * 72)
    print(f"Vaso {POT_VOLUME_L} L / {POT_DIAMETER_CM} cm, "
          f"profondita' {DEPTH_MM:.0f} mm, substrato universale.")
    print(f"{'Specie':12s} {'Kc':>5s} {'p':>5s} {'soglia':>7s}  ", end="")
    for s in SEASONS:
        print(f"{s+'(m/s)':>16s}", end="")
    print()
    print("-" * 100)

    for sp in SPECIES_CATALOG:
        soglia = (FC_MM - sp.depletion_fraction * TAW_MM) / DEPTH_MM
        print(f"{sp.common_name:12s} {sp.kc_mid:5.2f} "
              f"{sp.depletion_fraction:5.2f} {soglia:7.3f}  ", end="")
        for season, (d, tmn, tmx) in SEASONS.items():
            et0 = et0_hargreaves_samani(tmn, tmx, LATITUDE_MILANO,
                                        day_of_year(d))
            rm = simulate_root_overlay(sp, 0.90, et0)
            rd = simulate_root_overlay(sp, 0.35, et0)
            am = str(rm["alert_day"]) if rm["alert_day"] else "-"
            ad = str(rd["alert_day"]) if rd["alert_day"] else "-"
            print(f"{am+'/'+ad:>16s}", end="")
        print()
    print()


# =========================================================================
#  Grafici
# =========================================================================

def plot_four_seasons(species: Species, output_path: Path) -> None:
    """Grafico 4 stagioni per una specie, due curve radicali ciascuna."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True)
    axes = axes.flatten()

    for ax, (season, (d, tmn, tmx)) in zip(axes, SEASONS.items()):
        et0 = et0_hargreaves_samani(tmn, tmx, LATITUDE_MILANO, day_of_year(d))
        for label, f in ROOT_STATES.items():
            r = simulate_root_overlay(species, f, et0)
            color = COLOR_MATURE if f > 0.5 else COLOR_DEVELOPING
            style = "-" if f > 0.5 else "--"
            ax.plot(range(DAYS + 1), r["theta"], color=color, ls=style,
                    linewidth=2.2, marker="o", markersize=4, label=label)
            alert_theta = r["alert_theta"]

        ax.axhline(SUBSTRATE.theta_fc, color="#56AC56", ls="--", alpha=0.5, lw=1)
        ax.axhline(SUBSTRATE.theta_pwp, color="#999999", ls="--", alpha=0.5, lw=1)
        ax.axhline(alert_theta, color="#E8A33A", ls=":", alpha=0.8, lw=1.2)

        ax.set_title(f"{season}  —  ET0={et0:.1f} mm/g", fontsize=11, loc="left")
        ax.set_ylabel("θ (frazione volumetrica)")
        ax.set_ylim(0.10, 0.43)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper right", fontsize=8)

    for ax in axes[2:]:
        ax.set_xlabel("Giorni dall'irrigazione")

    fig.suptitle(
        f"Pane radicale e curva idrica — {species.common_name} "
        f"(Kc_mid={species.kc_mid}, p={species.depletion_fraction})\n"
        f"Stesso vaso ({POT_VOLUME_L} L), 7 giorni post-irrigazione — "
        f"overlay root_fraction sopra la fisica FAO-56 di fitosim",
        fontsize=12.5, fontweight="bold",
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(output_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Grafico salvato: {output_path}")


def plot_species_in_summer(output_path: Path) -> None:
    """Grafico che confronta le 5 specie in estate (differenze massime)."""
    d, tmn, tmx = SEASONS["Estate"]
    et0 = et0_hargreaves_samani(tmn, tmx, LATITUDE_MILANO, day_of_year(d))

    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5), sharex=True, sharey=True)
    axes = axes.flatten()

    for ax, sp in zip(axes, SPECIES_CATALOG):
        for label, f in ROOT_STATES.items():
            r = simulate_root_overlay(sp, f, et0)
            color = COLOR_MATURE if f > 0.5 else COLOR_DEVELOPING
            style = "-" if f > 0.5 else "--"
            ax.plot(range(DAYS + 1), r["theta"], color=color, ls=style,
                    linewidth=2.2, marker="o", markersize=4, label=label)
            alert_theta = r["alert_theta"]
        ax.axhline(SUBSTRATE.theta_fc, color="#56AC56", ls="--", alpha=0.5, lw=1)
        ax.axhline(SUBSTRATE.theta_pwp, color="#999999", ls="--", alpha=0.5, lw=1)
        ax.axhline(alert_theta, color="#E8A33A", ls=":", alpha=0.8, lw=1.2)
        ax.set_title(f"{sp.common_name}  (Kc={sp.kc_mid}, p={sp.depletion_fraction})",
                     fontsize=10.5, loc="left")
        ax.set_ylim(0.10, 0.43)
        ax.grid(True, alpha=0.25)

    axes[0].set_ylabel("θ (frazione volumetrica)")
    axes[3].set_ylabel("θ (frazione volumetrica)")
    for ax in axes[3:]:
        ax.set_xlabel("Giorni dall'irrigazione")
    axes[0].legend(loc="upper right", fontsize=8)
    # Il sesto pannello (vuoto) ospita una legenda esplicativa.
    axes[5].axis("off")
    axes[5].text(
        0.05, 0.5,
        "Estate a Milano (ET0=%.1f mm/g).\n\n"
        "Blu continuo: radici mature (f=0.90)\n"
        "Rosso tratteggiato: radici in sviluppo (f=0.35)\n\n"
        "Verde: capacita' di campo (FC)\n"
        "Arancio: soglia di allerta della specie\n"
        "Grigio: punto di appassimento (PWP)" % et0,
        fontsize=10, va="center",
    )

    fig.suptitle(
        "Pane radicale x temperamento della specie — estate, "
        "stesso vaso (5 L), 7 giorni post-irrigazione",
        fontsize=13, fontweight="bold",
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(output_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Grafico salvato: {output_path}")


# =========================================================================
#  Main
# =========================================================================

def main() -> int:
    print_comparison_table()

    output_dir = Path(__file__).parent.parent / "output" / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_four_seasons(BASIL, output_dir / "root_ball_basil_4seasons.png")
    plot_species_in_summer(output_dir / "root_ball_species_summer.png")

    print("\nNota: root_fraction e' un overlay dimostrativo del design "
          "doc di fascia 3\n(docs/fitosim_root_modeling_design.md), non "
          "una feature attuale di fitosim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
