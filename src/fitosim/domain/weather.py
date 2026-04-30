"""
Strutture di dato per i dati meteo grezzi di un singolo giorno.

Questo modulo introduce la dataclass `WeatherDay`, che incapsula gli
ingredienti meteo che il modello scientifico consuma per calcolare
l'evapotraspirazione attraverso il selettore "best available" del
modulo `science/et0.py`.

La distinzione tra `WeatherDay` e `WeatherDayForecast` (che vive in
`scheduling.py`) merita un po' di attenzione perché le due dataclass
si somigliano in superficie ma servono scopi concettualmente diversi.

`WeatherDayForecast` è "previsione meteo aggregata per il forecast a
N giorni del Garden". Ha solo tre campi (data, ET₀ pre-calcolata,
pioggia) perché chi la usa è già in possesso di ET₀ pronta da
applicare al bilancio idrico, tipicamente dal forecast Open-Meteo
che la calcola al posto suo.

`WeatherDay` è invece "dati meteo grezzi di un singolo giorno", quelli
che la stazione Ecowitt sul balcone produce direttamente: temperature
minima e massima, umidità relativa, velocità del vento, radiazione
solare globale. Il chiamante che usa `WeatherDay` lascia al modello
scientifico (attraverso il selettore della sotto-tappa B) il compito
di trasformare questi dati grezzi in ET, scegliendo automaticamente
la formula migliore applicabile in funzione di quali dati sono
effettivamente disponibili.

Le due dataclass sono complementari, non concorrenti: il chiamante
sceglie quella adatta al proprio contesto. Chi ha già ET₀ calcolata
da un'altra fonte usa `WeatherDayForecast`. Chi ha dati meteo grezzi
e vuole che la libreria scelga la formula migliore usa `WeatherDay`.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class WeatherDay:
    """
    Dati meteo grezzi di un singolo giorno.

    Incapsula gli ingredienti che la stazione meteo (Ecowitt sul
    balcone, Open-Meteo come forecast, qualunque altra fonte) produce
    direttamente, in una struttura immutabile e facile da passare in
    giro tra i livelli applicativi della libreria.

    Le temperature minima e massima sono sempre obbligatorie perché
    sono il minimo richiesto dal fallback Hargreaves del selettore.
    I tre dati meteo aggiuntivi (umidità, vento, radiazione solare)
    sono opzionali: quando sono tutti presenti il selettore userà
    Penman-Monteith; quando uno o più mancano ricadrà su Hargreaves.

    Il campo `solar_radiation_mj_m2_day` contiene la radiazione globale
    Rs misurata dal piranometro (la quantità che la stazione meteo
    riporta direttamente), non la radiazione netta Rn richiesta da
    Penman-Monteith. La conversione da Rs a Rn richiede temperatura,
    umidità e quota del sito, ed è eseguita internamente dal codice
    che consuma `WeatherDay` (per esempio dal `Pot.apply_balance_step_from_weather`)
    invece di essere richiesta al chiamante.

    Campi
    -----
    date_ : date
        La data del giorno cui si riferiscono i dati meteo. Usata per
        derivare il giorno dell'anno (1-366) richiesto dai calcoli
        astronomici della radiazione extra-atmosferica.
    t_min : float
        Temperatura minima giornaliera, in °C. Tipicamente registrata
        poco prima dell'alba.
    t_max : float
        Temperatura massima giornaliera, in °C. Tipicamente registrata
        nel primo pomeriggio.
    humidity_relative : float, opzionale
        Umidità relativa media giornaliera come frazione 0..1 (NON
        percentuale). Esempio: 65% di umidità si esprime come 0.65.
        Se None, il selettore non potrà usare Penman-Monteith e
        ricadrà su Hargreaves.
    wind_speed_m_s : float, opzionale
        Velocità del vento a 2 metri di altezza, in m/s. Stesso
        comportamento di humidity_relative quando assente.
    solar_radiation_mj_m2_day : float, opzionale
        Radiazione solare globale Rs, in MJ/m²/giorno. È la grandezza
        misurata direttamente dal piranometro. Stesso comportamento
        delle altre due quando assente.
    """

    date_: date
    t_min: float
    t_max: float
    humidity_relative: Optional[float] = None
    wind_speed_m_s: Optional[float] = None
    solar_radiation_mj_m2_day: Optional[float] = None

    @property
    def has_full_weather(self) -> bool:
        """
        True se tutti e tre i dati meteo aggiuntivi sono presenti, cioè
        se i dati sono "completi" per Penman-Monteith. Utile come
        sanity check rapido senza dover ispezionare i tre campi
        individualmente.
        """
        return (
            self.humidity_relative is not None
            and self.wind_speed_m_s is not None
            and self.solar_radiation_mj_m2_day is not None
        )
