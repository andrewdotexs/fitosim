"""
Radiazione solare extra-atmosferica R_a.

Questo modulo calcola la radiazione solare che raggiungerebbe la superficie
terrestre in assenza di atmosfera — una quantità puramente geometrica e
deterministica, funzione soltanto della latitudine del luogo e del giorno
dell'anno. È il mattoncino di partenza del motore scientifico di fitosim:
tutte le formule successive (Hargreaves-Samani, Penman-Monteith) la usano
come ingrediente.

Perché ci interessa R_a in pratica:
  1. La formula di Hargreaves-Samani stima l'evapotraspirazione di
     riferimento ET₀ usando solo le temperature (min, max) e R_a, che
     non è misurata ma calcolata.
  2. Quando disponiamo di una stazione meteo con piranometro, R_a ci
     permette di calcolare il "rapporto di trasparenza" dell'atmosfera
     (R_s / R_a) e dedurne la nuvolosità effettiva.
  3. R_a è un limite fisico superiore per la radiazione misurata: se una
     stazione riporta R_s > R_a, sappiamo con certezza che il sensore è
     tarato male (violerebbe la conservazione dell'energia).

Riferimento bibliografico:
    Allen, R. G., Pereira, L. S., Raes, D., & Smith, M. (1998).
    Crop Evapotranspiration — Guidelines for Computing Crop Water
    Requirements. FAO Irrigation and Drainage Paper No. 56,
    Capitolo 3 "Meteorological data", equazioni 21, 23, 24, 25.
"""

import math
from datetime import date


# Costante solare: flusso di radiazione solare che attraversa una superficie
# perpendicolare ai raggi solari, alla distanza media Terra-Sole, al di
# fuori dell'atmosfera. Il valore riportato da FAO-56 è 0.0820 MJ m⁻²
# min⁻¹, ricavato dal valore "ufficiale" di 1367 W/m² convertito in
# unità di megajoule al minuto (1367 × 60 / 10⁶ ≈ 0.0820).
SOLAR_CONSTANT = 0.0820  # MJ m^-2 min^-1


def day_of_year(d: date) -> int:
    """
    Giorno progressivo dell'anno (1-366) per una data data.

    1 gennaio → 1, 31 dicembre → 365 in un anno normale, 366 in anno
    bisestile. È un wrapper esplicito attorno a `timetuple().tm_yday`
    usato per rendere visibile il ruolo di questo parametro nel calcolo
    successivo: tutte le formule FAO-56 usano "J" come questa quantità.
    """
    return d.timetuple().tm_yday


def inverse_relative_distance(j: int) -> float:
    """
    Inversa della distanza relativa Terra-Sole d_r, adimensionale.

    L'orbita terrestre non è circolare ma leggermente ellittica, con il
    Sole in uno dei due fuochi. Di conseguenza, la distanza Terra-Sole
    varia lungo l'anno: è minima al perielio (inizio gennaio) e massima
    all'afelio (inizio luglio). Poiché il flusso solare che colpisce la
    Terra è inversamente proporzionale al quadrato della distanza, in
    gennaio riceviamo circa il 3% in più di energia che in luglio.

    Il fattore d_r definito da FAO-56 è il rapporto (d_media / d)², che
    oscilla tra circa 1.033 (gennaio) e 0.967 (luglio) con periodo
    annuale. Moltiplichiamo R_a per d_r per tenere conto di questa
    variazione.

    FAO-56 eq. 23.
    """
    return 1.0 + 0.033 * math.cos(2.0 * math.pi * j / 365.0)


def solar_declination(j: int) -> float:
    """
    Declinazione solare δ, in radianti.

    La declinazione è l'angolo tra la direzione della radiazione solare
    incidente e il piano dell'equatore terrestre. Nasce dal fatto che
    l'asse di rotazione terrestre è inclinato di circa 23.45° rispetto
    alla perpendicolare al piano orbitale — è *questa* l'origine fisica
    delle stagioni.

    Andamento tipico nel corso dell'anno:
      - δ ≈ 0         agli equinozi (marzo e settembre)
      - δ ≈ +23.45°   al solstizio d'estate boreale (21 giugno)
      - δ ≈ -23.45°   al solstizio d'inverno boreale (21 dicembre)

    In radianti, l'ampiezza 23.45° corrisponde a 0.409. La formula
    FAO-56 è un'approssimazione sinusoidale del moto reale (che ha
    piccole asimmetrie); l'offset di 1.39 rad posiziona gli zero
    crossings agli equinozi.

    FAO-56 eq. 24.
    """
    return 0.409 * math.sin(2.0 * math.pi * j / 365.0 - 1.39)


def sunset_hour_angle(latitude_rad: float, declination_rad: float) -> float:
    """
    Angolo orario del tramonto ω_s, in radianti.

    L'angolo orario misura il tempo in unità angolari: ogni 15° = 1 ora.
    A mezzogiorno solare l'angolo orario del Sole è 0; al tramonto vale
    ω_s, al sorgere -ω_s. Quindi la durata del giorno solare in ore è
    semplicemente (2 · ω_s) / (π / 12) = 24 · ω_s / π.

    All'equatore, agli equinozi, ω_s = π/2: il giorno dura esattamente
    12 ore, indipendentemente dalla latitudine. Spostandosi dall'equatore
    o cambiando stagione, ω_s si allarga (giorni più lunghi) o si
    restringe (giorni più corti). Alle altissime latitudini, nei pressi
    dei solstizi, l'argomento dell'arcocoseno può uscire dall'intervallo
    [-1, 1]: ciò segnala il "sole di mezzanotte" (24 ore di luce) o la
    "notte polare" (0 ore di luce).

    FAO-56 eq. 25.
    """
    arg = -math.tan(latitude_rad) * math.tan(declination_rad)
    # Clamp difensivo: protegge da minimi errori di arrotondamento e
    # gestisce in modo degradante le zone polari senza sollevare
    # eccezioni. Un vero supporto polare richiederà logica dedicata,
    # che rimandiamo alle versioni successive del modello (agronomia
    # domestica raramente si pratica sopra il circolo polare artico).
    arg = max(-1.0, min(1.0, arg))
    return math.acos(arg)


def extraterrestrial_radiation(latitude_deg: float, j: int) -> float:
    """
    Radiazione extra-atmosferica giornaliera R_a, in MJ m⁻² giorno⁻¹.

    Calcola la quantità di energia solare che raggiungerebbe una
    superficie orizzontale posta al limite superiore dell'atmosfera
    nell'arco della giornata, integrando dal sorgere al tramonto.

    La formula è l'integrale analitico del flusso solare (pesato per
    l'angolo di incidenza cos θ) sul semicerchio diurno, e ha forma
    chiusa grazie alla simmetria giornaliera dell'angolo orario.

    Parametri
    ---------
    latitude_deg : float
        Latitudine in gradi decimali. Positiva a nord dell'equatore,
        negativa a sud. Milano ≈ 45.47, Roma ≈ 41.90, Sydney ≈ -33.87.
    j : int
        Giorno dell'anno (1-366). Usare `day_of_year(data)` per
        derivarlo da un oggetto `datetime.date`.

    Ritorna
    -------
    float
        R_a in megajoule per metro quadrato per giorno.
        Per convertire in W/m², dividere per 0.0864.
        Per convertire in mm di acqua equivalente (energia che sarebbe
        necessaria a evaporare quei millimetri), dividere per 2.45.

    FAO-56 eq. 21.
    """
    # Conversione latitudine → radianti: tutte le funzioni trig di Python
    # lavorano in radianti, così come le formule FAO.
    phi = math.radians(latitude_deg)

    # Calcolo delle tre quantità astronomiche intermedie.
    delta = solar_declination(j)
    dr = inverse_relative_distance(j)
    omega_s = sunset_hour_angle(phi, delta)

    # Il fattore (24 * 60 / π) = 1440/π nasce dall'integrazione nel tempo:
    #   - il 1440 = 24 * 60 è la conversione giorno → minuti, necessaria
    #     perché G_sc è espressa in MJ/m²/minuto e vogliamo R_a al giorno;
    #   - la divisione per π viene dalla conversione angolo-orario → tempo
    #     (la Terra ruota 2π radianti in 1440 minuti, quindi dt = 720/π dω)
    #     combinata con il fattore 2 della simmetria del giorno attorno a
    #     mezzogiorno (l'integrazione va da -ω_s a +ω_s).
    factor = (24.0 * 60.0 / math.pi) * SOLAR_CONSTANT * dr

    # Questo è il termine tra parentesi quadre nella formula FAO-56: nel
    # paper appare come "[ ω_s·sin(φ)·sin(δ) + cos(φ)·cos(δ)·sin(ω_s) ]",
    # ma in Python usiamo le parentesi tonde perché le quadre sono
    # riservate alla sintassi delle liste. Il risultato è la forma chiusa
    # dell'integrale analitico di cos(θ) sull'arco diurno, e raccoglie
    # due contributi fisicamente distinti:
    #   - ω_s * sin(φ) * sin(δ):       componente stagionale, pesata dalla
    #                                  durata del giorno (ω_s);
    #   - cos(φ) * cos(δ) * sin(ω_s):  componente zenitale, pesata dalla
    #                                  verticalità dei raggi a mezzogiorno.
    # All'equatore agli equinozi domina la zenitale; al Polo Nord al
    # solstizio d'estate domina la stagionale (giorno di 24 ore).
    bracket = (
        omega_s * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(omega_s)
    )

    return factor * bracket


def clear_sky_radiation(
    extraterrestrial_radiation_mj: float, elevation_m: float = 0.0,
) -> float:
    """
    Radiazione solare in giornata di cielo sereno R_so, in MJ m⁻² giorno⁻¹.

    Significato fisico: quanta radiazione solare arriverebbe al suolo in
    un giorno di cielo perfettamente sereno (niente nuvole, niente
    foschia significativa) a partire dalla radiazione extra-atmosferica
    R_a. È la "soglia massima" che la radiazione globale misurata Rs
    può raggiungere: misure di Rs sistematicamente superiori a R_so
    indicano un sensore mal calibrato o un errore di unità di misura.

    R_so si usa anche all'interno del calcolo della radiazione netta
    a onde lunghe: il rapporto Rs/R_so è il "coefficiente di copertura
    del cielo" (cloud cover factor) che modula quanto la superficie
    irraggia calore verso lo spazio. Cielo sereno (Rs/R_so → 1)
    significa molta perdita di calore radiativo notturno; cielo nuvoloso
    (Rs/R_so piccolo) significa che le nuvole rimandano indietro
    parte di quel calore.

    Formula (FAO-56 equazione 37):

        R_so = (0.75 + 2 × 10⁻⁵ × z) × R_a

    dove z è la quota in metri sul livello del mare. Il coefficiente
    base 0.75 rappresenta la trasmissività media dell'atmosfera in
    giorno sereno al livello del mare (il 75% della radiazione
    extra-atmosferica raggiunge il suolo); il termine z corregge per
    il fatto che a quote più alte l'aria attraversata è meno densa e
    la trasmissività cresce leggermente.

    Parametri
    ---------
    extraterrestrial_radiation_mj : float
        R_a in MJ/m²/giorno, calcolata via `extraterrestrial_radiation`.
    elevation_m : float, default 0.0
        Quota del sito in metri sul livello del mare. Per Milano usare
        circa 150 m, per le località costiere usare 0.

    Ritorna
    -------
    float
        R_so in MJ/m²/giorno.
    """
    return (0.75 + 2e-5 * elevation_m) * extraterrestrial_radiation_mj


def net_radiation(
    solar_radiation_mj: float,
    extraterrestrial_radiation_mj: float,
    t_max_c: float,
    t_min_c: float,
    actual_vapor_pressure_kpa: float,
    elevation_m: float = 0.0,
    albedo: float = 0.23,
) -> float:
    """
    Radiazione netta R_n giornaliera, in MJ m⁻² giorno⁻¹.

    Significato fisico: il bilancio energetico tra l'energia solare a
    onde corte assorbita dalla superficie e l'energia termica a onde
    lunghe netta scambiata con l'atmosfera. È la componente che
    effettivamente alimenta l'evapotraspirazione: non tutta la
    radiazione solare che arriva (Rs) finisce in vapor d'acqua, perché
    una parte viene riflessa (albedo) e una parte viene riemessa come
    radiazione termica verso lo spazio.

    Il calcolo si articola in due termini distinti che rispecchiano
    fisiche diverse:

      R_n = R_ns − R_nl

    dove R_ns è la radiazione netta a onde corte (energia solare
    assorbita, al netto della riflessione) e R_nl è la radiazione netta
    a onde lunghe (energia termica netta scambiata con il cielo).

    Per R_ns la formula è semplice (FAO-56 equazione 38):

        R_ns = (1 − α) × Rs

    dove α è l'albedo della superficie (0.23 per la coltura di
    riferimento erbosa, valore raccomandato da FAO-56). Una frazione
    α della radiazione solare viene riflessa; il complemento (1 − α)
    viene assorbita.

    Per R_nl la formula è più articolata (FAO-56 equazione 39) perché
    il bilancio termico dipende dalla temperatura della superficie,
    dall'umidità dell'aria (vapor d'acqua è un gas serra), e dalla
    copertura del cielo:

        R_nl = σ × ((T_max⁴ + T_min⁴)/2) ×
               (0.34 − 0.14 × √ea) ×
               (1.35 × Rs/R_so − 0.35)

    dove σ = 4.903 × 10⁻⁹ MJ K⁻⁴ m⁻² giorno⁻¹ è la costante di
    Stefan-Boltzmann nelle unità FAO, T_max e T_min sono le temperature
    estreme in Kelvin, ea è l'umidità attuale in kPa, e Rs/R_so è il
    coefficiente di copertura del cielo.

    L'interpretazione dei tre fattori del prodotto è significativa.
    Il primo è il termine di Stefan-Boltzmann sulla quarta potenza
    della temperatura: superfici più calde irraggiano molto di più.
    Il secondo cattura l'effetto serra del vapore acqueo: aria più
    umida (ea grande) trattiene più calore vicino al suolo, riducendo
    la perdita radiativa netta. Il terzo è la modulazione delle nuvole:
    Rs/R_so vicino a 1 significa cielo sereno e perdita massima; piccolo
    significa cielo coperto e perdita ridotta perché le nuvole rimandano
    indietro il calore.

    Parametri
    ---------
    solar_radiation_mj : float
        Radiazione solare globale Rs misurata o stimata, in MJ/m²/giorno.
    extraterrestrial_radiation_mj : float
        Radiazione extra-atmosferica R_a, in MJ/m²/giorno.
    t_max_c, t_min_c : float
        Temperatura massima e minima giornaliera, in °C.
    actual_vapor_pressure_kpa : float
        Umidità attuale ea, in kPa.
    elevation_m : float, default 0.0
        Quota del sito in metri sul livello del mare.
    albedo : float, default 0.23
        Riflettività della superficie. Il default 0.23 è il valore FAO-56
        per la coltura di riferimento erbosa. Variazioni tipiche: 0.15
        per coperture vegetali dense scure, 0.30 per terreno nudo
        chiaro, fino a 0.85 per neve fresca.

    Ritorna
    -------
    float
        R_n in MJ/m²/giorno. Valori tipici a latitudini medie:
        circa 5-8 in giornata estiva serena, 1-3 in giornata invernale
        nuvolosa. Può scendere a valori negativi in giornate molto
        nuvolose dove la perdita termica notturna supera l'apporto
        solare diurno (rare ma fisicamente possibili).
    """
    # Costante di Stefan-Boltzmann nelle unità FAO-56.
    sigma = 4.903e-9  # MJ K⁻⁴ m⁻² giorno⁻¹

    # Termine 1: radiazione netta a onde corte. Quanto della radiazione
    # solare globale viene effettivamente assorbita.
    rns = (1.0 - albedo) * solar_radiation_mj

    # Termine 2: radiazione netta a onde lunghe. Bilancio termico
    # tra emissione della superficie e contro-emissione del cielo.
    # Le temperature vanno convertite in Kelvin perché Stefan-Boltzmann
    # è una legge sulla quarta potenza della temperatura assoluta.
    t_max_k = t_max_c + 273.16
    t_min_k = t_min_c + 273.16
    stefan_boltzmann_term = sigma * (t_max_k ** 4 + t_min_k ** 4) / 2.0

    # Fattore di emissione netta dipendente dall'umidità: aria umida
    # trattiene il calore (effetto serra del vapore d'acqua).
    humidity_factor = 0.34 - 0.14 * math.sqrt(actual_vapor_pressure_kpa)

    # Fattore di copertura del cielo. Calcoliamo R_so internamente
    # invece di chiederlo all'esterno: il chiamante ha già passato R_a
    # e la quota, dai quali R_so è derivabile, e questa scelta riduce
    # il numero di parametri della funzione.
    rso = (0.75 + 2e-5 * elevation_m) * extraterrestrial_radiation_mj
    # Limitiamo Rs/R_so a 1.0 per gestire la situazione (rara ma
    # possibile) in cui il sensore di radiazione misura più della
    # radiazione di cielo sereno teorica, cosa che produrrebbe un
    # cloudiness factor maggiore di 1 con conseguente sovrastima della
    # perdita radiativa.
    cloudiness_ratio = min(solar_radiation_mj / rso, 1.0) if rso > 0 else 0.0
    cloudiness_factor = 1.35 * cloudiness_ratio - 0.35

    rnl = stefan_boltzmann_term * humidity_factor * cloudiness_factor

    return rns - rnl


# =====================================================================
#  Il giorno fatto di blocchi (A7, 2026-09-29): la geometria solare su
#  un intervallo di ore invece che sul giorno intero — FAO-56 cap. 3,
#  eq. 28–33 — e la radiazione netta di un blocco (cap. 4). Servono al
#  Penman-Monteith a passo sub-giornaliero e alla ripartizione dell'ET₀
#  del giorno sui blocchi.
#
#  Le ore sono in tempo civile *standard* del sito, senza ora legale
#  (per l'Italia CET = UTC+1): è l'"ora dell'orologio" che FAO-56 vuole
#  nella eq. 31. La longitudine è positiva a est; FAO-56 la vuole in
#  gradi ovest, e la differenza L_z − L_m della eq. 31 in gradi ovest è
#  (longitudine_est − 15 · fuso_orario) — la stessa quantità, senza
#  giri di 360°.
# =====================================================================

# Costante di Stefan-Boltzmann nelle unità FAO-56 (MJ K⁻⁴ m⁻² giorno⁻¹);
# per un blocco di Δt ore si riscala di Δt/24 (2.043 × 10⁻¹⁰ all'ora).
STEFAN_BOLTZMANN_MJ_M2_DAY = 4.903e-9

# Limite inferiore del rapporto R_s/R_so nei passi sub-giornalieri
# (FAO-56 cap. 4): di notte e con il sole basso il rapporto misurato
# non è affidabile, e il termine nuvole della eq. 39 va tenuto in
# [0.3, 1.0].
RS_RSO_MIN_SUBDAILY = 0.3


def seasonal_correction_hours(j: int) -> float:
    """
    Correzione stagionale S_c dell'ora solare, in ore (FAO-56 eq. 32–33).

    È l'equazione del tempo: lo scarto fra il mezzogiorno dell'orologio
    e il passaggio del Sole al meridiano, dovuto all'eccentricità
    dell'orbita e all'inclinazione dell'asse. Oscilla fra circa −0.24 h
    (metà febbraio) e +0.27 h (inizio novembre).
    """
    b = 2.0 * math.pi * (j - 81) / 364.0
    return 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)


def solar_time_angle(
    clock_hour: float, j: int, longitude_deg: float, utc_offset_hours: float,
) -> float:
    """
    Angolo orario solare ω all'ora civile standard `clock_hour`, in
    radianti (FAO-56 eq. 31): zero al mezzogiorno solare, negativo la
    mattina, π/12 per ogni ora.

    `longitude_deg` è positiva a est; `utc_offset_hours` è il fuso
    orario standard del sito (1 per l'Italia), che fissa il meridiano
    di riferimento a 15° × fuso.
    """
    return (math.pi / 12.0) * (
        clock_hour
        + 0.06667 * (longitude_deg - 15.0 * utc_offset_hours)
        + seasonal_correction_hours(j)
        - 12.0
    )


def solar_noon_hour(j: int, longitude_deg: float, utc_offset_hours: float) -> float:
    """L'ora civile standard del mezzogiorno solare: la eq. 31 per ω = 0."""
    return (
        12.0
        - 0.06667 * (longitude_deg - 15.0 * utc_offset_hours)
        - seasonal_correction_hours(j)
    )


def sunrise_sunset_hours(
    latitude_deg: float, longitude_deg: float, j: int, utc_offset_hours: float,
) -> tuple[float, float]:
    """
    Le ore civili standard di alba e tramonto (la eq. 31 invertita per
    ω = ∓ω_s). Milano, 14 settembre: circa 6.13 e 18.47 CET.
    """
    ws = sunset_hour_angle(math.radians(latitude_deg), solar_declination(j))
    noon = solar_noon_hour(j, longitude_deg, utc_offset_hours)
    half_day = 12.0 * ws / math.pi
    return noon - half_day, noon + half_day


def _clipped_hour_angles(
    latitude_deg: float,
    longitude_deg: float,
    j: int,
    start_hour: float,
    end_hour: float,
    utc_offset_hours: float,
) -> tuple[float, float, float, float, float, float]:
    """
    Gli angoli orari agli estremi del blocco (ω₁, ω₂) e gli stessi
    limitati all'arco diurno [−ω_s, ω_s], come prescrive FAO-56 per la
    eq. 28. Ritorna (φ, δ, ω₁, ω₂, a, b): se b ≤ a il blocco è tutto
    di notte.
    """
    if not 0.0 <= start_hour < end_hour <= 24.0:
        raise ValueError(
            f"Il blocco [{start_hour}, {end_hour}) deve stare dentro le "
            f"24 ore del giorno, con inizio prima della fine."
        )
    phi = math.radians(latitude_deg)
    delta = solar_declination(j)
    ws = sunset_hour_angle(phi, delta)
    w1 = solar_time_angle(start_hour, j, longitude_deg, utc_offset_hours)
    w2 = solar_time_angle(end_hour, j, longitude_deg, utc_offset_hours)
    return phi, delta, w1, w2, max(w1, -ws), min(w2, ws)


def extraterrestrial_radiation_interval(
    latitude_deg: float,
    longitude_deg: float,
    j: int,
    start_hour: float,
    end_hour: float,
    utc_offset_hours: float,
) -> float:
    """
    Radiazione extra-atmosferica R_a integrata sul blocco
    [start_hour, end_hour) di ora civile standard, in MJ/m² (FAO-56
    eq. 28).

    La eq. 28 è l'integrale esatto del flusso solare fra due angoli
    orari: vale per un'ora come per sei, purché ω₁ e ω₂ restino dentro
    l'arco diurno — il taglio a [−ω_s, ω_s] è quello che FAO-56
    prescrive, e rende la somma dei blocchi di un giorno uguale alla
    R_a giornaliera della eq. 21. Di notte vale zero.
    """
    phi, delta, _w1, _w2, a, b = _clipped_hour_angles(
        latitude_deg, longitude_deg, j, start_hour, end_hour, utc_offset_hours,
    )
    if b <= a:
        return 0.0
    dr = inverse_relative_distance(j)
    return (12.0 * 60.0 / math.pi) * SOLAR_CONSTANT * dr * (
        (b - a) * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * (math.sin(b) - math.sin(a))
    )


def daylight_fraction(
    latitude_deg: float,
    longitude_deg: float,
    j: int,
    start_hour: float,
    end_hour: float,
    utc_offset_hours: float,
) -> float:
    """
    La frazione del blocco [start_hour, end_hour) in cui il sole è
    sopra l'orizzonte, in [0, 1]. Un blocco è «diurno» per le regole
    orarie di FAO-56 (G, R_s/R_so) quando la frazione è almeno 0.5.
    """
    _phi, _delta, w1, w2, a, b = _clipped_hour_angles(
        latitude_deg, longitude_deg, j, start_hour, end_hour, utc_offset_hours,
    )
    if b <= a:
        return 0.0
    return (b - a) / (w2 - w1)


def net_radiation_interval(
    solar_radiation_mj: float,
    extraterrestrial_radiation_mj: float,
    temperature_c: float,
    actual_vapor_pressure_kpa: float,
    hours: float,
    *,
    daytime: bool,
    rs_rso_night: float | None = None,
    elevation_m: float = 0.0,
    albedo: float = 0.23,
) -> float:
    """
    Radiazione netta R_n di un blocco di `hours` ore, in MJ/m² (FAO-56
    cap. 4, la forma oraria delle eq. 38–40).

    Rispetto a `net_radiation` (giornaliera) cambiano tre cose, tutte
    dettate da FAO-56 per i passi orari:

      - la temperatura è quella del blocco, alla quarta potenza, invece
        della media delle quarte potenze degli estremi del giorno;
      - σ è riscalata sulla durata (σ · hours / 24);
      - il rapporto R_s/R_so è limitato a [0.3, 1.0] e, quando il blocco
        è notturno (`daytime=False`) o non c'è radiazione di cielo
        sereno, va preso da fuori: `rs_rso_night`, il rapporto delle
        2–3 ore prima del tramonto. Senza, la funzione solleva
        ValueError: non si inventa un cielo.

    Parametri
    ---------
    solar_radiation_mj, extraterrestrial_radiation_mj : float
        R_s misurata e R_a del blocco, in MJ/m² sul blocco.
    temperature_c : float
        Temperatura media dell'aria nel blocco, in °C.
    actual_vapor_pressure_kpa : float
        e_a del blocco, in kPa.
    hours : float
        Durata del blocco, in ore (> 0).
    daytime : bool
        Se il blocco è diurno (sole sopra l'orizzonte per almeno metà
        della durata, `daylight_fraction` ≥ 0.5).
    rs_rso_night : float, opzionale
        Il rapporto R_s/R_so da usare quando il blocco è notturno.
    elevation_m, albedo : float
        Come in `net_radiation`.
    """
    if hours <= 0:
        raise ValueError(f"hours ({hours}) deve essere positivo.")
    rns = (1.0 - albedo) * solar_radiation_mj

    rso = clear_sky_radiation(extraterrestrial_radiation_mj, elevation_m)
    if daytime and rso > 0.0:
        ratio = solar_radiation_mj / rso
    else:
        if rs_rso_night is None:
            raise ValueError(
                "Blocco notturno: serve rs_rso_night, il rapporto R_s/R_so "
                "delle 2–3 ore prima del tramonto (FAO-56 cap. 4)."
            )
        ratio = rs_rso_night
    ratio = min(max(ratio, RS_RSO_MIN_SUBDAILY), 1.0)

    sigma = STEFAN_BOLTZMANN_MJ_M2_DAY * hours / 24.0
    t_k = temperature_c + 273.16
    rnl = (
        sigma * t_k ** 4
        * (0.34 - 0.14 * math.sqrt(actual_vapor_pressure_kpa))
        * (1.35 * ratio - 0.35)
    )
    return rns - rnl
