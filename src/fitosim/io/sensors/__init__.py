"""
Livello di astrazione per le sorgenti di dati di fitosim.

Questo package definisce le interfacce uniformi (`EnvironmentSensor` e
`SoilSensor`) attraverso le quali fitosim consuma dati da sorgenti
esterne. Ogni adapter concreto — Open-Meteo, Ecowitt, ATO 7-in-1 —
implementa una o entrambe queste interfacce, e il chiamante lavora
sempre con le stesse strutture dati canoniche (`EnvironmentReading`,
`SoilReading`) indipendentemente dal provider sottostante.

Uso tipico
----------

Per costruire un adapter concreto e leggere i dati::

    from fitosim.io.sensors import OpenMeteoEnvironmentSensor

    sensor = OpenMeteoEnvironmentSensor()
    conditions = sensor.current_conditions(latitude=45.46, longitude=9.19)
    print(f"Temperatura ora: {conditions.temperature_c} °C")

    forecast = sensor.forecast(latitude=45.46, longitude=9.19, days=7)
    for day in forecast:
        print(f"{day.timestamp.date()}: ET₀={day.et0_mm} mm")

Per costruire un adapter da variabili d'ambiente::

    from fitosim.io.sensors import EcowittEnvironmentSensor

    sensor = EcowittEnvironmentSensor.from_env()  # legge FITOSIM_ECOWITT_*
    conditions = sensor.current_conditions(latitude=45.46, longitude=9.19)

Per implementare un nuovo adapter custom, basta creare una classe che
espone i metodi richiesti dai Protocol — non è necessario importare
nulla da fitosim. Il duck typing strutturale farà il resto.
"""

from fitosim.io.sensors.ecowitt import (
    EcowittEnvironmentSensor,
    EcowittWH51SoilSensor,
)
from fitosim.io.sensors.errors import (
    SensorDataQualityError,
    SensorError,
    SensorPermanentError,
    SensorTemporaryError,
)
from fitosim.io.sensors.fixtures import (
    CsvEnvironmentFixture,
    CsvSoilFixture,
)
from fitosim.io.sensors.openmeteo import OpenMeteoEnvironmentSensor
from fitosim.io.sensors.protocols import EnvironmentSensor, SoilSensor
from fitosim.io.sensors.types import (
    EnvironmentReading,
    ReadingQuality,
    SoilReading,
    utc_now,
)

__all__ = [
    # Errori
    "SensorError",
    "SensorTemporaryError",
    "SensorPermanentError",
    "SensorDataQualityError",
    # Tipi di ritorno
    "EnvironmentReading",
    "SoilReading",
    "ReadingQuality",
    "utc_now",
    # Protocol
    "EnvironmentSensor",
    "SoilSensor",
    # Adapter operativi
    "OpenMeteoEnvironmentSensor",
    "EcowittEnvironmentSensor",
    "EcowittWH51SoilSensor",
    # Fixture per test e backfilling
    "CsvEnvironmentFixture",
    "CsvSoilFixture",
]
