"""
Demo end-to-end della tappa 4 della fascia 2 di fitosim.

Questa è una demo didattica che mostra in azione tutte le capacità
introdotte nelle cinque sotto-tappe della tappa 4, lavorando insieme
su uno scenario realistico del balcone milanese.

Cosa mostra
-----------

  * **Sotto-tappa A (Garden orchestratore)**: tre vasi gestiti come
    unità, evolvono insieme col meteo del giorno via apply_step_all.

  * **Sotto-tappa B fase 1 (persistenza SQLite)**: salvataggio dei
    snapshot giornalieri, query degli stati storici per produrre la
    "timeline" finale di un vaso.

  * **Sotto-tappa B fase 2 (serializzazione JSON)**: backup di
    metà periodo come formato di trasporto.

  * **Sotto-tappa C (integrazione sensori)**: fake sensor che
    simula i WH51, con errori transitori realistici al giorno 10
    (batteria scarica) per dimostrare la robustezza del sistema.

  * **Sotto-tappa D (eventi pianificati e forecast)**: piano di
    fertirrigazioni settimanali. A metà periodo (giorno 14) una
    previsione meteo a 7 giorni produce una proiezione dello stato.

  * **Sotto-tappa E (sistema di allerte)**: allerte correnti al
    giorno 14 e al giorno 21, e allerte previste nel forecast.

Lo scenario
-----------

Tre vasi di basilico sul balcone con esposizioni diverse:

  - "aperto"   : in pieno sole, esposto al 100% alla pioggia.
  - "ringhiera": sotto il balcone superiore, 50% di esposizione.
  - "albero"   : sotto la chioma di una pianta più grande, 20%.

I primi due hanno il sensore WH51 connesso (canali "1" e "2"). Il
terzo è "solo previsione" (giardino misto, lo cita la sotto-tappa C).

L'esecuzione è deterministica (random.Random(seed=42)), quindi
ottieni sempre la stessa simulazione.

Come eseguirlo
--------------

Dalla root del progetto fitosim::

    PYTHONPATH=src python examples/tappa4_complete_demo.py

Tempo di esecuzione: pochi secondi. Lascia un database SQLite
temporaneo in /tmp/ che viene cancellato alla fine.
"""

import os
import random
import tempfile
from datetime import date, datetime, timedelta, timezone
from typing import List

from fitosim.domain.alerts import AlertSeverity
from fitosim.domain.garden import Garden
from fitosim.domain.pot import Location, Pot
from fitosim.domain.scheduling import ScheduledEvent, WeatherDayForecast
from fitosim.domain.species import Species
from fitosim.io.persistence import GardenPersistence
from fitosim.io.sensors import (
    SensorTemporaryError,
    SoilReading,
)
from fitosim.io.serialization import export_garden_json
from fitosim.science.substrate import Substrate


# =======================================================================
#  Costanti di configurazione
# =======================================================================

RANDOM_SEED = 42
SIMULATION_DAYS = 21
START_DATE = date(2026, 5, 25)  # fine maggio per il basilico a Milano
GARDEN_NAME = "balcone-milano"


# =======================================================================
#  Fake sensor: simula i WH51 con letture realistiche e errori
#  transitori
# =======================================================================

class FakeWH51Sensor:
    """
    Fake sensor che simula i WH51 connessi al gateway Ecowitt.

    Ritorna letture di theta_volumetric basate su un valore "vero"
    interno + un piccolo rumore gaussiano (deviazione standard 0.01,
    realistico per il sensore reale).

    Su un canale specifico al giorno specificato simula una
    SensorTemporaryError per dimostrare la robustezza dell'orchestratore
    update_all_from_sensors.
    """

    def __init__(self, ground_truth_theta: dict, error_on_day: dict = None):
        # ground_truth_theta è un dict {channel_id: theta_corrente}
        # che viene aggiornato dal main loop.
        self._ground_truth = ground_truth_theta
        # error_on_day è {channel_id: day_index} per simulare gli errori
        # transitori a giorni specifici.
        self._error_on_day = error_on_day or {}
        self._current_day_index = 0
        self._rng = random.Random(RANDOM_SEED + 1000)
        self._current_timestamp = datetime(2026, 5, 25, tzinfo=timezone.utc)

    def set_day(self, day_index: int, timestamp: datetime) -> None:
        """Aggiorna lo stato corrente del fake sensor."""
        self._current_day_index = day_index
        self._current_timestamp = timestamp

    def current_state(self, channel_id: str) -> SoilReading:
        # Simulazione di errore transitorio.
        if self._error_on_day.get(channel_id) == self._current_day_index:
            raise SensorTemporaryError(
                f"WH51 canale {channel_id}: batteria scarica, lettura "
                f"non disponibile in questo ciclo."
            )

        if channel_id not in self._ground_truth:
            from fitosim.io.sensors import SensorPermanentError
            raise SensorPermanentError(
                f"Canale {channel_id} non configurato sul gateway."
            )

        # Lettura con piccolo rumore gaussiano.
        true_theta = self._ground_truth[channel_id]
        noise = self._rng.gauss(0.0, 0.01)
        observed_theta = max(0.0, true_theta + noise)

        return SoilReading(
            timestamp=self._current_timestamp,
            theta_volumetric=observed_theta,
        )


# =======================================================================
#  Generazione del meteo simulato
# =======================================================================

def make_weather_sequence(num_days: int) -> List[dict]:
    """
    Genera una sequenza meteo deterministica per il periodo.

    Pattern realistico per fine maggio - metà giugno a Milano:
      - ET₀ giornaliera oscillante tra 3.0 e 6.0 mm (giorni nuvolosi
        vs giorni di sole pieno).
      - Pioggia presente in ~25% dei giorni con intensità variabile.
    """
    rng = random.Random(RANDOM_SEED)
    weather = []
    for day_idx in range(num_days):
        # ET₀: variazione realistica con due picchi alti tipici di
        # giorni con sole pieno e vento.
        base_et = 4.5
        et_0_mm = base_et + rng.uniform(-1.5, 1.5)

        # Pioggia: 25% di probabilità, con intensità log-uniforme.
        rainfall_mm = 0.0
        if rng.random() < 0.25:
            rainfall_mm = rng.uniform(2.0, 18.0)

        weather.append({
            "et_0_mm": round(et_0_mm, 2),
            "rainfall_mm": round(rainfall_mm, 1),
        })
    return weather


# =======================================================================
#  Setup del catalogo e del giardino
# =======================================================================

def build_basil_species() -> Species:
    """Specie basilico con range chimici realistici."""
    return Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50,
        kc_mid=1.10,
        kc_late=0.85,
        ec_optimal_min_mscm=1.0,
        ec_optimal_max_mscm=1.6,
        ph_optimal_min=6.0,
        ph_optimal_max=7.0,
    )


def build_substrate() -> Substrate:
    """Terriccio universale con CEC moderata."""
    return Substrate(
        name="terriccio universale",
        theta_fc=0.40,
        theta_pwp=0.10,
        cec_meq_per_100g=50.0,
        ph_typical=6.8,
    )


def build_garden(species: Species, substrate: Substrate) -> Garden:
    """
    Costruisce il giardino con tre vasi di basilico a esposizioni
    diverse alla pioggia. I primi due sono mappati ai canali del WH51,
    il terzo è "solo previsione" (giardino misto).
    """
    garden = Garden(
        name=GARDEN_NAME,
        location_description=(
            "Balcone esposto a sud nella periferia di Milano, vasi "
            "con esposizioni diverse alla pioggia."
        ),
    )

    common = dict(
        species=species,
        substrate=substrate,
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 5, 1),
        # Stato iniziale realistico: ben idratato dopo l'invasamento,
        # EC al limite inferiore del range ottimale.
        state_mm=28.0,
        salt_mass_meq=8.5,
        ph_substrate=6.7,
    )

    garden.add_pot(Pot(label="aperto", rainfall_exposure=1.0, **common))
    garden.add_pot(Pot(label="ringhiera", rainfall_exposure=0.5, **common))
    garden.add_pot(Pot(label="albero", rainfall_exposure=0.2, **common))

    # Mappa dei sensori: solo i primi due hanno il WH51 collegato.
    garden.set_channel_id("aperto", "1")
    garden.set_channel_id("ringhiera", "2")
    # "albero" resta non mappato: continua solo in previsione.

    return garden


def schedule_weekly_fertigations(garden: Garden) -> None:
    """
    Pianifica fertirrigazioni settimanali per tutti i vasi.

    Pattern: ogni lunedì (giorni 7, 14, 21 della simulazione che parte
    da lunedì 25 maggio) con BioBizz Bio-Grow al dosaggio raccomandato.
    """
    fertigation_dates = [
        START_DATE + timedelta(days=i)
        for i in [6, 13, 20]  # giorni 7, 14, 21 (1-indexed)
    ]

    for pot_label in garden.pot_labels:
        for i, fert_date in enumerate(fertigation_dates):
            event = ScheduledEvent(
                event_id=f"fert-{pot_label}-week{i+1}",
                pot_label=pot_label,
                event_type="fertigation",
                scheduled_date=fert_date,
                payload={
                    "volume_l": 0.3,
                    "ec_mscm": 2.0,
                    "ph": 6.2,
                },
            )
            garden.add_scheduled_event(event)


# =======================================================================
#  Output formattato
# =======================================================================

def print_section_header(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def print_subsection(title: str) -> None:
    print()
    print(f"--- {title} ---")
    print()


def print_day_row(
    day_idx: int,
    current_date: date,
    weather: dict,
    garden: Garden,
    events_today: list,
    sensor_results: dict,
) -> None:
    """Riga compatta giornaliera con stato dei tre vasi."""
    et = weather["et_0_mm"]
    rain = weather["rainfall_mm"]
    rain_str = f"{rain:>4.1f}" if rain > 0 else "  — "

    # Marker degli eventi del giorno
    event_markers = []
    if events_today:
        event_markers.append(f"FERT×{len(events_today)}")
    if sensor_results:
        ok = sum(1 for r in sensor_results.values()
                 if not isinstance(r, Exception))
        err = sum(1 for r in sensor_results.values()
                  if isinstance(r, Exception))
        if ok > 0:
            event_markers.append(f"SENS×{ok}")
        if err > 0:
            event_markers.append(f"ERR×{err}")
    events_str = " ".join(event_markers) if event_markers else "—"

    # Stati compatti per i tre vasi
    states = []
    for label in ["aperto", "ringhiera", "albero"]:
        pot = garden.get_pot(label)
        states.append(
            f"{label[:4]}:θ{pot.state_theta:.2f}/EC{pot.ec_substrate_mscm:.1f}"
        )

    print(
        f"{day_idx+1:>3} {current_date.isoformat()} "
        f"ET{et:>4.1f} R{rain_str} | "
        f"{' · '.join(states)} | {events_str}"
    )


def print_alerts(alerts: list, max_show: int = 10) -> None:
    """Stampa le allerte con icone per severità."""
    if not alerts:
        print("  Nessuna allerta.")
        return
    icons = {
        AlertSeverity.INFO: "ℹ ",
        AlertSeverity.WARNING: "⚠ ",
        AlertSeverity.CRITICAL: "‼ ",
    }
    for alert in alerts[:max_show]:
        icon = icons.get(alert.severity, "  ")
        print(f"  {icon}[{alert.pot_label}] {alert.category.value} "
              f"({alert.severity.value})")
        # Messaggio su una riga indentata
        msg_short = alert.message[:90] + ("..." if len(alert.message) > 90 else "")
        print(f"      {msg_short}")
    if len(alerts) > max_show:
        print(f"  ... e altre {len(alerts) - max_show} allerte.")


# =======================================================================
#  Main demo
# =======================================================================

def main() -> None:
    print_section_header(
        "Demo end-to-end della tappa 4 fascia 2 di fitosim"
    )
    print(f"Giardino: '{GARDEN_NAME}'")
    print(f"Periodo: {SIMULATION_DAYS} giorni a partire dal "
          f"{START_DATE.isoformat()}")
    print(f"Seed deterministico: {RANDOM_SEED}")

    # =====================================================================
    # SETUP: catalogo, giardino, persistenza, fake sensor
    # =====================================================================

    print_section_header("Setup iniziale")

    # Costruzione di specie e substrato
    basil = build_basil_species()
    substrate = build_substrate()

    # Costruzione del giardino con i tre vasi e i mapping sensore
    garden = build_garden(basil, substrate)
    print(f"Giardino costruito con {len(garden)} vasi:")
    for label in garden.pot_labels:
        ch = garden.get_channel_id(label)
        ch_str = f"sensore canale {ch}" if ch else "solo previsione"
        pot = garden.get_pot(label)
        print(f"  - '{label}': rainfall_exposure={pot.rainfall_exposure}, "
              f"{ch_str}")

    # Persistenza SQLite su file temporaneo (cancellato alla fine).
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="fitosim_demo_")
    os.close(db_fd)
    print(f"\nDatabase temporaneo: {db_path}")

    persistence = GardenPersistence(db_path)
    persistence.register_species(basil)
    persistence.register_substrate(substrate)
    print("Catalogo registrato nel database.")

    # Pianificazione delle fertirrigazioni settimanali
    schedule_weekly_fertigations(garden)
    fertigations = garden.scheduled_events
    print(f"\nPianificate {len(fertigations)} fertirrigazioni:")
    for event in fertigations[:3]:
        print(f"  - {event.scheduled_date} {event.pot_label}: "
              f"BioBizz {event.payload['volume_l']} L EC "
              f"{event.payload['ec_mscm']} mS/cm")
    print(f"  ... e altre {len(fertigations) - 3} simili.")

    # Salvataggio iniziale del giardino
    persistence.save_garden(
        garden,
        snapshot_timestamp=datetime.combine(
            START_DATE, datetime.min.time(), tzinfo=timezone.utc,
        ),
    )

    # Fake sensor: simulerà letture coerenti con lo stato dei vasi
    # mappati. Su channel_id="1" al giorno 10 simula batteria scarica.
    ground_truth = {}
    fake_sensor = FakeWH51Sensor(
        ground_truth_theta=ground_truth,
        error_on_day={"1": 9},  # giorno 10 (0-indexed = 9)
    )

    # Generazione del meteo simulato per tutti i giorni
    weather_sequence = make_weather_sequence(SIMULATION_DAYS)

    # =====================================================================
    # GIORNI 1-7: prima settimana, loop completo
    # =====================================================================

    print_section_header(
        "Settimana 1 (giorni 1-7): setup e prima fertirrigazione"
    )
    print(
        "Loop giornaliero: per ogni giorno aggiorniamo i vasi mappati\n"
        "dalle letture del fake sensor, applichiamo gli eventi pianificati\n"
        "del giorno (apply_step_all gestisce ET e pioggia), e salviamo\n"
        "uno snapshot dello stato nel database SQLite."
    )
    print()
    print(f"{'Day':>3} {'Date':>10} {'  Met  ':>9} | "
          f"{'aperto · ringhiera · albero (θ/EC mS/cm)':<54} | Eventi")
    print("-" * 96)

    snapshot_ts_base = datetime.combine(
        START_DATE, datetime.min.time(), tzinfo=timezone.utc,
    )

    for day_idx in range(7):
        current_date = START_DATE + timedelta(days=day_idx)
        weather = weather_sequence[day_idx]
        timestamp = snapshot_ts_base + timedelta(days=day_idx + 1)

        # Aggiorna ground truth del fake sensor con lo stato corrente
        # dei vasi mappati.
        ground_truth["1"] = garden.get_pot("aperto").state_theta
        ground_truth["2"] = garden.get_pot("ringhiera").state_theta
        fake_sensor.set_day(day_idx, timestamp)

        # Prima leggiamo dal sensore (calibra i vasi mappati).
        sensor_results = garden.update_all_from_sensors(fake_sensor)

        # Applica gli eventi pianificati del giorno (fertirrigazioni).
        events_today = garden.events_due_today(current_date)
        for event in events_today:
            if event.event_type == "fertigation":
                pot = garden.get_pot(event.pot_label)
                pot.apply_fertigation_step(
                    volume_l=event.payload["volume_l"],
                    ec_mscm=event.payload["ec_mscm"],
                    ph=event.payload["ph"],
                    current_date=current_date,
                )

        # Step giornaliero: ET₀ e pioggia per tutti i vasi.
        garden.apply_step_all(
            et_0_mm=weather["et_0_mm"],
            current_date=current_date,
            rainfall_mm=weather["rainfall_mm"],
        )

        # Snapshot al database
        persistence.save_garden(garden, snapshot_timestamp=timestamp)

        print_day_row(
            day_idx, current_date, weather, garden,
            events_today, sensor_results,
        )

    # =====================================================================
    # SNAPSHOT INTERMEDIO (giorno 7): backup JSON e allerte
    # =====================================================================

    print_section_header("Snapshot intermedio (fine settimana 1)")

    # Export JSON come backup di trasporto
    json_str = export_garden_json(garden)
    print(f"Export JSON del giardino: {len(json_str)} caratteri "
          f"(~{len(json_str) // 1024} KB)")
    print(f"  Numero di vasi: {len(garden)}")
    print(f"  Catalogo incluso: 1 specie, 1 substrato")
    print(f"  Eventi pianificati: {len(garden.scheduled_events)}")
    print(
        "Il JSON è autocontenuto: chi lo riceve può ricostruire l'intero\n"
        "giardino con un singolo import_garden_json(), senza dipendenze."
    )

    # Allerte sullo stato corrente
    print_subsection("Allerte correnti dopo la prima settimana")
    alerts = garden.current_alerts(
        current_date=START_DATE + timedelta(days=6),
    )
    print_alerts(alerts)

    # =====================================================================
    # GIORNI 8-14: seconda settimana con errore sensore
    # =====================================================================

    print_section_header(
        "Settimana 2 (giorni 8-14): errore transitorio del sensore"
    )
    print(
        "Al giorno 10 il WH51 del canale 1 ('aperto') simula un errore\n"
        "transitorio (batteria scarica). Il sistema lo gestisce senza\n"
        "bloccare l'aggiornamento degli altri vasi: il vaso 'aperto'\n"
        "viene saltato per quel ciclo, e il giorno successivo riprende\n"
        "normalmente."
    )
    print()
    print(f"{'Day':>3} {'Date':>10} {'  Met  ':>9} | "
          f"{'aperto · ringhiera · albero (θ/EC mS/cm)':<54} | Eventi")
    print("-" * 96)

    for day_idx in range(7, 14):
        current_date = START_DATE + timedelta(days=day_idx)
        weather = weather_sequence[day_idx]
        timestamp = snapshot_ts_base + timedelta(days=day_idx + 1)

        ground_truth["1"] = garden.get_pot("aperto").state_theta
        ground_truth["2"] = garden.get_pot("ringhiera").state_theta
        fake_sensor.set_day(day_idx, timestamp)

        sensor_results = garden.update_all_from_sensors(fake_sensor)

        events_today = garden.events_due_today(current_date)
        for event in events_today:
            if event.event_type == "fertigation":
                pot = garden.get_pot(event.pot_label)
                pot.apply_fertigation_step(
                    volume_l=event.payload["volume_l"],
                    ec_mscm=event.payload["ec_mscm"],
                    ph=event.payload["ph"],
                    current_date=current_date,
                )

        garden.apply_step_all(
            et_0_mm=weather["et_0_mm"],
            current_date=current_date,
            rainfall_mm=weather["rainfall_mm"],
        )

        persistence.save_garden(garden, snapshot_timestamp=timestamp)

        print_day_row(
            day_idx, current_date, weather, garden,
            events_today, sensor_results,
        )

        # Per il giorno con errore, mostra dettagli sul sensore
        if day_idx == 9:
            print()
            print(
                "    >>> Giorno 10: il fake sensor ha simulato batteria "
                "scarica sul canale 1.\n"
                "        Il sistema ha catturato SensorTemporaryError per "
                "'aperto' e ha continuato\n"
                "        normalmente con il vaso 'ringhiera'. Il vaso "
                "'aperto' continua per\n"
                "        questo giorno solo con la previsione del modello, "
                "senza calibrazione\n"
                "        dal sensore. Il giorno successivo riprende con "
                "lettura regolare."
            )
            print()

    # =====================================================================
    # FORECAST a 7 giorni dal giorno 14
    # =====================================================================

    print_section_header(
        "Forecast: previsione a 7 giorni a partire da fine settimana 2"
    )
    print(
        "Il giardiniere virtuale produce una proiezione dello stato dei\n"
        "vasi nei prossimi 7 giorni dato un forecast meteo. Il forecast\n"
        "applica gli eventi pianificati (la fertirrigazione del giorno 21)\n"
        "e l'evapotraspirazione/pioggia di ogni giorno futuro, lavorando\n"
        "su deep copy dei vasi: lo stato del Garden corrente non viene\n"
        "modificato."
    )

    # Costruisci il forecast meteo a 7 giorni
    forecast_weather = [
        WeatherDayForecast(
            date_=START_DATE + timedelta(days=14 + i),
            et_0_mm=weather_sequence[14 + i]["et_0_mm"],
            rainfall_mm=weather_sequence[14 + i]["rainfall_mm"],
        )
        for i in range(7)
    ]

    forecast_result = garden.forecast(forecast_weather)

    print()
    print(f"{'Vaso':>10} | "
          f"{'D+1':>11} → {'D+7':>11} (state_mm, EC mS/cm)")
    print("-" * 78)
    for label in garden.pot_labels:
        traj = forecast_result.trajectories[label]
        first = traj.points[0]
        last = traj.points[-1]
        print(
            f"{label:>10} | "
            f"{first.state_mm:>5.1f}/{first.ec_substrate_mscm:>4.2f} → "
            f"{last.state_mm:>5.1f}/{last.ec_substrate_mscm:>4.2f}"
        )

    # Allerte previste nei prossimi 7 giorni
    print_subsection("Allerte previste nel forecast a 7 giorni")
    forecast_alerts = garden.forecast_alerts(forecast_weather)
    if forecast_alerts:
        print(f"  Totale allerte previste: {len(forecast_alerts)}")
        # Conta per categoria e severity
        from collections import Counter
        by_cat = Counter(a.category.value for a in forecast_alerts)
        by_sev = Counter(a.severity.value for a in forecast_alerts)
        print(f"  Per categoria: {dict(by_cat)}")
        print(f"  Per severity: {dict(by_sev)}")
        print()
        print("  Prime allerte previste (per data crescente):")
        print_alerts(forecast_alerts, max_show=5)
    else:
        print("  Nessuna allerta prevista nei prossimi 7 giorni.")

    # =====================================================================
    # GIORNI 15-21: terza settimana
    # =====================================================================

    print_section_header("Settimana 3 (giorni 15-21): evoluzione reale")
    print(
        "L'evoluzione effettiva nei prossimi 7 giorni dovrebbe coincidere\n"
        "con il forecast (il meteo simulato è lo stesso). In produzione,\n"
        "qualunque differenza tra forecast e realtà sarebbe il segnale di\n"
        "un evento non previsto (pioggia non prevista, fertirrigazione\n"
        "non programmata, errore di calibrazione del sensore)."
    )
    print()
    print(f"{'Day':>3} {'Date':>10} {'  Met  ':>9} | "
          f"{'aperto · ringhiera · albero (θ/EC mS/cm)':<54} | Eventi")
    print("-" * 96)

    for day_idx in range(14, 21):
        current_date = START_DATE + timedelta(days=day_idx)
        weather = weather_sequence[day_idx]
        timestamp = snapshot_ts_base + timedelta(days=day_idx + 1)

        ground_truth["1"] = garden.get_pot("aperto").state_theta
        ground_truth["2"] = garden.get_pot("ringhiera").state_theta
        fake_sensor.set_day(day_idx, timestamp)

        sensor_results = garden.update_all_from_sensors(fake_sensor)

        events_today = garden.events_due_today(current_date)
        for event in events_today:
            if event.event_type == "fertigation":
                pot = garden.get_pot(event.pot_label)
                pot.apply_fertigation_step(
                    volume_l=event.payload["volume_l"],
                    ec_mscm=event.payload["ec_mscm"],
                    ph=event.payload["ph"],
                    current_date=current_date,
                )

        garden.apply_step_all(
            et_0_mm=weather["et_0_mm"],
            current_date=current_date,
            rainfall_mm=weather["rainfall_mm"],
        )

        persistence.save_garden(garden, snapshot_timestamp=timestamp)

        print_day_row(
            day_idx, current_date, weather, garden,
            events_today, sensor_results,
        )

    # =====================================================================
    # SINTESI FINALE
    # =====================================================================

    print_section_header("Sintesi finale del periodo")

    # Storia degli stati di un vaso via query_states
    print_subsection("Timeline di 'aperto' dal database (query_states)")
    print(
        "La tabella pot_states del database conserva uno snapshot dello\n"
        "stato di ogni vaso a ogni save_garden. Il dashboard può ricostruire\n"
        "la storia completa per produrre grafici di evoluzione."
    )
    print()
    history = persistence.query_states(GARDEN_NAME, "aperto")
    print(f"  Snapshot totali: {len(history)}")
    print()
    print(f"  {'Data':>11} | {'state_mm':>8} | {'salt':>5} | {'pH':>4}")
    # Stampa solo i primi e gli ultimi 5 per leggibilità
    samples = list(history[:3]) + ["..."] + list(history[-5:])
    for s in samples:
        if s == "...":
            print(f"  {'...':>11} | {'...':>8} | {'...':>5} | {'...':>4}")
            continue
        ts_str = s.timestamp.date().isoformat()
        print(f"  {ts_str:>11} | {s.state_mm:>8.2f} | "
              f"{s.salt_mass_meq:>5.2f} | {s.ph_substrate:>4.2f}")
    print()
    print("  (salt = salt_mass in meq; per ottenere EC moltiplicare per il "
          "fattore acqua)")

    # Allerte correnti finali
    print_subsection("Allerte correnti alla fine del periodo")
    final_alerts = garden.current_alerts(
        current_date=START_DATE + timedelta(days=20),
    )
    print_alerts(final_alerts)

    # Statistiche del periodo
    print_subsection("Statistiche del periodo")
    total_rain = sum(w["rainfall_mm"] for w in weather_sequence)
    total_et = sum(w["et_0_mm"] for w in weather_sequence)
    rain_days = sum(1 for w in weather_sequence if w["rainfall_mm"] > 0)
    print(f"  Pioggia totale (su area aperta): {total_rain:.1f} mm "
          f"in {rain_days} giorni di pioggia")
    print(f"  ET₀ totale: {total_et:.1f} mm")
    print(f"  Bilancio pioggia − ET₀: {total_rain - total_et:+.1f} mm "
          f"(deficit idrico fisiologico se negativo)")
    print(f"  Fertirrigazioni eseguite: {3 * 3} (3 vasi × 3 settimane)")
    print()
    for label in garden.pot_labels:
        pot = garden.get_pot(label)
        print(f"  Stato finale '{label}': θ={pot.state_theta:.3f}, "
              f"EC={pot.ec_substrate_mscm:.2f} mS/cm, pH={pot.ph_substrate:.2f}")

    # =====================================================================
    # CLEANUP
    # =====================================================================

    persistence.close()
    os.unlink(db_path)
    print()
    print(f"Database temporaneo {db_path} cancellato.")
    print()
    print("=" * 78)
    print("  Demo completata. Tutte le capacità della tappa 4 in azione.")
    print("=" * 78)


if __name__ == "__main__":
    main()
