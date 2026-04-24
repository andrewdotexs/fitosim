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

    # La formula intera. Il fattore (24 × 60 / π) converte il prodotto
    # adimensionale di costante solare × d_r × integrale-angolare in
    # energia giornaliera per unità di superficie. Il termine fra
    # parentesi quadre (bracket) è l'integrale di cos(θ) sulla semigiornata,
    # scritto in forma chiusa per l'emisfero visibile.
    factor = (24.0 * 60.0 / math.pi) * SOLAR_CONSTANT * dr
    bracket = (
        omega_s * math.sin(phi) * math.sin(delta)
        + math.cos(phi) * math.cos(delta) * math.sin(omega_s)
    )

    return factor * bracket
