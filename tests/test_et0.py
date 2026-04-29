"""
Test per fitosim.science.et0.

La formula di Hargreaves-Samani è deterministica e relativamente semplice,
quindi i test mescolano:
  1. Conversioni di unità elementari (MJ/m² → mm di acqua) come sanity
     check numerici di base.
  2. Un caso di validazione calcolato a mano con input "tondi", così da
     poter verificare il codice confrontandolo con aritmetica eseguibile
     su carta.
  3. Verifica di comportamenti fisicamente attesi: stagionalità, range
     di letteratura per un clima temperato continentale, gestione dei
     casi degeneri (escursione zero, temperature invertite).
"""

import math
import unittest
from datetime import date

from fitosim.science.et0 import (
    LATENT_HEAT_VAPORIZATION,
    EtMethod,
    EtResult,
    actual_vapor_pressure,
    aerodynamic_resistance,
    atmospheric_pressure,
    compute_et,
    compute_et0_penman_monteith,
    compute_et_penman_monteith_physical,
    et0_hargreaves_samani,
    mj_per_m2_to_mm_water,
    psychrometric_constant,
    saturation_vapor_pressure,
    slope_vapor_pressure,
)
from fitosim.science.radiation import day_of_year


class TestUnitConversion(unittest.TestCase):
    """Controllo della costante fisica e della conversione energia→acqua."""

    def test_latent_heat_value(self):
        # Valore standard FAO-56 a circa 20 °C.
        self.assertEqual(LATENT_HEAT_VAPORIZATION, 2.45)

    def test_mj_to_mm_identity_at_one(self):
        # 1 MJ/m² deve produrre 1/2.45 ≈ 0.408 mm di acqua.
        self.assertAlmostEqual(mj_per_m2_to_mm_water(1.0), 1.0 / 2.45, places=6)

    def test_mj_to_mm_zero_is_zero(self):
        # Nessuna energia → nessuna evaporazione.
        self.assertEqual(mj_per_m2_to_mm_water(0.0), 0.0)

    def test_mj_to_mm_linearity(self):
        # La conversione è lineare: 10 MJ/m² → 10/2.45 mm.
        self.assertAlmostEqual(mj_per_m2_to_mm_water(10.0), 10.0 / 2.45, places=6)


class TestHargreavesSamani(unittest.TestCase):
    """Test sulla formula ET₀ vera e propria."""

    def test_hand_calculated_equator_near_equinox(self):
        """
        Caso di validazione calcolato a mano, scelto con input "tondi"
        per facilitare la verifica indipendente.

        Input:
            Latitudine = 0° (equatore)
            J = 80 (circa 21 marzo, equinozio di primavera)
            T_min = 20 °C
            T_max = 30 °C

        Calcolo passo-passo:
            R_a(0°, J=80) ≈ 37.8 MJ/m²/giorno  (già validato in
                                                 test_radiation.py)
            R_a in mm      = 37.8 / 2.45 ≈ 15.428 mm/giorno
            T_med          = (20 + 30) / 2 = 25 °C
            ΔT             = 30 − 20 = 10 °C
            √ΔT            ≈ 3.1623
            fattore termico = 25 + 17.8 = 42.8
            ET₀            = 0.0023 × 42.8 × 3.1623 × 15.428
                           ≈ 4.80 mm/giorno
        """
        et0 = et0_hargreaves_samani(
            t_min=20.0, t_max=30.0, latitude_deg=0.0, j=80
        )
        self.assertAlmostEqual(et0, 4.80, delta=0.05)

    def test_milan_summer_in_expected_range(self):
        """
        Per Milano (45.47° N) a metà luglio con condizioni tipiche della
        pianura padana (T_min=18, T_max=30), ET₀ deve cadere nel range
        documentato per il clima temperato continentale europeo, cioè
        circa 4-7 mm/giorno.
        """
        et0 = et0_hargreaves_samani(
            t_min=18.0, t_max=30.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 7, 15)),
        )
        self.assertGreater(et0, 4.0)
        self.assertLess(et0, 7.0)

    def test_summer_higher_than_winter_same_location(self):
        """
        Stessa latitudine (Milano), condizioni meteo tipiche per la
        stagione. ET₀ estiva deve superare largamente quella invernale:
        il fattore è dovuto sia alla temperatura media (che moltiplica
        via il termine T_med + 17.8) sia alla radiazione astronomica
        R_a (molto maggiore in estate). Ci aspettiamo un rapporto di
        almeno 5x.
        """
        et0_summer = et0_hargreaves_samani(
            t_min=16.0, t_max=28.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 6, 15)),
        )
        et0_winter = et0_hargreaves_samani(
            t_min=-1.0, t_max=6.0, latitude_deg=45.47,
            j=day_of_year(date(2025, 1, 15)),
        )
        self.assertGreater(et0_summer, et0_winter)
        self.assertGreater(et0_summer / et0_winter, 5.0)

    def test_zero_thermal_range_yields_zero(self):
        """
        Caso limite degenerato: se T_max = T_min, l'escursione è nulla,
        la radice quadrata produce zero e l'intera ET₀ si azzera. Il
        risultato è matematicamente corretto ma fisicamente degradato:
        segnala che la formula non è in grado di dedurre il segnale
        radiativo dalla sola escursione. In pratica una giornata reale
        ha sempre un'escursione non nulla, quindi questo caso serve
        soprattutto come test del comportamento numerico al limite.
        """
        et0 = et0_hargreaves_samani(
            t_min=20.0, t_max=20.0, latitude_deg=0.0, j=80
        )
        self.assertEqual(et0, 0.0)

    def test_inverted_temperatures_raise_value_error(self):
        """
        Input corrotto (t_max < t_min) deve provocare una ValueError
        esplicita, non un risultato silenziosamente sbagliato (la radice
        quadrata di un numero negativo in Python produce un errore di
        dominio, ma vogliamo segnalarlo prima e con un messaggio
        leggibile).
        """
        with self.assertRaises(ValueError):
            et0_hargreaves_samani(
                t_min=30.0, t_max=20.0, latitude_deg=0.0, j=80
            )

    def test_thermal_range_effect_is_monotonic(self):
        """
        A parità di T_mean, latitudine e giorno, ET₀ deve crescere con
        l'escursione termica (T_max − T_min): un'escursione maggiore
        riflette cieli più limpidi e aria più secca, quindi più
        evaporazione. Test di monotonia su tre escursioni crescenti.
        """
        common = dict(latitude_deg=45.47, j=day_of_year(date(2025, 6, 15)))
        et0_small = et0_hargreaves_samani(t_min=21.0, t_max=23.0, **common)
        et0_medium = et0_hargreaves_samani(t_min=18.0, t_max=26.0, **common)
        et0_large = et0_hargreaves_samani(t_min=14.0, t_max=30.0, **common)
        self.assertLess(et0_small, et0_medium)
        self.assertLess(et0_medium, et0_large)


# =====================================================================
#  Test degli helper di base del Penman-Monteith.
#
#  Questi sei helper sono i mattoni elementari della formula. Li
#  testiamo individualmente confrontando con i valori tabulati di
#  FAO-56 capitolo 2 (appendice 2 della pubblicazione) e con i casi
#  limite fisicamente significativi.
# =====================================================================


class TestSaturationVaporPressure(unittest.TestCase):
    """
    Pressione di vapore saturo es alla temperatura specificata.
    Confrontiamo con i valori tabulati di FAO-56 a temperature
    rappresentative.
    """

    def test_freezing_point(self):
        # FAO-56 tabella 2.4: a 0 °C, es ≈ 0.6108 kPa.
        self.assertAlmostEqual(
            saturation_vapor_pressure(0.0), 0.6108, places=4,
        )

    def test_room_temperature(self):
        # A 20 °C (temperatura ambiente standard), es ≈ 2.339 kPa.
        self.assertAlmostEqual(
            saturation_vapor_pressure(20.0), 2.3383, places=3,
        )

    def test_summer_heat(self):
        # A 30 °C (giornata estiva calda), es ≈ 4.243 kPa.
        self.assertAlmostEqual(
            saturation_vapor_pressure(30.0), 4.2431, places=3,
        )

    def test_grows_monotonically_with_temperature(self):
        # es deve crescere strettamente con T (proprietà fondamentale
        # della curva di pressione di vapore).
        previous = -1.0
        for t in range(-10, 51, 5):
            current = saturation_vapor_pressure(float(t))
            self.assertGreater(current, previous)
            previous = current


class TestSlopeVaporPressure(unittest.TestCase):
    """
    Pendenza Δ della curva di pressione di vapore saturo. Verifichiamo
    che sia la derivata effettiva di es rispetto a T (test numerico
    via differenza finita) e che produca i valori tabulati.
    """

    def test_known_value_at_20c(self):
        # FAO-56 tabella 2.5: a 20 °C, Δ ≈ 0.1448 kPa/°C.
        self.assertAlmostEqual(
            slope_vapor_pressure(20.0), 0.1448, places=3,
        )

    def test_is_numerical_derivative_of_saturation(self):
        # Δ deve coincidere con la derivata numerica di es: differenza
        # finita centrata di passo piccolo deve dare lo stesso valore
        # entro errore numerico.
        t = 25.0
        h = 0.001
        numerical_derivative = (
            saturation_vapor_pressure(t + h) - saturation_vapor_pressure(t - h)
        ) / (2 * h)
        analytical_derivative = slope_vapor_pressure(t)
        self.assertAlmostEqual(
            numerical_derivative, analytical_derivative, places=4,
        )


class TestActualVaporPressure(unittest.TestCase):
    """
    Pressione di vapore attuale ea = RH × es(T).
    """

    def test_saturated_air_equals_es(self):
        # A umidità relativa 100% (saturazione), ea deve essere
        # esattamente uguale a es alla stessa temperatura.
        for t in [0.0, 15.0, 30.0]:
            self.assertAlmostEqual(
                actual_vapor_pressure(t, 1.0),
                saturation_vapor_pressure(t),
            )

    def test_dry_air_equals_zero(self):
        # A umidità relativa 0%, ea deve essere zero indipendentemente
        # dalla temperatura.
        for t in [0.0, 20.0, 40.0]:
            self.assertEqual(actual_vapor_pressure(t, 0.0), 0.0)

    def test_invalid_humidity_raises(self):
        # Umidità fuori dall'intervallo [0, 1] deve sollevare ValueError
        # con messaggio chiaro.
        for invalid_rh in [-0.1, 1.5, 50.0, 100.0]:
            with self.assertRaises(ValueError):
                actual_vapor_pressure(20.0, invalid_rh)


class TestAtmosphericPressure(unittest.TestCase):
    """
    Pressione atmosferica P alla quota specificata.
    """

    def test_sea_level_is_standard(self):
        # A z=0, P = 101.3 kPa per costruzione della formula.
        self.assertAlmostEqual(atmospheric_pressure(0.0), 101.3, places=3)

    def test_decreases_with_elevation(self):
        # P deve cala monotonicamente con la quota (l'aria sopra è
        # progressivamente meno densa).
        previous = atmospheric_pressure(0.0)
        for z in [100, 500, 1000, 2000, 3000]:
            current = atmospheric_pressure(float(z))
            self.assertLess(current, previous)
            previous = current

    def test_milan_value(self):
        # A 150 m (quota tipica del balcone milanese), P deve essere
        # circa 99.5 kPa (poco sotto al livello del mare, come ci si
        # aspetta per quote modeste).
        self.assertAlmostEqual(
            atmospheric_pressure(150.0), 99.54, places=1,
        )


class TestPsychrometricConstant(unittest.TestCase):
    """
    Costante psicrometrica γ.
    """

    def test_proportional_to_pressure(self):
        # γ è proporzionale a P attraverso il coefficiente 0.000665.
        # Verifichiamo la proporzionalità a tre valori di pressione.
        p1, p2 = 100.0, 80.0
        gamma1 = psychrometric_constant(p1)
        gamma2 = psychrometric_constant(p2)
        self.assertAlmostEqual(gamma1 / gamma2, p1 / p2, places=6)

    def test_standard_atmosphere_value(self):
        # A pressione standard 101.3 kPa, γ ≈ 0.0673 kPa/°C.
        self.assertAlmostEqual(
            psychrometric_constant(101.3), 0.0673, places=3,
        )


class TestAerodynamicResistance(unittest.TestCase):
    """
    Resistenza aerodinamica ra in funzione di vento e altezza colturale.
    """

    def test_reference_crop_matches_short_formula(self):
        # Per coltura di riferimento (h=0.12 m), la formula generale
        # deve produrre valori vicinissimi alla forma compatta 208/u₂.
        for u in [0.5, 1.0, 2.0, 4.0]:
            ra_general = aerodynamic_resistance(u, crop_height_m=0.12)
            ra_short = 208.0 / u
            relative_error = abs(ra_general - ra_short) / ra_short
            self.assertLess(relative_error, 0.01)  # entro 1%

    def test_decreases_with_wind(self):
        # Più vento → minore resistenza aerodinamica.
        previous = aerodynamic_resistance(0.5)
        for u in [1.0, 2.0, 4.0, 8.0]:
            current = aerodynamic_resistance(u)
            self.assertLess(current, previous)
            previous = current

    def test_zero_or_negative_wind_raises(self):
        # Vento ≤ 0 deve sollevare ValueError esplicito (senza vento
        # ra diventa infinita e la formula perde di significato).
        for invalid_u in [0.0, -1.0, -0.5]:
            with self.assertRaises(ValueError):
                aerodynamic_resistance(invalid_u)


# =====================================================================
#  Test della formula Penman-Monteith FAO-56 standard.
#
#  Verifichiamo il comportamento end-to-end della funzione che produce
#  ET₀ contro casi di letteratura, casi limite, e proprietà strutturali.
# =====================================================================


class TestPenmanMonteithStandard(unittest.TestCase):

    def test_milan_summer_in_expected_range(self):
        """
        Scenario tipico balcone milanese in luglio: ET₀ deve cadere
        nell'intervallo agronomicamente plausibile 4-7 mm/giorno.
        Verifica di "ordine di grandezza" che cattura errori grossolani.
        """
        # Calcoliamo una R_n realistica dalla radiazione globale.
        from fitosim.science.radiation import (
            extraterrestrial_radiation, net_radiation,
        )
        ra = extraterrestrial_radiation(45.47, 200)
        ea = actual_vapor_pressure(26.0, 0.60)
        rn = net_radiation(
            solar_radiation_mj=24.0,
            extraterrestrial_radiation_mj=ra,
            t_max_c=32.0, t_min_c=20.0,
            actual_vapor_pressure_kpa=ea,
            elevation_m=150.0,
        )

        et0 = compute_et0_penman_monteith(
            temperature_c=26.0,
            humidity_relative=0.60,
            wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=rn,
            elevation_m=150.0,
        )
        self.assertGreater(et0, 4.0)
        self.assertLess(et0, 7.0)

    def test_zero_wind_raises_via_aerodynamic_resistance(self):
        # Il vento non può essere zero (la formula diverge). L'errore
        # si propaga attraverso aerodynamic_resistance.
        with self.assertRaises(ValueError):
            compute_et0_penman_monteith(
                temperature_c=25.0,
                humidity_relative=0.5,
                wind_speed_m_s=0.0,
                net_radiation_mj_m2_day=10.0,
            )

    def test_invalid_humidity_raises(self):
        # Umidità fuori da [0, 1] deve sollevare ValueError.
        with self.assertRaises(ValueError):
            compute_et0_penman_monteith(
                temperature_c=25.0,
                humidity_relative=50.0,  # errore tipico: percentuale invece di frazione
                wind_speed_m_s=2.0,
                net_radiation_mj_m2_day=10.0,
            )

    def test_higher_radiation_yields_higher_et0(self):
        # A parità di tutto il resto, più radiazione → più ET₀.
        common = dict(
            temperature_c=20.0, humidity_relative=0.6,
            wind_speed_m_s=2.0, elevation_m=100.0,
        )
        et0_low = compute_et0_penman_monteith(
            net_radiation_mj_m2_day=5.0, **common,
        )
        et0_high = compute_et0_penman_monteith(
            net_radiation_mj_m2_day=15.0, **common,
        )
        self.assertGreater(et0_high, et0_low)

    def test_higher_humidity_yields_lower_et0(self):
        # A parità di tutto il resto, più umidità → minore deficit di
        # vapore → minore ET₀ (effetto del termine aerodinamico).
        common = dict(
            temperature_c=25.0,
            wind_speed_m_s=2.0,
            net_radiation_mj_m2_day=12.0,
            elevation_m=100.0,
        )
        et0_dry = compute_et0_penman_monteith(
            humidity_relative=0.30, **common,
        )
        et0_humid = compute_et0_penman_monteith(
            humidity_relative=0.85, **common,
        )
        self.assertGreater(et0_dry, et0_humid)


# =====================================================================
#  Test della formula Penman-Monteith fisica.
#
#  La versione fisica è la "canonica" di cui la standard è un caso
#  particolare. I test verificano questa relazione gerarchica e la
#  sensibilità ai parametri della specie.
# =====================================================================


class TestPenmanMonteithPhysical(unittest.TestCase):

    def test_reference_crop_parameters_recover_standard(self):
        """
        Quando passiamo i parametri della coltura di riferimento
        (rs=70 s/m, h=0.12 m), la versione fisica deve produrre
        esattamente lo stesso valore della standard. Questa è la
        proprietà chiave che giustifica la nostra implementazione
        gerarchica e va testata su molteplici scenari.
        """
        scenarios = [
            dict(temperature_c=10.0, humidity_relative=0.5,
                 wind_speed_m_s=2.0, net_radiation_mj_m2_day=5.0),
            dict(temperature_c=25.0, humidity_relative=0.7,
                 wind_speed_m_s=1.5, net_radiation_mj_m2_day=15.0),
            dict(temperature_c=35.0, humidity_relative=0.3,
                 wind_speed_m_s=4.0, net_radiation_mj_m2_day=20.0),
        ]
        for scenario in scenarios:
            with self.subTest(**scenario):
                et_standard = compute_et0_penman_monteith(
                    elevation_m=150.0, **scenario,
                )
                et_physical = compute_et_penman_monteith_physical(
                    stomatal_resistance_s_m=70.0,
                    crop_height_m=0.12,
                    elevation_m=150.0,
                    **scenario,
                )
                self.assertAlmostEqual(et_standard, et_physical, places=8)

    def test_higher_stomatal_resistance_yields_lower_et(self):
        """
        Resistenza stomatica maggiore → ET minore, a parità di tutto
        il resto. Questa è la proprietà fisiologica fondamentale che
        distingue una succulenta da un'erba mesofila.
        """
        common = dict(
            temperature_c=25.0,
            humidity_relative=0.5,
            wind_speed_m_s=2.0,
            net_radiation_mj_m2_day=12.0,
            crop_height_m=0.30,
            elevation_m=100.0,
        )
        et_low_resistance = compute_et_penman_monteith_physical(
            stomatal_resistance_s_m=70.0, **common,
        )
        et_medium_resistance = compute_et_penman_monteith_physical(
            stomatal_resistance_s_m=200.0, **common,
        )
        et_high_resistance = compute_et_penman_monteith_physical(
            stomatal_resistance_s_m=500.0, **common,
        )
        self.assertGreater(et_low_resistance, et_medium_resistance)
        self.assertGreater(et_medium_resistance, et_high_resistance)

    def test_zero_or_negative_stomatal_resistance_raises(self):
        # Resistenza stomatica deve essere positiva.
        common = dict(
            temperature_c=20.0, humidity_relative=0.5,
            wind_speed_m_s=2.0, net_radiation_mj_m2_day=10.0,
            crop_height_m=0.30,
        )
        for invalid_rs in [0.0, -50.0]:
            with self.assertRaises(ValueError):
                compute_et_penman_monteith_physical(
                    stomatal_resistance_s_m=invalid_rs, **common,
                )

    def test_zero_or_negative_crop_height_raises(self):
        # L'altezza colturale deve essere positiva (entra nel calcolo
        # della resistenza aerodinamica).
        common = dict(
            temperature_c=20.0, humidity_relative=0.5,
            wind_speed_m_s=2.0, net_radiation_mj_m2_day=10.0,
            stomatal_resistance_s_m=100.0,
        )
        for invalid_h in [0.0, -0.1]:
            with self.assertRaises(ValueError):
                compute_et_penman_monteith_physical(
                    crop_height_m=invalid_h, **common,
                )


# =====================================================================
#  Test della dataclass EtResult e dell'enum EtMethod.
#
#  Strutture di dato pure introdotte dalla sotto-tappa B come valore
#  di ritorno del selettore. I test verificano le proprietà strutturali
#  (frozen, accesso ai campi, valori dell'enum) senza ancora coinvolgere
#  la logica di selezione.
# =====================================================================


class TestEtMethodAndResult(unittest.TestCase):

    def test_enum_has_three_methods(self):
        # L'enum deve esporre esattamente i tre membri previsti dal
        # design della sotto-tappa B. Questo test fallirebbe se in
        # futuro qualcuno aggiungesse un quarto membro senza aggiornare
        # la documentazione e i chiamanti.
        self.assertEqual(
            {m.name for m in EtMethod},
            {
                "PENMAN_MONTEITH_PHYSICAL",
                "PENMAN_MONTEITH_STANDARD",
                "HARGREAVES_SAMANI",
            },
        )

    def test_result_holds_value_and_method(self):
        # Verifica della struttura base: i due campi sono accessibili
        # e contengono i valori passati al costruttore.
        result = EtResult(value_mm=5.5, method=EtMethod.PENMAN_MONTEITH_PHYSICAL)
        self.assertEqual(result.value_mm, 5.5)
        self.assertEqual(result.method, EtMethod.PENMAN_MONTEITH_PHYSICAL)

    def test_result_is_frozen(self):
        # La dataclass è frozen: assegnare un nuovo valore a un campo
        # deve sollevare FrozenInstanceError. Questo è importante perché
        # un risultato di calcolo non deve essere modificabile dopo la
        # produzione (richiederebbe di rifare il calcolo, e questo è
        # responsabilità del chiamante).
        from dataclasses import FrozenInstanceError
        result = EtResult(value_mm=5.0, method=EtMethod.HARGREAVES_SAMANI)
        with self.assertRaises(FrozenInstanceError):
            result.value_mm = 6.0


# =====================================================================
#  Test del selettore compute_et.
#
#  Verifichiamo tre famiglie di proprietà:
#    1. Logica di selezione corretta in base ai parametri forniti.
#    2. Non-regressione: il valore prodotto coincide con quello della
#       formula sottostante chiamata direttamente.
#    3. Gestione degli errori per i parametri obbligatori mancanti.
# =====================================================================


class TestComputeEtSelector(unittest.TestCase):

    def setUp(self):
        # Scenario meteo condiviso: balcone milanese in luglio.
        # Calcolato una volta sola in setUp per non ripeterlo in ogni
        # test e per assicurare che tutti i test usino esattamente lo
        # stesso scenario (variazioni accidentali nascondono bug).
        self.common = dict(
            t_min=20.0, t_max=32.0,
            latitude_deg=45.47, j=200,
            elevation_m=150.0,
        )
        # Calcoliamo Rn per i casi che hanno bisogno di tutti i dati
        # meteo aggiuntivi. Questo richiede importare le funzioni del
        # modulo radiation, che fanno parte del layer scientifico già
        # testato dalla sotto-tappa A.
        from fitosim.science.radiation import (
            extraterrestrial_radiation, net_radiation,
        )
        ra = extraterrestrial_radiation(45.47, 200)
        ea = actual_vapor_pressure(26.0, 0.60)
        self.rn = net_radiation(
            solar_radiation_mj=24.0,
            extraterrestrial_radiation_mj=ra,
            t_max_c=32.0, t_min_c=20.0,
            actual_vapor_pressure_kpa=ea,
            elevation_m=150.0,
        )

    # ---- Famiglia 1: logica di selezione ----

    def test_full_data_selects_physical(self):
        # Tutti i dati meteo + parametri specie disponibili: deve usare
        # Penman-Monteith fisico. È il caso "best" del best-available.
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            stomatal_resistance_s_m=100.0, crop_height_m=0.30,
            **self.common,
        )
        self.assertEqual(result.method, EtMethod.PENMAN_MONTEITH_PHYSICAL)

    def test_weather_only_selects_standard(self):
        # Dati meteo completi ma parametri specie assenti: deve usare
        # Penman-Monteith standard FAO-56 (con parametri della coltura
        # di riferimento).
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            **self.common,
        )
        self.assertEqual(result.method, EtMethod.PENMAN_MONTEITH_STANDARD)

    def test_minimal_data_selects_hargreaves(self):
        # Solo le temperature minime obbligatorie: deve ricadere su
        # Hargreaves come fallback finale.
        result = compute_et(**self.common)
        self.assertEqual(result.method, EtMethod.HARGREAVES_SAMANI)

    def test_partial_weather_falls_back_to_hargreaves(self):
        # Quando manca anche solo uno dei tre dati meteo aggiuntivi
        # (qui manca la radiazione netta), la logica "tutto o niente"
        # ricade su Hargreaves. Questo è un test importante perché
        # Penman-Monteith con dati parziali produrrebbe risultati di
        # qualità imprevedibile, e preferiamo il fallback robusto.
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            # net_radiation_mj_m2_day mancante intenzionalmente
            **self.common,
        )
        self.assertEqual(result.method, EtMethod.HARGREAVES_SAMANI)

    def test_partial_species_params_falls_back_to_standard(self):
        # Quando manca anche solo uno dei due parametri della specie
        # (qui manca crop_height_m), la logica "tutto o niente" ricade
        # su Penman-Monteith standard invece di fisico. Stessa filosofia
        # del test precedente: meglio un calcolo robusto su parametri
        # standardizzati che un calcolo "fisico" con parametri inventati.
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            stomatal_resistance_s_m=100.0,
            # crop_height_m mancante intenzionalmente
            **self.common,
        )
        self.assertEqual(result.method, EtMethod.PENMAN_MONTEITH_STANDARD)

    # ---- Famiglia 2: non-regressione contro le formule sottostanti ----

    def test_hargreaves_path_matches_direct_call(self):
        # Quando il selettore sceglie Hargreaves, il valore numerico
        # deve coincidere bit-per-bit con la chiamata diretta della
        # funzione sottostante. Questa proprietà verifica che il
        # selettore non aggiunga distorsioni al risultato.
        result = compute_et(**self.common)
        direct = et0_hargreaves_samani(
            t_min=20.0, t_max=32.0, latitude_deg=45.47, j=200,
        )
        self.assertEqual(result.value_mm, direct)

    def test_pm_standard_path_matches_direct_call(self):
        # Stessa verifica per Penman-Monteith standard.
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            **self.common,
        )
        direct = compute_et0_penman_monteith(
            temperature_c=26.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            elevation_m=150.0,
        )
        self.assertEqual(result.value_mm, direct)

    def test_pm_physical_path_matches_direct_call(self):
        # Stessa verifica per Penman-Monteith fisico.
        result = compute_et(
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            stomatal_resistance_s_m=100.0, crop_height_m=0.30,
            **self.common,
        )
        direct = compute_et_penman_monteith_physical(
            temperature_c=26.0,
            humidity_relative=0.60, wind_speed_m_s=1.5,
            net_radiation_mj_m2_day=self.rn,
            stomatal_resistance_s_m=100.0, crop_height_m=0.30,
            elevation_m=150.0,
        )
        self.assertEqual(result.value_mm, direct)

    # ---- Famiglia 3: gestione degli errori ----

    def test_missing_t_min_raises_with_explicit_message(self):
        # Manca t_min: il messaggio dell'eccezione deve identificare
        # esplicitamente il parametro mancante per facilitare il debug
        # del codice chiamante.
        with self.assertRaises(ValueError) as ctx:
            compute_et(
                t_min=None, t_max=32.0,
                latitude_deg=45.47, j=200,
            )
        self.assertIn("t_min", str(ctx.exception))

    def test_missing_t_max_raises_with_explicit_message(self):
        # Stesso pattern per t_max.
        with self.assertRaises(ValueError) as ctx:
            compute_et(
                t_min=20.0, t_max=None,
                latitude_deg=45.47, j=200,
            )
        self.assertIn("t_max", str(ctx.exception))

    def test_missing_latitude_raises_with_explicit_message(self):
        # Stesso pattern per la latitudine.
        with self.assertRaises(ValueError) as ctx:
            compute_et(
                t_min=20.0, t_max=32.0,
                latitude_deg=None, j=200,
            )
        self.assertIn("latitude_deg", str(ctx.exception))

    def test_missing_j_raises_with_explicit_message(self):
        # Stesso pattern per il giorno dell'anno.
        with self.assertRaises(ValueError) as ctx:
            compute_et(
                t_min=20.0, t_max=32.0,
                latitude_deg=45.47, j=None,
            )
        self.assertIn("j", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
