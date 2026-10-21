"""
Hargreaves-Samani contro Penman-Monteith a quattro passi temporali
(24 h, 6 h, 4 h, 1 h) su settimane vere, d'estate e d'inverno, e che
cosa cambia nel bilancio idrico di un vaso — a giorni, e poi a blocchi
(A7). Con le tabelle, e quattro grafici se matplotlib c'è.

La domanda a cui risponde: quanto conta la risoluzione temporale dei
dati meteo nel calcolo di ET₀, e quanto di quella differenza arriva
fino al vaso — cioè fino al giorno, e all'ora, in cui il modello dice
"innaffia"? E la risposta cambia con la stagione?

Le settimane
------------
Balcone a Milano (45.47 N, 9.19 E, 160 m), dati orari ERA5 scaricati da
Open-Meteo (archive-api, timezone UTC, poi riportati in ora solare
CET = UTC+1, che è l'"ora standard" richiesta dalle formule orarie di
FAO-56; d'estate l'orologio segna un'ora in più). I dati sono
incorporati nel file, così l'esempio gira senza rete ed è
riproducibile: per ogni ora [h, h+1) la temperatura, l'umidità
relativa e il vento a 10 m sono la media dei due istantanei agli
estremi, la radiazione è la media dell'ora.

  estate     13–19 luglio 2026: la canicola, massime 32–36 °C, 22–26
             MJ/m² al giorno, un temporale il pomeriggio del 15.
  inverno    12–18 gennaio 2026: un giorno sereno e gelido, poi la
             nebbia padana, umidità 90–100 %, 1–3 MJ/m² al giorno.
  settembre  14–20 settembre 2026: la settimana con cui è nato
             l'esempio. Non gira di default; si chiede per nome.

Il vaso è lo stesso nelle due stagioni: un rosmarino (fixture
`ROSEMARY`, perenne: Kc mid 0.75 d'estate, Kc iniziale 0.40 nel riposo
invernale, p 0.60, resistenza stomatica 200 s/m) in un mix drenante
con perlite abbondante (fixture `PERLITE_RICH`, θ_FC 0.30, θ_PWP 0.10);
vaso di plastica da 5 L, diametro 20 cm, colore medio, pieno sole —
cioè Kp = 1, perché la differenza fra i metodi deve stare tutta
nell'ET₀. Sta sotto il balcone di sopra (niente pioggia) e parte a
capacità di campo, innaffiato la sera prima. Nessuna irrigazione
durante la settimana, salvo il litro dell'esperimento sull'ora.

I sei metodi a confronto
------------------------
  HS          Hargreaves-Samani (FAO-56 eq. 52): T_max, T_min e R_a.
  PM 24h FAO  Penman-Monteith giornaliera come la scrive FAO-56 (eq. 6):
              T_mean = media degli estremi (eq. 9), e_s dalla media di
              e°(T_max) ed e°(T_min) (eq. 12), e_a da RH_max/RH_min
              (eq. 17), R_nl con gli estremi (eq. 39), G = 0 (eq. 42).
  PM 24h fito Penman-Monteith giornaliera come la calcola fitosim nel
              cammino giornaliero (`compute_et0_penman_monteith` +
              `net_radiation`, la catena di `Pot.apply_balance_step_from_weather`).
              Dal 21-10-2026 (A9) e_s ed e_a vengono dagli estremi del
              giorno come nella FAO (eq. 12 e 17): resta il coefficiente
              aerodinamico, ρ_a·c_p/r_a esplicito contro 900/(T+273).
  PM 6h/4h/1h Penman-Monteith a blocchi, con le funzioni della libreria
              (`domain.blocks.et0_for_blocks`): la eq. 53 di FAO-56 a
              passo generico (`compute_et0_penman_monteith(..., hours)`),
              R_a del blocco (eq. 28–33), R_n del blocco (cap. 4), G di
              giorno e di notte (eq. 45–46), il rapporto notturno
              R_s/R_so dalle 2–3 ore prima del tramonto, i blocchi
              negativi azzerati. L'ET₀ del giorno è la somma dei blocchi.
              Le decisioni, con le ragioni, sono in `domain/blocks.py`.

Le due parti, per ogni stagione
-------------------------------
La prima parte confronta le ET₀ e fa girare il vaso *a giorni* con
ciascuna: la risoluzione entra solo nell'ET₀. La seconda fa girare il
vaso *a blocchi* (`Pot.apply_blocks_from_weather`, un'ora alla volta)
e mostra le due cose che il passo giornaliero non può dire: l'ora
dell'allerta, e quanto drena un litro dato alle 8 o alle 20. In fondo,
le due stagioni fianco a fianco.

I grafici
---------
Se matplotlib è installato (`pip install -e '.[dev]'`, il core di
fitosim resta stdlib) l'esempio salva quattro PNG nella cartella
`FITOSIM_DEMO_OUTPUT_DIR` — o in `examples/`, dove git li ignora —,
ciascuno con un pannello per stagione:

  confronto_et0_metodi.png            l'ET₀ del giorno con i sei metodi
  confronto_et0_dentro_il_giorno.png  il profilo orario del giorno in
                                      cui 24 h e somma delle ore
                                      divergono di più, coi blocchi
  confronto_et0_vaso_a_giorni.png     l'acqua nel vaso con le sei ET₀
  confronto_et0_vaso_a_blocchi.png    la settimana un'ora alla volta,
                                      l'ora dell'allerta, il litro alle
                                      8 o alle 20

Per eseguirlo:
    uv run python examples/confronto_et0_risoluzione_temporale.py
    uv run python examples/confronto_et0_risoluzione_temporale.py estate inverno settembre
oppure
    PYTHONPATH=src python examples/confronto_et0_risoluzione_temporale.py
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from fitosim.domain.blocks import BlockFertigation, et0_for_blocks
from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import ROSEMARY
from fitosim.domain.weather import WeatherBlock, weather_day_from_blocks
from fitosim.science.et0 import (
    atmospheric_pressure,
    compute_et0_penman_monteith,
    daily_vapor_pressures,
    et0_hargreaves_samani,
    psychrometric_constant,
    saturation_vapor_pressure,
    slope_vapor_pressure,
)
from fitosim.science.radiation import (
    clear_sky_radiation,
    day_of_year,
    extraterrestrial_radiation,
    extraterrestrial_radiation_interval,
    net_radiation,
    sunrise_sunset_hours,
)
from fitosim.science.substrate import PERLITE_RICH

# ---------------------------------------------------------------------
#  Il sito
# ---------------------------------------------------------------------

LATITUDINE = 45.47          # gradi, positiva a nord
LONGITUDINE_EST = 9.19      # gradi, positiva a est
FUSO_ORARIO = 1.0           # CET = UTC+1, ora solare (niente ora legale)
QUOTA_M = 160.0             # balcone: la città più qualche piano
# Vento da 10 m a 2 m, FAO-56 eq. 47.
FATTORE_U10_U2 = 4.87 / math.log(67.8 * 10.0 - 5.42)

# ---------------------------------------------------------------------
#  Le settimane: per ogni ora [h, h+1) in ora solare (CET),
#  (T °C, RH %, vento a 10 m in m/s, radiazione globale media in W/m²).
#  ERA5 via Open-Meteo:
#    https://archive-api.open-meteo.com/v1/archive?latitude=45.47
#      &longitude=9.19&start_date=<giorno prima>&end_date=<ultimo giorno>
#      &hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,
#      shortwave_radiation&timezone=UTC&wind_speed_unit=ms
# ---------------------------------------------------------------------

ESTATE: dict[str, list[tuple[float, float, float, float]]] = {
    "2026-07-13": [
        (27.9, 56, 3.46, 0), (26.8, 66, 3.58, 0), (25.9, 72, 3.04, 0),
        (25.3, 73, 2.62, 0), (24.9, 72, 2.51, 0), (24.7, 70, 2.58, 51),
        (25.1, 68, 2.68, 182), (26.0, 65, 2.73, 343), (27.1, 60, 2.41, 489),
        (28.5, 53, 1.73, 655), (29.9, 46, 1.35, 773), (31.2, 42, 1.38, 830),
        (32.4, 40, 1.53, 792), (33.1, 40, 1.43, 709), (33.6, 38, 0.99, 642),
        (34.1, 36, 1.06, 561), (34.2, 36, 1.09, 409), (33.7, 38, 1.33, 191),
        (33.0, 40, 1.74, 57), (32.4, 42, 1.68, 25), (31.8, 45, 1.25, 0),
        (31.1, 48, 0.96, 0), (30.5, 49, 1.15, 0), (29.8, 51, 0.89, 0),
    ],
    "2026-07-14": [
        (28.5, 52, 0.90, 0), (27.8, 52, 1.29, 0), (27.5, 53, 1.03, 0),
        (26.8, 58, 0.79, 0), (26.4, 63, 1.87, 0), (26.4, 64, 2.17, 50),
        (26.8, 64, 1.29, 152), (27.7, 60, 0.86, 349), (29.4, 54, 0.82, 502),
        (30.9, 48, 0.91, 647), (32.2, 44, 1.22, 760), (33.3, 39, 1.62, 802),
        (34.4, 35, 1.89, 761), (35.3, 32, 2.09, 786), (35.6, 30, 2.04, 689),
        (35.8, 30, 2.17, 597), (35.5, 30, 2.42, 419), (35.1, 31, 2.46, 315),
        (35.1, 31, 2.21, 169), (34.8, 32, 1.96, 46), (33.4, 35, 1.57, 0),
        (32.2, 38, 1.35, 0), (31.3, 43, 0.97, 0), (30.2, 48, 1.80, 0),
    ],
    "2026-07-15": [
        (29.2, 52, 2.93, 0), (28.1, 58, 2.50, 0), (27.1, 62, 1.98, 0),
        (26.6, 64, 1.44, 0), (26.1, 64, 0.93, 0), (26.2, 64, 0.45, 46),
        (26.7, 61, 0.62, 173), (27.7, 58, 0.81, 343), (29.2, 53, 0.72, 510),
        (30.6, 49, 0.85, 650), (31.9, 46, 1.17, 756), (33.0, 42, 1.39, 816),
        (33.5, 42, 1.15, 769), (32.3, 45, 2.21, 805), (28.0, 64, 3.29, 279),
        (25.7, 75, 2.94, 309), (26.2, 75, 2.87, 328), (26.1, 78, 2.51, 229),
        (26.3, 74, 2.06, 116), (26.0, 73, 1.92, 14), (25.4, 75, 1.92, 0),
        (24.7, 78, 1.88, 0), (24.2, 80, 1.61, 0), (24.1, 82, 1.33, 0),
    ],
    "2026-07-16": [
        (24.4, 80, 1.29, 0), (24.4, 80, 1.42, 0), (23.8, 84, 1.38, 0),
        (23.1, 87, 1.48, 0), (22.5, 88, 1.60, 0), (22.4, 86, 1.67, 48),
        (22.9, 82, 0.95, 181), (24.4, 74, 0.76, 348), (26.4, 64, 1.24, 518),
        (28.1, 56, 1.18, 669), (29.5, 52, 1.00, 786), (30.8, 49, 1.07, 846),
        (31.8, 48, 1.47, 850), (32.5, 46, 1.27, 805), (33.1, 44, 0.82, 717),
        (33.5, 44, 1.25, 579), (33.3, 44, 1.75, 475), (33.0, 44, 1.57, 319),
        (32.1, 46, 2.00, 160), (31.2, 50, 2.10, 40), (30.9, 51, 1.42, 0),
        (30.4, 53, 1.70, 0), (29.8, 54, 2.03, 0), (29.2, 54, 2.00, 0),
    ],
    "2026-07-17": [
        (26.3, 65, 3.66, 0), (22.5, 84, 4.36, 0), (21.4, 91, 3.83, 0),
        (21.4, 88, 3.59, 0), (21.1, 90, 3.50, 0), (21.2, 90, 3.79, 31),
        (21.6, 90, 2.23, 170), (22.6, 87, 0.52, 336), (24.3, 78, 0.34, 494),
        (25.8, 72, 0.85, 635), (27.0, 67, 1.39, 777), (28.5, 61, 1.02, 835),
        (29.8, 54, 1.11, 718), (30.5, 50, 1.83, 818), (31.1, 49, 1.65, 753),
        (31.4, 49, 1.24, 642), (31.6, 48, 0.92, 508), (31.5, 47, 0.77, 336),
        (31.2, 46, 1.21, 174), (30.6, 49, 1.08, 44), (29.8, 54, 0.78, 0),
        (29.0, 59, 1.05, 0), (28.1, 67, 1.35, 0), (27.4, 70, 1.97, 0),
    ],
    "2026-07-18": [
        (26.6, 73, 2.30, 0), (25.9, 78, 2.38, 0), (25.4, 80, 2.38, 0),
        (25.0, 82, 2.10, 0), (24.6, 86, 1.79, 0), (24.6, 86, 1.64, 43),
        (25.6, 82, 1.73, 162), (27.1, 76, 1.36, 336), (28.5, 70, 0.99, 502),
        (28.3, 70, 1.25, 571), (28.1, 72, 1.68, 595), (29.1, 68, 1.36, 620),
        (31.8, 48, 1.89, 757), (33.8, 30, 2.00, 741), (34.5, 27, 0.68, 731),
        (35.2, 23, 0.68, 624), (35.3, 21, 1.05, 473), (35.0, 20, 1.03, 241),
        (33.2, 34, 1.40, 176), (31.6, 46, 1.26, 42), (29.6, 47, 2.72, 0),
        (25.0, 63, 3.69, 0), (23.1, 80, 2.05, 0), (23.2, 76, 1.62, 0),
    ],
    "2026-07-19": [
        (21.9, 78, 1.69, 0), (21.2, 88, 1.95, 0), (21.6, 89, 1.75, 0),
        (22.3, 84, 2.21, 0), (22.4, 81, 3.36, 0), (22.4, 79, 3.00, 37),
        (23.1, 74, 3.15, 148), (24.3, 68, 3.30, 321), (25.6, 62, 2.31, 494),
        (26.8, 57, 1.64, 654), (28.0, 54, 1.06, 750), (29.2, 50, 0.69, 816),
        (30.1, 50, 0.77, 844), (30.9, 50, 1.04, 744), (31.6, 44, 1.30, 746),
        (32.1, 39, 1.50, 602), (31.9, 40, 1.85, 468), (31.2, 44, 2.33, 319),
        (30.5, 44, 2.87, 164), (29.8, 42, 2.28, 39), (29.0, 46, 1.02, 0),
        (28.4, 52, 0.78, 0), (27.7, 55, 1.02, 0), (27.1, 55, 0.98, 0),
    ],
}

INVERNO: dict[str, list[tuple[float, float, float, float]]] = {
    "2026-01-12": [
        (0.5, 70, 0.63, 0), (0.6, 68, 0.80, 0), (0.6, 68, 1.81, 0),
        (0.2, 68, 1.25, 0), (-0.4, 70, 0.39, 0), (-0.6, 72, 0.34, 0),
        (-0.7, 76, 0.24, 0), (-1.0, 80, 0.33, 0), (-0.8, 79, 0.89, 29),
        (0.5, 72, 1.27, 148), (2.5, 64, 0.84, 251), (4.2, 58, 0.53, 331),
        (5.1, 56, 0.38, 346), (5.7, 56, 0.45, 235), (6.0, 58, 0.79, 126),
        (5.8, 64, 0.89, 107), (4.7, 70, 0.97, 33), (3.3, 72, 1.16, 0),
        (3.1, 74, 1.32, 0), (3.4, 76, 1.39, 0), (3.0, 77, 1.60, 0),
        (2.4, 76, 1.72, 0), (2.0, 74, 1.68, 0), (1.9, 72, 1.71, 0),
    ],
    "2026-01-13": [
        (2.5, 72, 1.16, 0), (3.0, 74, 0.71, 0), (3.1, 76, 0.78, 0),
        (3.0, 78, 0.95, 0), (3.0, 77, 1.19, 0), (3.0, 76, 1.34, 0),
        (3.0, 74, 1.56, 0), (3.3, 73, 1.69, 0), (3.6, 73, 1.50, 7),
        (4.0, 74, 1.42, 27), (4.5, 74, 1.45, 53), (5.0, 74, 1.22, 80),
        (4.8, 74, 0.95, 87), (4.6, 77, 0.68, 73), (4.9, 80, 0.47, 66),
        (5.2, 82, 0.42, 35), (5.0, 83, 0.64, 15), (4.5, 84, 0.93, 0),
        (4.0, 86, 1.08, 0), (3.9, 86, 1.23, 0), (4.1, 83, 1.14, 0),
        (4.0, 84, 1.04, 0), (3.8, 88, 0.75, 0), (3.8, 89, 0.44, 0),
    ],
    "2026-01-14": [
        (3.7, 90, 0.30, 0), (3.6, 92, 0.30, 0), (3.5, 92, 0.83, 0),
        (3.5, 93, 1.24, 0), (3.5, 94, 1.36, 0), (3.5, 94, 1.47, 0),
        (3.5, 96, 1.84, 0), (3.6, 96, 2.09, 0), (3.8, 96, 2.07, 8),
        (4.0, 96, 1.90, 34), (4.5, 94, 1.56, 55), (5.1, 91, 1.35, 94),
        (5.2, 90, 1.34, 98), (5.2, 89, 1.21, 90), (5.8, 88, 0.97, 74),
        (6.0, 87, 0.96, 72), (5.8, 88, 1.00, 22), (5.2, 88, 1.21, 0),
        (4.9, 90, 1.45, 0), (5.2, 90, 1.46, 0), (5.6, 90, 1.44, 0),
        (5.7, 88, 1.53, 0), (5.7, 88, 1.33, 0), (5.6, 90, 0.99, 0),
    ],
    "2026-01-15": [
        (5.5, 90, 0.58, 0), (5.5, 90, 0.42, 0), (5.3, 92, 0.39, 0),
        (5.2, 92, 0.29, 0), (4.9, 94, 0.39, 0), (4.8, 96, 0.30, 0),
        (5.0, 96, 0.73, 0), (5.0, 97, 0.69, 0), (5.0, 98, 0.38, 9),
        (5.2, 99, 0.99, 24), (5.7, 98, 1.25, 56), (6.1, 96, 0.88, 60),
        (5.8, 96, 0.39, 58), (5.7, 95, 0.23, 56), (5.9, 94, 0.67, 42),
        (5.8, 96, 0.90, 25), (5.7, 98, 0.64, 11), (5.4, 99, 0.48, 0),
        (5.3, 100, 0.48, 0), (5.3, 100, 0.57, 0), (5.3, 99, 0.94, 0),
        (5.5, 99, 1.11, 0), (5.5, 99, 0.98, 0), (5.2, 100, 0.72, 0),
    ],
    "2026-01-16": [
        (5.2, 100, 0.69, 0), (5.5, 98, 0.62, 0), (5.8, 98, 0.42, 0),
        (5.7, 98, 0.65, 0), (5.5, 99, 0.73, 0), (5.3, 99, 0.54, 0),
        (5.4, 98, 0.62, 0), (5.5, 98, 0.89, 0), (5.6, 98, 1.16, 18),
        (6.1, 98, 1.25, 44), (6.7, 96, 1.07, 62), (7.2, 94, 1.21, 124),
        (7.1, 94, 1.23, 189), (6.8, 95, 1.22, 76), (7.0, 94, 1.17, 48),
        (7.0, 94, 0.66, 29), (6.8, 95, 0.52, 10), (6.6, 97, 0.74, 0),
        (6.4, 98, 0.70, 0), (6.5, 99, 0.72, 0), (6.7, 98, 1.13, 0),
        (6.8, 98, 1.48, 0), (6.8, 98, 1.53, 0), (6.8, 98, 1.48, 0),
    ],
    "2026-01-17": [
        (6.7, 98, 0.97, 0), (6.7, 99, 0.53, 0), (6.7, 99, 0.88, 0),
        (6.7, 99, 1.17, 0), (6.7, 99, 1.35, 0), (6.7, 98, 1.69, 0),
        (6.8, 98, 1.86, 0), (6.8, 96, 1.97, 0), (6.9, 95, 2.03, 4),
        (7.3, 92, 2.08, 30), (8.1, 90, 2.04, 58), (8.8, 88, 1.85, 82),
        (8.9, 89, 1.64, 78), (9.2, 90, 1.76, 152), (10.1, 85, 1.76, 201),
        (10.2, 86, 0.93, 84), (9.4, 89, 0.26, 28), (8.7, 90, 0.21, 0),
        (8.2, 92, 0.58, 0), (8.3, 90, 1.37, 0), (8.5, 88, 1.79, 0),
        (8.2, 88, 1.73, 0), (7.8, 88, 1.77, 0), (7.6, 89, 1.79, 0),
    ],
    "2026-01-18": [
        (7.2, 90, 1.64, 0), (7.0, 91, 1.58, 0), (7.2, 90, 1.65, 0),
        (7.2, 88, 1.73, 0), (7.3, 88, 1.68, 0), (7.2, 88, 1.65, 0),
        (7.1, 87, 1.77, 0), (7.0, 85, 2.02, 0), (7.1, 82, 2.38, 14),
        (7.4, 78, 2.45, 55), (7.8, 74, 2.91, 71), (8.1, 71, 3.40, 70),
        (8.3, 72, 2.74, 90), (8.9, 72, 2.07, 132), (9.4, 68, 2.17, 178),
        (9.4, 68, 2.33, 134), (8.6, 71, 2.31, 41), (7.9, 72, 2.15, 0),
        (7.7, 73, 1.99, 0), (7.7, 74, 2.08, 0), (7.6, 72, 2.25, 0),
        (7.3, 71, 2.30, 0), (7.1, 72, 2.30, 0), (6.8, 74, 2.24, 0),
    ],
}

SETTEMBRE: dict[str, list[tuple[float, float, float, float]]] = {
    "2026-09-14": [
        (20.9, 82, 0.47, 0), (20.2, 87, 0.72, 0), (19.8, 88, 0.63, 0),
        (19.4, 88, 0.47, 0), (19.1, 89, 0.21, 0), (18.7, 90, 0.26, 0),
        (18.6, 92, 0.65, 40), (19.7, 90, 0.78, 182), (21.6, 82, 0.70, 350),
        (23.2, 73, 0.64, 495), (24.6, 66, 0.64, 608), (25.6, 61, 0.91, 685),
        (26.6, 58, 0.94, 707), (27.4, 54, 1.04, 661), (27.6, 52, 1.42, 553),
        (27.4, 54, 1.65, 434), (26.9, 59, 1.81, 289), (25.9, 66, 1.99, 122),
        (25.0, 72, 2.44, 12), (24.4, 72, 2.65, 0), (23.8, 72, 2.46, 0),
        (23.0, 72, 2.52, 0), (22.4, 74, 2.65, 0), (21.9, 74, 2.81, 0),
    ],
    "2026-09-15": [
        (21.4, 73, 2.92, 0), (20.9, 74, 2.73, 0), (20.4, 76, 2.51, 0),
        (19.9, 77, 2.35, 0), (19.5, 78, 2.04, 0), (19.1, 80, 1.89, 0),
        (19.2, 80, 2.04, 37), (20.1, 78, 2.04, 176), (21.5, 74, 1.84, 343),
        (22.7, 68, 1.75, 494), (23.8, 62, 1.58, 614), (24.7, 57, 1.29, 688),
        (25.7, 54, 1.11, 703), (26.5, 52, 0.99, 667), (26.8, 51, 0.65, 581),
        (26.7, 52, 0.33, 443), (26.4, 52, 0.11, 281), (25.9, 56, 0.12, 118),
        (25.2, 62, 0.20, 10), (24.4, 66, 0.59, 0), (23.3, 72, 1.22, 0),
        (22.2, 78, 1.27, 0), (21.6, 80, 1.28, 0), (21.2, 80, 1.44, 0),
    ],
    "2026-09-16": [
        (20.6, 82, 1.25, 0), (20.2, 84, 1.20, 0), (20.1, 84, 1.77, 0),
        (19.6, 84, 2.16, 0), (19.1, 86, 1.90, 0), (18.6, 86, 1.58, 0),
        (18.7, 86, 1.64, 33), (19.6, 82, 1.48, 173), (21.0, 75, 1.22, 335),
        (22.4, 68, 1.25, 484), (23.6, 63, 1.10, 596), (24.6, 60, 0.93, 659),
        (25.9, 54, 0.91, 669), (27.0, 51, 0.81, 634), (27.4, 50, 0.63, 557),
        (27.2, 51, 0.49, 414), (26.8, 53, 0.87, 227), (25.6, 60, 1.28, 83),
        (24.0, 70, 1.60, 7), (22.6, 80, 2.02, 0), (21.4, 89, 1.86, 0),
        (20.7, 91, 2.22, 0), (20.1, 90, 2.77, 0), (19.7, 90, 2.96, 0),
    ],
    "2026-09-17": [
        (18.9, 93, 2.67, 0), (18.4, 95, 2.18, 0), (18.1, 94, 2.79, 0),
        (18.1, 96, 1.82, 0), (18.1, 96, 0.49, 0), (18.1, 96, 1.02, 0),
        (18.4, 97, 1.64, 15), (18.9, 96, 1.90, 124), (19.1, 93, 2.07, 180),
        (19.6, 88, 2.06, 252), (20.8, 80, 1.92, 442), (21.9, 74, 2.10, 461),
        (22.0, 75, 2.75, 370), (22.6, 72, 3.37, 540), (23.4, 66, 3.17, 494),
        (23.4, 65, 2.99, 354), (23.0, 67, 2.95, 224), (22.3, 71, 2.74, 88),
        (21.3, 76, 2.83, 6), (20.4, 80, 2.83, 0), (19.8, 83, 2.75, 0),
        (19.2, 86, 2.91, 0), (19.0, 86, 3.01, 0), (18.9, 88, 2.89, 0),
    ],
    "2026-09-18": [
        (18.8, 88, 2.23, 0), (18.6, 89, 1.93, 0), (18.4, 91, 2.10, 0),
        (18.2, 92, 2.41, 0), (17.9, 93, 2.95, 0), (17.4, 94, 2.98, 0),
        (17.4, 94, 2.60, 20), (17.9, 93, 2.50, 76), (18.2, 92, 2.60, 148),
        (18.9, 88, 2.46, 244), (20.2, 82, 2.09, 422), (21.6, 73, 1.58, 557),
        (22.6, 68, 1.50, 548), (23.2, 66, 1.83, 530), (23.4, 64, 2.01, 386),
        (23.4, 62, 1.96, 348), (23.4, 62, 1.54, 193), (22.6, 70, 1.06, 86),
        (21.6, 76, 0.76, 6), (21.1, 78, 0.80, 0), (20.8, 80, 0.85, 0),
        (20.4, 81, 0.95, 0), (19.8, 84, 1.25, 0), (19.2, 87, 1.59, 0),
    ],
    "2026-09-19": [
        (18.7, 89, 2.09, 0), (18.4, 89, 1.85, 0), (18.1, 89, 1.25, 0),
        (17.8, 89, 1.17, 0), (17.4, 90, 1.14, 0), (17.1, 94, 0.67, 0),
        (16.9, 94, 1.61, 25), (17.6, 90, 2.21, 119), (19.2, 84, 1.28, 285),
        (21.1, 76, 0.89, 460), (22.6, 72, 0.34, 599), (23.7, 67, 0.08, 631),
        (24.3, 65, 0.14, 620), (24.9, 64, 0.20, 627), (25.2, 62, 0.32, 524),
        (25.2, 60, 0.46, 395), (25.1, 59, 0.58, 256), (24.4, 64, 0.60, 99),
        (23.4, 70, 0.60, 5), (22.8, 70, 0.72, 0), (22.2, 72, 0.75, 0),
        (21.4, 78, 0.78, 0), (20.5, 83, 0.89, 0), (19.8, 88, 0.95, 0),
    ],
    "2026-09-20": [
        (19.1, 90, 1.17, 0), (18.9, 88, 1.29, 0), (18.8, 86, 1.02, 0),
        (18.6, 86, 0.81, 0), (18.3, 88, 0.63, 0), (17.9, 90, 0.32, 0),
        (17.9, 90, 0.17, 29), (18.9, 86, 0.15, 160), (20.8, 80, 0.12, 321),
        (22.7, 74, 0.33, 479), (24.1, 68, 0.66, 594), (25.0, 64, 0.85, 664),
        (26.1, 59, 1.03, 681), (26.8, 56, 1.23, 618), (26.8, 56, 1.25, 544),
        (26.6, 56, 1.19, 412), (26.3, 56, 1.12, 244), (25.4, 62, 1.04, 87),
        (24.2, 65, 0.80, 4), (23.6, 62, 0.38, 0), (22.9, 67, 0.54, 0),
        (21.9, 76, 1.27, 0), (21.1, 82, 1.35, 0), (20.4, 86, 1.15, 0),
    ],
}

STAGIONI: dict[str, tuple[str, dict[str, list[tuple[float, float, float, float]]]]] = {
    "estate": ("ESTATE — 13–19 luglio 2026, la canicola", ESTATE),
    "inverno": ("INVERNO — 12–18 gennaio 2026, un giorno di sole e poi la nebbia", INVERNO),
    "settembre": ("SETTEMBRE — 14–20 settembre 2026, la settimana con cui è nato l'esempio", SETTEMBRE),
}
STAGIONI_DI_DEFAULT = ("estate", "inverno")
# Tutte le ore di tutte le settimane, per data: le funzioni sotto leggono qui.
METEO: dict[str, list[tuple[float, float, float, float]]] = {
    giorno: ore for _, dati in STAGIONI.values() for giorno, ore in dati.items()
}

PASSI_SUB_GIORNALIERI = (6, 4, 1)
METODI = ("HS", "PM 24h FAO", "PM 24h fito", "PM 6h", "PM 4h", "PM 1h")
ORE_EVENTO = (8, 20)        # un litro il quarto giorno, alle 8 o alle 20


# ---------------------------------------------------------------------
#  Dalle ore ai blocchi della libreria
# ---------------------------------------------------------------------


def blocchi_del_giorno(giorno: date, passo_h: int) -> list[WeatherBlock]:
    """I `WeatherBlock` di un giorno, di `passo_h` ore (divisore di 24)."""
    ore = METEO[giorno.isoformat()]
    blocchi = []
    for k in range(24 // passo_h):
        fetta = ore[k * passo_h:(k + 1) * passo_h]
        n = len(fetta)
        blocchi.append(WeatherBlock(
            date_=giorno,
            start_hour=k * passo_h,
            hours=passo_h,
            t_c=sum(o[0] for o in fetta) / n,
            humidity_relative=sum(o[1] for o in fetta) / n / 100.0,
            wind_speed_m_s=sum(o[2] for o in fetta) / n * FATTORE_U10_U2,
            # W/m² medi per un'ora = 3600 J/m² = 0.0036 MJ/m²
            solar_radiation_mj_m2=sum(o[3] for o in fetta) * 3600.0 / 1e6,
        ))
    return blocchi


def estremi_del_giorno(giorno: date) -> tuple[float, float, float, float, float, float]:
    """T_max, T_min, RH_max, RH_min (frazioni), u₂ medio, R_s del giorno."""
    ore = METEO[giorno.isoformat()]
    t = [o[0] for o in ore]
    rh = [o[1] / 100.0 for o in ore]
    u2 = sum(o[2] for o in ore) / len(ore) * FATTORE_U10_U2
    rs = sum(o[3] for o in ore) * 3600.0 / 1e6
    return max(t), min(t), max(rh), min(rh), u2, rs


# ---------------------------------------------------------------------
#  Le due giornaliere
# ---------------------------------------------------------------------


def et0_pm_giornaliera_fao56(giorno: date) -> float:
    """FAO-56 eq. 6 con le convenzioni del capitolo 3 (eq. 9, 12, 17, 42)."""
    t_max, t_min, rh_max, rh_min, u2, rs = estremi_del_giorno(giorno)
    t_mean = (t_max + t_min) / 2.0
    es = (saturation_vapor_pressure(t_max) + saturation_vapor_pressure(t_min)) / 2.0
    ea = (
        saturation_vapor_pressure(t_min) * rh_max
        + saturation_vapor_pressure(t_max) * rh_min
    ) / 2.0
    delta = slope_vapor_pressure(t_mean)
    gamma = psychrometric_constant(atmospheric_pressure(QUOTA_M))
    ra = extraterrestrial_radiation(LATITUDINE, day_of_year(giorno))
    rn = net_radiation(rs, ra, t_max, t_min, ea, QUOTA_M)
    return (
        0.408 * delta * rn
        + gamma * 900.0 / (t_mean + 273.0) * u2 * (es - ea)
    ) / (delta + gamma * (1.0 + 0.34 * u2))


def et0_pm_giornaliera_fitosim(giorno: date) -> float:
    """
    La catena di `Pot.apply_balance_step_from_weather`, senza vaso, con il
    `WeatherDay` che una stazione dà: la media dell'umidità e i suoi
    estremi. Dal 21 ottobre 2026 (A9) e_s ed e_a vengono dagli estremi del
    giorno (FAO-56 eq. 12 e 17) e non da e°(T_media): quello che resta
    fra questa colonna e la FAO qui sopra è il coefficiente aerodinamico,
    900/(T+273) fisso nella FAO, ρ_a·c_p/r_a esplicito in fitosim.
    """
    t_max, t_min, rh_max, rh_min, u2, rs = estremi_del_giorno(giorno)
    t_mean = (t_max + t_min) / 2.0
    rh_mean = sum(o[1] for o in METEO[giorno.isoformat()]) / 24 / 100.0
    ra = extraterrestrial_radiation(LATITUDINE, day_of_year(giorno))
    _es, ea = daily_vapor_pressures(t_min, t_max, rh_mean, rh_min, rh_max)
    rn = net_radiation(rs, ra, t_max, t_min, ea, QUOTA_M)
    return compute_et0_penman_monteith(
        temperature_c=t_mean, humidity_relative=rh_mean, wind_speed_m_s=u2,
        net_radiation_mj_m2_day=rn, elevation_m=QUOTA_M,
        t_min=t_min, t_max=t_max, humidity_min=rh_min, humidity_max=rh_max,
    )


def serie_sub_giornaliera(giorni: list[date], passo_h: int):
    """
    ET₀ giornaliera come somma dei blocchi di `passo_h` ore, per tutta la
    settimana, con `et0_for_blocks` della libreria (standard: niente
    parametri di specie) e il rapporto R_s/R_so pre-tramonto passato da
    un giorno all'altro. Ritorna (somme, negativi azzerati, dettaglio).
    """
    somme, negativi, dettagli = {}, {}, {}
    rapporto_notte = None
    for giorno in giorni:
        blocchi = blocchi_del_giorno(giorno, passo_h)
        passi, _metodo, rapporto_notte = et0_for_blocks(
            blocchi,
            latitude_deg=LATITUDINE, longitude_deg=LONGITUDINE_EST,
            utc_offset_hours=FUSO_ORARIO, elevation_m=QUOTA_M,
            rs_rso_night_previous=rapporto_notte,
        )
        somme[giorno] = sum(p.et_mm for p in passi)
        negativi[giorno] = sum(min(p.et_raw_mm, 0.0) for p in passi)
        dettagli[giorno] = list(zip(blocchi, passi))
    return somme, negativi, dettagli


# ---------------------------------------------------------------------
#  Il vaso
# ---------------------------------------------------------------------


def nuovo_vaso() -> Pot:
    """Lo stesso vaso, nuovo, per ogni metodo e stagione: parte a capacità di campo."""
    return Pot(
        label="Rosmarino del balcone",
        species=ROSEMARY,
        substrate=PERLITE_RICH,
        pot_volume_l=5.0,
        pot_diameter_cm=20.0,
        location=Location.OUTDOOR,
        planting_date=date(2024, 4, 15),    # perenne: lo stadio segue il calendario
        rainfall_exposure=0.0,              # sotto il balcone di sopra
        latitude_deg=LATITUDINE,
        elevation_m=QUOTA_M,
    )


def settimana_a_blocchi(
    giorni: list[date],
    fertigazione: BlockFertigation | None = None,
    giorno_evento: date | None = None,
    fino_a: int = 7,
):
    """
    La settimana un'ora alla volta con `apply_blocks_from_weather`, il
    rapporto pre-tramonto passato da un giorno all'altro; l'eventuale
    irrigazione il giorno dell'evento. Ritorna il vaso e gli esiti per
    giorno.
    """
    vaso = nuovo_vaso()
    esiti = []
    rapporto_notte = None
    for giorno in giorni[:fino_a]:
        eventi = (
            [fertigazione] if fertigazione is not None and giorno == giorno_evento else []
        )
        esito = vaso.apply_blocks_from_weather(
            blocchi_del_giorno(giorno, 1), giorno,
            longitude_deg=LONGITUDINE_EST, utc_offset_hours=FUSO_ORARIO,
            rs_rso_night_previous=rapporto_notte, fertigations=eventi,
        )
        rapporto_notte = esito.rs_rso_pre_sunset
        esiti.append(esito)
    return vaso, esiti


# ---------------------------------------------------------------------
#  L'analisi di una stagione
# ---------------------------------------------------------------------


def analizza(nome: str) -> SimpleNamespace:
    """Tutti i numeri di una settimana: le ET₀, il vaso a giorni, il vaso a blocchi, l'evento."""
    titolo, dati = STAGIONI[nome]
    giorni = [date.fromisoformat(g) for g in dati]

    # Le ET₀ con i sei metodi.
    et0: dict[str, dict[date, float]] = {m: {} for m in METODI}
    negativi: dict[str, dict[date, float]] = {}
    dettagli: dict[int, dict] = {}
    for giorno in giorni:
        t_max, t_min, *_ = estremi_del_giorno(giorno)
        j = day_of_year(giorno)
        et0["HS"][giorno] = et0_hargreaves_samani(t_min, t_max, LATITUDINE, j)
        et0["PM 24h FAO"][giorno] = et0_pm_giornaliera_fao56(giorno)
        et0["PM 24h fito"][giorno] = et0_pm_giornaliera_fitosim(giorno)
    for passo in PASSI_SUB_GIORNALIERI:
        nome_metodo = f"PM {passo}h"
        et0[nome_metodo], negativi[nome_metodo], dettagli[passo] = serie_sub_giornaliera(giorni, passo)
    totali = {m: sum(et0[m].values()) for m in METODI}
    giorno_max = max(giorni, key=lambda g: abs(et0["PM 24h FAO"][g] - et0["PM 1h"][g]))

    # Il vaso a giorni, un esemplare per metodo.
    stato: dict[str, list[float]] = {}
    allerta: dict[str, tuple[date, float] | None] = {}   # giorno, mm sotto soglia
    for metodo in METODI:
        vaso = nuovo_vaso()
        stato[metodo] = []
        allerta[metodo] = None
        for giorno in giorni:
            t_max, t_min, *_ = estremi_del_giorno(giorno)
            esito = vaso.apply_balance_step(
                et_0_mm=et0[metodo][giorno], water_input_mm=0.0,
                current_date=giorno, t_mean_c=(t_max + t_min) / 2.0,
            )
            stato[metodo].append(vaso.state_mm)
            if esito.under_alert and allerta[metodo] is None:
                allerta[metodo] = (giorno, esito.deficit)

    # Il vaso dal meteo: il cammino giornaliero e quello a blocchi.
    giornaliero = nuovo_vaso()
    stati_giornaliero: list[float] = []
    etc_giornaliero: list[float] = []
    for giorno in giorni:
        prima = giornaliero.state_mm
        giornaliero.apply_step_from_weather(
            weather_day_from_blocks(blocchi_del_giorno(giorno, 1)), current_date=giorno,
        )
        stati_giornaliero.append(giornaliero.state_mm)
        etc_giornaliero.append(prima - giornaliero.state_mm)
    _, esiti_blocchi = settimana_a_blocchi(giorni)

    # Un litro il quarto giorno, alle 8 o alle 20.
    giorno_evento = giorni[3]
    eventi: dict[int, tuple[float, object, float, float]] = {}
    for ora_evento in ORE_EVENTO:
        vaso, esiti = settimana_a_blocchi(
            giorni,
            BlockFertigation(start_hour=ora_evento, volume_l=1.0, ec_mscm=0.5, ph=7.5),
            giorno_evento=giorno_evento, fino_a=4,
        )
        eventi[ora_evento] = (
            esiti[-2].blocks_result.balance_result.new_state,     # la mattina del giorno
            esiti[-1].blocks_result,
            esiti[-1].fertigation_results[0].water_drained_mm,
            vaso.state_mm,
        )

    vaso_base = nuovo_vaso()
    return SimpleNamespace(
        nome=nome, titolo=titolo, giorni=giorni,
        et0=et0, negativi=negativi, dettagli=dettagli, totali=totali, giorno_max=giorno_max,
        stato=stato, allerta=allerta,
        stati_giornaliero=stati_giornaliero, etc_giornaliero=etc_giornaliero,
        esiti_blocchi=esiti_blocchi, giorno_evento=giorno_evento, eventi=eventi,
        fc_mm=vaso_base.fc_mm, alert_mm=vaso_base.alert_mm, pwp_mm=vaso_base.pwp_mm,
        vaso=vaso_base,
    )


# ---------------------------------------------------------------------
#  Stampa
# ---------------------------------------------------------------------

SETTIMANA = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


def stampa_sezione(titolo: str, carattere: str = "=") -> None:
    print()
    print(carattere * 78)
    print(f"  {titolo}")
    print(carattere * 78)


def etichetta(giorno: date) -> str:
    return f"{giorno:%d/%m} {SETTIMANA[giorno.weekday()]}"


def colonna(valore: float | None, larghezza: int = 8) -> str:
    """Un numero a tre decimali, o spazi se il blocco non inizia qui."""
    return f"{valore:>{larghezza}.3f}" if valore is not None else " " * larghezza


def ora(h: float) -> str:
    return f"{int(h):02d}:{round((h % 1) * 60):02d}"


def testo_allerta(alert_hour: int | None) -> str:
    if alert_hour is None:
        return "no"
    return "già sotto" if alert_hour == 0 else f"dalle {alert_hour:02d}:00"


def stampa_stagione(r: SimpleNamespace) -> None:
    """Le tabelle di una stagione."""
    giorni = r.giorni
    stampa_sezione(r.titolo, "#")

    # --- Lo scenario ---
    j0 = day_of_year(giorni[0])
    ra_giorno = extraterrestrial_radiation(LATITUDINE, j0)
    ra_somma = sum(
        extraterrestrial_radiation_interval(LATITUDINE, LONGITUDINE_EST, j0, h, h + 1, FUSO_ORARIO)
        for h in range(24)
    )
    alba, tramonto = sunrise_sunset_hours(LATITUDINE, LONGITUDINE_EST, j0, FUSO_ORARIO)
    print(f"Il {giorni[0]:%d/%m}: alba alle {ora(alba)}, tramonto alle {ora(tramonto)} CET "
          f"({(tramonto - alba):.1f} ore di luce); R_a del giorno {ra_giorno:.2f} MJ/m² (eq. 21), "
          f"somma delle 24 ore {ra_somma:.2f} (eq. 28).")
    v = r.vaso
    print(f"Vaso: {v.label} — {v.species.common_name}, {v.substrate.name}, "
          f"{v.pot_volume_l:.0f} L, Ø {v.pot_diameter_cm:.0f} cm, profondità "
          f"{v.substrate_depth_mm:.0f} mm, Kp {v.kp:.2f}; FC {v.fc_mm:.1f} mm, allerta "
          f"{v.alert_mm:.1f} mm (p {v.species.depletion_fraction:.2f}), PWP {v.pwp_mm:.1f} mm;")
    print(f"      stadio {v.current_stage(giorni[0]).name}, "
          f"Kc·Kp·Ks·Kn a FC = {v.current_et_c(1.0, giorni[0]):.2f}.")

    # --- Il meteo ---
    stampa_sezione("Il meteo, giorno per giorno")
    print(f"{'giorno':<10}{'T min':>7}{'T max':>7}{'RH med':>8}{'u2 med':>8}"
          f"{'Rs MJ':>8}{'Rs/Rso':>8}")
    for giorno in giorni:
        t_max, t_min, _, _, u2, rs = estremi_del_giorno(giorno)
        rh_med = sum(o[1] for o in METEO[giorno.isoformat()]) / 24
        rso = clear_sky_radiation(
            extraterrestrial_radiation(LATITUDINE, day_of_year(giorno)), QUOTA_M,
        )
        print(f"{etichetta(giorno):<10}{t_min:>7.1f}{t_max:>7.1f}{rh_med:>8.0f}"
              f"{u2:>8.2f}{rs:>8.2f}{rs / rso:>8.2f}")

    # --- ET₀ per metodo ---
    stampa_sezione("ET₀ del giorno (mm) con i sei metodi")
    print(f"{'giorno':<10}" + "".join(f"{m:>13}" for m in METODI))
    for giorno in giorni:
        print(f"{etichetta(giorno):<10}" + "".join(f"{r.et0[m][giorno]:>13.2f}" for m in METODI))
    print("-" * 88)
    print(f"{'settimana':<10}" + "".join(f"{r.totali[m]:>13.2f}" for m in METODI))
    riferimento = r.totali["PM 1h"]
    print(f"{'vs PM 1h':<10}"
          + "".join(f"{100.0 * (r.totali[m] / riferimento - 1.0):>+12.1f}%" for m in METODI))
    print()
    print("Blocchi notturni negativi azzerati prima della somma (mm sulla settimana, e quanto "
          "sono del totale):")
    for passo in PASSI_SUB_GIORNALIERI:
        nome = f"PM {passo}h"
        neg = sum(r.negativi[nome].values()) + 0.0     # −0.0 → 0.0
        quota = -neg / r.totali[nome] if neg else 0.0
        print(f"  {nome:<8}{neg:>+7.2f}   ({100.0 * quota:.0f} %)")

    # --- Dentro un giorno ---
    g = r.giorno_max
    stampa_sezione(f"Dentro il {etichetta(g)}: il giorno in cui la 24 h e la somma delle ore "
                   f"divergono di più")
    print(f"{'ora':<7}{'T':>6}{'RH':>5}{'u2':>6}{'Rs':>7}{'Ra':>7}{'Rn':>7}"
          f"{'G':>7}{'ET0 1h':>8}{'4h':>8}{'6h':>8}")
    print(f"{'CET':<7}{'°C':>6}{'%':>5}{'m/s':>6}{'MJ':>7}{'MJ':>7}{'MJ':>7}"
          f"{'MJ':>7}{'mm':>8}{'mm':>8}{'mm':>8}")
    per_inizio = {
        passo: {b.start_hour: p for b, p in r.dettagli[passo][g]} for passo in PASSI_SUB_GIORNALIERI
    }
    for b, p in r.dettagli[1][g]:
        col4 = per_inizio[4].get(b.start_hour)
        col6 = per_inizio[6].get(b.start_hour)
        print(f"{b.start_hour:02d}-{b.end_hour:02d}{'' if p.daytime else '*':<2}"
              f"{b.t_c:>6.1f}{b.humidity_relative * 100:>5.0f}{b.wind_speed_m_s:>6.2f}"
              f"{b.solar_radiation_mj_m2:>7.2f}"
              f"{p.ra_mj:>7.2f}{p.rn_mj:>7.2f}{p.g_mj:>7.2f}{p.et_raw_mm:>8.3f}"
              + colonna(col4.et_raw_mm if col4 else None)
              + colonna(col6.et_raw_mm if col6 else None))
    passi_1h = [p for _, p in r.dettagli[1][g]]
    print(f"{'somma':<7}{'':>6}{'':>5}{'':>6}"
          f"{sum(b.solar_radiation_mj_m2 for b, _ in r.dettagli[1][g]):>7.2f}"
          f"{sum(p.ra_mj for p in passi_1h):>7.2f}"
          f"{sum(p.rn_mj for p in passi_1h):>7.2f}"
          f"{sum(p.g_mj for p in passi_1h):>7.2f}"
          f"{sum(p.et_raw_mm for p in passi_1h):>8.3f}"
          f"{sum(p.et_raw_mm for _, p in r.dettagli[4][g]):>8.3f}"
          f"{sum(p.et_raw_mm for _, p in r.dettagli[6][g]):>8.3f}")
    print("* = blocco notturno (G = 0.5 R_n, R_s/R_so delle 2–3 ore prima del tramonto). "
          "Le somme qui tengono i negativi;")
    print(f"  azzerandoli: 1 h {r.et0['PM 1h'][g]:.2f}, 4 h {r.et0['PM 4h'][g]:.2f}, "
          f"6 h {r.et0['PM 6h'][g]:.2f}; la 24 h FAO dà {r.et0['PM 24h FAO'][g]:.2f}, "
          f"HS {r.et0['HS'][g]:.2f}.")

    # --- Il vaso a giorni ---
    stampa_sezione(f"Il vaso a giorni: acqua nel substrato a fine giornata (mm; FC {r.fc_mm:.1f}, "
                   f"allerta {r.alert_mm:.1f})")
    print(f"{'giorno':<10}" + "".join(f"{m:>13}" for m in METODI))
    for k, giorno in enumerate(giorni):
        print(f"{etichetta(giorno):<10}" + "".join(f"{r.stato[m][k]:>13.1f}" for m in METODI))
    print("-" * 88)
    print(f"{'ETc sett.':<10}" + "".join(f"{r.fc_mm - r.stato[m][-1]:>13.1f}" for m in METODI))
    print(f"{'allerta':<10}"
          + "".join(f"{(f'{a[0]:%d/%m} −{a[1]:.1f}' if (a := r.allerta[m]) else 'no'):>13}"
                    for m in METODI))

    # --- Il vaso a blocchi ---
    stampa_sezione("Il vaso a blocchi: la stessa settimana un'ora alla volta "
                   "(Pot.apply_blocks_from_weather)")
    print(f"{'giorno':<10}{'ETc 24h':>9}{'ETc 1h':>9}{'vaso 24h':>10}{'vaso 1h':>9}"
          f"{'allerta 24h':>13}{'allerta 1h':>12}  metodo")
    for k, giorno in enumerate(giorni):
        esito_b = r.esiti_blocchi[k]
        allerta_g = "sì" if r.stati_giornaliero[k] < r.alert_mm else "no"
        print(f"{etichetta(giorno):<10}{r.etc_giornaliero[k]:>9.2f}"
              f"{esito_b.blocks_result.et_c_mm:>9.2f}"
              f"{r.stati_giornaliero[k]:>10.1f}"
              f"{esito_b.blocks_result.balance_result.new_state:>9.1f}"
              f"{allerta_g:>13}{testo_allerta(esito_b.blocks_result.alert_hour):>12}"
              f"  {esito_b.et_method.value}")
    print()
    inizio_8 = r.eventi[ORE_EVENTO[0]][0]
    print(f"Un litro il {r.giorno_evento:%d/%m} (deficit {r.fc_mm - inizio_8:.1f} mm quella "
          f"mattina): a che ora lo dai conta?")
    for ora_evento in ORE_EVENTO:
        _, _, drenato, sera = r.eventi[ora_evento]
        print(f"  alle {ora_evento:02d}:00  drena {drenato:5.2f} mm, la sera il vaso ha {sera:5.1f} mm")


def stampa_confronto(risultati: list[SimpleNamespace]) -> None:
    """Le stagioni fianco a fianco."""
    stampa_sezione("Le stagioni a confronto", "#")
    larg = 16
    print(f"{'':<34}" + "".join(f"{r.nome:>{larg}}" for r in risultati))
    print(f"{'ET₀ della settimana, PM 1h (mm)':<34}"
          + "".join(f"{r.totali['PM 1h']:>{larg}.2f}" for r in risultati))
    for m in METODI[:-1]:
        print(f"{'  ' + m + ' vs PM 1h':<34}"
              + "".join(f"{100.0 * (r.totali[m] / r.totali['PM 1h'] - 1.0):>{larg - 2}.1f} %"
                        for r in risultati))
    print(f"{'  negativi notturni azzerati, 1h':<34}"
          + "".join(f"{100.0 * -sum(r.negativi['PM 1h'].values()) / r.totali['PM 1h']:>{larg - 2}.0f} %"
                    for r in risultati))
    print(f"{'ETc della settimana a giorni (mm)':<34}"
          + "".join(f"{r.fc_mm - r.stati_giornaliero[-1]:>{larg}.2f}" for r in risultati))
    print(f"{'ETc della settimana a blocchi (mm)':<34}"
          + "".join(f"{r.fc_mm - r.esiti_blocchi[-1].blocks_result.balance_result.new_state:>{larg}.2f}"
                    for r in risultati))

    def allerta_giorni(r):
        for k, s in enumerate(r.stati_giornaliero):
            if s < r.alert_mm:
                return f"{r.giorni[k]:%d/%m}"
        return "no"

    def allerta_blocchi(r):
        for k, e in enumerate(r.esiti_blocchi):
            if e.blocks_result.alert_hour is not None:
                return f"{r.giorni[k]:%d/%m} {e.blocks_result.alert_hour:02d}:00"
        return "no"

    print(f"{'allerta, a giorni':<34}" + "".join(f"{allerta_giorni(r):>{larg}}" for r in risultati))
    print(f"{'allerta, a blocchi':<34}" + "".join(f"{allerta_blocchi(r):>{larg}}" for r in risultati))
    print(f"{'1 L il 4° giorno: drena alle 8 / 20':<34}"
          + "".join(f"{r.eventi[8][2]:>{larg - 8}.1f} / {r.eventi[20][2]:.1f} mm" for r in risultati))
    print(f"{'  la sera resta nel vaso, alle 20 vs 8':<34}"
          + "".join(f"{r.eventi[20][3] - r.eventi[8][3]:>{larg - 3}.1f} mm" for r in risultati))


# ---------------------------------------------------------------------
#  I grafici
# ---------------------------------------------------------------------

COLORI = {
    "HS": "#8c8c8c", "PM 24h FAO": "#1f4e79", "PM 24h fito": "#6fa8dc",
    "PM 6h": "#b5651d", "PM 4h": "#e69f00", "PM 1h": "#2e8b57",
}


def disegna_grafici(risultati: list[SimpleNamespace]) -> None:
    """
    Quattro PNG in `FITOSIM_DEMO_OUTPUT_DIR` (o in `examples/`), un
    pannello per stagione. Senza matplotlib lo dice e non fa altro: il
    core di fitosim è stdlib.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        stampa_sezione("I grafici")
        print("matplotlib non è installato: niente grafici. `pip install -e '.[dev]'` per averli.")
        return

    cartella = Path(os.environ.get("FITOSIM_DEMO_OUTPUT_DIR") or Path(__file__).parent)
    cartella.mkdir(parents=True, exist_ok=True)
    salvati = []
    ns = len(risultati)

    def salva(fig, nome: str) -> None:
        percorso = cartella / nome
        fig.tight_layout()
        fig.savefig(percorso, dpi=130)
        plt.close(fig)
        salvati.append(percorso)

    def titolo_breve(r) -> str:
        return f"{r.nome}: {r.giorni[0]:%d/%m} – {r.giorni[-1]:%d/%m/%Y}"

    # 1. L'ET₀ del giorno con i sei metodi: barre raggruppate, un pannello
    #    per stagione con la sua scala (d'inverno si parla di decimi).
    fig, axes = plt.subplots(1, ns, figsize=(7.5 * ns, 5.2), squeeze=False)
    for ax, r in zip(axes[0], risultati):
        n = len(r.giorni)
        larghezza = 0.13
        for i, m in enumerate(METODI):
            ax.bar([k + (i - (len(METODI) - 1) / 2) * larghezza for k in range(n)],
                   [r.et0[m][g] for g in r.giorni], larghezza, color=COLORI[m],
                   label=f"{m}  ({r.totali[m]:.1f} mm)")
        ax.set_xticks(range(n))
        ax.set_xticklabels([etichetta(g) for g in r.giorni], fontsize=9)
        ax.set_ylabel("ET₀ (mm/giorno)")
        ax.set_title(f"{titolo_breve(r)} — totali della settimana in legenda", fontsize=11)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8, ncol=2)
    fig.suptitle("ET₀ del giorno con i sei metodi — Milano (ERA5)")
    salva(fig, "confronto_et0_metodi.png")

    # 2. Dentro il giorno: l'ora per ora, i blocchi di 4 e 6 ore come tassi,
    #    la giornaliera FAO spalmata sulle 24 ore, la notte in grigio.
    fig, axes = plt.subplots(1, ns, figsize=(7.5 * ns, 5.2), squeeze=False)
    for ax, r in zip(axes[0], risultati):
        g = r.giorno_max
        ore_1h = r.dettagli[1][g]
        for b, p in ore_1h:
            if not p.daytime:
                ax.axvspan(b.start_hour, b.end_hour, color="grey", alpha=0.10, lw=0)
        ax.bar([b.start_hour + 0.5 for b, _ in ore_1h], [p.et_raw_mm for _, p in ore_1h],
               width=0.9, color=COLORI["PM 1h"], alpha=0.85,
               label="PM 1 h: il blocco com'è (negativo di notte)")
        for passo in (4, 6):
            xs, ys = [], []
            for b, p in r.dettagli[passo][g]:
                xs += [b.start_hour, b.end_hour]
                ys += [p.et_raw_mm / b.hours] * 2
            ax.plot(xs, ys, color=COLORI[f"PM {passo}h"], lw=2.2,
                    label=f"PM {passo} h: mm/h medi del blocco")
        ax.axhline(r.et0["PM 24h FAO"][g] / 24.0, color=COLORI["PM 24h FAO"], ls="--", lw=1.5,
                   label="PM 24 h FAO, spalmata sulle 24 ore")
        ax.axhline(0.0, color="k", lw=0.6)
        ax.set_xlim(0, 24)
        ax.set_xticks(range(0, 25, 2))
        ax.set_xlabel("ora solare (CET)")
        ax.set_ylabel("mm/h")
        ax.set_title(
            f"{r.nome}, {etichetta(g)}: 1 h {r.et0['PM 1h'][g]:.2f} mm, 4 h {r.et0['PM 4h'][g]:.2f}, "
            f"6 h {r.et0['PM 6h'][g]:.2f}, 24 h FAO {r.et0['PM 24h FAO'][g]:.2f}", fontsize=10,
        )
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8, loc="upper left")
    fig.suptitle("Dentro il giorno in cui la 24 h e la somma delle ore divergono di più "
                 "(i blocchi negativi valgono zero nelle somme)")
    salva(fig, "confronto_et0_dentro_il_giorno.png")

    # 3. Il vaso a giorni: lo stesso vaso con le sei ET₀, stessa scala nelle
    #    stagioni perché il vaso è lo stesso.
    fig, axes = plt.subplots(1, ns, figsize=(7.5 * ns, 5.2), squeeze=False, sharey=True)
    for ax, r in zip(axes[0], risultati):
        n = len(r.giorni)
        xs = list(range(n + 1))
        for m in METODI:
            ax.plot(xs, [r.fc_mm] + r.stato[m], marker="o", ms=4, color=COLORI[m], label=m)
        ax.axhline(r.fc_mm, color="k", ls=":", lw=1, label=f"capacità di campo {r.fc_mm:.1f} mm")
        ax.axhline(r.alert_mm, color="#c0392b", ls="--", lw=1.5,
                   label=f"soglia della specie (p {r.vaso.species.depletion_fraction:.2f}) "
                         f"{r.alert_mm:.1f} mm")
        ax.axhline(r.pwp_mm, color="#7f8c8d", ls="-.", lw=1, label=f"appassimento {r.pwp_mm:.1f} mm")
        ax.set_xticks(xs)
        ax.set_xticklabels(["sera prima"] + [f"{g:%d/%m}" for g in r.giorni], fontsize=9)
        ax.set_title(titolo_breve(r), fontsize=11)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, ncol=2)
    axes[0][0].set_ylabel("acqua nel substrato (mm)")
    fig.suptitle(f"Il vaso a giorni: {risultati[0].vaso.species.common_name.lower()}, "
                 f"{risultati[0].vaso.pot_volume_l:.0f} L, con le sei ET₀")
    salva(fig, "confronto_et0_vaso_a_giorni.png")

    # 4. Il vaso a blocchi: una riga per stagione — la settimana un'ora alla
    #    volta contro il cammino giornaliero, e il litro alle 8 o alle 20.
    fig, axes = plt.subplots(ns, 2, figsize=(14, 4.8 * ns), squeeze=False,
                             gridspec_kw={"width_ratios": [2, 1]})
    y_min = min(
        min(t.state_after_mm for e in r.esiti_blocchi for t in e.blocks_result.blocks)
        for r in risultati
    )
    for (ax1, ax2), r in zip(axes, risultati):
        n = len(r.giorni)
        xs_h, ys_h = [0.0], [r.fc_mm]
        ora_allerta = None
        for k, esito in enumerate(r.esiti_blocchi):
            for t in esito.blocks_result.blocks:
                xs_h.append(k * 24 + t.end_hour)
                ys_h.append(t.state_after_mm)
            if ora_allerta is None and esito.blocks_result.alert_hour:
                ora_allerta = k * 24 + esito.blocks_result.alert_hour
        ax1.plot(xs_h, ys_h, color=COLORI["PM 1h"], lw=1.8, label="a blocchi di un'ora")
        ax1.plot([0] + [24 * (k + 1) for k in range(n)], [r.fc_mm] + r.stati_giornaliero,
                 marker="o", ms=5, ls="--", color=COLORI["PM 24h FAO"], label="a giorni (fine giornata)")
        ax1.axhline(r.alert_mm, color="#c0392b", ls="--", lw=1.5, label="soglia della specie")
        if ora_allerta is not None:
            ax1.axvline(ora_allerta, color="#c0392b", lw=1, alpha=0.7)
            ax1.annotate(
                f"allerta: {r.giorni[ora_allerta // 24]:%d/%m} alle {ora_allerta % 24:02d}:00",
                xy=(ora_allerta, r.alert_mm), xytext=(max(ora_allerta - 78, 2), r.alert_mm - 5.5),
                fontsize=9, color="#c0392b",
                arrowprops={"arrowstyle": "->", "color": "#c0392b", "lw": 1},
            )
        ax1.set_ylim(y_min - 2, r.fc_mm + 2)
        ax1.set_xticks([24 * k for k in range(n + 1)])
        ax1.set_xticklabels(["sera prima"] + [f"{g:%d/%m}" for g in r.giorni], fontsize=9)
        ax1.set_ylabel("acqua nel substrato (mm)")
        ax1.set_title(f"{titolo_breve(r)} — un'ora alla volta (Penman-Monteith fisico)", fontsize=11)
        ax1.grid(alpha=0.3)
        ax1.legend(fontsize=9, loc="lower left")

        for ora_evento, colore in zip(ORE_EVENTO, ("#e69f00", "#2e8b57")):
            inizio, blocchi_res, drenato, _sera = r.eventi[ora_evento]
            xs_e = [0] + [t.end_hour for t in blocchi_res.blocks]
            ys_e = [inizio] + [t.state_after_mm for t in blocchi_res.blocks]
            ax2.plot(xs_e, ys_e, color=colore, lw=2,
                     label=f"1 L alle {ora_evento:02d}:00 — drena {drenato:.1f} mm")
        ax2.axhline(r.fc_mm, color="k", ls=":", lw=1, label="capacità di campo")
        ax2.set_xlim(0, 24)
        ax2.set_xticks(range(0, 25, 4))
        ax2.set_xlabel("ora solare (CET)")
        ax2.set_title(f"un litro il {r.giorno_evento:%d/%m}", fontsize=11)
        ax2.grid(alpha=0.3)
        ax2.legend(fontsize=9, loc="lower right")
    fig.suptitle("Il vaso a blocchi (A7): la settimana un'ora alla volta, l'ora dell'allerta, "
                 "il litro alle 8 o alle 20")
    salva(fig, "confronto_et0_vaso_a_blocchi.png")

    stampa_sezione("I grafici")
    for percorso in salvati:
        print(f"  {percorso}")


def main(argv: list[str]) -> None:
    # La console di Windows parte in cp1252 e non sa stampare θ e ₀.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    nomi = argv or list(STAGIONI_DI_DEFAULT)
    sconosciute = [n for n in nomi if n not in STAGIONI]
    if sconosciute:
        raise SystemExit(
            f"Stagioni sconosciute: {', '.join(sconosciute)}. "
            f"Scegli fra: {', '.join(STAGIONI)}."
        )

    print(f"Milano {LATITUDINE} N {LONGITUDINE_EST} E, {QUOTA_M:.0f} m; ore in ora solare CET "
          f"(d'estate l'orologio segna un'ora in più).")
    risultati = [analizza(nome) for nome in nomi]
    for r in risultati:
        stampa_stagione(r)
    if len(risultati) > 1:
        stampa_confronto(risultati)
    disegna_grafici(risultati)


if __name__ == "__main__":
    main(sys.argv[1:])
