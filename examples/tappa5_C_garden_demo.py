"""
Esempio della sotto-tappa C della tappa 5 fascia 2: integrazione del
selettore "best available" nel Pot e nel Garden.

Questo script mostra in azione i nuovi metodi apply_balance_step_from_weather
e apply_step_all_from_weather simulando l'evoluzione di un piccolo
giardino di tre vasi sul balcone milanese di Andrea durante una settimana
di luglio 2026, con dati meteo di qualità variabile e gestione realistica
delle irrigazioni.

Mentre la demo della sotto-tappa B mostrava il selettore in modo isolato
(ogni giorno era un calcolo a sé stante), questa demo è la prima dove
il selettore vive dentro al ciclo di vita del Pot e del Garden: il
chiamante passa solo i dati meteo grezzi, e l'intera orchestrazione
(calcolo di Rn dalla radiazione globale, scelta della formula migliore,
applicazione del Kc se necessario, aggiornamento dello stato del vaso)
avviene automaticamente all'interno della libreria. La tracciabilità
del metodo di evapotraspirazione si propaga attraverso il
BalanceStepResult, permettendo al chiamante di sapere a posteriori
con quale livello di accuratezza è stato calcolato l'ET di ogni giorno.

Per eseguirlo:
    PYTHONPATH=src python examples/tappa5_C_garden_demo.py

Output atteso: circa 130-160 righe di output didattico con la
simulazione giorno per giorno, le statistiche aggregate della settimana,
e la diagnostica ex-post.
"""

from datetime import date, timedelta
from typing import Dict, List

# Importiamo le strutture introdotte dalla sotto-tappa C: la dataclass
# WeatherDay, le specie del catalogo (estese coi parametri fisiologici),
# il Pot e il Garden coi nuovi metodi from_weather. L'enum EtMethod
# serve per la diagnostica ex-post.
from fitosim.domain.garden import Garden
from fitosim.domain.pot import Pot, Location
from fitosim.domain.species import BASIL, ROSEMARY, Species
from fitosim.domain.weather import WeatherDay
from fitosim.science.et0 import EtMethod
from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL


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
#  PARTE 1: setup del giardino con tre vasi.
# =====================================================================
#
# Il balcone milanese di Andrea ospita tre vasi di specie diverse,
# scelte per illustrare la differenziazione fisiologica che il
# Penman-Monteith fisico riesce a catturare. Il basilico e il rosmarino
# vengono dal catalogo della libreria (sono già popolati coi parametri
# rs e h dalla sotto-tappa C). La succulenta CAM la creo ad-hoc per
# la demo, come avrebbe fatto Andrea aggiungendo una specie al suo
# catalogo personale.

stampa_sezione("Parte 1: setup del giardino milanese")

# Specie ad-hoc: succulenta CAM con resistenza stomatica molto alta.
# Le piante CAM (Crassulacean Acid Metabolism) chiudono gli stomi
# durante il giorno e li aprono solo di notte per limitare la perdita
# d'acqua, e questo si traduce in resistenza stomatica >500 s/m. Per
# la libreria questa è una specie con Kc empirico molto basso (0.40)
# E parametri fisiologici espliciti.
SUCCULENT = Species(
    common_name="Succulenta CAM",
    scientific_name="Aeonium arboreum",
    kc_initial=0.40,
    kc_mid=0.40,
    kc_late=0.40,
    depletion_fraction=0.70,
    initial_stage_days=60,
    mid_stage_days=240,
    notes=(
        "Pianta CAM ornamentale, esempio di xerofita estrema. Chiude "
        "gli stomi di giorno per limitare la traspirazione. Tollera "
        "stress idrico prolungato (p=0.70). Kc empirico molto basso, "
        "ma il valore reale di ET è ancora più basso quando si applica "
        "Penman-Monteith fisico con la sua resistenza stomatica reale."
    ),
    stomatal_resistance_s_m=500.0,
    crop_height_m=0.10,
)

# Setup del giardino: nome, latitudine e quota di Milano.
LATITUDINE_MILANO = 45.47
QUOTA_MILANO_M = 150.0
DATA_INIZIO = date(2026, 7, 19)

garden = Garden(name="Balcone milanese di Andrea")

# Tre vasi del giardino con coordinate Milano popolate sui Pot stessi.
# Questo è il pattern ergonomico introdotto dalla sotto-tappa C: il
# chiamante non deve passare le coordinate ad ogni chiamata, ma le
# dichiara una volta sola quando costruisce il Pot.
vasi_iniziali = [
    Pot(
        label="Basilico-vaso-1",
        species=BASIL,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=2.5, pot_diameter_cm=15.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 6, 1),
        latitude_deg=LATITUDINE_MILANO, elevation_m=QUOTA_MILANO_M,
    ),
    Pot(
        label="Rosmarino-vaso-1",
        species=ROSEMARY,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=5.0, pot_diameter_cm=22.0,
        location=Location.OUTDOOR,
        planting_date=date(2025, 5, 1),
        latitude_deg=LATITUDINE_MILANO, elevation_m=QUOTA_MILANO_M,
    ),
    Pot(
        label="Succulenta-vaso-1",
        species=SUCCULENT,
        substrate=UNIVERSAL_POTTING_SOIL,
        pot_volume_l=1.5, pot_diameter_cm=14.0,
        location=Location.OUTDOOR,
        planting_date=date(2024, 4, 1),
        latitude_deg=LATITUDINE_MILANO, elevation_m=QUOTA_MILANO_M,
    ),
]
for vaso in vasi_iniziali:
    garden.add_pot(vaso)

print()
print(f"  Giardino: {garden.name}")
print(f"  Coordinate: lat={LATITUDINE_MILANO}, quota={QUOTA_MILANO_M:.0f} m")
print()
print(f"  Vasi del giardino:")
print(f"  {'Etichetta':<22} {'Specie':<22} {'rs (s/m)':<10} {'h (m)':<8} {'fc (mm)':<10}")
print(f"  {'-'*22} {'-'*22} {'-'*10} {'-'*8} {'-'*10}")
for vaso in vasi_iniziali:
    rs = vaso.species.stomatal_resistance_s_m
    h = vaso.species.crop_height_m
    rs_str = f"{rs:.0f}" if rs is not None else "-"
    h_str = f"{h:.2f}" if h is not None else "-"
    print(f"  {vaso.label:<22} {vaso.species.common_name:<22} "
          f"{rs_str:<10} {h_str:<8} {vaso.fc_mm:<10.2f}")


# =====================================================================
#  PARTE 2: la settimana di dati meteo del 19-25 luglio 2026.
# =====================================================================
#
# Lo scenario meteo della settimana riprende quello della demo della
# sotto-tappa B (con guasti progressivi della stazione Ecowitt) ma
# arricchito con qualche evento di pioggia per rendere la simulazione
# più realistica. Il giardiniere irriga manualmente quando un vaso
# scende sotto la soglia di allerta.

stampa_sezione("Parte 2: la settimana di simulazione")

# Definiamo la settimana di dati meteo. Per ogni giorno specifichiamo
# i dati meteo (con None per i campi mancanti) e l'eventuale pioggia.
# Lo scenario riflette pattern realistici di una stazione meteo che
# non sempre funziona perfettamente, e di un'estate milanese con
# qualche temporale pomeridiano.
SETTIMANA = [
    {
        "data": date(2026, 7, 19), "t_min": 20.0, "t_max": 32.0,
        "humidity": 0.60, "wind": 1.5, "rs": 24.0,
        "rainfall_mm": 0.0,
        "nota": "stazione operativa, giornata di pieno sole",
    },
    {
        "data": date(2026, 7, 20), "t_min": 21.0, "t_max": 33.5,
        "humidity": 0.55, "wind": 2.0, "rs": 25.5,
        "rainfall_mm": 0.0,
        "nota": "stazione operativa, ancora pieno sole",
    },
    {
        "data": date(2026, 7, 21), "t_min": 22.0, "t_max": 34.0,
        "humidity": 0.52, "wind": None, "rs": 26.0,
        "rainfall_mm": 0.0,
        "nota": "anemometro offline (manca vento)",
    },
    {
        "data": date(2026, 7, 22), "t_min": 21.5, "t_max": 28.5,
        "humidity": 0.78, "wind": 1.8, "rs": 14.0,
        "rainfall_mm": 8.0,
        "nota": "temporale pomeridiano (8 mm di pioggia)",
    },
    {
        "data": date(2026, 7, 23), "t_min": 19.5, "t_max": 28.0,
        "humidity": None, "wind": None, "rs": None,
        "rainfall_mm": 0.0,
        "nota": "internet offline, solo temperature da forecast",
    },
    {
        "data": date(2026, 7, 24), "t_min": 19.0, "t_max": 29.5,
        "humidity": 0.70, "wind": 1.2, "rs": 22.0,
        "rainfall_mm": 0.0,
        "nota": "stazione operativa, ripresa dopo black-out",
    },
    {
        "data": date(2026, 7, 25), "t_min": 20.5, "t_max": 31.5,
        "humidity": None, "wind": 1.6, "rs": 24.5,
        "rainfall_mm": 0.0,
        "nota": "igrometro offline (manca umidità)",
    },
]

# Storico delle simulazioni: per ogni giorno e per ogni vaso, registriamo
# il risultato del passo per fare l'analisi diagnostica a fine settimana.
storico: List[Dict] = []

# Loop di simulazione giorno per giorno.
for giorno_dati in SETTIMANA:
    # Costruiamo il WeatherDay del giorno con i dati a disposizione.
    weather = WeatherDay(
        date_=giorno_dati["data"],
        t_min=giorno_dati["t_min"],
        t_max=giorno_dati["t_max"],
        humidity_relative=giorno_dati["humidity"],
        wind_speed_m_s=giorno_dati["wind"],
        solar_radiation_mj_m2_day=giorno_dati["rs"],
    )

    # Snapshot degli stati prima dell'applicazione del passo (per
    # calcolare la perdita giornaliera).
    stati_pre = {
        vaso.label: vaso.state_mm for vaso in garden
    }

    # Il pezzo concettualmente importante della demo: una sola chiamata
    # del Garden orchestra tutto. Ogni Pot al suo interno chiamerà il
    # selettore con i dati meteo del giorno e i propri parametri specie,
    # produrrà un risultato, e aggiornerà il proprio stato.
    risultati = garden.apply_step_all_from_weather(
        weather=weather,
        rainfall_mm=giorno_dati["rainfall_mm"],
    )

    # Stampa del giorno, con per ogni vaso il metodo selezionato e
    # l'evoluzione dello stato.
    print()
    print(f"  {weather.date_.isoformat()} ({giorno_dati['nota']}):")
    if giorno_dati["rainfall_mm"] > 0:
        print(f"    Pioggia: {giorno_dati['rainfall_mm']:.1f} mm")

    for vaso in garden:
        risultato = risultati[vaso.label]
        balance = risultato.balance_result
        metodo = balance.et_method.value if balance.et_method else "?"
        perdita = stati_pre[vaso.label] - balance.new_state
        # Nota: la perdita può essere negativa nei giorni di pioggia
        # se la pioggia eccede l'evapotraspirazione del giorno.
        allerta = " ⚠ ALLERTA" if balance.under_alert else ""

        print(f"    {vaso.label:<22} method={metodo:<28} "
              f"state={balance.new_state:>5.2f} mm "
              f"(Δ={-perdita:+5.2f}){allerta}")

        # Salva nello storico per l'analisi finale.
        storico.append({
            "data": weather.date_,
            "vaso": vaso.label,
            "specie": vaso.species.common_name,
            "method": balance.et_method,
            "state_pre": stati_pre[vaso.label],
            "state_post": balance.new_state,
            "perdita_mm": perdita,
            "under_alert": balance.under_alert,
            "drainage": balance.drainage,
        })


# =====================================================================
#  PARTE 3: gestione delle irrigazioni quando scattano le allerte.
# =====================================================================
#
# Adesso vediamo cosa succede quando un vaso scende sotto la soglia di
# allerta: il giardiniere irriga manualmente per riportarlo a capacità
# di campo. Riprendiamo gli stati dei vasi alla fine della settimana e
# applichiamo le irrigazioni necessarie. Questa è una semplificazione
# rispetto alla realtà (il giardiniere normalmente irrigia DURANTE la
# settimana, non alla fine), ma serve a mostrare il pattern di interazione.

stampa_sezione("Parte 3: irrigazioni di fine settimana")

print()
print(f"  Stato dei vasi al termine della settimana:")
for vaso in garden:
    deficit = max(0.0, vaso.alert_mm - vaso.state_mm)
    if vaso.state_mm < vaso.alert_mm:
        print(f"    {vaso.label}: state={vaso.state_mm:.2f} mm, "
              f"alert={vaso.alert_mm:.2f} mm, deficit={deficit:.2f} mm "
              f"-> serve irrigazione")
    else:
        print(f"    {vaso.label}: state={vaso.state_mm:.2f} mm, "
              f"alert={vaso.alert_mm:.2f} mm -> ok")

# Irrigazione manuale dei vasi sotto allerta. La demo applica
# l'irrigazione tramite apply_balance_step_from_weather usando un
# WeatherDay "neutro" (stesso meteo del giorno conclusivo) e
# water_input_mm pari al deficit fino a fc.
print()
print(f"  Applicazione delle irrigazioni:")
ultimo_giorno = SETTIMANA[-1]
weather_neutrale = WeatherDay(
    date_=ultimo_giorno["data"] + timedelta(days=1),
    t_min=ultimo_giorno["t_min"],
    t_max=ultimo_giorno["t_max"],
    humidity_relative=ultimo_giorno["humidity"],
    wind_speed_m_s=ultimo_giorno["wind"],
    solar_radiation_mj_m2_day=ultimo_giorno["rs"],
)
for vaso in garden:
    if vaso.state_mm < vaso.alert_mm:
        # Quanta acqua serve per riportarlo a capacità di campo?
        irrigazione_mm = vaso.water_to_field_capacity()
        # Aggiorniamo lo stato passando questo valore come water_input_mm.
        risultato = vaso.apply_balance_step_from_weather(
            weather=weather_neutrale,
            water_input_mm=irrigazione_mm,
            current_date=weather_neutrale.date_,
        )
        print(f"    {vaso.label}: irrigato con {irrigazione_mm:.2f} mm, "
              f"nuovo state={risultato.new_state:.2f} mm")
    else:
        print(f"    {vaso.label}: nessuna irrigazione necessaria")


# =====================================================================
#  PARTE 4: analisi diagnostica della settimana.
# =====================================================================
#
# La tracciabilità del metodo nel BalanceStepResult permette di fare
# diagnostica ex-post della qualità delle stime. Vediamo per ogni vaso
# quante volte ogni metodo è stato usato durante la settimana, e
# quanta acqua totale è stata persa per evapotraspirazione.

stampa_sezione("Parte 4: analisi diagnostica della settimana")

stampa_sottosezione("Distribuzione dei metodi usati per ogni vaso")

# Conta il numero di volte ogni metodo è stato usato per ogni vaso.
print()
for vaso in garden:
    print(f"  {vaso.label}:")
    record_vaso = [r for r in storico if r["vaso"] == vaso.label]
    conteggi: Dict[EtMethod, int] = {}
    for record in record_vaso:
        m = record["method"]
        conteggi[m] = conteggi.get(m, 0) + 1
    for method, count in sorted(conteggi.items(), key=lambda x: x[0].value):
        percentuale = count / len(record_vaso) * 100
        print(f"    {method.value:<28}: {count}/{len(record_vaso)} "
              f"({percentuale:.0f}%)")

stampa_sottosezione("Bilancio idrico cumulato della settimana")

print()
print(f"  {'Vaso':<22} {'Persa (mm)':<12} {'Drenata (mm)':<14} {'Allerte':<10}")
print(f"  {'-'*22} {'-'*12} {'-'*14} {'-'*10}")
for vaso in garden:
    record_vaso = [r for r in storico if r["vaso"] == vaso.label]
    persa_totale = sum(r["perdita_mm"] for r in record_vaso if r["perdita_mm"] > 0)
    drenata_totale = sum(r["drainage"] for r in record_vaso)
    n_allerte = sum(1 for r in record_vaso if r["under_alert"])
    print(f"  {vaso.label:<22} "
          f"{persa_totale:<12.2f} "
          f"{drenata_totale:<14.2f} "
          f"{n_allerte:<10}")

stampa_sottosezione("Confronto fisiologico tra le specie del giardino")

print(f"""
  La differenziazione fisiologica delle specie è il valore aggiunto
  più tangibile del Penman-Monteith fisico integrato nel ciclo di vita
  del Pot. Nello stesso giardino, con lo stesso meteo, le tre specie
  evolvono in modi sensibilmente diversi:
""")

# Per il confronto, per ogni vaso calcoliamo la perdita media giornaliera
# nei giorni in cui è stato usato Penman-Monteith fisico (gli altri
# usano Hargreaves che è "uguale per tutti" e non differenzia le specie).
for vaso in garden:
    record_vaso = [
        r for r in storico
        if r["vaso"] == vaso.label
        and r["method"] == EtMethod.PENMAN_MONTEITH_PHYSICAL
    ]
    if record_vaso:
        perdita_media = sum(r["perdita_mm"] for r in record_vaso) / len(record_vaso)
        rs = vaso.species.stomatal_resistance_s_m
        print(f"    {vaso.label} (rs={rs:.0f} s/m): "
              f"perdita media {perdita_media:.2f} mm/giorno (PM fisico)")


# =====================================================================
#  PARTE 5: conclusioni.
# =====================================================================

stampa_sezione("Conclusioni")

print(f"""
  Quello che abbiamo visto in questa demo è la sotto-tappa C in azione:
  il selettore "best available" della sotto-tappa B integrato dentro
  al ciclo di vita del Pot e del Garden. Il chiamante non orchestra
  più manualmente la chiamata al selettore o il calcolo della
  radiazione netta: passa solo un WeatherDay al Garden e l'intera
  catena (selezione della formula, calcolo intermedio di Rn,
  applicazione del Kc, aggiornamento dello stato del vaso) avviene
  automaticamente all'interno della libreria.

  I tre messaggi principali da portare a casa sono:

  PRIMO: il valore architetturale dell'incapsulamento. Confronta il
  codice della demo della sotto-tappa B con quello di questa demo. Lì
  il chiamante doveva costruire una funzione applica_kc per gestire
  manualmente la distinzione ET vs ET₀, calcolare separatamente Rn
  con net_radiation, orchestrare le chiamate al selettore con tutti
  i parametri. Qui il chiamante chiama una sola volta
  garden.apply_step_all_from_weather() e tutto succede.

  SECONDO: la differenziazione fisiologica resta visibile e diagnostica.
  Anche se il chiamante non vede più i dettagli di calcolo, il campo
  et_method nel BalanceStepResult permette di sapere a posteriori
  quale formula è stata usata per ogni vaso ogni giorno. Questo è il
  ponte verso la fascia 3 di calibrazione: confrontando le previsioni
  con le osservazioni reali del balcone, sapremo se una discrepanza
  viene da un calcolo Hargreaves di backup o da un Penman-Monteith
  fisico, e l'interpretazione della discrepanza cambia di conseguenza.

  TERZO: lo scope è chiaramente outdoor. Tutti i dati meteo che abbiamo
  passato (temperatura, umidità, vento, radiazione globale) sono
  grandezze che la stazione Ecowitt sul balcone misura direttamente.
  La sotto-tappa D introdurrà il modello indoor con la nuova entità
  Room, e il pattern di chiamata cambierà di conseguenza: invece di
  WeatherDay outdoor avremo un IndoorMicroclimate che incapsula la
  temperatura e l'umidità della stanza misurate dal sensore WN31
  ambientale, con la radiazione luminosa parametrizzata su tre livelli
  (buio, luminoso indiretto, sole diretto) invece che misurata da un
  piranometro. Le fondamenta architetturali che la sotto-tappa C ha
  appena messo (la separazione tra dati meteo grezzi e parametri
  fisiologici della specie, la propagazione della tracciabilità del
  metodo, il pattern from_weather come fratello del metodo classico)
  saranno preziose per accomodare il modello indoor senza duplicazioni.
""")

print("=" * 76)
print(f"  Demo completata. Per i dettagli vedi CHANGELOG-tappa5-C.md")
print("=" * 76)
