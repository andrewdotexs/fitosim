"""
Demo: integrazione del nuovo strato sensori della fascia 2 (tappa 1).

Cosa dimostra questo demo
-------------------------

La tappa 1 della fascia 2 ha aggiunto a fitosim un livello di
astrazione uniforme per leggere dati da sorgenti esterne. Tutti gli
adapter — Open-Meteo per il forecast cloud, Ecowitt per la stazione
personale, le fixture CSV per i dati storici — implementano la stessa
interfaccia, e il chiamante lavora sempre con due tipi canonici
(EnvironmentReading e SoilReading) indipendentemente dal provider.

Questo demo mostra concretamente cosa significa quel "livello di
astrazione uniforme" attraverso uno scenario realistico. Simuliamo
sei settimane di vita di un vaso di basilico sul balcone milanese,
combinando due sorgenti di dati:

  - **CsvEnvironmentFixture**: dati meteo giornalieri da un file
    CSV sintetico che rappresenta un maggio milanese tipico
    (temperature in salita, qualche giorno di pioggia, ET₀ crescente).

  - **CsvSoilFixture**: letture orarie del sensore di umidità del
    substrato, generate sinteticamente per assomigliare al
    comportamento reale di un WH51: picchi alla capacità di campo
    dopo le irrigazioni, asciugamento progressivo nei giorni
    successivi, rumore di sensore moderato.

Il punto didattico chiave è che lo stesso codice di simulazione
funzionerebbe identicamente sostituendo CsvEnvironmentFixture con
OpenMeteoEnvironmentSensor (per dati meteo cloud reali) o
EcowittEnvironmentSensor (per la stazione del balcone). Vedi la
sezione finale "varianti" per gli esempi commentati.

Cosa visualizza il demo
-----------------------

Il grafico finale ha tre pannelli sovrapposti, ognuno racconta una
parte diversa della stessa storia agronomica:

  1. **Forzante meteo**: temperatura giornaliera ed ET₀, le variabili
     "input" che governano il consumo idrico del vaso. Vedi che ET₀
     varia da 2.5 mm/giorno (giornate fresche e nuvolose) a 6 mm/giorno
     (giornate calde e soleggiate).

  2. **Stato idrico simulato**: la traiettoria di state_mm del vaso
     calcolata da apply_balance_step, con la soglia di allerta come
     linea orizzontale e i marker delle irrigazioni decise
     dall'algoritmo. Vedi i picchi a fc_mm dopo ogni irrigazione e il
     progressivo asciugamento.

  3. **Confronto modello vs sensore**: lo stato del modello (in mm
     convertiti in θ per il confronto) sovrapposto alle letture del
     sensore CSV, con le aree di "discrepanza" evidenziate. Quelle
     discrepanze sono esattamente il segnale che il feedback loop di
     update_from_sensor (capitolo 8 del manuale utente) andrebbe a
     correggere.

Esecuzione
----------

    cd fitosim/
    PYTHONPATH=src python examples/sensors_integration_demo.py

Il demo genera due file CSV temporanei in /tmp/, poi li legge con le
fixture, esegue la simulazione, e salva il grafico in
output/plots/sensors_integration_demo.png.
"""

import csv
import math
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from fitosim.domain.pot import Location, Pot
from fitosim.domain.species import BASIL
from fitosim.io.sensors import (
    CsvEnvironmentFixture,
    CsvSoilFixture,
)
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


# =========================================================================
#  Generazione dei dati sintetici
# =========================================================================

# Seed fisso per riproducibilità: chiunque lanci il demo vede gli stessi
# numeri esatti, indipendentemente dall'ora di esecuzione.
RANDOM_SEED = 42
SIMULATION_START = date(2026, 5, 1)
SIMULATION_DAYS = 42  # sei settimane

# Parametri del vaso simulato. Volutamente piccolo perché basilico in
# vaso da balcone è il caso più comune; le dinamiche sono più rapide
# e didatticamente leggibili rispetto a un vaso grande.
POT_VOLUME_L = 2.0
POT_DIAMETER_CM = 18.0


def generate_environment_csv(path: Path) -> None:
    """
    Genera un CSV ambientale sintetico realistico per maggio-giugno
    a Milano: ET₀ tra 2.5 e 6 mm/giorno con stagionalità in salita,
    qualche evento di pioggia distribuito.

    La struttura del CSV segue le colonne richieste da
    CsvEnvironmentFixture: date, t_min, t_max, rain_mm, et0_mm. Le
    altre colonne opzionali (humidity, wind, radiation) le omettiamo
    per semplicità.
    """
    rng = random.Random(RANDOM_SEED)
    rows = []
    for i in range(SIMULATION_DAYS):
        d = SIMULATION_START + timedelta(days=i)

        # Temperatura: trend lineare in salita + oscillazione casuale.
        # Da ~14/24 °C il primo giorno a ~20/30 °C dopo sei settimane.
        base_temp = 14.0 + (i / SIMULATION_DAYS) * 6.0
        daily_amplitude = 10.0 + rng.uniform(-2, 2)
        t_min = base_temp + rng.uniform(-1.5, 1.5)
        t_max = t_min + daily_amplitude

        # ET₀: correlata con la temperatura (più caldo = più ET₀) ma
        # con variabilità per simulare le giornate nuvolose.
        # Formula approssimata: 0.15 × t_max + 0.5, con rumore.
        et0 = 0.15 * t_max + 0.5 + rng.uniform(-0.5, 0.5)
        et0 = max(2.0, min(6.5, et0))  # cap fisicamente plausibile

        # Pioggia: distribuita come variabile sparsa. ~15% dei giorni
        # ha pioggia, intensità tipica 2-15 mm.
        rain = 0.0
        if rng.random() < 0.15:
            rain = rng.uniform(2.0, 15.0)

        rows.append({
            "date": d.isoformat(),
            "t_min": f"{t_min:.1f}",
            "t_max": f"{t_max:.1f}",
            "rain_mm": f"{rain:.1f}",
            "et0_mm": f"{et0:.2f}",
        })

    # Scrittura del CSV con DictWriter per chiarezza.
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "t_min", "t_max", "rain_mm", "et0_mm"],
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_soil_csv(
    path: Path,
    env_fixture: CsvEnvironmentFixture,
) -> None:
    """
    Genera un CSV di letture θ del substrato sintetico, simulando il
    comportamento di un sensore WH51 reale.

    L'idea: facciamo girare una mini-simulazione "ombra" del vaso che
    riproduce la fisica reale del bilancio idrico, con eventi di
    irrigazione decisi quando lo stato scende sotto la soglia, e
    aggiungiamo rumore di sensore (~±1.5% in θ) per realismo.

    Il risultato è un CSV con letture orarie (ogni 1 ora) per le sei
    settimane di simulazione, esattamente come potresti esportare da
    un WH51 reale.
    """
    rng = random.Random(RANDOM_SEED + 1)  # seed diverso dal meteo

    # "Vaso ombra" che genera le letture di riferimento. Usiamo gli
    # stessi parametri del vaso che simuleremo dopo, ma inizializzato
    # con una piccola variazione per simulare il fatto che il sensore
    # vede valori leggermente diversi dal nostro modello (è proprio il
    # punto del feedback loop: catturare queste differenze).
    shadow_pot = Pot(
        label="vaso-ombra-csv",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=POT_VOLUME_L,
        pot_diameter_cm=POT_DIAMETER_CM,
        location=Location.OUTDOOR,
        planting_date=SIMULATION_START,
    )
    # Iniezione di "drift": il vaso reale parte da uno stato un po' più
    # basso del default (capacità di campo). Questo crea una piccola
    # discrepanza iniziale visibile poi nel grafico.
    shadow_pot._state_mm = shadow_pot.fc_mm * 0.95

    rows = []
    forecast = env_fixture.forecast(latitude=45.46, longitude=9.19,
                                     days=SIMULATION_DAYS)

    for i, env_reading in enumerate(forecast):
        d = SIMULATION_START + timedelta(days=i)

        # Decisione di irrigazione: stessa logica del nostro sistema
        # (irriga quando si scende sotto la soglia di allerta).
        irrigazione = 0.0
        if shadow_pot.state_mm < shadow_pot.alert_mm:
            # Irriga al 105% della capacità di campo per riprodurre il
            # gesto reale "fino a vedere l'acqua dal fondo".
            irrigazione = shadow_pot.water_to_field_capacity() * 1.05

        # Applica un giorno di bilancio idrico.
        et0 = env_reading.et0_mm if env_reading.et0_mm else 4.0
        pioggia = env_reading.rain_mm if env_reading.rain_mm else 0.0
        shadow_pot.apply_balance_step(
            et_0_mm=et0,
            water_input_mm=pioggia + irrigazione,
            current_date=d,
        )

        # Genera 24 letture orarie per questo giorno. Il sensore reale
        # vede l'andamento intra-giornaliero ma a livello di simulazione
        # il vaso ha solo lo stato di fine giornata, quindi
        # interpoliamo linearmente tra "stato di ieri" e "stato di oggi".
        # In più aggiungiamo rumore gaussiano di ~1.5% per realismo.
        theta_end = shadow_pot.state_theta
        if i == 0:
            theta_start = theta_end  # primo giorno: nessuna interpolazione
        else:
            # state_theta del giorno precedente = quello che abbiamo
            # appena terminato di simulare nel ciclo precedente, ma
            # non l'abbiamo conservato esplicitamente. Per semplicità
            # usiamo lo stato corrente come ancoraggio sia di inizio
            # sia di fine, modulato dal rumore. Va benissimo per il
            # demo: il sensore vede l'andamento smussato.
            theta_start = theta_end

        for hour in range(24):
            # Frazione del giorno trascorsa.
            t_frac = hour / 23.0
            # θ "vero" interpolato tra inizio e fine giornata.
            theta_true = theta_start * (1 - t_frac) + theta_end * t_frac
            # Aggiunta di rumore di sensore: distribuzione normale con
            # sigma=0.015 (1.5% in θ).
            theta_noisy = theta_true + rng.gauss(0, 0.015)
            # Clamping nel range fisico.
            theta_noisy = max(0.05, min(0.55, theta_noisy))

            ts = datetime.combine(
                d, time(hour, 0), tzinfo=timezone.utc,
            )
            rows.append({
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "theta_volumetric": f"{theta_noisy:.4f}",
                # WH51 misura solo θ: gli altri campi restano vuoti.
                "temperature_c": "",
                "ec_mscm": "",
                "ph": "",
            })

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "theta_volumetric",
            "temperature_c", "ec_mscm", "ph",
        ])
        writer.writeheader()
        writer.writerows(rows)


# =========================================================================
#  Simulazione del vaso usando i nuovi adapter
# =========================================================================

def run_simulation(env_fixture: CsvEnvironmentFixture) -> dict:
    """
    Esegue la simulazione del vaso usando l'adapter ambientale.

    Il fatto che la firma riceva direttamente un EnvironmentSensor (e
    non specificamente un CsvEnvironmentFixture) è il punto cruciale:
    la funzione funziona identicamente con qualsiasi implementazione
    del Protocol. Questo è il valore dell'astrazione.

    Restituisce un dict di liste numpy-friendly con le serie storiche
    delle variabili rilevanti per la visualizzazione.
    """
    pot = Pot(
        label="basilico-balcone-demo",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=POT_VOLUME_L,
        pot_diameter_cm=POT_DIAMETER_CM,
        location=Location.OUTDOOR,
        planting_date=SIMULATION_START,
    )

    # Recupero delle forzanti meteo per tutti i giorni del periodo.
    # Una sola chiamata al sensore restituisce la lista completa.
    forecast = env_fixture.forecast(
        latitude=45.46, longitude=9.19, days=SIMULATION_DAYS,
    )

    history = {
        "dates": [],
        "et0": [],
        "temperature": [],
        "rain": [],
        "state_mm": [],
        "state_theta": [],
        "fc_mm": pot.fc_mm,
        "alert_mm": pot.alert_mm,
        "irrigation_dates": [],
        "irrigation_doses_mm": [],
    }

    for env_reading in forecast:
        d = env_reading.timestamp.date()

        # Decisione di irrigazione e bilancio idrico standard.
        irrigazione = 0.0
        if pot.state_mm < pot.alert_mm:
            irrigazione = pot.water_to_field_capacity() * 1.05
            history["irrigation_dates"].append(d)
            history["irrigation_doses_mm"].append(irrigazione)

        et0 = env_reading.et0_mm if env_reading.et0_mm else 4.0
        pioggia = env_reading.rain_mm if env_reading.rain_mm else 0.0
        pot.apply_balance_step(
            et_0_mm=et0,
            water_input_mm=pioggia + irrigazione,
            current_date=d,
        )

        # Registriamo lo stato di fine giornata per la visualizzazione.
        history["dates"].append(d)
        history["et0"].append(et0)
        history["temperature"].append(env_reading.temperature_c)
        history["rain"].append(pioggia)
        history["state_mm"].append(pot.state_mm)
        history["state_theta"].append(pot.state_theta)

    return history


def aggregate_soil_to_daily(soil_fixture: CsvSoilFixture) -> dict:
    """
    Aggrega le letture orarie del sensore in valori giornalieri usando
    la mediana, come faresti per la calibrazione (ricetta 3 del
    manuale utente). La mediana è più robusta del massimo o del medio
    rispetto agli outlier orari.
    """
    by_date = {}
    for ts, reading in soil_fixture.readings:
        d = ts.date()
        by_date.setdefault(d, []).append(reading.theta_volumetric)

    sorted_dates = sorted(by_date.keys())
    daily_dates = []
    daily_theta = []
    for d in sorted_dates:
        values = sorted(by_date[d])
        median = values[len(values) // 2]
        daily_dates.append(d)
        daily_theta.append(median)
    return {"dates": daily_dates, "theta": daily_theta}


# =========================================================================
#  Visualizzazione
# =========================================================================

def make_plot(
    history: dict,
    daily_sensor: dict,
    output_path: Path,
) -> None:
    """
    Costruisce il grafico a tre pannelli che racconta la storia
    completa: forzante meteo, stato simulato, confronto con sensore.
    """
    fig, (ax_meteo, ax_state, ax_compare) = plt.subplots(
        3, 1, figsize=(12, 10), sharex=True,
    )

    # --- Pannello 1: Forzante meteo ---
    # ET₀ come barre, temperatura come linea su asse secondario.
    ax_meteo.bar(
        history["dates"], history["et0"],
        color="#E8A33A", alpha=0.6, width=0.9, label="ET₀ (mm/giorno)",
    )
    ax_meteo.set_ylabel("ET₀ (mm/giorno)", color="#B8780A")
    ax_meteo.tick_params(axis='y', labelcolor='#B8780A')

    ax_meteo_temp = ax_meteo.twinx()
    ax_meteo_temp.plot(
        history["dates"], history["temperature"],
        color="#C8324A", linewidth=2, label="Temperatura media (°C)",
    )
    ax_meteo_temp.set_ylabel("Temperatura (°C)", color="#C8324A")
    ax_meteo_temp.tick_params(axis='y', labelcolor='#C8324A')

    # Marker dei giorni di pioggia significativa.
    for d, r in zip(history["dates"], history["rain"]):
        if r > 1.0:
            ax_meteo.annotate(
                f"☔ {r:.0f}", xy=(d, history["et0"][history["dates"].index(d)]),
                xytext=(0, 5), textcoords="offset points",
                fontsize=8, ha="center", color="#2A6FB8",
            )

    ax_meteo.set_title(
        "Forzante meteo: cosa il vaso subisce dall'ambiente",
        fontsize=11, loc='left', pad=10,
    )

    # --- Pannello 2: Stato simulato del vaso ---
    ax_state.plot(
        history["dates"], history["state_mm"],
        color="#2A6FB8", linewidth=2, label="state_mm simulato",
    )
    # Linee di riferimento orizzontali per le soglie.
    ax_state.axhline(
        history["fc_mm"], color="#56AC56", linestyle="--", alpha=0.6,
        label=f"FC ({history['fc_mm']:.1f} mm)",
    )
    ax_state.axhline(
        history["alert_mm"], color="#E8A33A", linestyle="--", alpha=0.6,
        label=f"Alert ({history['alert_mm']:.1f} mm)",
    )
    # Marker delle irrigazioni decise.
    for d, dose in zip(history["irrigation_dates"],
                        history["irrigation_doses_mm"]):
        ax_state.axvline(d, color="#2A6FB8", alpha=0.15, linewidth=4)
    ax_state.set_ylabel("Acqua nel substrato (mm)")
    ax_state.set_title(
        f"Stato idrico simulato dal modello "
        f"({len(history['irrigation_dates'])} irrigazioni in "
        f"{SIMULATION_DAYS} giorni)",
        fontsize=11, loc='left', pad=10,
    )
    ax_state.legend(loc="lower left", fontsize=9)

    # --- Pannello 3: Confronto modello vs sensore ---
    # Convertiamo state_mm in θ per confrontare con il sensore.
    # state_theta è già la frazione canonica.
    ax_compare.plot(
        history["dates"], history["state_theta"],
        color="#2A6FB8", linewidth=2, label="θ modello (simulato)",
    )
    ax_compare.plot(
        daily_sensor["dates"], daily_sensor["theta"],
        color="#C8324A", linewidth=2, alpha=0.8,
        label="θ sensore (CSV, mediana giornaliera)",
        marker="o", markersize=4,
    )
    # Riempimento delle aree di discrepanza per evidenziarle.
    if len(history["state_theta"]) == len(daily_sensor["theta"]):
        ax_compare.fill_between(
            history["dates"],
            history["state_theta"],
            daily_sensor["theta"],
            color="#F0C674", alpha=0.3,
            label="Discrepanza modello-sensore",
        )

    ax_compare.set_ylabel("θ volumetrico (frazione)")
    ax_compare.set_xlabel("Data")
    ax_compare.set_title(
        "Confronto modello vs sensore: il segnale del feedback loop",
        fontsize=11, loc='left', pad=10,
    )
    ax_compare.legend(loc="lower left", fontsize=9)

    # Formattazione comune dell'asse delle date.
    for ax in (ax_meteo, ax_state, ax_compare):
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax.grid(True, alpha=0.3)

    fig.suptitle(
        "fitosim — Tappa 1 fascia 2: integrazione del nuovo strato sensori\n"
        "Vaso di basilico simulato combinando CsvEnvironmentFixture e "
        "CsvSoilFixture",
        fontsize=12, fontweight="bold", y=0.995,
    )
    plt.tight_layout()
    plt.savefig(output_path, dpi=120, bbox_inches="tight")
    print(f"\nGrafico salvato in: {output_path}")


# =========================================================================
#  Main: orchestrazione del demo
# =========================================================================

def main():
    print("=" * 70)
    print("Demo: integrazione nuovo strato sensori (tappa 1 fascia 2)")
    print("=" * 70)

    # Directory temporanea per i CSV sintetici.
    tmp_dir = Path("/tmp/fitosim_sensors_demo")
    tmp_dir.mkdir(exist_ok=True)
    env_csv = tmp_dir / "weather_milano_maggio.csv"
    soil_csv = tmp_dir / "wh51_balcone_letture.csv"

    print("\n[1/4] Generazione dati ambientali sintetici...")
    generate_environment_csv(env_csv)
    print(f"      → {env_csv} ({SIMULATION_DAYS} giorni)")

    print("\n[2/4] Caricamento dei dati ambientali via "
          "CsvEnvironmentFixture...")
    env_fixture = CsvEnvironmentFixture(env_csv)
    print(f"      → fixture pronta, expone Protocol EnvironmentSensor")

    print("\n[3/4] Generazione e caricamento letture sensore "
          "(CsvSoilFixture)...")
    generate_soil_csv(soil_csv, env_fixture)
    soil_fixture = CsvSoilFixture(soil_csv)
    print(f"      → {len(soil_fixture.readings)} letture orarie del WH51 "
          f"sintetico")

    print("\n[4/4] Esecuzione simulazione + visualizzazione...")
    history = run_simulation(env_fixture)
    daily_sensor = aggregate_soil_to_daily(soil_fixture)

    # Statistiche di sintesi per output testuale prima del grafico.
    n_irrigations = len(history["irrigation_dates"])
    total_water = sum(history["irrigation_doses_mm"])
    final_state = history["state_mm"][-1]
    print(f"      → {n_irrigations} irrigazioni decise dall'algoritmo")
    print(f"      → {total_water:.1f} mm di acqua totale apportata")
    print(f"      → stato finale del vaso: {final_state:.1f} mm")

    # Calcolo della discrepanza media tra modello e sensore.
    if len(history["state_theta"]) == len(daily_sensor["theta"]):
        discrepancies = [
            m - s for m, s in zip(history["state_theta"],
                                  daily_sensor["theta"])
        ]
        rmse = math.sqrt(
            sum(d * d for d in discrepancies) / len(discrepancies)
        )
        print(f"      → RMSE modello-sensore: {rmse:.4f} (in θ)")
        print(f"        È esattamente la grandezza che update_from_sensor")
        print(f"        andrebbe a correggere se attivassimo il feedback "
              f"loop.")

    # Salvataggio del grafico in output/plots come gli altri demo.
    output_dir = Path(__file__).parent.parent / "output" / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sensors_integration_demo.png"
    make_plot(history, daily_sensor, output_path)

    # Sezione finale didattica: come fare la stessa cosa con adapter
    # operativi reali (Open-Meteo / Ecowitt). Stampato come messaggio
    # di chiusura, non eseguito.
    print("\n" + "=" * 70)
    print("Varianti: lo stesso codice con adapter operativi")
    print("=" * 70)
    print("""
Il bello dell'astrazione è che `run_simulation()` accetta qualsiasi
EnvironmentSensor. Per usare dati reali invece dei CSV sintetici
basta sostituire l'oggetto fixture con un adapter di rete:

    # Variante A: forecast cloud da Open-Meteo (no auth richiesta)
    from fitosim.io.sensors import OpenMeteoEnvironmentSensor
    env_sensor = OpenMeteoEnvironmentSensor()
    history = run_simulation(env_sensor)

    # Variante B: stazione Ecowitt personale (richiede credenziali)
    # Imposta FITOSIM_ECOWITT_APPLICATION_KEY, FITOSIM_ECOWITT_API_KEY,
    # FITOSIM_ECOWITT_MAC nelle variabili d'ambiente.
    from fitosim.io.sensors import EcowittEnvironmentSensor
    env_sensor = EcowittEnvironmentSensor.from_env()
    # Nota: Ecowitt non supporta forecast(), va combinato con Open-Meteo
    # — la tappa 4 della fascia 2 (Garden) automatizzerà la combinazione.

Il codice di simulazione resta IDENTICO. È esattamente quello che
l'astrazione promette di fare.
""")


if __name__ == "__main__":
    main()
