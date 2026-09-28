"""
Hargreaves-Samani contro Penman-Monteith a quattro passi temporali
(24 h, 6 h, 4 h, 1 h) su una settimana vera, e che cosa cambia nel
bilancio idrico di un vaso — a giorni, e poi a blocchi (A7). Con le
tabelle, e quattro grafici se matplotlib c'è.

La domanda a cui risponde: quanto conta la risoluzione temporale dei
dati meteo nel calcolo di ET₀, e quanto di quella differenza arriva
fino al vaso — cioè fino al giorno, e all'ora, in cui il modello dice
"innaffia"?

Lo scenario
-----------
Balcone a Milano (45.47 N, 9.19 E, 160 m), settimana 14–20 settembre
2026, dati orari ERA5 scaricati da Open-Meteo (archive-api, timezone
UTC, poi riportati in ora solare CET = UTC+1, che è l'"ora standard"
richiesta dalle formule orarie di FAO-56). I dati sono incorporati nel
file, così l'esempio gira senza rete ed è riproducibile: per ogni ora
[h, h+1) la temperatura, l'umidità relativa e il vento a 10 m sono la
media dei due istantanei agli estremi, la radiazione è la media
dell'ora (Open-Meteo la etichetta alla fine dell'ora).

Nel vaso: un basilico (fixture `BASIL`, Kc mid 1.05, p 0.40) piantato
il 20 luglio, quindi in stadio mid per tutta la settimana; terriccio
universale (fixture, θ_FC 0.40, θ_PWP 0.15); vaso di plastica da 5 L,
diametro 20 cm, colore medio, pieno sole — cioè Kp = 1, perché la
differenza fra i metodi deve stare tutta nell'ET₀. Sta sotto il
balcone di sopra (niente pioggia) e parte a capacità di campo: è stato
innaffiato la sera del 13. Nessuna irrigazione durante la settimana:
vogliamo vedere quando ogni metodo fa scattare l'allerta.

I sei metodi a confronto
------------------------
  HS          Hargreaves-Samani (FAO-56 eq. 52): T_max, T_min e R_a.
  PM 24h FAO  Penman-Monteith giornaliera come la scrive FAO-56 (eq. 6):
              T_mean = media degli estremi (eq. 9), e_s dalla media di
              e°(T_max) ed e°(T_min) (eq. 12), e_a da RH_max/RH_min
              (eq. 17), R_nl con gli estremi (eq. 39), G = 0 (eq. 42).
  PM 24h fito Penman-Monteith giornaliera come la calcola fitosim nel
              cammino giornaliero (`compute_et0_penman_monteith` +
              `net_radiation`, la catena di `Pot.apply_balance_step_from_weather`):
              e_s = e°(T_mean), e_a = RH_mean · e°(T_mean).
  PM 6h/4h/1h Penman-Monteith a blocchi, con le funzioni della libreria
              (`domain.blocks.et0_for_blocks`): la eq. 53 di FAO-56 a
              passo generico (`compute_et0_penman_monteith(..., hours)`),
              R_a del blocco (eq. 28–33), R_n del blocco (cap. 4), G di
              giorno e di notte (eq. 45–46), il rapporto notturno
              R_s/R_so dalle 2–3 ore prima del tramonto, i blocchi
              negativi azzerati. L'ET₀ del giorno è la somma dei blocchi.
              Le decisioni, con le ragioni, sono in `domain/blocks.py`.

Le due parti
------------
La prima parte confronta le ET₀ e fa girare il vaso *a giorni* con
ciascuna: la risoluzione entra solo nell'ET₀. La seconda fa girare il
vaso *a blocchi* (`Pot.apply_blocks_from_weather`, un'ora alla volta)
e mostra le due cose che il passo giornaliero non può dire: l'ora
dell'allerta, e quanto drena un litro dato alle 8 o alle 20.

I grafici
---------
Se matplotlib è installato (`pip install -e '.[dev]'`, il core di
fitosim resta stdlib) l'esempio salva quattro PNG nella cartella
`FITOSIM_DEMO_OUTPUT_DIR` — o in `examples/`, dove git li ignora —:

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
from fitosim.domain.species import BASIL
from fitosim.domain.weather import WeatherBlock, weather_day_from_blocks
from fitosim.science.et0 import (
    actual_vapor_pressure,
    atmospheric_pressure,
    compute_et0_penman_monteith,
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
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL

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
#  La settimana: per ogni ora [h, h+1) in ora solare (CET),
#  (T °C, RH %, vento a 10 m in m/s, radiazione globale media in W/m²).
#  ERA5 via Open-Meteo:
#    https://archive-api.open-meteo.com/v1/archive?latitude=45.47
#      &longitude=9.19&start_date=2026-09-13&end_date=2026-09-20
#      &hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,
#      shortwave_radiation&timezone=UTC&wind_speed_unit=ms
# ---------------------------------------------------------------------

METEO: dict[str, list[tuple[float, float, float, float]]] = {
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

GIORNI = [date.fromisoformat(g) for g in METEO]
PASSI_SUB_GIORNALIERI = (6, 4, 1)
METODI = ("HS", "PM 24h FAO", "PM 24h fito", "PM 6h", "PM 4h", "PM 1h")
GIORNO_EVENTO = GIORNI[3]           # il 17/09: un litro alle 8 o alle 20
ORE_EVENTO = (8, 20)


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
    """La catena di `Pot.apply_balance_step_from_weather`, senza vaso."""
    t_max, t_min, _, _, u2, rs = estremi_del_giorno(giorno)
    t_mean = (t_max + t_min) / 2.0
    rh_mean = sum(o[1] for o in METEO[giorno.isoformat()]) / 24 / 100.0
    ra = extraterrestrial_radiation(LATITUDINE, day_of_year(giorno))
    ea = actual_vapor_pressure(t_mean, rh_mean)
    rn = net_radiation(rs, ra, t_max, t_min, ea, QUOTA_M)
    return compute_et0_penman_monteith(
        temperature_c=t_mean, humidity_relative=rh_mean, wind_speed_m_s=u2,
        net_radiation_mj_m2_day=rn, elevation_m=QUOTA_M,
    )


def serie_sub_giornaliera(passo_h: int):
    """
    ET₀ giornaliera come somma dei blocchi di `passo_h` ore, per tutta la
    settimana, con `et0_for_blocks` della libreria (standard: niente
    parametri di specie) e il rapporto R_s/R_so pre-tramonto passato da
    un giorno all'altro. Ritorna (somme, negativi azzerati, dettaglio).
    """
    somme, negativi, dettagli = {}, {}, {}
    rapporto_notte = None
    for giorno in GIORNI:
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
    """Lo stesso vaso, nuovo, per ogni metodo: parte a capacità di campo."""
    return Pot(
        label="Basilico del balcone",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0,
        pot_diameter_cm=20.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 7, 20),
        rainfall_exposure=0.0,      # sotto il balcone di sopra
        latitude_deg=LATITUDINE,
        elevation_m=QUOTA_M,
    )


def settimana_a_blocchi(fertigazione: BlockFertigation | None = None, fino_a: int = 7):
    """
    La settimana un'ora alla volta con `apply_blocks_from_weather`, il
    rapporto pre-tramonto passato da un giorno all'altro; l'eventuale
    irrigazione il giorno dell'evento. Ritorna il vaso e gli esiti per
    giorno.
    """
    vaso = nuovo_vaso()
    esiti = []
    rapporto_notte = None
    for giorno in GIORNI[:fino_a]:
        eventi = (
            [fertigazione] if fertigazione is not None and giorno == GIORNO_EVENTO else []
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
#  Stampa
# ---------------------------------------------------------------------

SETTIMANA = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


def stampa_sezione(titolo: str) -> None:
    print()
    print("=" * 78)
    print(f"  {titolo}")
    print("=" * 78)


def etichetta(giorno: date) -> str:
    return f"{giorno:%d/%m} {SETTIMANA[giorno.weekday()]}"


def colonna(valore: float | None, larghezza: int = 8) -> str:
    """Un numero a tre decimali, o spazi se il blocco non inizia qui."""
    return f"{valore:>{larghezza}.3f}" if valore is not None else " " * larghezza


def ora(h: float) -> str:
    return f"{int(h):02d}:{round((h % 1) * 60):02d}"


def main() -> None:
    # La console di Windows parte in cp1252 e non sa stampare θ e ₀.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # --- 1. ET₀ con i sei metodi ------------------------------------
    et0: dict[str, dict[date, float]] = {m: {} for m in METODI}
    negativi: dict[str, dict[date, float]] = {}
    dettagli: dict[int, dict] = {}
    for giorno in GIORNI:
        t_max, t_min, *_ = estremi_del_giorno(giorno)
        j = day_of_year(giorno)
        et0["HS"][giorno] = et0_hargreaves_samani(t_min, t_max, LATITUDINE, j)
        et0["PM 24h FAO"][giorno] = et0_pm_giornaliera_fao56(giorno)
        et0["PM 24h fito"][giorno] = et0_pm_giornaliera_fitosim(giorno)
    for passo in PASSI_SUB_GIORNALIERI:
        nome = f"PM {passo}h"
        et0[nome], negativi[nome], dettagli[passo] = serie_sub_giornaliera(passo)

    # --- 2. Il vaso a giorni, un esemplare per metodo -----------------
    stato: dict[str, list[float]] = {}
    allerta: dict[str, tuple[date, float] | None] = {}   # giorno, mm sotto soglia
    vaso_base = nuovo_vaso()
    for metodo in METODI:
        vaso = nuovo_vaso()
        stato[metodo] = []
        allerta[metodo] = None
        for giorno in GIORNI:
            t_max, t_min, *_ = estremi_del_giorno(giorno)
            esito = vaso.apply_balance_step(
                et_0_mm=et0[metodo][giorno], water_input_mm=0.0,
                current_date=giorno, t_mean_c=(t_max + t_min) / 2.0,
            )
            stato[metodo].append(vaso.state_mm)
            if esito.under_alert and allerta[metodo] is None:
                allerta[metodo] = (giorno, esito.deficit)

    # --- 3. Intestazione ----------------------------------------------
    stampa_sezione("Lo scenario")
    j0 = day_of_year(GIORNI[0])
    ra_giorno = extraterrestrial_radiation(LATITUDINE, j0)
    ra_somma = sum(
        extraterrestrial_radiation_interval(
            LATITUDINE, LONGITUDINE_EST, j0, h, h + 1, FUSO_ORARIO,
        )
        for h in range(24)
    )
    alba, tramonto = sunrise_sunset_hours(LATITUDINE, LONGITUDINE_EST, j0, FUSO_ORARIO)
    print(f"Milano {LATITUDINE} N {LONGITUDINE_EST} E, {QUOTA_M:.0f} m; "
          f"settimana {GIORNI[0]:%d/%m} – {GIORNI[-1]:%d/%m/%Y}, ora solare CET.")
    print(f"Il {GIORNI[0]:%d/%m}: alba alle {ora(alba)}, tramonto alle {ora(tramonto)} CET; "
          f"R_a del giorno {ra_giorno:.2f} MJ/m² (eq. 21), "
          f"somma delle 24 ore {ra_somma:.2f} (eq. 28).")
    print()
    print(f"Vaso: {vaso_base.label} — {vaso_base.species.common_name}, "
          f"{vaso_base.substrate.name}, {vaso_base.pot_volume_l:.0f} L, "
          f"Ø {vaso_base.pot_diameter_cm:.0f} cm, "
          f"profondità {vaso_base.substrate_depth_mm:.0f} mm, Kp {vaso_base.kp:.2f}.")
    print(f"      FC {vaso_base.fc_mm:.1f} mm, allerta {vaso_base.alert_mm:.1f} mm "
          f"(p {vaso_base.species.depletion_fraction:.2f}), "
          f"PWP {vaso_base.pwp_mm:.1f} mm; "
          f"stadio {vaso_base.current_stage(GIORNI[0]).name}, "
          f"Kc·Kp·Ks·Kn a FC = {vaso_base.current_et_c(1.0, GIORNI[0]):.2f}.")

    # --- 4. Il meteo della settimana --------------------------------
    stampa_sezione("Il meteo, giorno per giorno")
    print(f"{'giorno':<10}{'T min':>7}{'T max':>7}{'RH med':>8}{'u2 med':>8}"
          f"{'Rs MJ':>8}{'Rs/Rso':>8}")
    for giorno in GIORNI:
        t_max, t_min, _, _, u2, rs = estremi_del_giorno(giorno)
        rh_med = sum(o[1] for o in METEO[giorno.isoformat()]) / 24
        rso = clear_sky_radiation(
            extraterrestrial_radiation(LATITUDINE, day_of_year(giorno)), QUOTA_M,
        )
        print(f"{etichetta(giorno):<10}{t_min:>7.1f}{t_max:>7.1f}{rh_med:>8.0f}"
              f"{u2:>8.2f}{rs:>8.2f}{rs / rso:>8.2f}")

    # --- 5. ET₀ per metodo --------------------------------------------
    stampa_sezione("ET₀ del giorno (mm) con i sei metodi")
    print(f"{'giorno':<10}" + "".join(f"{m:>13}" for m in METODI))
    for giorno in GIORNI:
        print(f"{etichetta(giorno):<10}"
              + "".join(f"{et0[m][giorno]:>13.2f}" for m in METODI))
    totali = {m: sum(et0[m].values()) for m in METODI}
    print("-" * 88)
    print(f"{'settimana':<10}" + "".join(f"{totali[m]:>13.2f}" for m in METODI))
    riferimento = totali["PM 1h"]
    print(f"{'vs PM 1h':<10}"
          + "".join(f"{100.0 * (totali[m] / riferimento - 1.0):>+12.1f}%" for m in METODI))
    print()
    print("Blocchi notturni negativi azzerati prima della somma (mm sulla settimana):")
    for passo in PASSI_SUB_GIORNALIERI:
        nome = f"PM {passo}h"
        print(f"  {nome:<8}{sum(negativi[nome].values()):>+7.2f}")

    # --- 6. Dentro un giorno ------------------------------------------
    giorno_max = max(
        GIORNI, key=lambda g: abs(et0["PM 24h FAO"][g] - et0["PM 1h"][g]),
    )
    stampa_sezione(
        f"Dentro il {etichetta(giorno_max)}: il giorno in cui la 24 h e la "
        f"somma delle ore divergono di più"
    )
    print(f"{'ora':<7}{'T':>6}{'RH':>5}{'u2':>6}{'Rs':>7}{'Ra':>7}{'Rn':>7}"
          f"{'G':>7}{'ET0 1h':>8}{'4h':>8}{'6h':>8}")
    print(f"{'CET':<7}{'°C':>6}{'%':>5}{'m/s':>6}{'MJ':>7}{'MJ':>7}{'MJ':>7}"
          f"{'MJ':>7}{'mm':>8}{'mm':>8}{'mm':>8}")
    per_inizio = {
        passo: {b.start_hour: p for b, p in dettagli[passo][giorno_max]}
        for passo in PASSI_SUB_GIORNALIERI
    }
    for b, p in dettagli[1][giorno_max]:
        col4 = per_inizio[4].get(b.start_hour)
        col6 = per_inizio[6].get(b.start_hour)
        print(f"{b.start_hour:02d}-{b.end_hour:02d}{'' if p.daytime else '*':<2}"
              f"{b.t_c:>6.1f}{b.humidity_relative * 100:>5.0f}{b.wind_speed_m_s:>6.2f}"
              f"{b.solar_radiation_mj_m2:>7.2f}"
              f"{p.ra_mj:>7.2f}{p.rn_mj:>7.2f}{p.g_mj:>7.2f}{p.et_raw_mm:>8.3f}"
              + colonna(col4.et_raw_mm if col4 else None)
              + colonna(col6.et_raw_mm if col6 else None))
    passi_1h = [p for _, p in dettagli[1][giorno_max]]
    print(f"{'somma':<7}{'':>6}{'':>5}{'':>6}"
          f"{sum(b.solar_radiation_mj_m2 for b, _ in dettagli[1][giorno_max]):>7.2f}"
          f"{sum(p.ra_mj for p in passi_1h):>7.2f}"
          f"{sum(p.rn_mj for p in passi_1h):>7.2f}"
          f"{sum(p.g_mj for p in passi_1h):>7.2f}"
          f"{sum(p.et_raw_mm for p in passi_1h):>8.3f}"
          f"{sum(p.et_raw_mm for _, p in dettagli[4][giorno_max]):>8.3f}"
          f"{sum(p.et_raw_mm for _, p in dettagli[6][giorno_max]):>8.3f}")
    print("* = blocco notturno (G = 0.5 R_n, R_s/R_so delle 2–3 ore prima del tramonto). "
          "Le somme qui tengono i negativi;")
    print(f"  azzerandoli: 1 h {et0['PM 1h'][giorno_max]:.2f}, "
          f"4 h {et0['PM 4h'][giorno_max]:.2f}, 6 h {et0['PM 6h'][giorno_max]:.2f}; "
          f"la 24 h FAO dà {et0['PM 24h FAO'][giorno_max]:.2f}, "
          f"HS {et0['HS'][giorno_max]:.2f}.")

    # --- 7. Il vaso a giorni --------------------------------------------
    stampa_sezione(
        f"Il vaso a giorni: acqua nel substrato a fine giornata (mm; FC {vaso_base.fc_mm:.1f}, "
        f"allerta {vaso_base.alert_mm:.1f})"
    )
    print(f"{'giorno':<10}" + "".join(f"{m:>13}" for m in METODI))
    for k, giorno in enumerate(GIORNI):
        print(f"{etichetta(giorno):<10}"
              + "".join(f"{stato[m][k]:>13.1f}" for m in METODI))
    print("-" * 88)
    print(f"{'ETc sett.':<10}"
          + "".join(f"{vaso_base.fc_mm - stato[m][-1]:>13.1f}" for m in METODI))
    print(f"{'allerta':<10}"
          + "".join(
              f"{(f'{a[0]:%d/%m} −{a[1]:.1f}' if (a := allerta[m]) else 'no'):>13}"
              for m in METODI
          ))
    print()
    print("L'allerta è il giorno in cui l'acqua scende sotto la soglia della specie "
          "(p × TAW sotto FC), cioè il giorno")
    print("in cui il modello dice di innaffiare; accanto, di quanti mm è sotto "
          "la soglia quella sera.")

    # --- 8. Il vaso a blocchi (A7) -------------------------------------
    stampa_sezione("Il vaso a blocchi: la stessa settimana un'ora alla volta "
                   "(Pot.apply_blocks_from_weather)")
    print("Il basilico ha resistenza stomatica e altezza: la libreria usa Penman-Monteith "
          "fisico per blocco e lo")
    print("riporta a ET₀ equivalente, come fa il cammino giornaliero "
          "(apply_balance_step_from_weather) con cui è confrontato.")
    print()
    giornaliero = nuovo_vaso()
    stati_giornaliero: list[float] = []
    etc_giornaliero: list[float] = []
    for giorno in GIORNI:
        prima = giornaliero.state_mm
        giornaliero.apply_step_from_weather(
            weather_day_from_blocks(blocchi_del_giorno(giorno, 1)), current_date=giorno,
        )
        stati_giornaliero.append(giornaliero.state_mm)
        etc_giornaliero.append(prima - giornaliero.state_mm)
    _, esiti_blocchi = settimana_a_blocchi()

    print(f"{'giorno':<10}{'ETc 24h':>9}{'ETc 1h':>9}{'vaso 24h':>10}{'vaso 1h':>9}"
          f"{'allerta 24h':>13}{'allerta 1h':>12}  metodo")
    for k, giorno in enumerate(GIORNI):
        esito_b = esiti_blocchi[k]
        ora_allerta = esito_b.blocks_result.alert_hour
        allerta_b = (
            "no" if ora_allerta is None
            else "già sotto" if ora_allerta == 0
            else f"dalle {ora_allerta:02d}:00"
        )
        allerta_g = "sì" if stati_giornaliero[k] < vaso_base.alert_mm else "no"
        print(f"{etichetta(giorno):<10}{etc_giornaliero[k]:>9.2f}"
              f"{esito_b.blocks_result.et_c_mm:>9.2f}"
              f"{stati_giornaliero[k]:>10.1f}"
              f"{esito_b.blocks_result.balance_result.new_state:>9.1f}"
              f"{allerta_g:>13}{allerta_b:>12}  {esito_b.et_method.value}")
    print()
    print("Sopra la soglia i due cammini coincidono (stesso Kc, stessa ET₀ del giorno); "
          "sotto, i blocchi valutano Ks")
    print("ora per ora e consumano un po' meno — e dicono a che ora la soglia è stata "
          "passata.")

    # Gli eventi alla loro ora: un litro il 17, alle 8 o alle 20.
    print()
    print(f"Un litro il {GIORNO_EVENTO:%d/%m} (deficit "
          f"{vaso_base.fc_mm - esiti_blocchi[2].blocks_result.balance_result.new_state:.1f} mm "
          f"quella mattina): a che ora lo dai conta.")
    eventi: dict[int, tuple[float, object, float]] = {}
    for ora_evento in ORE_EVENTO:
        vaso, esiti = settimana_a_blocchi(
            BlockFertigation(start_hour=ora_evento, volume_l=1.0, ec_mscm=0.5, ph=7.5),
            fino_a=4,
        )
        drenato = esiti[-1].fertigation_results[0].water_drained_mm
        eventi[ora_evento] = (
            esiti[-2].blocks_result.balance_result.new_state, esiti[-1].blocks_result, drenato,
        )
        print(f"  alle {ora_evento:02d}:00  drena {drenato:5.2f} mm, "
              f"la sera il vaso ha {vaso.state_mm:5.1f} mm")
    print("La sera il vaso è più asciutto: lo stesso litro drena meno e resta nel substrato.")

    # --- 9. I grafici -----------------------------------------------------
    dati = SimpleNamespace(
        et0=et0, totali=totali, stato=stato, giorno_max=giorno_max, dettagli=dettagli,
        fc_mm=vaso_base.fc_mm, alert_mm=vaso_base.alert_mm,
        stati_giornaliero=stati_giornaliero, esiti_blocchi=esiti_blocchi, eventi=eventi,
    )
    disegna_grafici(dati)


# ---------------------------------------------------------------------
#  I grafici
# ---------------------------------------------------------------------

COLORI = {
    "HS": "#8c8c8c", "PM 24h FAO": "#1f4e79", "PM 24h fito": "#6fa8dc",
    "PM 6h": "#b5651d", "PM 4h": "#e69f00", "PM 1h": "#2e8b57",
}


def disegna_grafici(d: SimpleNamespace) -> None:
    """
    Quattro PNG in `FITOSIM_DEMO_OUTPUT_DIR` (o in `examples/`). Senza
    matplotlib lo dice e non fa altro: il core di fitosim è stdlib.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        stampa_sezione("I grafici")
        print("matplotlib non è installato: niente grafici. "
              "`pip install -e '.[dev]'` per averli.")
        return

    cartella = Path(os.environ.get("FITOSIM_DEMO_OUTPUT_DIR") or Path(__file__).parent)
    cartella.mkdir(parents=True, exist_ok=True)
    salvati = []

    def salva(fig, nome: str) -> None:
        percorso = cartella / nome
        fig.tight_layout()
        fig.savefig(percorso, dpi=130)
        plt.close(fig)
        salvati.append(percorso)

    giorni_lbl = [etichetta(g) for g in GIORNI]
    n = len(GIORNI)

    # 1. L'ET₀ del giorno con i sei metodi: barre raggruppate, il totale in legenda.
    fig, ax = plt.subplots(figsize=(11, 5.2))
    larghezza = 0.13
    for i, m in enumerate(METODI):
        ax.bar(
            [k + (i - (len(METODI) - 1) / 2) * larghezza for k in range(n)],
            [d.et0[m][g] for g in GIORNI], larghezza, color=COLORI[m],
            label=f"{m}  ({d.totali[m]:.1f} mm/settimana)",
        )
    ax.set_xticks(range(n))
    ax.set_xticklabels(giorni_lbl)
    ax.set_ylabel("ET₀ (mm/giorno)")
    ax.set_title("ET₀ del giorno con i sei metodi — Milano, 14–20 settembre 2026 (ERA5)")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(ncol=3, fontsize=9, loc="upper right")
    salva(fig, "confronto_et0_metodi.png")

    # 2. Dentro il giorno: l'ora per ora, i blocchi di 4 e 6 ore come tassi, la
    #    giornaliera FAO spalmata sulle 24 ore, la notte in grigio.
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ore_1h = d.dettagli[1][d.giorno_max]
    for b, p in ore_1h:
        if not p.daytime:
            ax.axvspan(b.start_hour, b.end_hour, color="grey", alpha=0.10, lw=0)
    ax.bar(
        [b.start_hour + 0.5 for b, _ in ore_1h], [p.et_raw_mm for _, p in ore_1h],
        width=0.9, color=COLORI["PM 1h"], alpha=0.85,
        label="PM 1 h: il blocco com'è (negativo di notte)",
    )
    for passo in (4, 6):
        xs, ys = [], []
        for b, p in d.dettagli[passo][d.giorno_max]:
            xs += [b.start_hour, b.end_hour]
            ys += [p.et_raw_mm / b.hours] * 2
        ax.plot(xs, ys, color=COLORI[f"PM {passo}h"], lw=2.2,
                label=f"PM {passo} h: mm/h medi del blocco")
    ax.axhline(d.et0["PM 24h FAO"][d.giorno_max] / 24.0, color=COLORI["PM 24h FAO"],
               ls="--", lw=1.5, label="PM 24 h FAO, spalmata sulle 24 ore")
    ax.axhline(0.0, color="k", lw=0.6)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.set_xlabel("ora solare (CET)")
    ax.set_ylabel("mm/h")
    ax.set_title(
        f"Dentro il {etichetta(d.giorno_max)}: 1 h {d.et0['PM 1h'][d.giorno_max]:.2f} mm, "
        f"4 h {d.et0['PM 4h'][d.giorno_max]:.2f}, 6 h {d.et0['PM 6h'][d.giorno_max]:.2f}, "
        f"24 h FAO {d.et0['PM 24h FAO'][d.giorno_max]:.2f} (i blocchi negativi valgono zero nelle somme)"
    )
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=9, loc="upper left")
    salva(fig, "confronto_et0_dentro_il_giorno.png")

    # 3. Il vaso a giorni: lo stesso vaso con le sei ET₀.
    fig, ax = plt.subplots(figsize=(11, 5.2))
    xs = list(range(n + 1))
    for m in METODI:
        ax.plot(xs, [d.fc_mm] + d.stato[m], marker="o", ms=4, color=COLORI[m], label=m)
    ax.axhline(d.fc_mm, color="k", ls=":", lw=1, label=f"capacità di campo {d.fc_mm:.1f} mm")
    ax.axhline(d.alert_mm, color="#c0392b", ls="--", lw=1.5,
               label=f"soglia della specie (p 0.40) {d.alert_mm:.1f} mm")
    ax.set_xticks(xs)
    ax.set_xticklabels(["13/09 sera"] + giorni_lbl)
    ax.set_ylabel("acqua nel substrato (mm)")
    ax.set_title("Il vaso a giorni: basilico, 5 L, con le sei ET₀ — l'allerta scatta il 19 per tutti")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9, ncol=2)
    salva(fig, "confronto_et0_vaso_a_giorni.png")

    # 4. Il vaso a blocchi: la settimana un'ora alla volta, e il litro alle 8 o alle 20.
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.2), gridspec_kw={"width_ratios": [2, 1]})
    xs_h, ys_h = [0.0], [d.fc_mm]
    ora_allerta = None
    for k, esito in enumerate(d.esiti_blocchi):
        for t in esito.blocks_result.blocks:
            xs_h.append(k * 24 + t.end_hour)
            ys_h.append(t.state_after_mm)
        if ora_allerta is None and esito.blocks_result.alert_hour:
            ora_allerta = k * 24 + esito.blocks_result.alert_hour
    ax1.plot(xs_h, ys_h, color=COLORI["PM 1h"], lw=1.8, label="a blocchi di un'ora")
    ax1.plot([0] + [24 * (k + 1) for k in range(n)], [d.fc_mm] + d.stati_giornaliero,
             marker="o", ms=5, ls="--", color=COLORI["PM 24h FAO"], label="a giorni (fine giornata)")
    ax1.axhline(d.alert_mm, color="#c0392b", ls="--", lw=1.5, label="soglia della specie")
    if ora_allerta is not None:
        ax1.axvline(ora_allerta, color="#c0392b", lw=1, alpha=0.7)
        ax1.annotate(
            f"allerta: {GIORNI[ora_allerta // 24]:%d/%m} alle {ora_allerta % 24:02d}:00",
            xy=(ora_allerta, d.alert_mm), xytext=(ora_allerta - 78, d.alert_mm - 4.5),
            fontsize=9, color="#c0392b",
            arrowprops={"arrowstyle": "->", "color": "#c0392b", "lw": 1},
        )
    ax1.set_xticks([24 * k for k in range(n + 1)])
    ax1.set_xticklabels(["13/09"] + [f"{g:%d/%m}" for g in GIORNI])
    ax1.set_ylabel("acqua nel substrato (mm)")
    ax1.set_title("La settimana un'ora alla volta (Penman-Monteith fisico, ET₀ equivalente)")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=9)

    for ora_evento, colore in zip(ORE_EVENTO, ("#e69f00", "#2e8b57")):
        inizio, blocchi_res, drenato = d.eventi[ora_evento]
        xs_e = [0] + [t.end_hour for t in blocchi_res.blocks]
        ys_e = [inizio] + [t.state_after_mm for t in blocchi_res.blocks]
        ax2.plot(xs_e, ys_e, color=colore, lw=2,
                 label=f"1 L alle {ora_evento:02d}:00 — drena {drenato:.1f} mm")
    ax2.axhline(d.fc_mm, color="k", ls=":", lw=1, label="capacità di campo")
    ax2.set_xlim(0, 24)
    ax2.set_xticks(range(0, 25, 4))
    ax2.set_xlabel("ora solare (CET)")
    ax2.set_title(f"Un litro il {GIORNO_EVENTO:%d/%m}: la sera il vaso è più asciutto")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=9, loc="lower right")
    salva(fig, "confronto_et0_vaso_a_blocchi.png")

    stampa_sezione("I grafici")
    for percorso in salvati:
        print(f"  {percorso}")


if __name__ == "__main__":
    main()
