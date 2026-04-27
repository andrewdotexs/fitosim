"""
Test dei tipi canonici di ritorno dei sensori.

Questo file copre i comportamenti garantiti da `EnvironmentReading`,
`SoilReading` e `ReadingQuality`: costruzione corretta nei casi normali,
validazione nei casi limite, gestione del timestamp UTC obbligatorio.

Famiglie di test
----------------

  - `Test_ReadingQuality`: validazione del sotto-oggetto qualità.
  - `Test_EnvironmentReading_construction`: casi felici di costruzione.
  - `Test_EnvironmentReading_validation`: range fisicamente plausibili.
  - `Test_SoilReading_construction`: casi felici, campi opzionali.
  - `Test_SoilReading_validation`: range plausibili e campo obbligatorio.
  - `Test_timestamp_awareness`: regola UTC aware obbligatoria.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from fitosim.io.sensors import (
    EnvironmentReading,
    ReadingQuality,
    SensorDataQualityError,
    SoilReading,
    utc_now,
)


# --------------------------------------------------------------------------
#  ReadingQuality
# --------------------------------------------------------------------------

class Test_ReadingQuality:
    """Validazione del sotto-oggetto metadati di qualità."""

    def test_default_construction_has_no_data(self):
        """Senza argomenti, tutti i campi sono None/zero (lettura
        anonima senza metadati di qualità noti)."""
        q = ReadingQuality()
        assert q.battery_level is None
        assert q.last_calibration is None
        assert q.staleness_seconds == 0

    def test_full_construction_preserves_values(self):
        """Con tutti i campi specificati, i valori vengono preservati
        senza trasformazioni."""
        cal_date = date(2026, 1, 15)
        q = ReadingQuality(
            battery_level=0.42,
            last_calibration=cal_date,
            staleness_seconds=120,
        )
        assert q.battery_level == 0.42
        assert q.last_calibration == cal_date
        assert q.staleness_seconds == 120

    def test_battery_level_out_of_range_low_raises(self):
        """Battery level negativo → errore di qualità (sensore guasto
        o conversione di unità sbagliata)."""
        with pytest.raises(SensorDataQualityError, match="battery_level"):
            ReadingQuality(battery_level=-0.1)

    def test_battery_level_out_of_range_high_raises(self):
        """Battery level > 1 → errore (forse il provider espone in
        percentuale 0-100 e l'adapter ha dimenticato di dividere)."""
        with pytest.raises(SensorDataQualityError, match="battery_level"):
            ReadingQuality(battery_level=85.0)

    def test_negative_staleness_raises(self):
        """Staleness negativo significa "lettura dal futuro": è il segno
        che l'orologio del sensore è sballato rispetto al nostro."""
        with pytest.raises(SensorDataQualityError, match="staleness"):
            ReadingQuality(staleness_seconds=-30)

    def test_is_frozen(self):
        """ReadingQuality è frozen dataclass: i campi non si possono
        modificare dopo la costruzione."""
        q = ReadingQuality(battery_level=0.5)
        with pytest.raises((AttributeError, TypeError)):
            q.battery_level = 0.8


# --------------------------------------------------------------------------
#  EnvironmentReading: costruzione nei casi normali
# --------------------------------------------------------------------------

class Test_EnvironmentReading_construction:
    """Costruzione di EnvironmentReading nei casi felici."""

    def test_minimal_construction_only_timestamp(self):
        """Il timestamp è l'unico campo strettamente obbligatorio.
        Tutti gli altri sono opzionali per accomodare provider con
        dati parziali."""
        r = EnvironmentReading(timestamp=utc_now())
        assert r.temperature_c is None
        assert r.humidity_relative is None
        assert r.radiation_mj_m2 is None
        assert r.wind_speed_m_s is None
        assert r.rain_mm is None
        assert r.et0_mm is None

    def test_full_construction_preserves_values(self):
        """Tutti i campi valorizzati vengono preservati senza
        conversione di unità (la conversione è responsabilità
        dell'adapter, non del Reading)."""
        ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
        r = EnvironmentReading(
            timestamp=ts,
            temperature_c=22.5,
            humidity_relative=0.65,
            radiation_mj_m2=18.3,
            wind_speed_m_s=2.1,
            rain_mm=0.0,
            et0_mm=4.2,
        )
        assert r.timestamp == ts
        assert r.temperature_c == 22.5
        assert r.humidity_relative == 0.65
        assert r.radiation_mj_m2 == 18.3
        assert r.wind_speed_m_s == 2.1
        assert r.rain_mm == 0.0
        assert r.et0_mm == 4.2

    def test_default_quality_is_anonymous(self):
        """Senza specificare quality, il Reading ha metadati anonimi.
        Riflette la realtà di provider che non espongono dati di
        qualità (es. Open-Meteo non ha "batteria")."""
        r = EnvironmentReading(timestamp=utc_now())
        assert r.quality.battery_level is None
        assert r.quality.staleness_seconds == 0

    def test_extreme_but_plausible_values_accepted(self):
        """Valori estremi ma fisicamente possibili sono accettati. Il
        deserto del Sahara raggiunge 50 °C, il polo Nord -55 °C, ma
        sono entrambi reali e il Reading li deve permettere."""
        r1 = EnvironmentReading(timestamp=utc_now(), temperature_c=50.0)
        r2 = EnvironmentReading(timestamp=utc_now(), temperature_c=-55.0)
        assert r1.temperature_c == 50.0
        assert r2.temperature_c == -55.0


# --------------------------------------------------------------------------
#  EnvironmentReading: validazione dei range
# --------------------------------------------------------------------------

class Test_EnvironmentReading_validation:
    """Range fisicamente plausibili. Valori fuori range → DataQuality."""

    def test_temperature_too_low_raises(self):
        with pytest.raises(SensorDataQualityError, match="temperature_c"):
            EnvironmentReading(timestamp=utc_now(), temperature_c=-100.0)

    def test_temperature_too_high_raises(self):
        with pytest.raises(SensorDataQualityError, match="temperature_c"):
            EnvironmentReading(timestamp=utc_now(), temperature_c=150.0)

    def test_humidity_in_percentage_raises(self):
        """Umidità relativa è frazione 0..1, NON percentuale. Se
        l'adapter passa 65 invece di 0.65 il messaggio di errore
        suggerisce esplicitamente la causa probabile."""
        with pytest.raises(SensorDataQualityError, match="percentuale"):
            EnvironmentReading(timestamp=utc_now(), humidity_relative=65.0)

    def test_humidity_negative_raises(self):
        with pytest.raises(SensorDataQualityError):
            EnvironmentReading(timestamp=utc_now(), humidity_relative=-0.1)

    def test_radiation_negative_raises(self):
        """La radiazione globale è una grandezza positiva per
        definizione (è un flusso entrante)."""
        with pytest.raises(SensorDataQualityError, match="radiation"):
            EnvironmentReading(timestamp=utc_now(), radiation_mj_m2=-1.0)

    def test_radiation_extreme_raises(self):
        """Valori >50 MJ/m²/giorno sono fuori range fisico (il massimo
        teorico per la latitudine equatoriale è circa 35-40)."""
        with pytest.raises(SensorDataQualityError):
            EnvironmentReading(timestamp=utc_now(), radiation_mj_m2=80.0)

    def test_wind_extreme_raises(self):
        """Vento >100 m/s non si è mai osservato sulla terra."""
        with pytest.raises(SensorDataQualityError, match="wind"):
            EnvironmentReading(timestamp=utc_now(), wind_speed_m_s=200.0)

    def test_rain_negative_raises(self):
        with pytest.raises(SensorDataQualityError, match="rain"):
            EnvironmentReading(timestamp=utc_now(), rain_mm=-5.0)

    def test_et0_negative_raises(self):
        """ET₀ è una stima di evapotraspirazione, sempre positiva."""
        with pytest.raises(SensorDataQualityError, match="et0"):
            EnvironmentReading(timestamp=utc_now(), et0_mm=-2.0)


# --------------------------------------------------------------------------
#  SoilReading: costruzione e validazione
# --------------------------------------------------------------------------

class Test_SoilReading_construction:
    """Costruzione di SoilReading nei casi felici."""

    def test_minimal_construction_requires_theta(self):
        """θ è OBBLIGATORIO (a differenza degli altri campi).
        È l'unica misura che ogni sensore di suolo fornisce."""
        r = SoilReading(timestamp=utc_now(), theta_volumetric=0.32)
        assert r.theta_volumetric == 0.32
        assert r.temperature_c is None
        assert r.ec_mscm is None
        assert r.ph is None

    def test_full_construction_for_ato_7in1(self):
        """Caso d'uso tappa 2: l'ATO 7-in-1 espone θ, T, EC, pH tutti
        contemporaneamente. Tutti i campi vengono preservati."""
        ts = utc_now()
        r = SoilReading(
            timestamp=ts,
            theta_volumetric=0.35,
            temperature_c=18.5,
            ec_mscm=1.8,
            ph=6.5,
        )
        assert r.theta_volumetric == 0.35
        assert r.temperature_c == 18.5
        assert r.ec_mscm == 1.8
        assert r.ph == 6.5

    def test_partial_construction_for_xiaomi_miflora(self):
        """Sensore tipo MiFlora espone θ, T, EC ma niente pH. Il
        pattern tipico è di lasciare il campo non disponibile a None,
        non di inventare valori finti."""
        r = SoilReading(
            timestamp=utc_now(),
            theta_volumetric=0.28,
            temperature_c=20.0,
            ec_mscm=0.9,
            # ph non specificato → resta None
        )
        assert r.ph is None
        assert r.ec_mscm == 0.9


class Test_SoilReading_validation:
    """Validazione fisica delle letture del substrato."""

    def test_theta_negative_raises(self):
        """θ negativo è impossibile fisicamente (sensore scollegato o
        bug del firmware)."""
        with pytest.raises(SensorDataQualityError, match="theta"):
            SoilReading(timestamp=utc_now(), theta_volumetric=-0.05)

    def test_theta_above_one_slightly_accepted(self):
        """Tolleriamo piccoli valori sopra 1 (rumore di sensori TDR
        in saturazione). 1.02 è accettato, 1.5 no."""
        r = SoilReading(timestamp=utc_now(), theta_volumetric=1.02)
        assert r.theta_volumetric == 1.02

    def test_theta_in_percentage_raises(self):
        """Se l'adapter passa 32 invece di 0.32 (percentuale invece
        che frazione), il messaggio suggerisce la causa probabile."""
        with pytest.raises(SensorDataQualityError, match="percentuale"):
            SoilReading(timestamp=utc_now(), theta_volumetric=32.0)

    def test_temperature_substrate_extreme_raises(self):
        """Il substrato in vaso è meno esposto agli estremi dell'aria.
        Range di accettazione più stretto."""
        with pytest.raises(SensorDataQualityError, match="temperature"):
            SoilReading(
                timestamp=utc_now(),
                theta_volumetric=0.3,
                temperature_c=80.0,
            )

    def test_ec_in_microsiemens_raises(self):
        """EC > 20 mS/cm è quasi certamente un errore di unità: il
        provider sta esponendo μS/cm e l'adapter ha dimenticato la
        conversione."""
        with pytest.raises(SensorDataQualityError, match="μS"):
            SoilReading(
                timestamp=utc_now(),
                theta_volumetric=0.3,
                ec_mscm=2500.0,
            )

    def test_ph_above_14_raises(self):
        """pH è limitato dalla chimica a [0,14]. Fuori range = sensore
        completamente scalibrato."""
        with pytest.raises(SensorDataQualityError, match="ph"):
            SoilReading(
                timestamp=utc_now(),
                theta_volumetric=0.3,
                ph=15.5,
            )


# --------------------------------------------------------------------------
#  Timestamp: regola UTC aware obbligatoria
# --------------------------------------------------------------------------

class Test_timestamp_awareness:
    """La regola architetturale: timestamp aware in UTC, sempre."""

    def test_naive_timestamp_in_environment_raises(self):
        """datetime senza tzinfo è vietato a livello architetturale."""
        naive = datetime(2026, 5, 1, 12, 0)  # niente tzinfo
        with pytest.raises(SensorDataQualityError, match="timezone-aware"):
            EnvironmentReading(timestamp=naive)

    def test_naive_timestamp_in_soil_raises(self):
        naive = datetime(2026, 5, 1, 12, 0)
        with pytest.raises(SensorDataQualityError, match="timezone-aware"):
            SoilReading(timestamp=naive, theta_volumetric=0.3)

    def test_aware_timestamp_other_timezone_accepted(self):
        """Aware timestamp in qualsiasi timezone è accettato. Il
        chiamante ha responsabilità di passare UTC, ma noi non ci
        rifiutiamo se per qualche ragione il provider espone già
        in fuso locale aware (purché sia aware)."""
        # Timezone fittizia +02:00 (ora legale Europa centrale)
        cest = timezone(timedelta(hours=2))
        ts = datetime(2026, 5, 1, 14, 0, tzinfo=cest)
        r = EnvironmentReading(timestamp=ts, temperature_c=20.0)
        # Il timestamp è preservato così com'è, in CEST.
        assert r.timestamp.tzinfo is not None

    def test_utc_now_returns_aware(self):
        """L'helper utc_now() produce sempre datetime aware in UTC.
        È la funzione canonica che gli adapter devono usare quando
        il provider non espone un timestamp proprio."""
        ts = utc_now()
        assert ts.tzinfo is not None
        assert ts.tzinfo == timezone.utc
