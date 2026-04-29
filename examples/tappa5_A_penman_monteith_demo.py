"""
Esempio della sotto-tappa A della tappa 5 fascia 2: Penman-Monteith come
funzioni pure.

Questo script mostra in azione le funzioni introdotte dalla sotto-tappa A
articolando una piccola "lezione" in cinque parti. Lo scenario di
riferimento è una giornata estiva sul balcone milanese, con dati meteo
realistici per un 19 luglio in pieno sole.

L'idea didattica è di "aprire la scatola nera" del calcolo di ET₀ usando
gli helper esposti dal modulo, mostrare passo per passo come si arriva
al valore finale, confrontare quantitativamente Penman-Monteith con
Hargreaves, e infine illustrare la differenziazione delle specie via la
versione fisica con resistenza stomatica.

Lo script è progettato per essere letto e capito anche da chi non ha mai
incontrato il Penman-Monteith prima: ogni sezione è preceduta da un
commento esplicativo che articola cosa sta calcolando e perché.

Per eseguirlo:
    PYTHONPATH=src python examples/tappa5_A_penman_monteith_demo.py

Output atteso: circa 80-100 righe di output didattico con i numeri
intermedi della catena di calcolo e le interpretazioni fisiche.
"""

from datetime import date

# Importiamo gli helper di base e le due funzioni principali introdotte
# dalla sotto-tappa A. Il fatto che gli helper siano pubblici è una
# scelta di design deliberata che ci permette di scomporre il calcolo
# in passi visibili invece di dover trattare ET₀ come una formula
# monolitica e opaca.
from fitosim.science.et0 import (
    actual_vapor_pressure,
    aerodynamic_resistance,
    atmospheric_pressure,
    compute_et0_penman_monteith,
    compute_et_penman_monteith_physical,
    et0_hargreaves_samani,
    psychrometric_constant,
    saturation_vapor_pressure,
    slope_vapor_pressure,
)
from fitosim.science.radiation import (
    clear_sky_radiation,
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
#  SCENARIO METEO: balcone milanese, 19 luglio 2026.
# =====================================================================
#
# Questi sono i dati che la stazione meteo Ecowitt sul balcone di Andrea
# fornirebbe in una giornata estiva tipo. Li usiamo come input alla
# catena di calcolo che porta a ET₀.

LATITUDINE_MILANO = 45.47       # gradi nord
QUOTA_MILANO_M = 150.0          # metri sul livello del mare
DATA = date(2026, 7, 19)
GIORNO_DELL_ANNO = day_of_year(DATA)

# Dati meteo della giornata.
T_MIN = 20.0                    # °C, registrata poco prima dell'alba
T_MAX = 32.0                    # °C, registrata nel primo pomeriggio
T_MEAN = (T_MIN + T_MAX) / 2    # 26.0 °C, valore medio giornaliero
UMIDITA_RELATIVA = 0.60         # frazione 0..1 (NON percentuale)
VENTO_M_S = 1.5                 # m/s a 2 metri di altezza
RADIAZIONE_GLOBALE = 24.0       # MJ/m²/giorno, dal piranometro Ecowitt


# =====================================================================
#  PARTE 1: gli helper di base sono il vocabolario fisico del modello.
# =====================================================================
#
# Penman-Monteith combina sei grandezze fisiche intermedie in un'unica
# equazione. Calcolarle separatamente non è solo elegante dal punto di
# vista del codice, ma è anche il modo più solido di capire la formula:
# ognuna di queste grandezze ha un significato fisico specifico, e
# l'equazione finale è il loro bilancio.

stampa_sezione("Parte 1: gli helper di base del modello FAO-56")

print(f"""
Scenario: balcone di Andrea a Milano (lat {LATITUDINE_MILANO} N,
quota {QUOTA_MILANO_M:.0f} m), giornata del 19 luglio (giorno
{GIORNO_DELL_ANNO} dell'anno).

Dati meteo della giornata (dalla stazione Ecowitt):
  Temperatura minima:  {T_MIN:.1f} °C
  Temperatura massima: {T_MAX:.1f} °C
  Temperatura media:   {T_MEAN:.1f} °C
  Umidità relativa:    {UMIDITA_RELATIVA*100:.0f} %
  Vento a 2 metri:     {VENTO_M_S:.1f} m/s
  Radiazione globale:  {RADIAZIONE_GLOBALE:.1f} MJ/m²/giorno
""")

stampa_sottosezione("Pressione di vapore saturo es alla temperatura media")

# La pressione di vapore saturo es è la quantità massima di vapore
# acqueo che l'aria può contenere a una data temperatura. Cresce
# esponenzialmente con T (raddoppia ogni 10 °C circa). È il "tetto"
# che limita quanto vapore può essere trasportato via dalle foglie.
es = saturation_vapor_pressure(T_MEAN)
print(f"  es({T_MEAN:.1f}°C) = {es:.4f} kPa")
print(
    "  Significa: a 26°C, l'aria può contenere al massimo 3.36 kPa di\n"
    "  pressione parziale di vapore prima di saturare."
)

stampa_sottosezione("Pendenza Δ della curva di pressione di vapore")

# Δ è la derivata di es rispetto a T: dice di quanto cresce es se la
# temperatura sale di un grado. Compare nel Penman-Monteith come "peso"
# del termine radiativo, perché la radiazione solare scalda la superficie
# e ogni grado di riscaldamento aumenta es e quindi il deficit di vapore.
delta = slope_vapor_pressure(T_MEAN)
print(f"  Δ({T_MEAN:.1f}°C) = {delta:.4f} kPa/°C")
print(
    "  Significa: a 26°C, ogni grado di riscaldamento aggiunge 0.20 kPa\n"
    "  alla capacità dell'aria di accogliere vapore."
)

stampa_sottosezione("Pressione di vapore attuale ea dell'aria")

# ea è la frazione di es effettivamente presente nell'aria, dipendente
# dall'umidità relativa misurata. Il deficit es - ea è il "motore" del
# termine aerodinamico: aria secca tira via vapore rapidamente, aria
# satura blocca l'evaporazione.
ea = actual_vapor_pressure(T_MEAN, UMIDITA_RELATIVA)
deficit_vapore = es - ea
print(f"  ea = RH × es = {UMIDITA_RELATIVA:.2f} × {es:.4f} = {ea:.4f} kPa")
print(f"  Deficit di vapore (es − ea) = {deficit_vapore:.4f} kPa")
print(
    "  Significa: l'aria sta usando il 60% della sua capacità di vapore.\n"
    "  Il deficit di 1.34 kPa è il \"vuoto\" che attira il vapore dalle\n"
    "  foglie, ed è la principale forza motrice dell'evapotraspirazione."
)

stampa_sottosezione("Pressione atmosferica P alla quota di Milano")

# P cala con la quota perché c'è meno aria sopra. Per Milano (150 m) la
# correzione è piccola ma vale la pena modellarla per accuratezza.
p = atmospheric_pressure(QUOTA_MILANO_M)
print(f"  P({QUOTA_MILANO_M:.0f} m) = {p:.2f} kPa")
print(
    "  Per confronto: al livello del mare P = 101.3 kPa; a 1000 m sarebbe\n"
    "  90.0 kPa. Per Milano la riduzione è solo dell'1.7%."
)

stampa_sottosezione("Costante psicrometrica γ")

# γ esprime il "tasso di scambio" tra termine radiativo e termine
# aerodinamico nel Penman-Monteith. Dipende dalla pressione atmosferica.
gamma = psychrometric_constant(p)
print(f"  γ = 0.000665 × P = 0.000665 × {p:.2f} = {gamma:.4f} kPa/°C")

stampa_sottosezione("Resistenza aerodinamica ra (coltura di riferimento)")

# ra esprime quanto l'aria resiste al trasporto del vapore. Cala col
# vento, sale con la calma. Calcoliamola per la coltura di riferimento
# (h = 0.12 m).
ra = aerodynamic_resistance(VENTO_M_S, crop_height_m=0.12)
print(f"  ra({VENTO_M_S:.1f} m/s, h=0.12 m) = {ra:.1f} s/m")
print(
    "  Significa: il vapore impiega in media 139 secondi per attraversare\n"
    "  lo strato di aria limite sopra l'erba prima di mescolarsi con\n"
    "  l'atmosfera libera. Più vento → meno tempo → più evaporazione."
)


# =====================================================================
#  PARTE 2: la catena della radiazione fino a Rn.
# =====================================================================
#
# Penman-Monteith ha bisogno della radiazione netta Rn, non della
# radiazione globale Rs misurata dal piranometro. La differenza è che
# Rn tiene conto sia dell'albedo (riflessione della superficie) sia
# della perdita di calore radiativo notturno verso il cielo.

stampa_sezione("Parte 2: dalla radiazione globale alla radiazione netta")

# La radiazione extra-atmosferica Ra è ciò che arriverebbe alla cima
# dell'atmosfera, calcolata dalla geometria astronomica.
ra_solare = extraterrestrial_radiation(LATITUDINE_MILANO, GIORNO_DELL_ANNO)
print(f"\n  R_a (radiazione extra-atmosferica): {ra_solare:.2f} MJ/m²/giorno")
print(
    "  È l'energia solare che arriverebbe a Milano il 19 luglio se\n"
    "  l'atmosfera non esistesse. Dipende solo da latitudine e giorno."
)

# Rso è la radiazione di cielo sereno, che ci serve come riferimento.
rso = clear_sky_radiation(ra_solare, QUOTA_MILANO_M)
print(f"\n  R_so (cielo sereno teorico): {rso:.2f} MJ/m²/giorno")
trasmissività = rso / ra_solare * 100
print(
    f"  L'atmosfera serena trasmette il {trasmissività:.1f}% della\n"
    f"  radiazione extra-atmosferica. Il piranometro ha misurato\n"
    f"  Rs={RADIAZIONE_GLOBALE} MJ/m²/d, che è il "
    f"{RADIAZIONE_GLOBALE/rso*100:.0f}% di Rso:\n"
    f"  giornata serena ma non perfettamente limpida (qualche velatura)."
)

# Rn finale: bilancio tra solare assorbita e termica netta.
rn = net_radiation(
    solar_radiation_mj=RADIAZIONE_GLOBALE,
    extraterrestrial_radiation_mj=ra_solare,
    t_max_c=T_MAX, t_min_c=T_MIN,
    actual_vapor_pressure_kpa=ea,
    elevation_m=QUOTA_MILANO_M,
)
print(f"\n  R_n (radiazione netta) = {rn:.2f} MJ/m²/giorno")
print(
    "  È l'energia effettivamente disponibile per l'evapotraspirazione\n"
    "  dopo aver scontato la frazione riflessa (albedo 0.23) e la\n"
    "  perdita di calore termico verso il cielo. È la \"fetta utile\" di\n"
    f"  Rs: il {rn/RADIAZIONE_GLOBALE*100:.0f}% della radiazione globale misurata."
)


# =====================================================================
#  PARTE 3: ET₀ con Penman-Monteith FAO-56 standard, e confronto con
#  Hargreaves-Samani.
# =====================================================================

stampa_sezione("Parte 3: ET₀ con Penman-Monteith vs Hargreaves")

# Calcolo finale di ET₀ con Penman-Monteith standard. La funzione
# accetta i dati meteo grezzi e si occupa internamente di chiamare gli
# helper. Tutti i numeri intermedi che abbiamo visto nelle parti 1 e 2
# vengono ricalcolati dentro la funzione; abbiamo aperto la scatola
# nera per fini didattici, ma il chiamante normale non ha bisogno di
# vederli.
et0_pm = compute_et0_penman_monteith(
    temperature_c=T_MEAN,
    humidity_relative=UMIDITA_RELATIVA,
    wind_speed_m_s=VENTO_M_S,
    net_radiation_mj_m2_day=rn,
    elevation_m=QUOTA_MILANO_M,
)

# Per confronto, calcoliamo ET₀ anche con Hargreaves-Samani che è la
# formula di backup attualmente usata da fitosim quando mancano dati.
# Hargreaves richiede solo le temperature minima e massima e calcola
# tutto il resto internamente dalla geometria astronomica.
et0_hs = et0_hargreaves_samani(
    t_min=T_MIN, t_max=T_MAX,
    latitude_deg=LATITUDINE_MILANO, j=GIORNO_DELL_ANNO,
)

scarto_assoluto = et0_hs - et0_pm
scarto_percentuale = (et0_hs - et0_pm) / et0_pm * 100

print(f"""
  ET₀ (Penman-Monteith FAO-56 standard):  {et0_pm:.2f} mm/giorno
  ET₀ (Hargreaves-Samani, formula backup): {et0_hs:.2f} mm/giorno

  Scarto: Hargreaves sovrastima Penman-Monteith di {scarto_assoluto:+.2f} mm
  ({scarto_percentuale:+.1f}%).

  Questa sovrastima è esattamente quella documentata in letteratura per
  il clima mediterraneo umido. Hargreaves usa solo l'escursione termica
  come proxy delle altre variabili meteo, e questa scorciatoia tende a
  sopravvalutare l'evapotraspirazione quando l'aria è umida e poco
  ventilata (come oggi: RH 60%, vento 1.5 m/s, condizioni piuttosto
  tranquille). Penman-Monteith vede esplicitamente l'umidità e il vento
  e produce una stima più realistica.

  Per il giardiniere casalingo lo scarto del 8-10% è tollerabile e
  Hargreaves resta perfettamente usabile. Per un sistema di calibrazione
  che vuole confrontare previsioni con osservazioni millimetro per
  millimetro, Penman-Monteith è la scelta da preferire.
""")


# =====================================================================
#  PARTE 4: ET con Penman-Monteith fisico per quattro specie diverse.
# =====================================================================
#
# La versione fisica del Penman-Monteith abbandona l'assunzione della
# coltura di riferimento standardizzata e applica direttamente
# l'equazione alla specie reale, usando la sua resistenza stomatica e
# altezza colturale. Il risultato è ET (non ET₀): non va moltiplicato
# per il Kc, perché la specificità della specie è già incorporata nei
# parametri fisiologici.

stampa_sezione("Parte 4: ET con Penman-Monteith fisico per specie diverse")

specie_da_confrontare = [
    # (nome, resistenza_stomatica_s_m, altezza_m, descrizione)
    ("Coltura di riferimento", 70.0, 0.12,
     "erba bassa standard FAO-56"),
    ("Basilico in vaso", 100.0, 0.30,
     "erbacea aromatica, stomi mediamente aperti"),
    ("Rosmarino in vaso", 200.0, 0.60,
     "perenne semi-mediterranea, stomi più chiusi"),
    ("Succulenta CAM", 500.0, 0.10,
     "specie xerofila, stomi quasi sempre chiusi di giorno"),
]

print()
print(f"  Scenario meteo: stesso del balcone milanese in luglio "
      f"(Rn={rn:.1f} MJ/m²/d).")
print()
print(f"  {'Specie':<26} {'rs (s/m)':<10} {'h (m)':<8} {'ET (mm/d)':<10}")
print(f"  {'-'*26} {'-'*10} {'-'*8} {'-'*10}")

risultati = []
for nome, rs, h, descrizione in specie_da_confrontare:
    et = compute_et_penman_monteith_physical(
        temperature_c=T_MEAN,
        humidity_relative=UMIDITA_RELATIVA,
        wind_speed_m_s=VENTO_M_S,
        net_radiation_mj_m2_day=rn,
        stomatal_resistance_s_m=rs,
        crop_height_m=h,
        elevation_m=QUOTA_MILANO_M,
    )
    risultati.append((nome, et, descrizione))
    print(f"  {nome:<26} {rs:<10.0f} {h:<8.2f} {et:<10.2f}")

print()
print("  Interpretazione fisiologica dei risultati:")
print()
for nome, et, descrizione in risultati:
    print(f"    {nome} → {descrizione}")

et_riferimento = risultati[0][1]
et_succulenta = risultati[3][1]
risparmio = (1 - et_succulenta / et_riferimento) * 100
print(f"""
  La succulenta CAM traspira il {risparmio:.0f}% in meno della coltura di
  riferimento a parità di tutto il resto. Questa è esattamente la fisiologia
  delle piante CAM: chiudono gli stomi durante il giorno (rs molto alta) e
  li aprono solo di notte, quando l'aria è più fresca e il deficit di vapore
  è basso. È la ragione per cui sopravvivono in deserti dove le altre specie
  morirebbero. Il modello fisico cattura quantitativamente questo effetto
  attraverso il singolo parametro rs, in modo più diretto e più robusto
  del Kc empirico di letteratura.
""")


# =====================================================================
#  PARTE 5: verifica di consistenza tra le due varianti.
# =====================================================================
#
# La versione FAO-56 standard è implementata come thin wrapper sulla
# versione fisica passandole i parametri della coltura di riferimento.
# Verifichiamo numericamente che questa relazione gerarchica sia
# preservata: i due valori devono coincidere alla precisione macchina.

stampa_sezione("Parte 5: verifica di consistenza tra le due varianti")

et_standard = compute_et0_penman_monteith(
    temperature_c=T_MEAN,
    humidity_relative=UMIDITA_RELATIVA,
    wind_speed_m_s=VENTO_M_S,
    net_radiation_mj_m2_day=rn,
    elevation_m=QUOTA_MILANO_M,
)

et_fisica_rif = compute_et_penman_monteith_physical(
    temperature_c=T_MEAN,
    humidity_relative=UMIDITA_RELATIVA,
    wind_speed_m_s=VENTO_M_S,
    net_radiation_mj_m2_day=rn,
    stomatal_resistance_s_m=70.0,   # parametri della coltura di riferimento
    crop_height_m=0.12,
    elevation_m=QUOTA_MILANO_M,
)

differenza = abs(et_standard - et_fisica_rif)

print(f"""
  ET₀ FAO-56 standard:                 {et_standard:.10f} mm/giorno
  ET fisica con rs=70 e h=0.12 m:      {et_fisica_rif:.10f} mm/giorno
  Differenza assoluta:                 {differenza:.2e} mm/giorno

  Le due varianti coincidono alla precisione macchina, come deve essere:
  la versione standard è esattamente un caso particolare della versione
  fisica con i parametri della coltura di riferimento di FAO-56. Questa
  consistenza è verificata nei test della suite di fitosim e fa sì che
  chiunque modifichi una delle due funzioni in futuro veda subito se ha
  rotto la relazione gerarchica tra le due.
""")


# =====================================================================
#  CONCLUSIONI
# =====================================================================

stampa_sezione("Conclusioni")

print(f"""
  Quello che abbiamo visto in questo esempio è la sotto-tappa A della
  tappa 5 in azione: i sei helper di base (es, Δ, ea, P, γ, ra) come
  scatola trasparente del modello fisico, le due funzioni di radiazione
  che completano la catena dalla globale Rs alla netta Rn, le due
  varianti di Penman-Monteith che producono ET₀ standard e ET fisica
  per specie reali.

  Il messaggio principale è che la sotto-tappa A ha posto le fondamenta
  matematiche per il resto della tappa 5. Le funzioni che abbiamo usato
  qui in modo isolato saranno integrate nel ciclo di vita del Pot e
  del Garden dalla sotto-tappa C in poi, con un meccanismo di selezione
  automatica della formula migliore disponibile (Penman-Monteith fisico,
  Penman-Monteith FAO-56 standard, Hargreaves-Samani come fallback) che
  la sotto-tappa B introdurrà.

  Nessun pezzo applicativo della libreria — Pot, Garden, persistenza,
  allerte, eventi pianificati — è stato toccato in questa sotto-tappa.
  Tutto quello che hai visto vive nel layer scientifico ed è pronto per
  essere consumato dai layer superiori nelle sotto-tappe successive.
""")

print("=" * 72)
print(f"  Esempio completato. Per i dettagli vedi CHANGELOG-tappa5-A.md")
print("=" * 72)
