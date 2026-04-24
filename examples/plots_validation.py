"""
Grafici di validazione visiva per fitosim.science.

Questo script genera tre figure complementari al resoconto tabellare:

    1. ra_multilatitude.png
       Curve annuali di R_a a quattro latitudini caratteristiche
       (equatore, tropico del Cancro, Milano, circolo polare artico).
       Mostra i regimi fondamentali della radiazione astronomica.

    2. ra_et0_milan.png
       Curve annuali di R_a ed ET₀ per Milano sullo stesso grafico
       (doppio asse y). Visualizza come la modulazione meteo trasforma
       l'input astronomico nella domanda evapotraspirativa agronomica.

    3. ra_heatmap.png
       Heatmap globale di R_a su (latitudine, giorno dell'anno). Una
       singola immagine che contiene simultaneamente tutte le latitudini
       e tutti i giorni, rivelando la struttura complessiva della
       radiazione solare sulla Terra.

Le figure sono salvate in fitosim/output/plots/. Sono "validazione
visiva" nel senso che confermano con la forma geometrica delle curve che
l'implementazione riproduce correttamente la fisica attesa:
stagionalità, simmetrie emisferiche, bande polari, eccentricità orbitale.

Esegui dalla radice del progetto con:
    python examples/plots_validation.py
"""

from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year, extraterrestrial_radiation


# Directory di output per i grafici generati. Viene creata se non esiste.
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def plot_ra_multilatitude() -> Path:
    """
    Figura 1: curve annuali di R_a a quattro latitudini caratteristiche.

    Le quattro latitudini scelte non sono casuali: rappresentano soglie
    climatologiche riconosciute. L'equatore ha R_a quasi costante con
    due piccoli massimi agli equinozi (il Sole passa allo zenit due
    volte l'anno). Il tropico mostra un unico massimo estivo e un
    minimo invernale attenuato. La latitudine temperata come Milano ha
    una marcata sinusoide annuale. Il circolo polare artico mostra il
    valore zero per alcune settimane attorno al solstizio d'inverno
    (notte polare) e un picco estivo molto alto (giorno di 24 ore).
    """
    days = np.arange(1, 366)
    sites = [
        (0.0, "Equatore (0°)"),
        (23.5, "Tropico del Cancro (23.5° N)"),
        (45.47, "Milano (45.47° N)"),
        (66.5, "Circolo polare artico (66.5° N)"),
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    for lat, label in sites:
        # Chiamiamo la nostra funzione scalare in un loop: 365 chiamate
        # sono sufficientemente veloci (< 10 ms totali) da non motivare
        # una vettorializzazione esplicita.
        ra = [extraterrestrial_radiation(lat, j) for j in days]
        ax.plot(days, ra, label=label, linewidth=2)

    ax.set_xlabel("Giorno dell'anno")
    ax.set_ylabel("R_a (MJ m$^{-2}$ giorno$^{-1}$)")
    ax.set_title(
        "Radiazione solare extra-atmosferica "
        "al variare della latitudine"
    )

    # Linee verticali tratteggiate in corrispondenza di equinozi e
    # solstizi, utili per ancorare visivamente la posizione delle
    # curve nella geometria astronomica.
    reference_days = [
        (80, "Equin. primav."),
        (172, "Solst. estivo"),
        (266, "Equin. autun."),
        (355, "Solst. invern."),
    ]
    for j, name in reference_days:
        ax.axvline(j, color='gray', linestyle=':', alpha=0.4)
        ax.text(j + 2, 1.5, name, rotation=90, fontsize=8,
                color='gray', alpha=0.8, verticalalignment='bottom')

    ax.legend(loc='lower center', frameon=True, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(1, 365)
    ax.set_ylim(0, 48)

    path = OUTPUT_DIR / "ra_multilatitude.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_ra_et0_milan() -> Path:
    """
    Figura 2: R_a ed ET₀ per Milano sullo stesso asse temporale.

    Il grafico usa due assi y sovrapposti per rappresentare le due
    grandezze con le loro unità native (MJ/m²/giorno a sinistra per
    R_a, mm/giorno a destra per ET₀). Le due curve hanno picchi
    leggermente sfalsati: R_a raggiunge il suo massimo esattamente al
    solstizio d'estate (J=172, quando la geometria orbitale massimizza
    la radiazione in arrivo), mentre ET₀ ha il picco un paio di
    settimane dopo, trascinata dalle temperature massime che seguono
    il picco radiativo con inerzia termica.
    """
    days = np.arange(1, 366)
    lat = 45.47

    # Climatologia mensile usata come input termico. Interpoliamo i
    # dodici valori mensili (al giorno 15 di ogni mese) sull'intero
    # anno con np.interp, che gestisce la periodicità con il parametro
    # `period=365` — evita artefatti artificiali ai bordi dell'anno.
    month_days = np.array(
        [date(2025, m, 15).timetuple().tm_yday for m in range(1, 13)]
    )
    t_min_months = np.array([-1, 1, 4, 8, 12, 16, 19, 18, 14, 9, 4, 0])
    t_max_months = np.array([6, 9, 14, 19, 23, 28, 31, 30, 25, 18, 11, 6])

    t_min_daily = np.interp(days, month_days, t_min_months, period=365)
    t_max_daily = np.interp(days, month_days, t_max_months, period=365)

    ra = np.array(
        [extraterrestrial_radiation(lat, int(j)) for j in days]
    )
    et0 = np.array([
        et0_hargreaves_samani(
            t_min=float(t_min_daily[i]),
            t_max=float(t_max_daily[i]),
            latitude_deg=lat,
            j=int(days[i]),
        )
        for i in range(len(days))
    ])

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()

    line_ra, = ax1.plot(
        days, ra, color='tab:orange', linewidth=2,
        label="R$_a$ — radiazione astronomica",
    )
    line_et0, = ax2.plot(
        days, et0, color='tab:blue', linewidth=2,
        label="ET$_0$ — domanda evapotraspirativa",
    )

    ax1.set_xlabel("Giorno dell'anno")
    ax1.set_ylabel("R$_a$ (MJ m$^{-2}$ giorno$^{-1}$)", color='tab:orange')
    ax2.set_ylabel("ET$_0$ (mm giorno$^{-1}$)", color='tab:blue')
    ax1.tick_params(axis='y', labelcolor='tab:orange')
    ax2.tick_params(axis='y', labelcolor='tab:blue')

    ax1.set_title(
        "Milano: dall'input astronomico (R$_a$) "
        "alla domanda evapotraspirativa (ET$_0$)"
    )
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(1, 365)
    ax1.set_ylim(bottom=0)
    ax2.set_ylim(bottom=0)

    ax1.legend(handles=[line_ra, line_et0], loc='upper left', frameon=True)

    path = OUTPUT_DIR / "ra_et0_milan.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_ra_heatmap() -> Path:
    """
    Figura 3: heatmap globale di R_a su (latitudine, giorno dell'anno).

    È la visione "olimpica": ogni punto dell'immagine rappresenta una
    coppia (latitudine, giorno), e il colore codifica il valore di R_a.
    In una sola figura si vedono simultaneamente:
      - la simmetria emisferica sfalsata di sei mesi;
      - le bande polari di "notte eterna" (zero radiazione) in inverno;
      - il "sole di mezzanotte" al polo d'estate (picco molto alto);
      - la leggera asimmetria dovuta all'eccentricità orbitale (estate
        boreale meno intensa di estate australe, perché a gennaio la
        Terra è più vicina al Sole che a luglio).
    """
    # Griglia: passo di 2 gradi in latitudine e 2 giorni in tempo.
    # 81 × 183 = circa 15 000 punti, computazione in pochi secondi.
    latitudes = np.arange(-80, 81, 2)
    days = np.arange(1, 366, 2)

    R = np.zeros((len(latitudes), len(days)))
    for i, lat in enumerate(latitudes):
        for jidx, j in enumerate(days):
            R[i, jidx] = extraterrestrial_radiation(float(lat), int(j))

    fig, ax = plt.subplots(figsize=(11, 6))
    im = ax.imshow(
        R,
        extent=[1, 365, -80, 80],
        aspect='auto',
        origin='lower',
        cmap='inferno',
        interpolation='bilinear',
    )
    cbar = fig.colorbar(
        im, ax=ax, label="R$_a$ (MJ m$^{-2}$ giorno$^{-1}$)",
    )

    ax.set_xlabel("Giorno dell'anno")
    ax.set_ylabel("Latitudine (°)")
    ax.set_title("Radiazione solare extra-atmosferica globale R$_a$(φ, J)")

    # Linee di riferimento: equatore, tropici, circoli polari.
    for lat in [-66.5, -23.5, 0, 23.5, 66.5]:
        ax.axhline(lat, color='white', linestyle='--',
                   alpha=0.3, linewidth=0.7)
    # Linee verticali: equinozi e solstizi.
    for j in [80, 172, 266, 355]:
        ax.axvline(j, color='white', linestyle=':',
                   alpha=0.4, linewidth=0.7)

    # Etichette per le latitudini notevoli, fuori dall'area del grafico.
    labels = [
        (66.5, "Pol. artico"),
        (23.5, "Trop. Cancro"),
        (0, "Equatore"),
        (-23.5, "Trop. Capric."),
        (-66.5, "Pol. antartico"),
    ]
    for lat, name in labels:
        ax.text(370, lat, name, fontsize=8, color='dimgray',
                verticalalignment='center')

    path = OUTPUT_DIR / "ra_heatmap.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    print("Generazione grafici di validazione visiva...")
    p1 = plot_ra_multilatitude()
    print(f"  [1/3] {p1.name}")
    p2 = plot_ra_et0_milan()
    print(f"  [2/3] {p2.name}")
    p3 = plot_ra_heatmap()
    print(f"  [3/3] {p3.name}")
    print(f"\nTutti salvati in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
