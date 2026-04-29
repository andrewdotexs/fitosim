"""
Esempio della sotto-tappa B della tappa 5 fascia 2: il selettore
"best available" tra le tre formule di evapotraspirazione.

Questo script mostra in azione il selettore introdotto dalla sotto-tappa
B simulando una situazione realistica del balcone milanese. Lo scenario
narrativo è una settimana di dati meteo del 19-25 luglio 2026, durante
la quale la qualità dei dati raccolti varia da giorno a giorno: alcuni
giorni la stazione Ecowitt funziona perfettamente, altri giorni qualche
sensore è offline, un giorno la connessione internet cade e si finisce
per usare solo il forecast Open-Meteo che dà soltanto le temperature.

Il valore aggiunto del selettore in questo scenario è duplice. Da una
parte, il chiamante non deve riscrivere la sua logica in funzione dei
dati disponibili: passa quello che ha al selettore e lui sceglie la
formula migliore applicabile. Dall'altra parte, la tracciabilità del
metodo permette di sapere a posteriori con quale livello di accuratezza
è stata calcolata l'ET di ogni giorno, informazione preziosa per la
diagnostica del modello e per la calibrazione futura.

Per eseguirlo:
    PYTHONPATH=src python examples/tappa5_B_selettore_demo.py

Output atteso: circa 100-130 righe di output didattico con la
simulazione della settimana, l'analisi diagnostica dei metodi usati,
e qualche pattern di gestione degli errori.
"""

from datetime import date, timedelta

# Importiamo le strutture introdotte dalla sotto-tappa B (la dataclass
# EtResult, l'enum EtMethod, la funzione compute_et) e le funzioni di
# radiazione introdotte dalla sotto-tappa A che servono per calcolare
# Rn quando i dati meteo sono completi.
from fitosim.science.et0 import (
    EtMethod,
    EtResult,
    actual_vapor_pressure,
    compute_et,
)
from fitosim.science.radiation import (
    day_of_year,
    extraterrestrial_radiation,
    net_radiation,
)


def stampa_sezione(titolo: str) -> None:
    """Stampa un titolo di sezione con bordo per leggibilità."""
    print()
    print("=" * 72)
    print(f"  {titolo}")
    print("=" * 72)


def stampa_sottosezione(titolo: str) -> None:
    """Stampa un titolo di sottosezione."""
    print()
    print(f"--- {titolo} ---")


# =====================================================================
#  CONTESTO: il balcone milanese e le specie coltivate.
# =====================================================================
#
# Andrea coltiva tre specie sul suo balcone esposto a sud: basilico in
# vasi piccoli da cucina, rosmarino in vaso medio, una succulenta CAM
# come pianta ornamentale resistente. Il selettore della sotto-tappa B
# permetterà di calcolare l'ET di ogni specie con la formula più
# accurata applicabile in funzione dei dati disponibili nella giornata.

LATITUDINE_MILANO = 45.47
QUOTA_MILANO_M = 150.0

# Parametri fisiologici delle tre specie del balcone. La resistenza
# stomatica è il parametro critico che differenzia le specie nel modello
# Penman-Monteith fisico: cresce passando da specie mesofile a xerofile.
SPECIE_DEL_BALCONE = [
    {
        "nome": "Basilico",
        "stomatal_resistance_s_m": 100.0,
        "crop_height_m": 0.30,
        "kc_mid_season": 1.05,   # da catalogo, per Penman-Monteith standard
    },
    {
        "nome": "Rosmarino",
        "stomatal_resistance_s_m": 200.0,
        "crop_height_m": 0.60,
        "kc_mid_season": 0.80,
    },
    {
        "nome": "Succulenta CAM",
        "stomatal_resistance_s_m": 500.0,
        "crop_height_m": 0.10,
        "kc_mid_season": 0.40,
    },
]


# =====================================================================
#  PARTE 1: confronto qualitativo delle tre formule sullo stesso giorno.
# =====================================================================
#
# Prima di entrare nella simulazione della settimana voglio darti un
# riferimento numerico per gli ordini di grandezza delle tre formule
# applicate allo stesso scenario. Questo ti aiuterà a interpretare i
# risultati della parte 2.

stampa_sezione("Parte 1: ordini di grandezza delle tre formule")

# Scenario di riferimento: 19 luglio 2026, giornata estiva tipica.
DATA_RIFERIMENTO = date(2026, 7, 19)
J_RIFERIMENTO = day_of_year(DATA_RIFERIMENTO)

# Dati meteo "completi" della giornata.
T_MIN_RIF = 20.0
T_MAX_RIF = 32.0
RH_RIF = 0.60
VENTO_RIF = 1.5
RS_RIF = 24.0  # MJ/m²/d, dal piranometro Ecowitt

# Calcoliamo Rn per chi usa Penman-Monteith.
ra_rif = extraterrestrial_radiation(LATITUDINE_MILANO, J_RIFERIMENTO)
ea_rif = actual_vapor_pressure((T_MIN_RIF + T_MAX_RIF) / 2, RH_RIF)
rn_rif = net_radiation(
    solar_radiation_mj=RS_RIF,
    extraterrestrial_radiation_mj=ra_rif,
    t_max_c=T_MAX_RIF, t_min_c=T_MIN_RIF,
    actual_vapor_pressure_kpa=ea_rif,
    elevation_m=QUOTA_MILANO_M,
)

print(f"""
  Scenario di riferimento: 19 luglio 2026 sul balcone milanese.
  T_min = {T_MIN_RIF}, T_max = {T_MAX_RIF}, RH = {RH_RIF*100:.0f}%,
  vento = {VENTO_RIF} m/s, Rs = {RS_RIF} MJ/m²/d → Rn = {rn_rif:.2f} MJ/m²/d.

  Ecco cosa restituisce il selettore per il basilico in tre scenari di
  disponibilità dei dati progressivamente più restrittivi:
""")

basilico = SPECIE_DEL_BALCONE[0]
common = dict(
    t_min=T_MIN_RIF, t_max=T_MAX_RIF,
    latitude_deg=LATITUDINE_MILANO, j=J_RIFERIMENTO,
    elevation_m=QUOTA_MILANO_M,
)

# Caso completo: tutti i dati disponibili.
res_full = compute_et(
    humidity_relative=RH_RIF, wind_speed_m_s=VENTO_RIF,
    net_radiation_mj_m2_day=rn_rif,
    stomatal_resistance_s_m=basilico["stomatal_resistance_s_m"],
    crop_height_m=basilico["crop_height_m"],
    **common,
)

# Caso medio: dati meteo completi ma niente parametri specie.
res_meteo_solo = compute_et(
    humidity_relative=RH_RIF, wind_speed_m_s=VENTO_RIF,
    net_radiation_mj_m2_day=rn_rif,
    **common,
)

# Caso minimo: solo le temperature (forecast da Open-Meteo).
res_temperatura_sola = compute_et(**common)

print(f"  Caso completo (PM fisico):    "
      f"ET = {res_full.value_mm:.2f} mm/d, "
      f"metodo = {res_full.method.value}")
print(f"  Caso medio (PM standard):     "
      f"ET₀ = {res_meteo_solo.value_mm:.2f} mm/d, "
      f"metodo = {res_meteo_solo.method.value}")
print(f"  Caso minimo (Hargreaves):     "
      f"ET₀ = {res_temperatura_sola.value_mm:.2f} mm/d, "
      f"metodo = {res_temperatura_sola.method.value}")

# Distinzione semantica importante: i metodi "STANDARD" e "HARGREAVES"
# producono ET₀ che va moltiplicata per il Kc; "PHYSICAL" produce
# direttamente ET. Mostriamo i tre valori di ET dopo l'applicazione del
# Kc dove necessario.
def applica_kc(risultato: EtResult, kc: float) -> float:
    """
    Applica il coefficiente colturale Kc al risultato del selettore se
    necessario. La logica è semplice ma critica: solo PENMAN_MONTEITH_PHYSICAL
    produce direttamente ET; gli altri due metodi producono ET₀ e
    richiedono la moltiplicazione per Kc per ottenere l'ET effettiva
    della specie.
    """
    if risultato.method == EtMethod.PENMAN_MONTEITH_PHYSICAL:
        return risultato.value_mm
    return risultato.value_mm * kc


print(f"""
  Applicando il Kc del basilico ({basilico["kc_mid_season"]}) dove
  necessario, le tre stime di ET effettiva sono:

    Caso completo:  ET = {applica_kc(res_full, basilico["kc_mid_season"]):.2f} mm/d
    Caso medio:     ET = {applica_kc(res_meteo_solo, basilico["kc_mid_season"]):.2f} mm/d
    Caso minimo:    ET = {applica_kc(res_temperatura_sola, basilico["kc_mid_season"]):.2f} mm/d

  Nota la dispersione: le tre stime variano del 15-20%. Questo è il
  motivo per cui la tracciabilità del metodo è preziosa: chi userà
  questi numeri per decidere l'irrigazione vuole sapere con quale
  formula sono stati prodotti.
""")


# =====================================================================
#  PARTE 2: simulazione della settimana con dati di qualità variabile.
# =====================================================================
#
# Adesso simuliamo una settimana realistica del balcone, dove ogni
# giorno la stazione Ecowitt produce dati di qualità diversa. Questo
# è il pattern operativo tipico di un dashboard agronomico: i dati che
# arrivano non sono mai perfettamente uniformi, e il sistema deve
# saper produrre una stima sempre, con la formula migliore applicabile
# in quel momento.

stampa_sezione("Parte 2: simulazione della settimana 19-25 luglio 2026")

# Definiamo la settimana di dati. Ogni giorno ha le temperature (sempre
# disponibili dal forecast Open-Meteo) ma quantità variabili degli altri
# dati a seconda di cosa la stazione Ecowitt ha registrato quel giorno.
# La struttura della giornata riflette gli inconvenienti tipici di un
# sistema di monitoraggio reale.
SETTIMANA = [
    # 19 lug: stazione perfettamente operativa, tutti i dati disponibili.
    {
        "data": date(2026, 7, 19), "t_min": 20.0, "t_max": 32.0,
        "humidity": 0.60, "wind": 1.5, "rs": 24.0,
        "nota": "stazione operativa, dati completi",
    },
    # 20 lug: come ieri, dati completi.
    {
        "data": date(2026, 7, 20), "t_min": 21.0, "t_max": 33.5,
        "humidity": 0.55, "wind": 2.0, "rs": 25.5,
        "nota": "stazione operativa, dati completi",
    },
    # 21 lug: anemometro guasto, manca solo il vento.
    {
        "data": date(2026, 7, 21), "t_min": 22.0, "t_max": 34.0,
        "humidity": 0.52, "wind": None, "rs": 26.0,
        "nota": "anemometro offline (manca vento)",
    },
    # 22 lug: piranometro guasto, manca solo la radiazione globale.
    {
        "data": date(2026, 7, 22), "t_min": 21.5, "t_max": 31.0,
        "humidity": 0.65, "wind": 1.8, "rs": None,
        "nota": "piranometro offline (manca Rs e quindi Rn)",
    },
    # 23 lug: connessione internet caduta, solo forecast Open-Meteo.
    {
        "data": date(2026, 7, 23), "t_min": 19.5, "t_max": 28.0,
        "humidity": None, "wind": None, "rs": None,
        "nota": "internet offline, solo temperature da forecast",
    },
    # 24 lug: stazione di nuovo operativa.
    {
        "data": date(2026, 7, 24), "t_min": 19.0, "t_max": 29.5,
        "humidity": 0.70, "wind": 1.2, "rs": 22.0,
        "nota": "stazione operativa, dati completi",
    },
    # 25 lug: igrometro guasto, manca l'umidità.
    {
        "data": date(2026, 7, 25), "t_min": 20.5, "t_max": 31.5,
        "humidity": None, "wind": 1.6, "rs": 24.5,
        "nota": "igrometro offline (manca umidità relativa)",
    },
]


def calcola_rn_se_possibile(giorno: dict) -> "float | None":
    """
    Calcola la radiazione netta Rn dai dati meteo del giorno se tutti i
    parametri necessari sono disponibili. Restituisce None altrimenti.

    La funzione net_radiation richiede Rs (radiazione globale misurata),
    le temperature min/max, l'umidità attuale ea, e la quota. Quando
    manca anche solo uno di questi ingredienti, non possiamo calcolare
    Rn e dobbiamo passare None al selettore.
    """
    if giorno["rs"] is None or giorno["humidity"] is None:
        return None

    j = day_of_year(giorno["data"])
    ra = extraterrestrial_radiation(LATITUDINE_MILANO, j)
    t_mean = (giorno["t_min"] + giorno["t_max"]) / 2
    ea = actual_vapor_pressure(t_mean, giorno["humidity"])
    return net_radiation(
        solar_radiation_mj=giorno["rs"],
        extraterrestrial_radiation_mj=ra,
        t_max_c=giorno["t_max"], t_min_c=giorno["t_min"],
        actual_vapor_pressure_kpa=ea,
        elevation_m=QUOTA_MILANO_M,
    )


def calcola_et_giornaliera(giorno: dict, specie: dict) -> EtResult:
    """
    Calcola l'ET di una specie per un giorno specifico, passando al
    selettore solo i dati effettivamente disponibili. La logica
    "tutto o niente" interna al selettore farà la scelta corretta:
    se manca anche solo uno dei dati meteo aggiuntivi, ricadrà
    automaticamente su Hargreaves.
    """
    rn = calcola_rn_se_possibile(giorno)
    return compute_et(
        t_min=giorno["t_min"],
        t_max=giorno["t_max"],
        latitude_deg=LATITUDINE_MILANO,
        j=day_of_year(giorno["data"]),
        humidity_relative=giorno["humidity"],
        wind_speed_m_s=giorno["wind"],
        net_radiation_mj_m2_day=rn,
        stomatal_resistance_s_m=specie["stomatal_resistance_s_m"],
        crop_height_m=specie["crop_height_m"],
        elevation_m=QUOTA_MILANO_M,
    )


# Simulazione: per ogni giorno e ogni specie, calcoliamo l'ET e
# raccogliamo i risultati per l'analisi finale.
print()
print(f"  {'Data':<12} {'Specie':<18} {'Metodo':<28} {'ET (mm/d)':<10}")
print(f"  {'-'*12} {'-'*18} {'-'*28} {'-'*10}")

risultati_settimana = []
for giorno in SETTIMANA:
    for specie in SPECIE_DEL_BALCONE:
        et_result = calcola_et_giornaliera(giorno, specie)
        et_effettiva = applica_kc(et_result, specie["kc_mid_season"])
        risultati_settimana.append({
            "data": giorno["data"],
            "specie": specie["nome"],
            "method": et_result.method,
            "value_raw": et_result.value_mm,
            "et_effettiva": et_effettiva,
            "nota": giorno["nota"],
        })
        print(f"  {giorno['data'].isoformat():<12} "
              f"{specie['nome']:<18} "
              f"{et_result.method.value:<28} "
              f"{et_effettiva:<10.2f}")
    # Riga vuota tra giorni diversi per leggibilità.
    print()


# =====================================================================
#  PARTE 3: analisi diagnostica della settimana.
# =====================================================================
#
# La parte interessante del selettore è che la sua tracciabilità ci
# permette di fare diagnostica della qualità della stima. Vediamo
# quante volte ogni metodo è stato usato durante la settimana, e
# confrontiamo con lo scenario "ideale" in cui avremmo avuto sempre
# tutti i dati.

stampa_sezione("Parte 3: analisi diagnostica della settimana")

stampa_sottosezione("Distribuzione dei metodi usati")

# Conta quante volte ogni metodo è stato selezionato nella settimana.
conteggi_metodi = {m: 0 for m in EtMethod}
for r in risultati_settimana:
    conteggi_metodi[r["method"]] += 1

totale = len(risultati_settimana)
print()
for method, count in conteggi_metodi.items():
    percentuale = count / totale * 100
    print(f"  {method.value:<28}: {count:2d} su {totale} "
          f"({percentuale:5.1f}%)")

stampa_sottosezione("ET cumulata per specie nella settimana")

# Per ogni specie, calcoliamo la sua ET cumulata sui sette giorni come
# sarebbe stata stimata col selettore sui dati realmente disponibili.
print()
for specie in SPECIE_DEL_BALCONE:
    et_settimana = sum(
        r["et_effettiva"]
        for r in risultati_settimana
        if r["specie"] == specie["nome"]
    )
    print(f"  {specie['nome']:<18}: {et_settimana:.1f} mm cumulati nella settimana")

stampa_sottosezione("Confronto con uno scenario \"ideale\" (dati sempre completi)")

# Questo è il pezzo più interessante diagnosticamente. Ricalcoliamo l'ET
# della settimana come se la stazione Ecowitt avesse funzionato
# perfettamente ogni giorno, fornendo dati meteo completi. Per i giorni
# in cui qualcosa mancava, riempiamo con valori "tipici" stagionali
# (umidità 60%, vento 1.5 m/s, Rs 23 MJ/m²/d).
def calcola_et_ideale(giorno: dict, specie: dict) -> EtResult:
    """
    Calcola l'ET come se la stazione meteo avesse fornito sempre tutti
    i dati. Per i giorni con dati mancanti, riempiamo con valori medi
    stagionali realistici per Milano in luglio.
    """
    humidity_filled = giorno["humidity"] if giorno["humidity"] is not None else 0.60
    wind_filled = giorno["wind"] if giorno["wind"] is not None else 1.5
    rs_filled = giorno["rs"] if giorno["rs"] is not None else 23.0

    j = day_of_year(giorno["data"])
    ra = extraterrestrial_radiation(LATITUDINE_MILANO, j)
    t_mean = (giorno["t_min"] + giorno["t_max"]) / 2
    ea = actual_vapor_pressure(t_mean, humidity_filled)
    rn = net_radiation(
        solar_radiation_mj=rs_filled,
        extraterrestrial_radiation_mj=ra,
        t_max_c=giorno["t_max"], t_min_c=giorno["t_min"],
        actual_vapor_pressure_kpa=ea,
        elevation_m=QUOTA_MILANO_M,
    )
    return compute_et(
        t_min=giorno["t_min"], t_max=giorno["t_max"],
        latitude_deg=LATITUDINE_MILANO, j=j,
        humidity_relative=humidity_filled,
        wind_speed_m_s=wind_filled,
        net_radiation_mj_m2_day=rn,
        stomatal_resistance_s_m=specie["stomatal_resistance_s_m"],
        crop_height_m=specie["crop_height_m"],
        elevation_m=QUOTA_MILANO_M,
    )


print()
print(f"  {'Specie':<18} {'ET reale (mm)':<18} {'ET ideale (mm)':<18} {'Scarto':<10}")
print(f"  {'-'*18} {'-'*18} {'-'*18} {'-'*10}")
for specie in SPECIE_DEL_BALCONE:
    et_reale = sum(
        r["et_effettiva"]
        for r in risultati_settimana
        if r["specie"] == specie["nome"]
    )
    et_ideale = sum(
        applica_kc(calcola_et_ideale(g, specie), specie["kc_mid_season"])
        for g in SETTIMANA
    )
    scarto_pct = (et_reale - et_ideale) / et_ideale * 100
    print(f"  {specie['nome']:<18} "
          f"{et_reale:<18.1f} "
          f"{et_ideale:<18.1f} "
          f"{scarto_pct:+.1f}%")

print(f"""
  L'analisi diagnostica mostra un fenomeno didatticamente importante:
  lo scarto tra "settimana reale" e "settimana ideale" non è uniforme
  tra le specie. Basilico e rosmarino mostrano scarti piccoli (sotto
  il 3%), mentre la succulenta CAM mostra uno scarto significativo
  (intorno al 20%).

  Questo non è un difetto del modello, è esattamente il valore aggiunto
  del Penman-Monteith fisico che l'esempio mette in luce. Il Kc del
  catalogo per la succulenta (0.40) è una correlazione empirica
  calibrata come valore medio. Hargreaves usa questo Kc generico e
  produce una stima "media" che funziona bene per condizioni standard
  ma sbaglia per le specie xerofile in condizioni specifiche. Penman-
  Monteith fisico, invece, applica direttamente la resistenza stomatica
  della specie (500 s/m per la succulenta CAM) all'equazione fisica,
  e cattura accuratamente il comportamento di una pianta che chiude
  gli stomi durante il giorno. Per le specie standard come basilico e
  rosmarino la differenza tra le due approcci è piccola perché il Kc
  empirico è ben calibrato; per le specie atipiche la differenza si
  amplifica.

  Per la fascia 3 di calibrazione, dove confronteremo previsioni con
  osservazioni millimetro per millimetro, conoscere quali giorni
  avevano dati completi e quali no è essenziale per interpretare le
  discrepanze. Una discrepanza del 15% in un giorno Hargreaves su una
  succulenta è "normale" (il Kc empirico fa quel che può); la stessa
  discrepanza in un giorno Penman-Monteith fisico segnala invece un
  possibile problema di calibrazione dei parametri fisiologici della
  specie. Senza tracciabilità del metodo distinguere i due casi è
  impossibile.
""")


# =====================================================================
#  PARTE 4: gestione degli errori sui parametri obbligatori.
# =====================================================================
#
# Il selettore richiede quattro parametri sempre obbligatori (le due
# temperature, latitudine e giorno). Se uno qualsiasi è None, solleva
# un'eccezione che identifica esplicitamente il parametro mancante,
# facilitando il debug del codice chiamante.

stampa_sezione("Parte 4: gestione degli errori")

print(f"""
  Il selettore distingue due categorie di parametri. I quattro parametri
  fondamentali (t_min, t_max, latitude_deg, j) sono sempre obbligatori
  perché servono al fallback Hargreaves. Gli altri sei parametri sono
  opzionali e influenzano solo la qualità della stima.

  Quando uno dei parametri obbligatori è None, il selettore solleva
  ValueError con un messaggio che identifica esplicitamente quale
  parametro manca:
""")

casi_errore = [
    ("t_min", dict(t_min=None, t_max=32.0, latitude_deg=45.47, j=200)),
    ("t_max", dict(t_min=20.0, t_max=None, latitude_deg=45.47, j=200)),
    ("latitude_deg", dict(t_min=20.0, t_max=32.0, latitude_deg=None, j=200)),
    ("j", dict(t_min=20.0, t_max=32.0, latitude_deg=45.47, j=None)),
]

for nome_param, kwargs in casi_errore:
    try:
        compute_et(**kwargs)
        print(f"  {nome_param}=None → FAIL: avrebbe dovuto sollevare errore")
    except ValueError as e:
        print(f"  {nome_param}=None → ValueError: \"{e}\"")

print(f"""
  Questi messaggi di errore sono progettati per essere immediatamente
  utili durante il debug. Quando un cliente del selettore fa un errore
  di programmazione passando None per un parametro obbligatorio,
  l'eccezione gli dice subito quale variabile correggere senza
  costringerlo a guardare la firma della funzione.
""")


# =====================================================================
#  CONCLUSIONI
# =====================================================================

stampa_sezione("Conclusioni")

print(f"""
  Quello che abbiamo visto in questo esempio è il selettore "best
  available" della sotto-tappa B in azione su uno scenario realistico.
  Gli aspetti chiave da portare a casa sono tre.

  Il primo è il valore architetturale del selettore. Il chiamante non
  deve sapere a priori quale formula sarà applicabile: passa al
  selettore tutti i dati che ha (con None per quelli mancanti) e il
  selettore sceglie la formula migliore. Questo riduce la complessità
  del codice chiamante e centralizza la logica di scelta in un singolo
  punto del modulo scientifico.

  Il secondo è la tracciabilità del metodo come strumento diagnostico.
  Il campo `method` di EtResult permette al chiamante di sapere a
  posteriori con quale livello di accuratezza è stata calcolata l'ET
  di ogni giorno. Per la fascia 3 di calibrazione questa informazione
  è essenziale: una discrepanza tra previsione e osservazione va
  interpretata diversamente a seconda della formula usata.

  Il terzo è la distinzione semantica tra ET₀ (i metodi STANDARD e
  HARGREAVES, che vanno moltiplicati per il Kc della specie) e ET
  (il metodo PHYSICAL, che non va moltiplicato). La funzione applica_kc
  che abbiamo definito in questo script mostra il pattern corretto:
  guarda il metodo restituito e applica il Kc solo dove necessario.
  L'integrazione col Pot della sotto-tappa C gestirà questa logica
  automaticamente, ma chi consuma direttamente le funzioni del layer
  scientifico deve conoscerla.

  La sotto-tappa C aprirà il prossimo capitolo, integrando il selettore
  nel ciclo di vita del Pot e del Garden e propagando la tracciabilità
  del metodo attraverso il FullStepResult del bilancio idrico
  giornaliero.
""")

print("=" * 72)
print(f"  Esempio completato. Per i dettagli vedi CHANGELOG-tappa5-B.md")
print("=" * 72)
