"""
Evapotraspirazione di riferimento ET₀ con due formule complementari:
Hargreaves-Samani (formula di backup) e Penman-Monteith FAO-56 (formula
di riferimento internazionale, in versione standard e in versione fisica
con resistenza stomatica della specie).

ET₀ è l'evapotraspirazione giornaliera di una coltura di riferimento
ipotetica e standardizzata (prato verde, 12 cm di altezza, resistenza
stomatica 70 s/m, albedo 0.23, ben irrigato, vasta estensione). Dipende
soltanto dalle condizioni meteorologiche del sito ed è la "domanda
atmosferica" comune a tutte le piante in quel luogo. L'evapotraspirazione
effettiva di una specie specifica si ottiene moltiplicando ET₀ per il
coefficiente colturale Kc di quella specie nel suo stadio fenologico
corrente: ET_c = Kc × ET₀.

Le due formule che il modulo implementa servono casi d'uso diversi e si
completano a vicenda. Hargreaves-Samani (1985) è la via d'ingresso più
semplice: richiede soltanto temperature min/max del giorno e la radiazione
extra-atmosferica R_a (che calcoliamo in `fitosim.science.radiation`).
È meno accurata di Penman-Monteith in climi ventilati, ma ha l'enorme
vantaggio di non richiedere dati di vento e umidità, che nelle stazioni
domestiche sono spesso mancanti, rumorosi o di qualità non chiara. FAO-56
stessa la raccomanda come fallback quando non si dispone di dati meteo
completi.

Penman-Monteith FAO-56 è invece il riferimento internazionale per il
calcolo accurato di ET₀ quando hai a disposizione i quattro ingredienti
meteo completi: temperatura, umidità relativa, velocità del vento e
radiazione netta. Combina un termine "radiativo" (l'energia disponibile)
e un termine "aerodinamico" (la capacità dell'aria di trasportare via il
vapore) modulati dalla pendenza della curva di pressione di vapore e dalla
costante psicrometrica. Il modulo espone due varianti: la versione
standard FAO-56 che assume i parametri della coltura di riferimento (rs=70
s/m, h=12 cm), e la versione fisica che applica direttamente la formula
alla specie reale usando la sua resistenza stomatica e altezza colturale.
Quest'ultima è più accurata in condizioni anomale e per specie che
deviano dalla coltura di riferimento (succulente, perenni legnose).

Il trucco intellettuale di Hargreaves-Samani è usare l'escursione termica
giornaliera (T_max − T_min) come proxy di tre variabili normalmente
misurate separatamente — radiazione netta, nuvolosità e umidità
atmosferica — sfruttando il fatto che giornate limpide e secche hanno
grande escursione mentre giornate nuvolose e umide ne hanno poca.
Penman-Monteith fa l'opposto: misura tutto esplicitamente e arriva a una
stima fisicamente fondata.

Riferimenti:
    Hargreaves, G. H., & Samani, Z. A. (1985). Reference crop
    evapotranspiration from temperature. Applied Engineering in
    Agriculture, 1(2), 96-99.

    Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998). Crop
    evapotranspiration: Guidelines for computing crop water requirements.
    FAO Irrigation and Drainage Paper 56. Food and Agriculture
    Organization of the United Nations, Rome.
"""

import math

from fitosim.science.radiation import extraterrestrial_radiation


# Calore latente di vaporizzazione dell'acqua, riferito a circa 20 °C,
# in MJ/kg. Poiché 1 kg di acqua distribuita come film uniforme su 1 m²
# di superficie corrisponde a uno spessore di 1 mm (l'acqua ha densità
# 1000 kg/m³), questa costante si legge equivalentemente come
# MJ/(m² · mm): l'energia necessaria a evaporare uno strato di 1 mm
# d'acqua da 1 m². È la "chiave di conversione" tra linguaggio energetico
# (MJ/m²) e linguaggio idrologico (mm), in cui il bilancio idrico si
# esprime naturalmente.
LATENT_HEAT_VAPORIZATION = 2.45  # MJ / kg  (≡ MJ / (m² × mm))


def mj_per_m2_to_mm_water(radiation_mj: float) -> float:
    """
    Converte un flusso di energia in MJ/m²/giorno nel suo "equivalente
    in acqua" espresso in mm/giorno.

    Significato fisico: "se tutta questa energia fosse spesa per
    vaporizzare acqua, quanta ne evaporerebbe, misurata come spessore
    uniforme del film evaporato?". È una conversione lineare attraverso
    il calore latente di vaporizzazione, e permette di sommare
    direttamente radiazione, precipitazione e irrigazione nel bilancio
    idrico giornaliero.

    Esempio: 24.5 MJ/m² ↔ 10 mm d'acqua evaporabili.
    """
    return radiation_mj / LATENT_HEAT_VAPORIZATION


# =====================================================================
#  Helper di base del Penman-Monteith (FAO-56 capitoli 3 e 4).
#
#  Le sei funzioni che seguono sono i mattoni elementari che la formula
#  di Penman-Monteith compone insieme. Le esponiamo come funzioni
#  pubbliche perché sono utili anche fuori dal contesto di Penman-Monteith
#  (per esempio per fare diagnostica del modello, o per confrontare i
#  numeri della tua stazione meteo coi valori di letteratura), e perché
#  testarle separatamente è il modo più solido di assicurare la
#  correttezza della formula complessiva.
# =====================================================================


def saturation_vapor_pressure(temperature_c: float) -> float:
    """
    Pressione di vapore saturo es alla temperatura specificata, in kPa.

    Significato fisico: la quantità massima di vapore acqueo che l'aria
    può contenere a quella temperatura prima che il vapore in eccesso
    cominci a condensare. Cresce esponenzialmente con la temperatura
    (raddoppia ogni circa 10 °C) ed è il riferimento contro cui si
    misurano umidità relativa e umidità attuale: l'aria al 50% di
    umidità relativa contiene metà del vapore saturo possibile a quella
    temperatura.

    Formula (FAO-56 equazione 11), correlazione di Tetens-Murray:

        es = 0.6108 × exp(17.27 × T / (T + 237.3))

    dove T è in °C ed es esce in kPa. La forma esponenziale riflette la
    relazione di Clausius-Clapeyron tra temperatura e tensione di vapore.

    Valori tipici: a 0 °C, es ≈ 0.611 kPa; a 20 °C, es ≈ 2.339 kPa; a
    40 °C, es ≈ 7.384 kPa. La crescita molto rapida con la temperatura
    è la ragione fisica per cui le piante traspirano molto più
    intensamente in giornate calde anche se l'umidità relativa è la
    stessa: il deficit di pressione di vapore (es − ea) è molto più
    grande perché es cresce esponenzialmente.
    """
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def slope_vapor_pressure(temperature_c: float) -> float:
    """
    Pendenza Δ della curva di pressione di vapore saturo alla temperatura
    specificata, in kPa/°C.

    Significato fisico: di quanto aumenta la pressione di vapore saturo
    se la temperatura sale di un grado. È la derivata di es rispetto a T
    e compare nel Penman-Monteith come "peso" del termine radiativo:
    quando Δ è grande (cioè quando es cambia rapidamente con T) anche
    una piccola variazione di temperatura indotta dalla radiazione
    solare produce una grande variazione del deficit di vapore, e quindi
    favorisce un'evaporazione più rapida.

    Formula (FAO-56 equazione 13):

        Δ = 4098 × es / (T + 237.3)²

    derivata analiticamente dall'espressione di Tetens-Murray per es.

    Valori tipici: a 0 °C, Δ ≈ 0.044 kPa/°C; a 20 °C, Δ ≈ 0.145 kPa/°C;
    a 40 °C, Δ ≈ 0.358 kPa/°C. Cresce con la temperatura per la stessa
    ragione esponenziale di es.
    """
    es = saturation_vapor_pressure(temperature_c)
    return 4098.0 * es / (temperature_c + 237.3) ** 2


def actual_vapor_pressure(
    temperature_c: float, humidity_relative: float,
) -> float:
    """
    Pressione di vapore attuale ea dell'aria, in kPa.

    Significato fisico: la quantità di vapore acqueo effettivamente
    presente nell'aria. È sempre minore o uguale alla pressione di
    vapore saturo es alla stessa temperatura (uguale solo a saturazione,
    100% di umidità relativa). Il deficit es − ea è il "motore" del
    termine aerodinamico del Penman-Monteith: aria secca (deficit
    grande) tira via vapore dalla foglia rapidamente; aria satura
    (deficit zero) blocca l'evaporazione.

    Formula (FAO-56 equazione 19): per umidità relativa fornita come
    valore singolo medio giornaliero,

        ea = (RH / 100) × es(T)

    Per simulazioni più accurate la pubblicazione FAO-56 raccomanda di
    usare l'umidità relativa massima e minima della giornata, ma per
    fitosim — che lavora con dati medi forniti dalla stazione domestica
    — questa formulazione è sufficiente.

    Parametri
    ---------
    humidity_relative : float
        Umidità relativa come frazione tra 0 e 1 (NON percentuale).
        Esempio: 65% di umidità si esprime come 0.65.

    Solleva
    -------
    ValueError
        Se humidity_relative è fuori dall'intervallo [0, 1].
    """
    if not 0.0 <= humidity_relative <= 1.0:
        raise ValueError(
            f"humidity_relative ({humidity_relative}) deve essere una "
            f"frazione tra 0 e 1 (per il 65% passa 0.65, non 65)."
        )
    return humidity_relative * saturation_vapor_pressure(temperature_c)


def atmospheric_pressure(elevation_m: float) -> float:
    """
    Pressione atmosferica P alla quota specificata, in kPa.

    Significato fisico: la pressione esercitata dall'aria sopra la
    superficie. Cala con la quota perché c'è meno aria sopra. Compare
    nel Penman-Monteith attraverso la costante psicrometrica γ, che è
    proporzionale a P: a quote più alte la stessa quantità di vapore
    produce un effetto psicrometrico minore, perché l'aria è più rarefatta.

    Formula (FAO-56 equazione 7), modello atmosferico standard
    semplificato:

        P = 101.3 × ((293 - 0.0065 × z) / 293)^5.26

    dove z è la quota in metri sul livello del mare. È una buona
    approssimazione fino a circa 3000 m.

    Valori tipici: P ≈ 101.3 kPa al livello del mare; P ≈ 99.4 kPa a
    150 m (Milano); P ≈ 89.9 kPa a 1000 m; P ≈ 79.5 kPa a 2000 m. Per
    il giardinaggio domestico italiano la variazione di P è piccola
    (qualche percento) ma vale la pena modellarla per accuratezza.
    """
    return 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant(atmospheric_pressure_kpa: float) -> float:
    """
    Costante psicrometrica γ alla pressione atmosferica specificata, in
    kPa/°C.

    Significato fisico: il "tasso di scambio" tra il termine radiativo
    e il termine aerodinamico nel Penman-Monteith. Combina il calore
    specifico dell'aria, la pressione atmosferica, il rapporto dei pesi
    molecolari di vapore e aria secca, e il calore latente di
    vaporizzazione. Il nome "psicrometrica" deriva dallo psicrometro,
    lo strumento storicamente usato per misurare l'umidità dell'aria
    per via termica (un termometro a bulbo bagnato + uno secco).

    Formula (FAO-56 equazione 8):

        γ = (cp × P) / (ε × λ)

    dove cp = 1.013 × 10⁻³ MJ/(kg·°C) è il calore specifico dell'aria
    a pressione costante, ε = 0.622 è il rapporto dei pesi molecolari
    H₂O/aria, λ = 2.45 MJ/kg è il calore latente di vaporizzazione.
    Sostituendo le costanti la formula si semplifica a γ ≈ 0.000665 × P.

    Valori tipici: γ ≈ 0.0673 kPa/°C al livello del mare; γ ≈ 0.0661
    kPa/°C a 150 m. Varia poco perché P stessa varia poco a quote
    domestiche. Storicamente si usava un valore "tabulato" fisso, ma
    qui ricalcoliamo per coerenza con la quota dichiarata dal chiamante.
    """
    return 0.000665 * atmospheric_pressure_kpa


def aerodynamic_resistance(
    wind_speed_m_s: float, crop_height_m: float = 0.12,
) -> float:
    """
    Resistenza aerodinamica ra al trasporto di vapore, in s/m.

    Significato fisico: quanto l'aria "resiste" al trasporto del vapore
    acqueo dalla superficie evaporante (le foglie) verso l'atmosfera
    libera. È bassa quando c'è vento (l'aria è ben mescolata, il vapore
    viene portato via rapidamente) e alta quando l'aria è ferma. Compare
    al denominatore del termine aerodinamico del Penman-Monteith:
    resistenza alta significa termine aerodinamico piccolo, cioè poca
    evaporazione "tirata via dal vento".

    Formula (FAO-56 equazione 4), per coltura standardizzata con vento
    misurato a 2 m di altezza:

        ra = ln((zm - d)/zom) × ln((zh - d)/zoh) / (k² × u₂)

    dove zm = zh = 2 m è l'altezza di misura, d = 0.667·h è
    l'altezza di "displacement zero" (lo strato di aria stagnante
    sopra la coltura), zom = 0.123·h è la rugosità per momentum,
    zoh = 0.0123·h è la rugosità per il calore, k = 0.41 è la costante
    di von Kármán, u₂ è il vento a 2 m di altezza.

    Per la coltura di riferimento standard FAO-56 (h = 0.12 m), questa
    espressione si semplifica a:

        ra ≈ 208 / u₂

    che è la versione "abbreviata" che troverai nelle implementazioni
    rapide. Qui la calcoliamo nella forma generale perché ci serve
    parametrizzata su h diversi (la versione fisica del Penman-Monteith
    la userà con l'altezza colturale reale della specie).

    Parametri
    ---------
    wind_speed_m_s : float
        Velocità del vento a 2 m di altezza, in m/s. Per dati misurati
        a 10 m (stazioni meteo standard) si dovrebbe convertire prima
        a 2 m via la formula del profilo logaritmico, ma la conversione
        è un'operazione separata che non facciamo qui.
    crop_height_m : float, default 0.12
        Altezza colturale in metri. Il default 0.12 m corrisponde alla
        coltura di riferimento standard FAO-56 (erba bassa).

    Solleva
    -------
    ValueError
        Se wind_speed_m_s ≤ 0 o crop_height_m ≤ 0. Vento nullo
        produrrebbe ra infinita, vanificando il termine aerodinamico
        della formula; il chiamante che voglia "vento ferma" deve
        passare un valore minimo simbolico (la pratica agronomica usa
        0.5 m/s come "vento minimo convettivo" indoor).
    """
    if wind_speed_m_s <= 0:
        raise ValueError(
            f"wind_speed_m_s ({wind_speed_m_s}) deve essere positivo. "
            f"Per condizioni di calma assoluta usa un valore minimo "
            f"simbolico tipo 0.5 m/s (vento minimo convettivo)."
        )
    if crop_height_m <= 0:
        raise ValueError(
            f"crop_height_m ({crop_height_m}) deve essere positivo."
        )

    # Costante di von Kármán
    k = 0.41
    # Altezza di misura del vento e dell'umidità (standard FAO-56).
    z_m = 2.0
    z_h = 2.0
    # Spostamento del piano zero, parametri di rugosità per momentum
    # e per il trasferimento di calore. Le proporzioni 2/3, 0.123 e
    # 0.0123 rispetto all'altezza colturale sono valori empirici
    # consolidati per coperture vegetali uniformi.
    d = 0.667 * crop_height_m
    z_om = 0.123 * crop_height_m
    z_oh = 0.0123 * crop_height_m

    return (
        math.log((z_m - d) / z_om) * math.log((z_h - d) / z_oh)
        / (k ** 2 * wind_speed_m_s)
    )


def et0_hargreaves_samani(
    t_min: float,
    t_max: float,
    latitude_deg: float,
    j: int,
) -> float:
    """
    Evapotraspirazione di riferimento ET₀ secondo Hargreaves-Samani, in
    mm/giorno.

    Formula applicata:

        ET₀ = 0.0023 × (T_med + 17.8) × √(T_max − T_min) × R_a

    con T_med = (T_min + T_max) / 2, tutte le temperature in °C, e R_a
    espressa in mm/giorno di acqua equivalente (calcolata internamente
    da latitudine e giorno dell'anno).

    Significato dei termini:
      - 0.0023 è il coefficiente empirico globale calibrato su lisimetri
        da Hargreaves e Samani nel 1985.
      - (T_med + 17.8) è il fattore termico: l'offset 17.8 sposta il
        punto in cui la formula si annullerebbe al di sotto dello zero
        (a −17.8 °C), riflettendo il fatto che ET₀ si riduce ma non
        sparisce del tutto in clima freddo.
      - √(T_max − T_min) è il proxy "tre in uno" di radiazione netta,
        nuvolosità e umidità atmosferica. La radice quadrata attenua
        l'effetto di escursioni molto grandi, dove la relazione con la
        radiazione reale non è più lineare.
      - R_a è l'ingrediente astronomico già calcolato nel nostro modulo
        `radiation` e qui ottenuto automaticamente.

    Parametri
    ---------
    t_min : float
        Temperatura minima giornaliera in °C (tipicamente misurata
        poco prima dell'alba).
    t_max : float
        Temperatura massima giornaliera in °C (tipicamente misurata
        nel primo pomeriggio).
    latitude_deg : float
        Latitudine del sito in gradi decimali, positiva a nord.
    j : int
        Giorno progressivo dell'anno (1-366).

    Ritorna
    -------
    float
        ET₀ in mm/giorno. Valori tipici:
          - 0.5-2 mm/giorno in inverno temperato;
          - 4-7 mm/giorno in estate temperata;
          - fino a 10-12 mm/giorno in estate desertica ventilata.

    Solleva
    -------
    ValueError
        Se t_max < t_min: segnala dati corrotti o invertiti.

    Limiti noti: Hargreaves-Samani tende a sovrastimare ET₀ in climi
    umidi ventilati (fino a +15% sulla costa mediterranea d'estate) e a
    sottostimarlo in climi aridi molto ventilati, perché il vento non
    entra esplicitamente nella formula. Per giardinaggio a latitudini
    medie gli errori restano generalmente nell'intervallo ±10%, più che
    accettabili per decisioni di irrigazione su scala settimanale.
    """
    if t_max < t_min:
        raise ValueError(
            f"t_max ({t_max} °C) non può essere minore di t_min "
            f"({t_min} °C). Verifica i dati di input."
        )

    t_mean = (t_min + t_max) / 2.0

    # Ingrediente astronomico: R_a per questa latitudine e giorno.
    # Scelta architetturale: la funzione è "tutto incluso" — basta
    # fornire lat e giorno, R_a viene calcolata internamente. In futuro,
    # quando orchestreremo simulazioni multi-giorno, introdurremo una
    # variante che accetta R_a pre-calcolata per evitare ricalcoli
    # ridondanti.
    ra_mj = extraterrestrial_radiation(latitude_deg, j)
    ra_mm = mj_per_m2_to_mm_water(ra_mj)

    delta_t = t_max - t_min
    return 0.0023 * (t_mean + 17.8) * math.sqrt(delta_t) * ra_mm


# =====================================================================
#  Penman-Monteith FAO-56: la formula di riferimento internazionale.
#
#  Le due funzioni che seguono implementano Penman-Monteith in due
#  varianti che condividono la stessa matematica di fondo. La versione
#  fisica applica l'equazione completa alla specie reale usando la sua
#  resistenza stomatica e altezza colturale; la versione standard FAO-56
#  è un caso particolare della fisica con i parametri della coltura di
#  riferimento (resistenza stomatica 70 s/m, altezza 12 cm), e produce
#  ET₀ "puro" che poi va moltiplicato per il Kc della specie.
#
#  Implementiamo prima la versione fisica come funzione canonica, e poi
#  la versione standard come thin wrapper sulla fisica. Questo riflette
#  esplicitamente nel codice la relazione gerarchica tra le due
#  formulazioni e ci consente di provare numericamente la loro
#  consistenza nei test.
# =====================================================================


def compute_et_penman_monteith_physical(
    temperature_c: float,
    humidity_relative: float,
    wind_speed_m_s: float,
    net_radiation_mj_m2_day: float,
    stomatal_resistance_s_m: float,
    crop_height_m: float,
    elevation_m: float = 0.0,
    soil_heat_flux_mj_m2_day: float = 0.0,
) -> float:
    """
    Evapotraspirazione ET secondo l'equazione fisica di Penman-Monteith,
    in mm/giorno.

    Significato fisico: l'evapotraspirazione effettiva di una specie
    specifica calcolata applicando direttamente l'equazione di
    Penman-Monteith alla coltura reale, usando la sua resistenza
    stomatica e altezza colturale invece di quelle standardizzate
    della coltura di riferimento. Il risultato è già ET (non ET₀): non
    va moltiplicato per il Kc, perché la specificità della specie è
    già stata incorporata nei suoi parametri fisiologici.

    Quando si preferisce questa versione: per specie che deviano
    significativamente dalla coltura di riferimento erbosa (succulente
    con alta resistenza stomatica, perenni legnose con grande altezza,
    erbe aromatiche con stomi piccoli), o per condizioni anomale dove
    il Kc empirico di letteratura potrebbe non essere ben calibrato.
    Per le colture standard a latitudini medie la versione FAO-56
    standard moltiplicata per Kc è perfettamente adeguata.

    Equazione (FAO-56 equazione 3, "Penman-Monteith form"):

        λ × ET = (Δ × (R_n - G) + ρ_a × c_p × (e_s - e_a) / r_a) /
                 (Δ + γ × (1 + r_s / r_a))

    dove:
      - λ = 2.45 MJ/kg è il calore latente di vaporizzazione, e divide
        per convertire da energia (MJ/m²/d) a millimetri d'acqua;
      - Δ è la pendenza della curva di pressione di vapore saturo;
      - R_n è la radiazione netta a onde corte e lunghe;
      - G è il flusso termico nel suolo (a scala giornaliera ≈ 0);
      - ρ_a × c_p è la capacità termica volumetrica dell'aria;
      - e_s − e_a è il deficit di pressione di vapore;
      - r_a è la resistenza aerodinamica al trasporto di vapore;
      - γ è la costante psicrometrica;
      - r_s è la resistenza stomatica della specie.

    L'equazione esprime un bilancio: il numeratore somma il termine
    "radiativo" (Δ·(R_n−G), l'energia disponibile pesata dalla
    sensibilità termica del vapor d'acqua) e il termine "aerodinamico"
    (ρ_a·c_p·(e_s−e_a)/r_a, il deficit di vapore pesato dalla
    capacità di trasporto dell'aria). Il denominatore "frena" il
    risultato attraverso la resistenza stomatica della specie:
    piante con stomi più chiusi (r_s grande) traspirano meno a parità
    di tutto il resto. Quando r_s → 0 si recupera la formula di
    Penman originale per superficie d'acqua libera; quando r_s = 70
    s/m e h = 0.12 m si recupera la versione FAO-56 standard.

    La versione "operativa" che effettivamente calcoliamo, dove le
    costanti fisiche sono incorporate nei coefficienti numerici
    (FAO-56 equazione 6, "form for daily timestep"):

        ET = (0.408·Δ·(R_n − G) + γ·(900/(T+273))·u₂·(e_s − e_a)·k_r) /
             (Δ + γ·(1 + k_s·u₂))

    con k_r e k_s coefficienti che dipendono da r_s e h secondo la loro
    relazione con la resistenza aerodinamica (FAO-56 box 6).

    Per la versione fisica generale derivata di nuovo dall'equazione
    base, evitiamo i coefficienti specializzati alla coltura di
    riferimento e calcoliamo esplicitamente ρ_a·c_p e r_a usando i
    parametri della specie reale. È leggermente più costosa in termini
    di operazioni floating point ma molto più trasparente.

    Parametri
    ---------
    temperature_c : float
        Temperatura media giornaliera, in °C. Per simulazioni più
        accurate FAO-56 raccomanda di usare T_mean = (T_max + T_min)/2.
    humidity_relative : float
        Umidità relativa media giornaliera come frazione 0..1.
    wind_speed_m_s : float
        Velocità del vento a 2 m di altezza, in m/s. Deve essere > 0
        (per condizioni di calma assoluta passare 0.5 m/s come vento
        minimo convettivo).
    net_radiation_mj_m2_day : float
        Radiazione netta R_n, in MJ/m²/giorno. Si calcola via
        `fitosim.science.radiation.net_radiation` dalla radiazione
        globale Rs misurata e dai dati meteo.
    stomatal_resistance_s_m : float
        Resistenza stomatica della specie, in s/m. Valori tipici:
        70 per coltura di riferimento erbosa, 100 per basilico,
        200 per rosmarino, 500+ per succulente CAM. Deve essere > 0.
    crop_height_m : float
        Altezza colturale in metri. Influenza la resistenza
        aerodinamica. Deve essere > 0.
    elevation_m : float, default 0.0
        Quota del sito sul livello del mare. Influenza la pressione
        atmosferica e quindi la costante psicrometrica.
    soil_heat_flux_mj_m2_day : float, default 0.0
        Flusso termico G nel suolo, in MJ/m²/giorno. A scala giornaliera
        e per coperture vegetali ben sviluppate è quasi sempre
        trascurabile, e il default 0 è la scelta raccomandata da FAO-56.

    Ritorna
    -------
    float
        ET in mm/giorno. Valori tipici per coltura ben irrigata a
        latitudini medie: 1-3 in inverno, 4-7 in estate, fino a 10+
        in condizioni desertiche ventilate.

    Solleva
    -------
    ValueError
        Se i parametri di input violano i loro vincoli fisici
        (umidità fuori da [0,1], vento o resistenze non positive).
    """
    # I sei helper introdotti sopra fanno il grosso del lavoro.
    # Ognuno è testato indipendentemente, e qui li componiamo nella
    # forma finale dell'equazione di Penman-Monteith.

    # Termodinamica del vapore d'acqua a questa temperatura.
    e_s = saturation_vapor_pressure(temperature_c)
    e_a = actual_vapor_pressure(temperature_c, humidity_relative)
    delta = slope_vapor_pressure(temperature_c)

    # Pressione atmosferica e costante psicrometrica per questa quota.
    p = atmospheric_pressure(elevation_m)
    gamma = psychrometric_constant(p)

    # Resistenza aerodinamica per questo vento e altezza colturale.
    r_a = aerodynamic_resistance(wind_speed_m_s, crop_height_m)

    if stomatal_resistance_s_m <= 0:
        raise ValueError(
            f"stomatal_resistance_s_m ({stomatal_resistance_s_m}) "
            f"deve essere positiva. Per acqua libera o superfici "
            f"completamente bagnate considera la formula di Penman "
            f"originale, non Penman-Monteith."
        )

    # Capacità termica volumetrica dell'aria a 20°C e pressione standard.
    # ρ_a × c_p ≈ 1.013 × 10⁻³ × P / (T_v · R_specifica). Per la
    # formulazione semplificata FAO-56 questo prodotto è incorporato
    # nei coefficienti finali: lavorando a temperature ambientali
    # tipiche (±20°C dalla standard) la variazione di ρ_a×c_p è di
    # pochi percento e si compensa con la presenza di altri parametri.
    # Qui usiamo la forma esplicita per coerenza didattica.
    rho_cp = 1.013e-3 * p / (1.01 * (temperature_c + 273.0) * 0.287)
    # Nota: 0.287 kJ/(kg·K) è la costante specifica dell'aria secca,
    # 1.01 è il fattore di correzione per aria umida (FAO-56 box 6).

    # Numeratore dell'equazione di Penman-Monteith.
    radiative_term = delta * (
        net_radiation_mj_m2_day - soil_heat_flux_mj_m2_day
    )
    aerodynamic_term = (86400.0 * rho_cp * (e_s - e_a) / r_a)
    # Il fattore 86400 = 24·3600 converte secondi → giorni: r_a è in
    # s/m, mentre R_n è in MJ/m²/giorno, e dobbiamo riportare le due
    # quantità sulla stessa base temporale. Il prodotto rho_cp·86400/r_a
    # ha unità di MJ/(m²·giorno·kPa) che, moltiplicato per (e_s−e_a) in
    # kPa, dà MJ/m²/giorno come il termine radiativo.
    numerator = radiative_term + aerodynamic_term

    # Denominatore: somma di Δ e del fattore psicrometrico modificato
    # dalla resistenza stomatica. Il rapporto r_s/r_a esprime quanto la
    # pianta "trattiene" il vapore rispetto a quanto l'aria lo
    # trasporta via.
    denominator = delta + gamma * (1.0 + stomatal_resistance_s_m / r_a)

    # Il risultato è in MJ/m²/giorno (energia equivalente all'ET).
    et_energy = numerator / denominator

    # Conversione finale in mm/giorno via il calore latente.
    return mj_per_m2_to_mm_water(et_energy)


def compute_et0_penman_monteith(
    temperature_c: float,
    humidity_relative: float,
    wind_speed_m_s: float,
    net_radiation_mj_m2_day: float,
    elevation_m: float = 0.0,
    soil_heat_flux_mj_m2_day: float = 0.0,
) -> float:
    """
    Evapotraspirazione di riferimento ET₀ secondo Penman-Monteith FAO-56,
    in mm/giorno.

    Significato fisico: la versione "standard" del Penman-Monteith che
    assume la coltura di riferimento ipotetica di FAO-56 (erba bassa
    di 12 cm, resistenza stomatica 70 s/m, ben irrigata, copertura
    completa). Il risultato è ET₀, non l'ET effettiva: per ottenere
    l'ET di una specie specifica moltiplica per il Kc del catalogo,
    esattamente come fai con Hargreaves-Samani.

    Quando si preferisce questa versione rispetto a Hargreaves-Samani:
    quando hai dati meteo completi (temperatura, umidità, vento,
    radiazione netta) e vuoi sfruttarli per una stima più accurata.
    FAO-56 raccomanda Penman-Monteith come formula di prima scelta;
    Hargreaves resta il fallback per quando mancano dati.

    Quando si preferisce questa versione rispetto al Penman-Monteith
    fisico: quando lavori con specie standard a latitudini medie e i
    Kc di letteratura sono ben calibrati per le tue condizioni. La
    versione fisica diventa preferibile quando deviazioni significative
    della specie dalla coltura di riferimento (succulente, perenni
    legnose, erbe aromatiche di pieno sole) potrebbero rendere il Kc
    empirico inadeguato.

    Implementazione: chiamiamo internamente la versione fisica passando
    i parametri della coltura di riferimento standard FAO-56. Questo
    evita duplicazione di codice e rende esplicita nel codice la
    relazione gerarchica "la versione standard è un caso particolare
    della fisica". I parametri della coltura di riferimento sono
    fissati dalla pubblicazione FAO-56:

      - resistenza stomatica r_s = 70 s/m
      - altezza colturale h = 0.12 m

    Parametri
    ---------
    temperature_c, humidity_relative, wind_speed_m_s,
    net_radiation_mj_m2_day, elevation_m, soil_heat_flux_mj_m2_day :
        Vedi `compute_et_penman_monteith_physical`. Stessi significati,
        stessi vincoli, stesse unità.

    Ritorna
    -------
    float
        ET₀ in mm/giorno. Da moltiplicare per il Kc della specie per
        ottenere l'ET effettiva.

    Solleva
    -------
    ValueError
        Se i parametri di input violano i loro vincoli fisici.
    """
    # Parametri della coltura di riferimento FAO-56.
    REFERENCE_STOMATAL_RESISTANCE_S_M = 70.0
    REFERENCE_CROP_HEIGHT_M = 0.12

    return compute_et_penman_monteith_physical(
        temperature_c=temperature_c,
        humidity_relative=humidity_relative,
        wind_speed_m_s=wind_speed_m_s,
        net_radiation_mj_m2_day=net_radiation_mj_m2_day,
        stomatal_resistance_s_m=REFERENCE_STOMATAL_RESISTANCE_S_M,
        crop_height_m=REFERENCE_CROP_HEIGHT_M,
        elevation_m=elevation_m,
        soil_heat_flux_mj_m2_day=soil_heat_flux_mj_m2_day,
    )
