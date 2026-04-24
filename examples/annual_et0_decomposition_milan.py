"""
Esempio: decomposizione visiva della curva annuale di ET₀ per Milano.

Produce un grafico a tre pannelli che mostra, giorno per giorno, come
ET₀ emerge come prodotto di due curve distinte:
  - R_a: componente astronomica, perfettamente smooth per costruzione,
    massima al solstizio d'estate (21 giugno);
  - Fattore termico (T_med + 17.8) · √ΔT: componente meteorologica,
    il cui picco è ritardato rispetto al solstizio per l'inerzia termica
    dell'atmosfera;
  - ET₀ = 0.0023 × fattore termico × R_a: il prodotto, il cui picco
    si colloca intermedio.

Il ritardo tra picco astronomico e picco termico si chiama "thermal lag"
ed è un fenomeno climatologico ben noto: è il motivo per cui l'estate
"pesa di più" a luglio-agosto che a giugno, nonostante i giorni siano
già più corti. Fitosim lo cattura correttamente perché la formula di
Hargreaves-Samani mescola radiazione (senza lag) e temperatura (con lag).

Lo script sovrappone inoltre, come validazione incrociata, i 12 valori
mensili di ET₀ calcolati nell'esempio `milan_monthly_et0.py`: devono
cadere esattamente sulla curva giornaliera, confermando che i due
percorsi di calcolo producono lo stesso risultato.

Esegui con:
    python examples/annual_et0_decomposition_milan.py

Salva il grafico in `plots/annual_et0_decomposition_milan.png`.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.science.et0 import mj_per_m2_to_mm_water
from fitosim.science.radiation import extraterrestrial_radiation


# Parametri del sito e I/O
LATITUDE = 45.47  # Milano, gradi decimali
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_PATH = OUTPUT_DIR / "annual_et0_decomposition_milan.png"


# Climatologia mensile di Milano: T_min e T_max tipiche riferite al 15
# di ogni mese. Fonte indicativa: normali trentennali 1991-2020.
MONTHLY_DAYS = np.array(
    [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]
)
MONTHLY_T_MIN = np.array(
    [-1.0, 1.0, 4.0, 8.0, 12.0, 16.0, 19.0, 18.0, 14.0, 9.0, 4.0, 0.0]
)
MONTHLY_T_MAX = np.array(
    [6.0, 9.0, 14.0, 19.0, 23.0, 28.0, 31.0, 30.0, 25.0, 18.0, 11.0, 6.0]
)


def interpolate_monthly_periodic(
    j_values: np.ndarray,
    monthly_days: np.ndarray,
    monthly_values: np.ndarray,
) -> np.ndarray:
    """
    Interpolazione lineare di valori mensili a frequenza giornaliera,
    gestendo correttamente il confine anno (dicembre-gennaio).

    Il trucco è estendere le osservazioni mensili periodicamente in
    avanti e all'indietro di un anno: np.interp in questo modo ha sempre
    due punti che bracketeggiano qualunque giorno dell'anno richiesto.
    """
    extended_days = np.concatenate(
        [monthly_days - 365, monthly_days, monthly_days + 365]
    )
    extended_values = np.concatenate(
        [monthly_values, monthly_values, monthly_values]
    )
    return np.interp(j_values, extended_days, extended_values)


def compute_components(
    j_values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcola R_a (mm/giorno equivalente), fattore termico, ed ET₀ per
    ogni giorno dell'anno, restituendoli come array paralleli.
    """
    # Componente astronomica: una chiamata a R_a per ogni giorno.
    # L'uso di una list-comprehension anziché una vettorializzazione
    # è volutamente esplicito — preferiamo codice leggibile a costo di
    # qualche millisecondo in più su 365 giorni (il collo di bottiglia
    # reale è la generazione della figura, non il calcolo).
    ra_mj = np.array([
        extraterrestrial_radiation(LATITUDE, int(j)) for j in j_values
    ])
    ra_mm = np.array([mj_per_m2_to_mm_water(r) for r in ra_mj])

    # Componente termica: interpolazione dei valori mensili.
    t_min = interpolate_monthly_periodic(j_values, MONTHLY_DAYS, MONTHLY_T_MIN)
    t_max = interpolate_monthly_periodic(j_values, MONTHLY_DAYS, MONTHLY_T_MAX)
    t_mean = (t_min + t_max) / 2.0
    delta_t = t_max - t_min
    thermal_factor = (t_mean + 17.8) * np.sqrt(delta_t)

    # Prodotto finale con il coefficiente empirico 0.0023.
    et0 = 0.0023 * thermal_factor * ra_mm

    return ra_mm, thermal_factor, et0


def compute_monthly_et0_for_scatter() -> tuple[np.ndarray, np.ndarray]:
    """
    Ricalcola i 12 valori mensili di ET₀ esattamente ai giorni centrali
    di ciascun mese, da sovrapporre al grafico giornaliero come scatter
    di validazione.
    """
    et0_monthly = []
    for day, t_min, t_max in zip(MONTHLY_DAYS, MONTHLY_T_MIN, MONTHLY_T_MAX):
        ra_mj = extraterrestrial_radiation(LATITUDE, int(day))
        ra_mm = mj_per_m2_to_mm_water(ra_mj)
        t_mean = (t_min + t_max) / 2.0
        delta_t = t_max - t_min
        thermal = (t_mean + 17.8) * np.sqrt(delta_t)
        et0_monthly.append(0.0023 * thermal * ra_mm)
    return MONTHLY_DAYS, np.array(et0_monthly)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Asse giornaliero e calcolo delle tre curve.
    j_values = np.arange(1, 366)
    ra_mm, thermal_factor, et0 = compute_components(j_values)

    # Punti mensili per scatter di validazione.
    monthly_j, monthly_et0 = compute_monthly_et0_for_scatter()

    # Indici notevoli: picchi delle tre curve.
    solstice_j = 172
    thermal_peak_j = int(j_values[np.argmax(thermal_factor)])
    et0_peak_j = int(j_values[np.argmax(et0)])

    # Figura con tre pannelli verticali che condividono l'asse x.
    fig, axes = plt.subplots(3, 1, figsize=(11, 9.5), sharex=True)

    # Pannello 1: componente astronomica R_a.
    axes[0].plot(j_values, ra_mm, color="tab:blue", lw=2)
    axes[0].axvline(solstice_j, color="gray", ls="--", lw=0.8, alpha=0.7)
    axes[0].set_ylabel("R_a  (mm/giorno)")
    axes[0].set_title(
        "Componente astronomica — R_a in acqua equivalente",
        fontsize=11,
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].annotate(
        f"Solstizio d'estate\nJ = {solstice_j}",
        xy=(solstice_j, ra_mm[solstice_j - 1]),
        xytext=(solstice_j + 22, ra_mm[solstice_j - 1] - 2.0),
        fontsize=9,
        arrowprops=dict(arrowstyle="->", alpha=0.5),
    )

    # Pannello 2: fattore termico.
    axes[1].plot(j_values, thermal_factor, color="tab:orange", lw=2)
    axes[1].axvline(thermal_peak_j, color="gray", ls="--", lw=0.8, alpha=0.7)
    axes[1].set_ylabel(r"$(T_{med} + 17.8)\,\sqrt{\Delta T}$")
    axes[1].set_title(
        "Componente termica — fattore meteo della formula",
        fontsize=11,
    )
    axes[1].grid(True, alpha=0.3)
    axes[1].annotate(
        f"Picco termico\nJ = {thermal_peak_j}",
        xy=(thermal_peak_j, thermal_factor[thermal_peak_j - 1]),
        xytext=(thermal_peak_j + 22, thermal_factor[thermal_peak_j - 1] - 15),
        fontsize=9,
        arrowprops=dict(arrowstyle="->", alpha=0.5),
    )

    # Pannello 3: ET₀ finale + scatter dei 12 mensili.
    axes[2].plot(
        j_values, et0,
        color="tab:green", lw=2.5,
        label="Curva giornaliera",
    )
    axes[2].scatter(
        monthly_j, monthly_et0,
        color="darkgreen", s=45, zorder=5, edgecolor="white", linewidth=1,
        label="12 valori mensili (tabella)",
    )
    axes[2].axvline(et0_peak_j, color="red", ls="--", lw=1.2, alpha=0.7)
    axes[2].set_ylabel("ET₀  (mm/giorno)")
    axes[2].set_title(
        "ET₀ = 0.0023 × termico × R_a  — il prodotto",
        fontsize=11,
    )
    axes[2].grid(True, alpha=0.3)
    axes[2].legend(loc="upper right", framealpha=0.95)
    axes[2].annotate(
        f"Picco ET₀\nJ = {et0_peak_j}",
        xy=(et0_peak_j, et0[et0_peak_j - 1]),
        xytext=(et0_peak_j + 22, et0[et0_peak_j - 1] - 1.2),
        fontsize=9,
        color="darkred",
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="red", alpha=0.6),
    )

    # Asse x con nomi dei mesi italiani, sull'ultimo pannello.
    month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_names = [
        "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
        "Lug", "Ago", "Set", "Ott", "Nov", "Dic",
    ]
    axes[-1].set_xticks(month_starts)
    axes[-1].set_xticklabels(month_names)
    axes[-1].set_xlim(1, 365)
    axes[-1].set_xlabel("Giorno dell'anno")

    fig.suptitle(
        f"Decomposizione di ET₀ per Milano ({LATITUDE}° N) — anno climatologico",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, dpi=120, bbox_inches="tight")

    # Resoconto numerico a terminale.
    print(f"Figura salvata in: {OUTPUT_PATH}\n")
    print("Punti notevoli della decomposizione:")
    print(f"  Solstizio d'estate (picco di R_a):        J = {solstice_j}  (21 giugno)")
    print(f"  Picco del fattore termico:                J = {thermal_peak_j}")
    print(f"  Picco di ET₀:                             J = {et0_peak_j}")
    print(f"  Ritardo termico rispetto al solstizio:    {thermal_peak_j - solstice_j} giorni")
    print(f"  Valore massimo di ET₀:                    {et0.max():.2f} mm/giorno")


if __name__ == "__main__":
    main()
