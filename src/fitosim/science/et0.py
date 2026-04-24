"""
Evapotraspirazione di riferimento ET₀ con la formula di Hargreaves-Samani.

ET₀ è l'evapotraspirazione giornaliera di una coltura di riferimento
ipotetica e standardizzata (prato verde, 12 cm di altezza, resistenza
stomatica 70 s/m, albedo 0.23, ben irrigato, vasta estensione). Dipende
soltanto dalle condizioni meteorologiche del sito ed è la "domanda
atmosferica" comune a tutte le piante in quel luogo. L'evapotraspirazione
effettiva di una specie specifica si ottiene moltiplicando ET₀ per il
coefficiente colturale Kc di quella specie nel suo stadio fenologico
corrente: ET_c = Kc × ET₀.

Questo modulo implementa Hargreaves-Samani (1985), la via d'ingresso più
semplice al calcolo di ET₀: richiede soltanto temperature min/max del
giorno e la radiazione extra-atmosferica R_a (che calcoliamo in
`fitosim.science.radiation`). È meno accurata di Penman-Monteith FAO-56
in climi ventilati, ma ha l'enorme vantaggio di non richiedere dati di
vento e umidità, che nelle stazioni domestiche sono spesso mancanti,
rumorosi o di qualità non chiara. FAO-56 stessa la raccomanda come
fallback quando non si dispone di dati meteo completi.

Il trucco intellettuale della formula è usare l'escursione termica
giornaliera (T_max − T_min) come proxy di tre variabili normalmente
misurate separatamente — radiazione netta, nuvolosità e umidità
atmosferica — sfruttando il fatto che giornate limpide e secche hanno
grande escursione mentre giornate nuvolose e umide ne hanno poca.

Riferimento:
    Hargreaves, G. H., & Samani, Z. A. (1985). Reference crop
    evapotranspiration from temperature. Applied Engineering in
    Agriculture, 1(2), 96-99.
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
