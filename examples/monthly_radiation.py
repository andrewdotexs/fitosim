"""
Esempio d'uso minimo: andamento mensile di R_a per Milano.

Stampa la radiazione solare extra-atmosferica per il 15 di ogni mese
alla latitudine di Milano (45.47° N). Serve come "proof of life" del
primo modulo del motore scientifico e per visualizzare a occhio nudo
il ciclo stagionale dell'irraggiamento.

Esegui dalla radice del progetto con:
    python examples/milan_monthly_radiation.py
"""

from datetime import date

from fitosim.science.radiation import (
    day_of_year,
    extraterrestrial_radiation,
)

MILAN_LATITUDE = 45.47    # gradi decimali, positiva a nord dell'equatore
SARONNO_LATITUDE = 45.63  
PALERMO_LATITUDE = 38.12  
YEAR = 2025               # anno non bisestile, qualunque va bene

MONTH_NAMES_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def main() -> None:
    print(f"Radiazione extra-atmosferica R_a per Milano ({PALERMO_LATITUDE}° N)")
    print(f"Anno: {YEAR}, giorno 15 di ogni mese\n")
    print(f"{'Mese':<12} {'R_a (MJ/m²/giorno)':>20}")
    print("-" * 34)

    for month in range(1, 13):
        d = date(YEAR, month, 15)
        j = day_of_year(d)
        ra = extraterrestrial_radiation(PALERMO_LATITUDE, j)
        print(f"{MONTH_NAMES_IT[month - 1]:<12} {ra:>20.2f}")


if __name__ == "__main__":
    main()
