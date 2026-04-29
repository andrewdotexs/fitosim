"""
Test per fitosim.science.radiation.

Le formule astronomiche per il calcolo di R_a sono completamente
deterministiche, quindi i test possono essere di due tipi:
  1. Confronto contro valori di riferimento pubblicati (FAO-56 e
     letteratura agronomica standard).
  2. Verifica di proprietà geometriche e simmetriche intrinseche
     (equinozi, solstizi, emisferi) che possiamo ragionare a mente
     senza bisogno di tabelle esterne.

Entrambi i tipi sono preziosi: i primi ci ancorano alla realtà
scientifica, i secondi segnalerebbero subito errori sistematici tipo
"segno invertito" o "radianti scambiati con gradi" che un confronto
numerico con una singola tabella potrebbe non catturare.
"""

import math
import unittest
from datetime import date

from fitosim.science.radiation import (
    clear_sky_radiation,
    day_of_year,
    extraterrestrial_radiation,
    inverse_relative_distance,
    net_radiation,
    solar_declination,
    sunset_hour_angle,
)


class TestAstronomicalPrimitives(unittest.TestCase):
    """Controllo dei singoli mattoncini astronomici."""

    def test_day_of_year_endpoints(self):
        # Primo e ultimo giorno dell'anno, anno normale.
        self.assertEqual(day_of_year(date(2025, 1, 1)), 1)
        self.assertEqual(day_of_year(date(2025, 12, 31)), 365)
        # Anno bisestile: 2024 ha 29 febbraio, quindi 31 dicembre = 366.
        self.assertEqual(day_of_year(date(2024, 12, 31)), 366)

    def test_inverse_relative_distance_perihelion_and_aphelion(self):
        # Al perielio (inizio gennaio, J ≈ 3) d_r è massima, circa 1.033:
        # la Terra è più vicina al Sole e riceve più flusso.
        self.assertAlmostEqual(inverse_relative_distance(3), 1.033, places=3)
        # All'afelio (inizio luglio, J ≈ 184) d_r è minima, circa 0.967.
        self.assertAlmostEqual(inverse_relative_distance(184), 0.967, places=3)

    def test_solar_declination_solstices(self):
        # Solstizio d'estate boreale (circa 21 giugno, J=172): declinazione
        # vicina al massimo teorico di 23.45° ≈ 0.409 rad.
        self.assertAlmostEqual(solar_declination(172), 0.409, places=2)
        # Solstizio d'inverno boreale (circa 21 dicembre, J=355):
        # speculare verso il basso, circa -0.409 rad.
        self.assertAlmostEqual(solar_declination(355), -0.409, places=2)

    def test_solar_declination_near_equinoxes(self):
        # Agli equinozi la declinazione deve essere "piccola". La formula
        # FAO-56 è un'approssimazione sinusoidale e l'esatta coincidenza
        # con i giorni dell'equinozio astronomico non è garantita — ma
        # il valore in quei giorni deve comunque restare entro ±2°
        # (circa 0.035 rad).
        self.assertLess(abs(solar_declination(80)), 0.035)   # ~21 marzo
        self.assertLess(abs(solar_declination(266)), 0.035)  # ~23 settembre

    def test_sunset_hour_angle_equator_at_equinox(self):
        # All'equatore negli equinozi il giorno dura esattamente 12 ore,
        # quindi ω_s deve valere π/2. È un test che cattura subito
        # eventuali errori sistematici di segno o di unità.
        omega = sunset_hour_angle(latitude_rad=0.0, declination_rad=0.0)
        self.assertAlmostEqual(omega, math.pi / 2, places=6)


class TestExtraterrestrialRadiation(unittest.TestCase):
    """Test di R_a contro valori tabellati e proprietà fisiche."""

    def test_fao56_example_8(self):
        """
        Esempio 8 di FAO-56 (Capitolo 3).

        Caso canonico: latitudine 20° Sud, 3 settembre.
        Valore pubblicato in FAO-56: R_a = 32.2 MJ m⁻² giorno⁻¹.

        Questo è il test di ancoraggio scientifico più importante del
        progetto: coincidere con questo valore significa parlare la
        stessa lingua numerica della letteratura agronomica mondiale.
        """
        ra = extraterrestrial_radiation(
            latitude_deg=-20.0,
            j=day_of_year(date(2025, 9, 3)),  # 3 settembre → J = 246
        )
        # Tolleranza 0.1: FAO-56 riporta il valore con una cifra decimale,
        # quindi ±0.05 è il rumore di arrotondamento atteso; concediamo
        # un margine leggermente più largo per sicurezza.
        self.assertAlmostEqual(ra, 32.2, delta=0.1)

    def test_equator_at_spring_equinox(self):
        """
        All'equatore agli equinozi R_a tende al suo valore "geometrico
        puro" (24 × 60 / π) × G_sc × d_r, perché seno di phi = 0 e
        seno di delta ≈ 0 azzerano uno dei termini della parentesi e
        il coseno di delta vale quasi 1. Con d_r ≈ 1.007 per J=80, ci
        aspettiamo R_a ≈ 37.8 MJ m⁻² giorno⁻¹.
        """
        ra = extraterrestrial_radiation(latitude_deg=0.0, j=80)
        self.assertAlmostEqual(ra, 37.8, delta=0.1)

    def test_milan_summer_solstice_is_in_expected_range(self):
        """
        Per Milano (45.47°N) al solstizio d'estate non abbiamo un
        riferimento tabellato FAO a portata, ma sappiamo dalla
        letteratura che R_a a latitudini temperate europee a mezza
        estate vale tra 40 e 42 MJ m⁻² giorno⁻¹. Questo test fa da
        "sanity check" di ordine di grandezza per il caso d'uso più
        tipico per noi.
        """
        ra = extraterrestrial_radiation(latitude_deg=45.47, j=172)
        self.assertGreater(ra, 40.0)
        self.assertLess(ra, 42.5)

    def test_hemispheric_summer_symmetry(self):
        """
        Estate boreale a +30° e estate australe a -30° dovrebbero
        produrre R_a molto simili: il contributo latitudinale è
        identico per simmetria, la differenza viene solo
        dall'eccentricità orbitale (d_r vale circa 0.967 a giugno e
        1.033 a dicembre, uno scarto di circa il 7%).
        """
        ra_north_jun = extraterrestrial_radiation(30.0, 172)
        ra_south_dec = extraterrestrial_radiation(-30.0, 355)
        relative_diff = abs(ra_north_jun - ra_south_dec) / ra_north_jun
        self.assertLess(relative_diff, 0.08)

    def test_radiation_is_always_positive_in_temperate_zones(self):
        """
        Sanity check: in zone temperate (entro ±60°) R_a deve essere
        strettamente positiva in qualsiasi giorno dell'anno. Un valore
        negativo indicherebbe un errore di segno da qualche parte.
        """
        for latitude in [-60.0, -30.0, 0.0, 30.0, 60.0]:
            for j in [1, 80, 172, 266, 355]:
                with self.subTest(latitude=latitude, j=j):
                    ra = extraterrestrial_radiation(latitude, j)
                    self.assertGreater(ra, 0.0)


# =====================================================================
#  Test delle funzioni di radiazione netta introdotte in tappa 5.
#
#  Le due funzioni clear_sky_radiation e net_radiation completano
#  la catena della radiazione fino al valore Rn che il Penman-Monteith
#  consuma. Le testiamo per coerenza fisica e per i casi limite
#  significativi.
# =====================================================================


class TestClearSkyRadiation(unittest.TestCase):
    """
    Radiazione di cielo sereno R_so. È una frazione della radiazione
    extra-atmosferica R_a, modulata dalla quota.
    """

    def test_sea_level_default_transmissivity(self):
        # A z=0 il coefficiente è esattamente 0.75 (trasmissività media
        # dell'atmosfera in giorno sereno al livello del mare).
        ra = 40.0
        rso = clear_sky_radiation(ra, elevation_m=0.0)
        self.assertAlmostEqual(rso / ra, 0.75, places=4)

    def test_higher_elevation_increases_transmissivity(self):
        # A quote più alte la trasmissività cresce leggermente perché
        # l'aria è meno densa e più trasparente.
        ra = 40.0
        rso_sea = clear_sky_radiation(ra, elevation_m=0.0)
        rso_mountain = clear_sky_radiation(ra, elevation_m=2000.0)
        self.assertGreater(rso_mountain, rso_sea)
        # Per 2000 m l'incremento è 2e-5 × 2000 = 0.04, quindi 79% di Ra.
        self.assertAlmostEqual(rso_mountain / ra, 0.79, places=3)

    def test_proportional_to_extraterrestrial(self):
        # A parità di quota, R_so è proporzionale a R_a.
        rso_low = clear_sky_radiation(20.0, elevation_m=100.0)
        rso_high = clear_sky_radiation(40.0, elevation_m=100.0)
        self.assertAlmostEqual(rso_high / rso_low, 2.0, places=4)


class TestNetRadiation(unittest.TestCase):
    """
    Radiazione netta R_n: bilancio energetico tra radiazione solare
    assorbita e radiazione termica netta verso il cielo.
    """

    def test_milan_summer_in_realistic_range(self):
        """
        Scenario tipico Milano in luglio: R_n deve cadere nell'intervallo
        agronomicamente plausibile 8-15 MJ/m²/d per giornata serena.
        """
        ra = extraterrestrial_radiation(45.47, 200)
        # ea per T_max 32, T_min 20, RH 60%.
        ea_at_t_min = 0.6108 * math.exp(17.27 * 20 / (20 + 237.3)) * 0.60
        ea_at_t_max = 0.6108 * math.exp(17.27 * 32 / (32 + 237.3)) * 0.60
        ea = (ea_at_t_min + ea_at_t_max) / 2
        rn = net_radiation(
            solar_radiation_mj=24.0,
            extraterrestrial_radiation_mj=ra,
            t_max_c=32.0, t_min_c=20.0,
            actual_vapor_pressure_kpa=ea,
            elevation_m=150.0,
        )
        self.assertGreater(rn, 8.0)
        self.assertLess(rn, 15.0)

    def test_higher_albedo_reduces_rn(self):
        """
        Albedo maggiore (superficie più riflettente) → meno energia
        assorbita → R_n minore. Questo è fisicamente fondamentale e
        spiega perché terreni nudi chiari evaporano meno di copertura
        verde scura.
        """
        common = dict(
            solar_radiation_mj=20.0,
            extraterrestrial_radiation_mj=35.0,
            t_max_c=25.0, t_min_c=15.0,
            actual_vapor_pressure_kpa=1.5,
            elevation_m=100.0,
        )
        rn_dark = net_radiation(albedo=0.10, **common)
        rn_grass = net_radiation(albedo=0.23, **common)
        rn_snow = net_radiation(albedo=0.85, **common)
        self.assertGreater(rn_dark, rn_grass)
        self.assertGreater(rn_grass, rn_snow)

    def test_overcast_sky_reduces_rn(self):
        """
        Una giornata molto nuvolosa (Rs ridotta a una frazione della
        radiazione di cielo sereno) deve produrre R_n significativamente
        ridotta rispetto alla stessa giornata serena. Non necessariamente
        negativa: la formula FAO-56 per la radiazione netta a onde lunghe
        è ben definita solo per Rs/Rso ≥ 0.26 circa, e nella realtà fisica
        anche le giornate più nuvolose mantengono Rs almeno a quella
        soglia per via della luce diffusa dalle nuvole.
        """
        common = dict(
            extraterrestrial_radiation_mj=35.0,
            t_max_c=15.0, t_min_c=5.0,
            actual_vapor_pressure_kpa=1.0,
            elevation_m=0.0,
        )
        # Cielo sereno: Rs = 0.75 × Ra (massima trasmissività).
        rn_clear = net_radiation(solar_radiation_mj=26.0, **common)
        # Cielo molto nuvoloso: Rs = 0.30 × Ra (luce diffusa minima).
        rn_overcast = net_radiation(solar_radiation_mj=10.5, **common)
        self.assertGreater(rn_clear, rn_overcast)
        self.assertGreater(rn_clear - rn_overcast, 5.0)  # differenza significativa


if __name__ == "__main__":
    unittest.main()
