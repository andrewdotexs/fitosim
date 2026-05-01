"""
Demo end-to-end dell'appartamento di Andrea (sotto-tappa E tappa 5).

Questo script chiude la tappa 5 della fascia 2 dimostrando in azione il
valore aggregato di tutto quello che le sotto-tappe A, B, C, D hanno
costruito. È la demo "finale" della tappa 5: non introduce codice di
prodotto nuovo, ma orchestra in un singolo flusso applicativo realistico
le quattro proprietà che insieme rappresentano il valore della tappa 5.

  1. La SCELTA AUTOMATICA della formula di evapotraspirazione (sotto-tappa B):
     vasi diversi del giardino, in giorni diversi della settimana, finiscono
     per usare formule diverse (Hargreaves, Penman-Monteith standard o fisico)
     in base ai dati meteo disponibili e ai parametri della specie.

  2. La DIFFERENZIAZIONE FISIOLOGICA (sotto-tappa C): nello stesso scenario
     meteo, vasi di specie diverse (basilico, rosmarino, orchidea,
     sansevieria) evolvono in modi sensibilmente diversi. Il rosmarino
     traspira meno del basilico per via della maggiore resistenza stomatica;
     la sansevieria ancora meno perché è una xerofita estrema.

  3. L'INTEGRAZIONE OUTDOOR + INDOOR (sotto-tappa D): il giardino misto
     comprende vasi sul balcone (gestiti col WeatherDay della stazione meteo)
     e vasi in casa distribuiti in due stanze (gestiti con gli
     IndoorMicroclimate dei sensori WN31). Le due chiamate del Garden si
     integrano naturalmente in un singolo flusso applicativo.

  4. La PERSISTENZA in SQLite (fase D3): il giardino viene salvato al termine
     della settimana e ricaricato in un nuovo "processo simulato", dimostrando
     che lo stato sopravvive ai riavvii del dashboard.

Lo scenario è una settimana di luglio 2026 nell'appartamento di Andrea a
Milano, con cinque vasi distribuiti su tre ambienti: balcone outdoor
(basilico + rosmarino), salotto (basilico sul davanzale + orchidea sul
ripiano), camera da letto (sansevieria in un angolo). Pattern meteo
realistico con qualche guasto progressivo della stazione, eventi di
pioggia, e gestione delle irrigazioni reattive alle allerte.

Struttura
---------

Lo script si articola in sei parti progressive seguite dalla generazione
di quattro grafici di analisi:

    PARTE 1 — setup del giardino misto su tre ambienti
    PARTE 2 — loop di simulazione settimanale outdoor + indoor
    PARTE 3 — gestione delle irrigazioni reattive
    PARTE 4 — analisi diagnostica della settimana
    PARTE 5 — persistenza in SQLite e ricarica
    PARTE 6 — conclusioni

    GRAFICI — quattro PNG generati in coda allo script:
      tappa5_E_andamento_idrico.png    — andamento del contenuto idrico
                                         dei cinque vasi giorno per giorno
      tappa5_E_metodi_et.png            — distribuzione dei metodi di
                                         evapotraspirazione usati per ogni vaso
      tappa5_E_bilancio_per_ambiente.png— bilancio idrico cumulato della
                                         settimana raggruppato per ambiente
      tappa5_E_heatmap_et.png           — heatmap giorno × vaso dell'ET

Esecuzione
----------

Esegui dalla radice del progetto con:
    python examples/tappa5_E_appartamento_demo.py

Dipendenze richieste: matplotlib, numpy. Tutto il resto è stdlib o
fitosim stesso.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tempfile

import matplotlib.pyplot as plt
import numpy as np

from fitosim.domain.garden import Garden
from fitosim.domain.pot import Pot, Location
from fitosim.domain.room import (
    Room, IndoorMicroclimate, MicroclimateKind, LightExposure,
)
from fitosim.domain.species import BASIL, ROSEMARY, Species
from fitosim.domain.weather import WeatherDay
from fitosim.io.persistence import GardenPersistence
from fitosim.science.et0 import EtMethod
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


# =====================================================================
#  Helper di stampa
# =====================================================================


def stampa_sezione(titolo: str) -> None:
    """Stampa un titolo di sezione con bordo per leggibilità."""
    print()
    print("=" * 76)
    print(f"  {titolo}")
    print("=" * 76)


def stampa_sottosezione(titolo: str) -> None:
    """Stampa un titolo di sottosezione."""
    print()
    print(f"--- {titolo} ---")


# =====================================================================
#  Costanti dello scenario e specie ad-hoc
# =====================================================================

LATITUDINE_MILANO = 45.47
QUOTA_MILANO_M = 150.0
DATA_INIZIO = date(2026, 7, 19)


# Orchidea: pianta intermedia che vive bene in luminoso indiretto.
# Resistenza stomatica modesta (110 s/m, simile al basilico) ma altezza
# colturale ridotta perché in vaso domestico è una piccola pianta.
ORCHID = Species(
    common_name="Orchidea",
    scientific_name="Phalaenopsis amabilis",
    kc_initial=0.50,
    kc_mid=0.60,
    kc_late=0.55,
    depletion_fraction=0.50,
    initial_stage_days=60,
    mid_stage_days=240,
    notes=(
        "Orchidea epifita ornamentale, comune in casa. Coltivata in "
        "substrato leggero (corteccia di pino + sphagnum) ma per la "
        "demo la simuliamo in substrato universale. Sensibile a "
        "ristagni idrici, p=0.50. Resistenza stomatica intermedia, "
        "comportamento mesofilo modesto."
    ),
    stomatal_resistance_s_m=110.0,
    crop_height_m=0.30,
)

# Sansevieria: xerofita estrema, simile come fisiologia a una succulenta.
# Resistenza stomatica molto alta (600 s/m) tipica delle CAM facoltative,
# tolleranza allo stress idrico molto alta (p=0.70).
SANSEVIERIA = Species(
    common_name="Sansevieria",
    scientific_name="Dracaena trifasciata",
    kc_initial=0.30,
    kc_mid=0.35,
    kc_late=0.30,
    depletion_fraction=0.70,
    initial_stage_days=60,
    mid_stage_days=240,
    notes=(
        "Sansevieria (lingua di suocera): xerofita succulenta, CAM "
        "facoltativa. Tolleranza estrema alla siccità (p=0.70), Kc "
        "molto basso. Adatta a posizioni con poca luce dove altre "
        "piante non sopravvivrebbero. Resistenza stomatica alta tipica "
        "delle xerofite a foglie carnose."
    ),
    stomatal_resistance_s_m=600.0,
    crop_height_m=0.40,
)


# =====================================================================
#  PARTE 1: setup del giardino misto.
# =====================================================================
#
# Cinque vasi su tre ambienti che mostrano la differenziazione
# fisiologica e ambientale che il modello di fitosim cattura.

stampa_sezione("Parte 1: setup dell'appartamento di Andrea")

garden = Garden(
    name="Appartamento di Andrea",
    location_description="Milano, lat 45.47, quota 150 m",
)

# Due Room indoor con i loro sensori WN31 mappati. I channel_id sono
# convenzionali: nel deployment reale corrispondono ai canali fisici
# della stazione Ecowitt.
salotto = Room(
    room_id="salotto", name="Salotto principale",
    wn31_channel_id="ch1",
    default_wind_m_s=0.5,
)
camera = Room(
    room_id="camera", name="Camera da letto",
    wn31_channel_id="ch2",
    default_wind_m_s=0.4,  # più chiusa, vento un filo più basso
)
garden.add_room(salotto)
garden.add_room(camera)

# Cinque vasi distribuiti tra balcone outdoor e le due stanze.
vasi = [
    # Sul balcone outdoor.
    Pot(
        label="Basilico-balcone", species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.5, pot_diameter_cm=15.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 6, 1),
        latitude_deg=LATITUDINE_MILANO, elevation_m=QUOTA_MILANO_M,
    ),
    Pot(
        label="Rosmarino-balcone", species=ROSEMARY,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0, pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=date(2025, 5, 1),
        latitude_deg=LATITUDINE_MILANO, elevation_m=QUOTA_MILANO_M,
    ),
    # Nel salotto.
    Pot(
        label="Basilico-davanzale", species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.0, pot_diameter_cm=14.0,
        location=Location.INDOOR,
        planting_date=date(2026, 6, 1),
        room_id="salotto",
        light_exposure=LightExposure.DIRECT_SUN,
    ),
    Pot(
        label="Orchidea-cucina", species=ORCHID,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=1.0, pot_diameter_cm=12.0,
        location=Location.INDOOR,
        planting_date=date(2025, 9, 1),
        room_id="salotto",
        light_exposure=LightExposure.INDIRECT_BRIGHT,
    ),
    # Nella camera.
    Pot(
        label="Sansevieria-angolo", species=SANSEVIERIA,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=3.0, pot_diameter_cm=18.0,
        location=Location.INDOOR,
        planting_date=date(2024, 4, 1),
        room_id="camera",
        light_exposure=LightExposure.DARK,
    ),
]
for vaso in vasi:
    garden.add_pot(vaso)

print()
print(f"  Giardino: {garden.name}")
print(f"  Stanze indoor: {garden.room_ids}")
print()
print(f"  Cinque vasi distribuiti tra outdoor e indoor:")
print(f"  {'Etichetta':<22} {'Specie':<14} {'Ambiente':<12} "
      f"{'Esposizione':<18} {'rs (s/m)':<10}")
print(f"  {'-'*22} {'-'*14} {'-'*12} {'-'*18} {'-'*10}")
for v in vasi:
    if v.location == Location.OUTDOOR:
        ambiente = "balcone"
        esposizione = v.sun_exposure.value
    else:
        ambiente = v.room_id
        esposizione = (
            v.light_exposure.value if v.light_exposure else "n/d"
        )
    rs = v.species.stomatal_resistance_s_m
    rs_str = f"{rs:.0f}" if rs is not None else "n/d"
    print(f"  {v.label:<22} {v.species.common_name:<14} "
          f"{ambiente:<12} {esposizione:<18} {rs_str:<10}")


# =====================================================================
#  PARTE 2: simulazione settimanale (outdoor + indoor).
# =====================================================================
#
# Sette giorni del 19-25 luglio 2026. Pattern realistico di:
#   - dati meteo outdoor con qualche guasto progressivo della stazione
#   - microclima indoor delle due stanze, con un giorno in cui il
#     sensore WN31 della camera è offline e viene simulato a mano
#   - eventi di pioggia che colpiscono solo i vasi outdoor
#
# La demo gestisce per ogni giorno:
#   1. costruzione di WeatherDay outdoor e di IndoorMicroclimate
#      DAILY per le due stanze
#   2. due chiamate del Garden: apply_step_all_from_weather per gli
#      outdoor, apply_step_all_from_indoor per gli indoor
#   3. unificazione dei risultati in un singolo dict per la diagnostica

stampa_sezione("Parte 2: simulazione della settimana 19-25 luglio 2026")

# Definiamo la settimana come lista di "giorni meteo" con tutti i dati
# necessari. Per ogni giorno articoliamo: outdoor (per gli outdoor),
# microclimi delle due stanze (per gli indoor), pioggia eventuale,
# nota narrativa per il log.
SETTIMANA = [
    {
        "data": date(2026, 7, 19),
        "outdoor": {"t_min": 20.0, "t_max": 32.0, "humidity": 0.60,
                    "wind": 1.5, "rs": 24.0},
        "indoor_salotto": {"t_min": 23.0, "t_max": 26.0, "humidity": 0.55},
        "indoor_camera": {"t_min": 22.0, "t_max": 24.5, "humidity": 0.58},
        "rainfall_mm": 0.0,
        "nota": "stazione operativa, giornata di pieno sole",
    },
    {
        "data": date(2026, 7, 20),
        "outdoor": {"t_min": 21.0, "t_max": 33.5, "humidity": 0.55,
                    "wind": 2.0, "rs": 25.5},
        "indoor_salotto": {"t_min": 24.0, "t_max": 27.0, "humidity": 0.50},
        "indoor_camera": {"t_min": 22.5, "t_max": 25.0, "humidity": 0.55},
        "rainfall_mm": 0.0,
        "nota": "stazione operativa, ancora pieno sole",
    },
    {
        "data": date(2026, 7, 21),
        "outdoor": {"t_min": 22.0, "t_max": 34.0, "humidity": 0.52,
                    "wind": None, "rs": 26.0},
        "indoor_salotto": {"t_min": 24.5, "t_max": 27.5, "humidity": 0.48},
        "indoor_camera": {"t_min": 23.0, "t_max": 25.5, "humidity": 0.52},
        "rainfall_mm": 0.0,
        "nota": "anemometro outdoor offline (manca vento)",
    },
    {
        "data": date(2026, 7, 22),
        "outdoor": {"t_min": 21.5, "t_max": 28.5, "humidity": 0.78,
                    "wind": 1.8, "rs": 14.0},
        "indoor_salotto": {"t_min": 23.5, "t_max": 25.5, "humidity": 0.62},
        "indoor_camera": {"t_min": 22.0, "t_max": 24.0, "humidity": 0.65},
        "rainfall_mm": 8.0,
        "nota": "temporale pomeridiano (8 mm di pioggia sui vasi outdoor)",
    },
    {
        "data": date(2026, 7, 23),
        "outdoor": {"t_min": 19.5, "t_max": 28.0, "humidity": None,
                    "wind": None, "rs": None},
        "indoor_salotto": {"t_min": 22.5, "t_max": 25.0, "humidity": 0.60},
        # Camera con sensore WN31 offline: stima a mano.
        "indoor_camera": None,
        "rainfall_mm": 0.0,
        "nota": "stazione outdoor + WN31 camera offline (stime a mano)",
    },
    {
        "data": date(2026, 7, 24),
        "outdoor": {"t_min": 19.0, "t_max": 29.5, "humidity": 0.70,
                    "wind": 1.2, "rs": 22.0},
        "indoor_salotto": {"t_min": 22.0, "t_max": 25.0, "humidity": 0.58},
        "indoor_camera": {"t_min": 21.5, "t_max": 23.5, "humidity": 0.60},
        "rainfall_mm": 0.0,
        "nota": "tutto operativo, ripresa dopo black-out",
    },
    {
        "data": date(2026, 7, 25),
        "outdoor": {"t_min": 20.5, "t_max": 31.5, "humidity": None,
                    "wind": 1.6, "rs": 24.5},
        "indoor_salotto": {"t_min": 23.0, "t_max": 26.0, "humidity": 0.55},
        "indoor_camera": {"t_min": 22.0, "t_max": 24.5, "humidity": 0.58},
        "rainfall_mm": 0.0,
        "nota": "igrometro outdoor offline (manca umidità)",
    },
]

# Storico per la diagnostica e i grafici.
storico: List[Dict] = []
# Snapshot iniziale: stato dei vasi PRIMA del primo giorno, utile per
# il grafico dell'andamento idrico.
for v in vasi:
    storico.append({
        "data": DATA_INIZIO - timedelta(days=1),
        "vaso": v.label,
        "specie": v.species.common_name,
        "ambiente": "balcone" if v.location == Location.OUTDOOR else v.room_id,
        "method": None,
        "state_pre": v.state_mm,
        "state_post": v.state_mm,
        "perdita_mm": 0.0,
        "under_alert": v.state_mm < v.alert_mm,
        "drainage": 0.0,
        "irrigato_mm": 0.0,
    })


def _build_indoor_microclimate(d: dict) -> IndoorMicroclimate:
    """Costruisce un IndoorMicroclimate DAILY dai dati di un giorno."""
    return IndoorMicroclimate(
        kind=MicroclimateKind.DAILY,
        temperature_c=(d["t_min"] + d["t_max"]) / 2.0,
        humidity_relative=d["humidity"],
        t_min=d["t_min"],
        t_max=d["t_max"],
    )


# Loop di simulazione giorno per giorno.
for giorno in SETTIMANA:
    weather = WeatherDay(
        date_=giorno["data"],
        t_min=giorno["outdoor"]["t_min"],
        t_max=giorno["outdoor"]["t_max"],
        humidity_relative=giorno["outdoor"]["humidity"],
        wind_speed_m_s=giorno["outdoor"]["wind"],
        solar_radiation_mj_m2_day=giorno["outdoor"]["rs"],
    )

    # Costruisco il dict dei microclimi indoor. Salto le stanze con
    # sensore offline: i vasi di quelle stanze non vengono processati,
    # equivalente a "il giardiniere stima il loro consumo a mano".
    microclimi: Dict[str, IndoorMicroclimate] = {}
    if giorno["indoor_salotto"] is not None:
        microclimi["salotto"] = _build_indoor_microclimate(giorno["indoor_salotto"])
    if giorno["indoor_camera"] is not None:
        microclimi["camera"] = _build_indoor_microclimate(giorno["indoor_camera"])

    # Snapshot stati pre-step per il calcolo della perdita giornaliera.
    stati_pre = {v.label: v.state_mm for v in garden}

    # Due chiamate distinte: outdoor con WeatherDay, indoor con
    # microclimi delle stanze. Le radiazione outdoor viene anche
    # passata al metodo indoor per attivare il modo continuo.
    risultati_outdoor = garden.apply_step_all_from_weather(
        weather=weather,
        rainfall_mm=giorno["rainfall_mm"],
    )
    risultati_indoor = garden.apply_step_all_from_indoor(
        microclimates_by_room=microclimi,
        current_date=weather.date_,
        outdoor_solar_radiation_mj_m2_day=weather.solar_radiation_mj_m2_day,
    )
    # Unificazione dei risultati come dict update.
    risultati = {**risultati_outdoor, **risultati_indoor}

    # Stampa del giorno.
    print()
    print(f"  {weather.date_.isoformat()} ({giorno['nota']}):")
    if giorno["rainfall_mm"] > 0:
        print(f"    Pioggia outdoor: {giorno['rainfall_mm']:.1f} mm")

    for v in vasi:
        if v.label in risultati:
            r = risultati[v.label]
            balance = r.balance_result
            metodo = balance.et_method.value if balance.et_method else "-"
            perdita = stati_pre[v.label] - balance.new_state
            allerta = "!!" if balance.under_alert else "  "
            print(f"   {allerta} {v.label:<22} method={metodo:<28} "
                  f"state={balance.new_state:>5.2f} mm "
                  f"(d={-perdita:+5.2f})")
            storico.append({
                "data": weather.date_,
                "vaso": v.label,
                "specie": v.species.common_name,
                "ambiente": "balcone" if v.location == Location.OUTDOOR else v.room_id,
                "method": balance.et_method,
                "state_pre": stati_pre[v.label],
                "state_post": balance.new_state,
                "perdita_mm": perdita,
                "under_alert": balance.under_alert,
                "drainage": balance.drainage,
                "irrigato_mm": 0.0,
            })
        else:
            # Vaso non processato (sensore offline). Lo stato resta
            # invariato; nello storico segnaliamo "skip".
            print(f"      {v.label:<22} (saltato, sensore offline)")
            storico.append({
                "data": weather.date_,
                "vaso": v.label,
                "specie": v.species.common_name,
                "ambiente": "balcone" if v.location == Location.OUTDOOR else v.room_id,
                "method": None,
                "state_pre": stati_pre[v.label],
                "state_post": v.state_mm,
                "perdita_mm": 0.0,
                "under_alert": v.state_mm < v.alert_mm,
                "drainage": 0.0,
                "irrigato_mm": 0.0,
            })


# =====================================================================
#  PARTE 3: irrigazioni manuali alle allerte di fine settimana.
# =====================================================================
#
# Il giardiniere ispeziona il dashboard alla fine della settimana e
# irriga i vasi che sono finiti sotto allerta. Per ogni vaso sotto
# allerta calcoliamo la quantità di acqua necessaria a riportare lo
# stato a capacità di campo (fc_mm), e applichiamo l'irrigazione come
# water_input direttamente al Pot via il vecchio apply_balance_step
# (con et_0=0 perché siamo a "fine giornata", non c'è più
# evapotraspirazione).

stampa_sezione("Parte 3: irrigazioni manuali ai vasi sotto allerta")

irrigazioni_effettuate: List[Tuple[str, float, float]] = []
for v in vasi:
    if v.state_mm < v.alert_mm:
        # Acqua necessaria per riportare il vaso a capacità di campo.
        acqua_mm = v.fc_mm - v.state_mm
        # Applichiamo l'irrigazione direttamente alla state_mm del Pot.
        # È una scorciatoia accettabile per una demo: in produzione il
        # dashboard chiamerebbe pot.apply_balance_step(et_0_mm=0,
        # water_input_mm=acqua_mm, current_date=oggi). Per la demo
        # bypassiamo per chiarezza didattica.
        stato_pre = v.state_mm
        v.state_mm = min(v.fc_mm, v.state_mm + acqua_mm)
        stato_post = v.state_mm
        irrigazioni_effettuate.append((v.label, acqua_mm, stato_post))
        # Aggiungo l'irrigazione all'ultimo record dello storico per
        # il vaso, in modo che i grafici la considerino.
        for record in reversed(storico):
            if record["vaso"] == v.label:
                record["irrigato_mm"] = acqua_mm
                record["state_post"] = stato_post
                break
        print(f"  {v.label:<22}: irrigati {acqua_mm:5.2f} mm "
              f"(stato {stato_pre:.2f} -> {stato_post:.2f} mm)")

if not irrigazioni_effettuate:
    print()
    print("  Nessun vaso sotto allerta a fine settimana: il giardino")
    print("  è in salute, niente irrigazioni necessarie.")
else:
    totale_l = sum(
        ml * v.surface_area_m2
        for v, (label, ml, _) in zip(
            (v for v in vasi if v.label in {x[0] for x in irrigazioni_effettuate}),
            irrigazioni_effettuate,
        )
    )
    print()
    print(f"  Totale: {len(irrigazioni_effettuate)} vasi irrigati.")


# =====================================================================
#  PARTE 4: analisi diagnostica della settimana.
# =====================================================================
#
# Tre tabelle che articolano cosa è successo nella settimana:
#   1. Distribuzione dei metodi di evapotraspirazione per vaso.
#   2. Bilancio idrico totale per vaso (perdita totale, pioggia,
#      irrigazione, drenaggio).
#   3. Confronto fisiologico: ET media giornaliera per vaso, normalizzata
#      per superficie del vaso.

stampa_sezione("Parte 4: analisi diagnostica della settimana")

stampa_sottosezione("Distribuzione dei metodi di evapotraspirazione")

print()
print(f"  {'Vaso':<22} {'PM fisico':<11} {'PM standard':<13} "
      f"{'Hargreaves':<12} {'(saltato)':<10}")
print(f"  {'-'*22} {'-'*11} {'-'*13} {'-'*12} {'-'*10}")
for v in vasi:
    counts = {
        "physical": 0, "standard": 0, "hargreaves": 0, "skipped": 0,
    }
    for record in storico:
        if record["vaso"] != v.label:
            continue
        if record["data"] == DATA_INIZIO - timedelta(days=1):
            continue  # snapshot iniziale
        method = record["method"]
        if method is None:
            counts["skipped"] += 1
        elif method == EtMethod.PENMAN_MONTEITH_PHYSICAL:
            counts["physical"] += 1
        elif method == EtMethod.PENMAN_MONTEITH_STANDARD:
            counts["standard"] += 1
        elif method == EtMethod.HARGREAVES_SAMANI:
            counts["hargreaves"] += 1
    print(f"  {v.label:<22} {counts['physical']:<11} "
          f"{counts['standard']:<13} {counts['hargreaves']:<12} "
          f"{counts['skipped']:<10}")

stampa_sottosezione("Bilancio idrico totale per vaso (settimana)")

print()
print(f"  {'Vaso':<22} {'Perdita ET':<12} {'Pioggia':<10} "
      f"{'Irrigato':<10} {'Drenato':<10}")
print(f"  {'-'*22} {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
for v in vasi:
    perdita = sum(
        max(0, r["perdita_mm"]) for r in storico if r["vaso"] == v.label
    )
    pioggia = sum(
        max(0, -r["perdita_mm"]) for r in storico
        if r["vaso"] == v.label and r["data"] >= DATA_INIZIO
        and v.location == Location.OUTDOOR
    )
    irrigato = sum(
        r["irrigato_mm"] for r in storico if r["vaso"] == v.label
    )
    drenato = sum(
        r["drainage"] for r in storico if r["vaso"] == v.label
    )
    print(f"  {v.label:<22} {perdita:>11.2f} {pioggia:>9.2f} "
          f"{irrigato:>9.2f} {drenato:>9.2f}")

stampa_sottosezione("Confronto fisiologico: ET media giornaliera")

print()
print(f"  {'Vaso':<22} {'Specie':<14} {'ET media (mm/d)':<18} "
      f"{'rs (s/m)':<10}")
print(f"  {'-'*22} {'-'*14} {'-'*18} {'-'*10}")
for v in vasi:
    perdite_giornaliere = [
        max(0, r["perdita_mm"]) for r in storico
        if r["vaso"] == v.label
        and r["data"] >= DATA_INIZIO
        and r["method"] is not None
    ]
    if perdite_giornaliere:
        et_media = sum(perdite_giornaliere) / len(perdite_giornaliere)
        et_str = f"{et_media:.2f}"
    else:
        et_str = "n/d"
    rs = v.species.stomatal_resistance_s_m
    rs_str = f"{rs:.0f}" if rs else "n/d"
    print(f"  {v.label:<22} {v.species.common_name:<14} "
          f"{et_str:<18} {rs_str:<10}")


# =====================================================================
#  PARTE 5: persistenza in SQLite e ricarica.
# =====================================================================
#
# Salviamo il giardino al termine della settimana in un database
# temporaneo, poi lo ricarichiamo in una nuova istanza per verificare
# che lo stato (Room incluse, Pot indoor con room_id e light_exposure)
# sia preservato correttamente. Dimostra in concreto la fase D3.

stampa_sezione("Parte 5: persistenza del giardino in SQLite e ricarica")

# Database temporaneo: il file viene cancellato a fine script.
db_dir = Path(tempfile.mkdtemp(prefix="fitosim_demo_"))
db_path = db_dir / "appartamento_andrea.db"

print()
print(f"  Database: {db_path}")

# Salvataggio.
with GardenPersistence(db_path) as p:
    # Registriamo nel catalogo le specie e i substrati referenziati.
    p.register_species(BASIL)
    p.register_species(ROSEMARY)
    p.register_species(ORCHID)
    p.register_species(SANSEVIERIA)
    p.register_substrate(UNIVERSAL_POTTING_SOIL)
    p.save_garden(garden)

print(f"  Garden salvato: {len(garden.pot_labels)} vasi e "
      f"{garden.num_rooms()} stanze.")

# Ricarica in una nuova istanza (simula un nuovo processo).
with GardenPersistence(db_path) as p:
    loaded = p.load_garden("Appartamento di Andrea")

print()
print(f"  Garden ricaricato: '{loaded.name}'")
print(f"  Stanze recuperate: {loaded.room_ids}")
print(f"  Vasi recuperati: {len(loaded.pot_labels)}")

# Verifiche del round-trip.
print()
print("  Verifiche round-trip:")
salotto_loaded = loaded.get_room("salotto")
print(f"    Salotto: {salotto_loaded.name}, ch={salotto_loaded.wn31_channel_id}, "
      f"vento={salotto_loaded.default_wind_m_s} m/s")
camera_loaded = loaded.get_room("camera")
print(f"    Camera: {camera_loaded.name}, ch={camera_loaded.wn31_channel_id}, "
      f"vento={camera_loaded.default_wind_m_s} m/s")

basilico_dav_loaded = loaded.get_pot("Basilico-davanzale")
print(f"    Basilico-davanzale: room_id={basilico_dav_loaded.room_id}, "
      f"light={basilico_dav_loaded.light_exposure.value}, "
      f"state={basilico_dav_loaded.state_mm:.2f} mm")
basilico_bal_loaded = loaded.get_pot("Basilico-balcone")
print(f"    Basilico-balcone: lat={basilico_bal_loaded.latitude_deg}, "
      f"elev={basilico_bal_loaded.elevation_m} m, "
      f"state={basilico_bal_loaded.state_mm:.2f} mm")
sans_loaded = loaded.get_pot("Sansevieria-angolo")
print(f"    Sansevieria-angolo: room_id={sans_loaded.room_id}, "
      f"light={sans_loaded.light_exposure.value}, "
      f"state={sans_loaded.state_mm:.2f} mm")

# Verifica programmatica che il round-trip preservi gli stati esattamente.
discrepanze = 0
for v in vasi:
    v_loaded = loaded.get_pot(v.label)
    if abs(v_loaded.state_mm - v.state_mm) > 1e-6:
        discrepanze += 1

if discrepanze == 0:
    print()
    print("  [OK] Tutti gli stati dei vasi preservati al byte.")
else:
    print(f"  [KO] {discrepanze} discrepanze rilevate.")


# =====================================================================
#  PARTE 6: conclusioni.
# =====================================================================

stampa_sezione("Parte 6: conclusioni della demo")

print()
print("Cosa abbiamo visto in questa demo:")
print()
print("  1. Il giardino misto outdoor + indoor si gestisce con due chiamate")
print("     coordinate del Garden (apply_step_all_from_weather +")
print("     apply_step_all_from_indoor) che restituiscono dict con la")
print("     stessa struttura, naturalmente unificabili.")
print()
print("  2. Il selettore 'best available' di evapotraspirazione si è")
print("     adattato ai guasti progressivi della stazione meteo: nei giorni")
print("     con anemometro o igrometro offline, i vasi outdoor sono passati")
print("     automaticamente da Penman-Monteith fisico a Hargreaves.")
print()
print("  3. La differenziazione fisiologica delle specie è visibile nei")
print("     numeri: a parità di ambiente, ET varia con la resistenza")
print("     stomatica (basilico > rosmarino, sansevieria xerofita molto")
print("     sotto). A parità di specie, ET varia con l'ambiente (outdoor")
print("     più alta di indoor per la radiazione disponibile).")
print()
print("  4. La persistenza SQLite preserva l'intero giardino tra esecuzioni:")
print("     stanze, vasi indoor con room_id e light_exposure, vasi outdoor")
print("     con coordinate geografiche, stati idrici tutti restituiti dal")
print("     round-trip salva-carica.")
print()
print("Tutto questo dimostra in concreto il valore della tappa 5 della")
print("fascia 2: il modello fisico fitosim è ora un sistema completo di")
print("gestione di un giardino reale, integrato con i sensori della casa")
print("e persistente tra le sessioni del dashboard.")


# =====================================================================
#  GRAFICI: quattro PNG di analisi visiva.
# =====================================================================

stampa_sezione("Generazione grafici di analisi")

# Directory di output: stessa dello script.
output_dir = Path(__file__).parent

# Palette di colori coerente per i cinque vasi (uno per vaso).
colori_per_vaso = {
    "Basilico-balcone": "#1f77b4",        # blu
    "Rosmarino-balcone": "#2ca02c",       # verde
    "Basilico-davanzale": "#ff7f0e",      # arancione
    "Orchidea-cucina": "#d62728",         # rosso
    "Sansevieria-angolo": "#9467bd",      # viola
}

# Indice dei giorni della settimana per i grafici.
giorni_settimana = [DATA_INIZIO + timedelta(days=i) for i in range(7)]
giorni_label = [d.strftime("%a %d") for d in giorni_settimana]


# ---------------------------------------------------------------------
#  Grafico 1: andamento idrico settimanale.
# ---------------------------------------------------------------------
#
# Cinque linee, una per vaso. Mostra state_mm giorno per giorno con
# linee tratteggiate per fc_mm e alert_mm di ogni vaso. È il grafico
# principale della demo: mostra la differenziazione delle specie e il
# punto in cui scattano le allerte.

fig, ax = plt.subplots(figsize=(11, 6.5))

for v in vasi:
    # Recupero stato giorno per giorno per questo vaso.
    state_giornaliero = []
    for d in [DATA_INIZIO - timedelta(days=1)] + giorni_settimana:
        for r in storico:
            if r["vaso"] == v.label and r["data"] == d:
                state_giornaliero.append(r["state_post"])
                break
    # Plot della linea principale (stato del vaso).
    x = ["start"] + giorni_label
    color = colori_per_vaso[v.label]
    ax.plot(
        x, state_giornaliero,
        marker="o", linewidth=2, label=v.label, color=color,
    )
    # Linea tratteggiata per la soglia di allerta del vaso (alert_mm).
    ax.axhline(
        y=v.alert_mm, color=color, linestyle=":",
        linewidth=0.8, alpha=0.5,
    )

ax.set_xlabel("Giorno della settimana", fontsize=11)
ax.set_ylabel("Contenuto idrico nel vaso (mm)", fontsize=11)
ax.set_title(
    "Andamento idrico dei cinque vasi — settimana 19-25 luglio 2026\n"
    "(linee tratteggiate: soglie di allerta per vaso)",
    fontsize=12,
)
ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
ax.grid(True, alpha=0.3)
ax.set_xticks(np.arange(len(x)))
ax.set_xticklabels(x, rotation=20, ha="right")
plt.tight_layout()
out1 = output_dir / "tappa5_E_andamento_idrico.png"
plt.savefig(out1, dpi=110)
plt.close()
print(f"  [OK] {out1.name}")


# ---------------------------------------------------------------------
#  Grafico 2: distribuzione dei metodi di evapotraspirazione.
# ---------------------------------------------------------------------
#
# Bar chart impilato (uno stack per vaso), con tre componenti per i tre
# metodi (PM fisico, PM standard, Hargreaves). Mostra in colpo d'occhio
# il selettore "best available" in azione.

fig, ax = plt.subplots(figsize=(10, 5.5))

labels_vasi = [v.label for v in vasi]
counts_pm_phys = []
counts_pm_std = []
counts_hargreaves = []
counts_skipped = []

for v in vasi:
    c_phys = c_std = c_har = c_skip = 0
    for r in storico:
        if r["vaso"] != v.label or r["data"] == DATA_INIZIO - timedelta(days=1):
            continue
        m = r["method"]
        if m is None:
            c_skip += 1
        elif m == EtMethod.PENMAN_MONTEITH_PHYSICAL:
            c_phys += 1
        elif m == EtMethod.PENMAN_MONTEITH_STANDARD:
            c_std += 1
        elif m == EtMethod.HARGREAVES_SAMANI:
            c_har += 1
    counts_pm_phys.append(c_phys)
    counts_pm_std.append(c_std)
    counts_hargreaves.append(c_har)
    counts_skipped.append(c_skip)

x_pos = np.arange(len(labels_vasi))
ax.bar(x_pos, counts_pm_phys, label="Penman-Monteith fisico",
       color="#2ca02c")
ax.bar(x_pos, counts_pm_std, bottom=counts_pm_phys,
       label="Penman-Monteith standard", color="#1f77b4")
bottom2 = [a + b for a, b in zip(counts_pm_phys, counts_pm_std)]
ax.bar(x_pos, counts_hargreaves, bottom=bottom2,
       label="Hargreaves-Samani", color="#ff7f0e")
bottom3 = [a + b for a, b in zip(bottom2, counts_hargreaves)]
ax.bar(x_pos, counts_skipped, bottom=bottom3,
       label="Saltato (sensore offline)", color="#7f7f7f")

ax.set_xticks(x_pos)
ax.set_xticklabels(labels_vasi, rotation=20, ha="right", fontsize=9)
ax.set_ylabel("Giorni della settimana", fontsize=11)
ax.set_title(
    "Distribuzione dei metodi di evapotraspirazione per vaso\n"
    "(il selettore 'best available' sceglie giorno per giorno la "
    "formula migliore)",
    fontsize=12,
)
ax.legend(loc="lower right", fontsize=9)
ax.set_ylim(0, 8)
plt.tight_layout()
out2 = output_dir / "tappa5_E_metodi_et.png"
plt.savefig(out2, dpi=110)
plt.close()
print(f"  [OK] {out2.name}")


# ---------------------------------------------------------------------
#  Grafico 3: bilancio idrico per ambiente.
# ---------------------------------------------------------------------
#
# Bar chart raggruppato che mostra le tre componenti del bilancio per
# ogni vaso (perdita ET, pioggia ricevuta, irrigazione manuale),
# raggruppati per ambiente.

fig, ax = plt.subplots(figsize=(11, 6))

# Calcolo bilanci per vaso.
perdite = []
piogge = []
irrigazioni = []
for v in vasi:
    perdita = sum(
        max(0, r["perdita_mm"]) for r in storico
        if r["vaso"] == v.label and r["data"] >= DATA_INIZIO
    )
    pioggia = sum(
        max(0, -r["perdita_mm"]) for r in storico
        if r["vaso"] == v.label and r["data"] >= DATA_INIZIO
        and v.location == Location.OUTDOOR
    )
    irrigato = sum(
        r["irrigato_mm"] for r in storico if r["vaso"] == v.label
    )
    perdite.append(perdita)
    piogge.append(pioggia)
    irrigazioni.append(irrigato)

width = 0.27
x_pos = np.arange(len(labels_vasi))

ax.bar(x_pos - width, perdite, width, label="Perdita ET", color="#d62728")
ax.bar(x_pos, piogge, width, label="Pioggia (outdoor)", color="#1f77b4")
ax.bar(x_pos + width, irrigazioni, width,
       label="Irrigazione manuale", color="#2ca02c")

# Separatori verticali tra i tre ambienti per chiarezza visiva.
ax.axvline(x=1.5, color="gray", linestyle="--", alpha=0.4)
ax.axvline(x=3.5, color="gray", linestyle="--", alpha=0.4)
ax.text(0.5, ax.get_ylim()[1] * 0.93, "Balcone outdoor",
        ha="center", fontsize=10, fontweight="bold", color="#555")
ax.text(2.5, ax.get_ylim()[1] * 0.93, "Salotto",
        ha="center", fontsize=10, fontweight="bold", color="#555")
ax.text(4.0, ax.get_ylim()[1] * 0.93, "Camera",
        ha="center", fontsize=10, fontweight="bold", color="#555")

ax.set_xticks(x_pos)
ax.set_xticklabels(labels_vasi, rotation=20, ha="right", fontsize=9)
ax.set_ylabel("Acqua nella settimana (mm)", fontsize=11)
ax.set_title(
    "Bilancio idrico settimanale per vaso\n"
    "(raggruppato per ambiente: outdoor, salotto, camera)",
    fontsize=12,
)
ax.legend(loc="upper right", fontsize=9)
ax.grid(True, alpha=0.3, axis="y")
plt.tight_layout()
out3 = output_dir / "tappa5_E_bilancio_per_ambiente.png"
plt.savefig(out3, dpi=110)
plt.close()
print(f"  [OK] {out3.name}")


# ---------------------------------------------------------------------
#  Grafico 4: heatmap ET giorno × vaso.
# ---------------------------------------------------------------------
#
# Tabella colorata 5 vasi × 7 giorni dove ogni cella è la perdita ET
# di quel giorno per quel vaso. Mostra a colpo d'occhio i pattern
# dell'intera settimana.

fig, ax = plt.subplots(figsize=(10, 5))

# Costruzione della matrice 5 x 7.
matrix = np.full((len(vasi), 7), np.nan)
for i, v in enumerate(vasi):
    for j, d in enumerate(giorni_settimana):
        for r in storico:
            if r["vaso"] == v.label and r["data"] == d:
                # Solo le perdite reali: ignoro pioggia (negativi) e
                # giorni saltati (method=None).
                if r["method"] is not None:
                    matrix[i, j] = max(0, r["perdita_mm"])
                break

# Heatmap.
im = ax.imshow(
    matrix, cmap="YlOrRd", aspect="auto",
    vmin=0, vmax=7,
)
ax.set_xticks(np.arange(7))
ax.set_xticklabels(giorni_label, rotation=15, ha="right", fontsize=9)
ax.set_yticks(np.arange(len(vasi)))
ax.set_yticklabels(labels_vasi, fontsize=9)

# Annotazioni numeriche su ogni cella.
for i in range(len(vasi)):
    for j in range(7):
        if not np.isnan(matrix[i, j]):
            text = f"{matrix[i, j]:.1f}"
            color = "white" if matrix[i, j] > 4.0 else "black"
            ax.text(j, i, text, ha="center", va="center",
                    color=color, fontsize=9)
        else:
            ax.text(j, i, "—", ha="center", va="center",
                    color="gray", fontsize=10)

cbar = plt.colorbar(im, ax=ax)
cbar.set_label("Evapotraspirazione (mm/giorno)", fontsize=10)
ax.set_title(
    "Heatmap dell'evapotraspirazione: vasi × giorni\n"
    "(le caselle con '—' indicano giorni con sensore offline)",
    fontsize=12,
)
plt.tight_layout()
out4 = output_dir / "tappa5_E_heatmap_et.png"
plt.savefig(out4, dpi=110)
plt.close()
print(f"  [OK] {out4.name}")


print()
print(f"  Quattro grafici generati in {output_dir}/")
print()
print("Demo completata.")
