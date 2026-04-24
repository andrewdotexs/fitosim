"""
Esempio: andamento mensile di ET₀ per Milano con temperature climatiche.

Calcola ET₀ di riferimento (prato ben irrigato) per il 15 di ogni mese,
usando le temperature climatologiche medie della stazione di Milano.
I valori di input sono approssimazioni letterarie dei normali trentennali
1991-2020; in un uso reale i dati verrebbero dall'Ecowitt o da Open-Meteo.

Questa tabella si interpreta agronomicamente così: per ogni mese, quella
colonna "ET₀ settimanale" è l'acqua persa in media in una settimana da
un prato di riferimento. L'acqua da fornire a una pianta specifica si
ottiene moltiplicando per il coefficiente colturale Kc della specie.
Un basilico in pieno vigore ha Kc ≈ 1.15 in estate: circa il 15% in più
del prato di riferimento.

Esegui dalla radice del progetto con:
    python examples/milan_monthly_et0.py
"""

from datetime import date

from fitosim.science.et0 import et0_hargreaves_samani
from fitosim.science.radiation import day_of_year


MILAN_LATITUDE = 45.47  # gradi decimali
YEAR = 2025

# Temperature climatiche mensili approssimate per Milano (°C), per il
# giorno 15 di ogni mese. Fonte indicativa: normali trentennali 1991-2020.
# T_min rappresenta la minima tipica (pre-alba), T_max la massima tipica
# (primo pomeriggio).
MILAN_CLIMATOLOGY = [
    # (mese, T_min, T_max)
    (1,  -1.0,  6.0),
    (2,   1.0,  9.0),
    (3,   4.0, 14.0),
    (4,   8.0, 19.0),
    (5,  12.0, 23.0),
    (6,  16.0, 28.0),
    (7,  19.0, 31.0),
    (8,  18.0, 30.0),
    (9,  14.0, 25.0),
    (10,  9.0, 18.0),
    (11,  4.0, 11.0),
    (12,  0.0,  6.0),
]

MONTH_NAMES_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def main() -> None:
    print(f"Evapotraspirazione di riferimento ET₀ per Milano "
          f"({MILAN_LATITUDE}° N)")
    print(f"Anno: {YEAR}, calcolata il 15 di ogni mese con "
          f"Hargreaves-Samani\n")

    # Intestazione della tabella.
    print(f"{'Mese':<12} {'T_min':>6} {'T_max':>6} "
          f"{'ΔT':>5} {'ET₀ (mm/gg)':>13} {'ET₀ (mm/set.)':>15}")
    print("-" * 60)

    total_year = 0.0

    for month, t_min, t_max in MILAN_CLIMATOLOGY:
        d = date(YEAR, month, 15)
        et0_daily = et0_hargreaves_samani(
            t_min=t_min,
            t_max=t_max,
            latitude_deg=MILAN_LATITUDE,
            j=day_of_year(d),
        )
        et0_weekly = et0_daily * 7.0
        delta_t = t_max - t_min

        print(f"{MONTH_NAMES_IT[month - 1]:<12} "
              f"{t_min:>6.1f} {t_max:>6.1f} {delta_t:>5.1f} "
              f"{et0_daily:>13.2f} {et0_weekly:>15.1f}")

        # Approssimazione annuale: moltiplichiamo il valore giornaliero
        # del 15 di ogni mese per i giorni di quel mese e sommiamo.
        days_in_month = (date(YEAR, month + 1, 1) - d).days + (d.day - 1) \
            if month < 12 else 31
        total_year += et0_daily * days_in_month

    print("-" * 60)
    print(f"{'ET₀ annuale stimata (mm):':<45} {total_year:>14.0f}")
    print(f"{'Equivalente in litri per m² di superficie:':<45} "
          f"{total_year:>14.0f}")


if __name__ == "__main__":
    main()
