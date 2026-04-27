"""
Test per fitosim.science.substrate.

Copertura in tre famiglie di test:
  1. Validazione della dataclass Substrate e dei suoi vincoli fisici.
  2. Correttezza delle funzioni di calcolo TAW, RAW, volumi.
  3. Sanity check sul catalogo: tutti i substrati pre-definiti devono
     essere fisicamente consistenti e ordinati in modo ragionevole.
"""

import math
import unittest

from fitosim.science.substrate import (
    ALL_SUBSTRATES,
    CACTUS_MIX,
    COCO_COIR,
    DEFAULT_DEPLETION_FRACTION,
    PEAT_BASED,
    PERLITE_RICH,
    Substrate,
    UNIVERSAL_POTTING_SOIL,
    circular_pot_surface_area_m2,
    mm_to_theta,
    pot_substrate_depth_mm,
    readily_available_water,
    theta_to_mm,
    total_available_water,
    water_volume_at_field_capacity,
    water_volume_available,
    water_volume_readily_available,
)


class TestSubstrateDataclass(unittest.TestCase):
    """Verifica creazione e validazione della dataclass."""

    def test_valid_creation(self):
        # Un substrato ben formato deve potersi creare senza errori.
        s = Substrate(name="test", theta_fc=0.4, theta_pwp=0.15)
        self.assertEqual(s.name, "test")
        self.assertEqual(s.theta_fc, 0.4)
        self.assertEqual(s.theta_pwp, 0.15)

    def test_pwp_equal_to_fc_is_rejected(self):
        # Un substrato con θ_PWP = θ_FC non avrebbe acqua disponibile:
        # è fisicamente degenerato e va rifiutato a monte.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.3, theta_pwp=0.3)

    def test_pwp_greater_than_fc_is_rejected(self):
        # Impossibile fisicamente: il punto di appassimento non può
        # superare la capacità di campo.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.2, theta_pwp=0.3)

    def test_negative_values_are_rejected(self):
        # Contenuti idrici volumetrici negativi sono senza senso fisico.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=0.4, theta_pwp=-0.1)

    def test_values_above_one_are_rejected(self):
        # Frazione volumetrica > 1 significherebbe "più acqua del volume
        # totale del substrato", che è impossibile.
        with self.assertRaises(ValueError):
            Substrate(name="bad", theta_fc=1.2, theta_pwp=0.5)

    def test_immutability(self):
        # frozen=True: modificare un attributo deve sollevare eccezione.
        s = Substrate(name="test", theta_fc=0.4, theta_pwp=0.15)
        with self.assertRaises(Exception):
            s.theta_fc = 0.5  # type: ignore[misc]


class TestWaterComputations(unittest.TestCase):
    """Verifica delle funzioni di calcolo idrico."""

    def test_taw_is_difference(self):
        # TAW = θ_FC − θ_PWP è la definizione fondamentale.
        s = Substrate(name="test", theta_fc=0.40, theta_pwp=0.15)
        self.assertAlmostEqual(total_available_water(s), 0.25, places=6)

    def test_raw_default_is_half_taw(self):
        # Con la frazione di deplezione di default (0.5), RAW è
        # esattamente metà TAW.
        s = UNIVERSAL_POTTING_SOIL
        taw = total_available_water(s)
        raw = readily_available_water(s)
        self.assertAlmostEqual(raw, taw * DEFAULT_DEPLETION_FRACTION, places=6)
        self.assertAlmostEqual(raw, taw / 2.0, places=6)

    def test_raw_with_custom_depletion(self):
        # Con p custom, RAW deve scalare linearmente.
        s = UNIVERSAL_POTTING_SOIL
        raw_p3 = readily_available_water(s, depletion_fraction=0.3)
        raw_p7 = readily_available_water(s, depletion_fraction=0.7)
        # RAW a p=0.7 deve essere esattamente 7/3 di RAW a p=0.3.
        self.assertAlmostEqual(raw_p7 / raw_p3, 7.0 / 3.0, places=6)

    def test_raw_at_p_zero_is_zero(self):
        # p=0 significa "nessuna deplezione tollerata" — RAW=0.
        raw = readily_available_water(UNIVERSAL_POTTING_SOIL, 0.0)
        self.assertEqual(raw, 0.0)

    def test_raw_at_p_one_equals_taw(self):
        # p=1 significa "tollera deplezione fino al PWP" — RAW=TAW.
        s = UNIVERSAL_POTTING_SOIL
        raw_full = readily_available_water(s, depletion_fraction=1.0)
        self.assertAlmostEqual(raw_full, total_available_water(s), places=6)

    def test_raw_invalid_depletion_raises(self):
        # Frazione fuori da [0, 1] deve essere rifiutata.
        with self.assertRaises(ValueError):
            readily_available_water(UNIVERSAL_POTTING_SOIL, -0.1)
        with self.assertRaises(ValueError):
            readily_available_water(UNIVERSAL_POTTING_SOIL, 1.5)

    def test_volume_at_field_capacity_scales_linearly(self):
        # Il volume a FC deve scalare linearmente con il volume del vaso.
        s = UNIVERSAL_POTTING_SOIL  # θ_FC = 0.40
        # Vaso 5 L → 2 L a FC; vaso 10 L → 4 L a FC.
        self.assertAlmostEqual(
            water_volume_at_field_capacity(s, 5.0), 2.0, places=6
        )
        self.assertAlmostEqual(
            water_volume_at_field_capacity(s, 10.0), 4.0, places=6
        )

    def test_volume_available_universal_5L(self):
        # Caso concreto calcolabile a mano: terriccio universale
        # (TAW=0.25) in un vaso da 5 L dà 1.25 L disponibili.
        vol = water_volume_available(UNIVERSAL_POTTING_SOIL, 5.0)
        self.assertAlmostEqual(vol, 1.25, places=6)

    def test_volume_readily_available_universal_5L(self):
        # Stesso vaso: RAW = 0.5 × 1.25 L = 0.625 L.
        vol = water_volume_readily_available(UNIVERSAL_POTTING_SOIL, 5.0)
        self.assertAlmostEqual(vol, 0.625, places=6)

    def test_negative_pot_volume_raises(self):
        # Nessuna delle funzioni volumetriche deve accettare un volume
        # di vaso negativo.
        with self.assertRaises(ValueError):
            water_volume_at_field_capacity(UNIVERSAL_POTTING_SOIL, -1.0)
        with self.assertRaises(ValueError):
            water_volume_available(UNIVERSAL_POTTING_SOIL, -1.0)
        with self.assertRaises(ValueError):
            water_volume_readily_available(UNIVERSAL_POTTING_SOIL, -1.0)

    def test_zero_pot_volume_yields_zero(self):
        # Vaso da 0 L è accettato come caso limite (è consistente: nessun
        # substrato, nessuna acqua).
        self.assertEqual(
            water_volume_available(UNIVERSAL_POTTING_SOIL, 0.0), 0.0
        )


class TestCatalogIntegrity(unittest.TestCase):
    """Sanity check sul catalogo di substrati predefiniti."""

    def test_all_catalog_entries_are_valid(self):
        # Ogni substrato del catalogo deve rispettare i vincoli fisici.
        # Il fatto stesso che siano stati creati senza eccezione lo
        # garantisce, ma rifarlo qui funge da regression guard: se un
        # domani qualcuno modifica un valore in modo sbagliato, questo
        # test fallisce esplicitamente.
        for s in ALL_SUBSTRATES:
            with self.subTest(name=s.name):
                self.assertGreater(s.theta_fc, s.theta_pwp)
                self.assertGreaterEqual(s.theta_pwp, 0.0)
                self.assertLessEqual(s.theta_fc, 1.0)
                self.assertGreater(total_available_water(s), 0.0)

    def test_peat_has_highest_fc(self):
        # La torba di sfagno deve avere il θ_FC più alto del catalogo:
        # è una proprietà di letteratura che vogliamo mantenere.
        fcs = [(s.name, s.theta_fc) for s in ALL_SUBSTRATES]
        top_name, top_fc = max(fcs, key=lambda x: x[1])
        self.assertEqual(top_name, PEAT_BASED.name)

    def test_cactus_has_lowest_fc(self):
        # Il substrato per cactacee deve avere θ_FC più bassa: è drenante.
        fcs = [(s.name, s.theta_fc) for s in ALL_SUBSTRATES]
        bottom_name, bottom_fc = min(fcs, key=lambda x: x[1])
        self.assertEqual(bottom_name, CACTUS_MIX.name)

    def test_catalog_ordering_matches_retention(self):
        # La tupla ALL_SUBSTRATES è documentata come ordinata dal più
        # ritentivo al più drenante. Verifichiamo che θ_FC sia
        # monotonicamente decrescente seguendo quell'ordine.
        fcs = [s.theta_fc for s in ALL_SUBSTRATES]
        for i in range(len(fcs) - 1):
            with self.subTest(position=i):
                self.assertGreater(fcs[i], fcs[i + 1])


class TestGeometryAndConversion(unittest.TestCase):
    """Verifica delle utility geometriche e di conversione θ ↔ mm."""

    def test_circular_pot_area_standard_size(self):
        # Vaso con diametro 20 cm → raggio 0.1 m → area π × 0.01 ≈
        # 0.0314 m². È il caso di riferimento citato negli esempi.
        area = circular_pot_surface_area_m2(20.0)
        self.assertAlmostEqual(area, 0.0314, places=3)

    def test_circular_pot_area_scales_with_square_of_diameter(self):
        # Raddoppiando il diametro, l'area deve quadruplicare.
        area_small = circular_pot_surface_area_m2(10.0)
        area_large = circular_pot_surface_area_m2(20.0)
        self.assertAlmostEqual(area_large / area_small, 4.0, places=6)

    def test_circular_pot_area_rejects_nonpositive(self):
        with self.assertRaises(ValueError):
            circular_pot_surface_area_m2(0.0)
        with self.assertRaises(ValueError):
            circular_pot_surface_area_m2(-5.0)

    def test_pot_depth_reference_case(self):
        # 5 L in un vaso di area 0.0314 m² dà circa 159 mm di profondità.
        depth = pot_substrate_depth_mm(5.0, 0.0314)
        self.assertAlmostEqual(depth, 159.2, places=1)

    def test_pot_depth_identity_1L_1m2_equals_1mm(self):
        # L'identità mnemonica fondamentale: 1 L spalmato su 1 m² dà
        # esattamente 1 mm di colonna d'acqua equivalente.
        self.assertAlmostEqual(pot_substrate_depth_mm(1.0, 1.0), 1.0, places=6)

    def test_pot_depth_rejects_nonpositive_area(self):
        with self.assertRaises(ValueError):
            pot_substrate_depth_mm(5.0, 0.0)
        with self.assertRaises(ValueError):
            pot_substrate_depth_mm(5.0, -0.01)

    def test_theta_to_mm_basic(self):
        # θ=0.40 su profondità 150 mm → 60 mm di colonna.
        self.assertAlmostEqual(theta_to_mm(0.40, 150.0), 60.0, places=6)

    def test_mm_to_theta_basic(self):
        # 60 mm su profondità 150 mm → θ=0.40.
        self.assertAlmostEqual(mm_to_theta(60.0, 150.0), 0.40, places=6)

    def test_theta_mm_roundtrip_identity(self):
        # La doppia conversione θ → mm → θ deve restituire il valore
        # originale entro l'errore di arrotondamento in virgola mobile.
        for theta in [0.05, 0.15, 0.30, 0.40, 0.55, 0.85]:
            with self.subTest(theta=theta):
                back = mm_to_theta(theta_to_mm(theta, 200.0), 200.0)
                self.assertAlmostEqual(theta, back, places=10)

    def test_mm_to_theta_rejects_zero_depth(self):
        # Divisione per zero deve essere rifiutata esplicitamente.
        with self.assertRaises(ValueError):
            mm_to_theta(50.0, 0.0)


# =======================================================================
#  Forme geometriche aggiuntive: tronco-conico, rettangolare, ovale
# =======================================================================

class TestTruncatedConePotSurface(unittest.TestCase):
    """
    Il vaso tronco-conico è geometricamente un alias del cilindrico per
    quanto riguarda la superficie evaporante (la sommità è circolare).
    Testo esplicitamente questa equivalenza, e i casi limite.
    """

    def test_equivalent_to_circular(self):
        # truncated_cone(d) deve dare lo stesso risultato di circular(d).
        from fitosim.science.substrate import (
            circular_pot_surface_area_m2,
            truncated_cone_pot_surface_area_m2,
        )
        for d in [10.0, 14.0, 22.0, 30.0, 40.0]:
            with self.subTest(diameter_cm=d):
                circ = circular_pot_surface_area_m2(d)
                trunc = truncated_cone_pot_surface_area_m2(d)
                self.assertAlmostEqual(circ, trunc, places=10)

    def test_canonical_value(self):
        # Vaso tronco-conico con apertura 20 cm: area = π(0.10)² ≈ 0.0314 m².
        from fitosim.science.substrate import (
            truncated_cone_pot_surface_area_m2,
        )
        area = truncated_cone_pot_surface_area_m2(20.0)
        self.assertAlmostEqual(area, math.pi * 0.01, places=6)

    def test_rejects_non_positive_diameter(self):
        from fitosim.science.substrate import (
            truncated_cone_pot_surface_area_m2,
        )
        with self.assertRaises(ValueError):
            truncated_cone_pot_surface_area_m2(0.0)
        with self.assertRaises(ValueError):
            truncated_cone_pot_surface_area_m2(-5.0)


class TestRectangularPotSurface(unittest.TestCase):
    """
    Vaso rettangolare (cassetta da balcone, fioriera quadrata).
    """

    def test_canonical_square(self):
        # 20 × 20 cm = 400 cm² = 0.04 m².
        from fitosim.science.substrate import rectangular_pot_surface_area_m2
        self.assertAlmostEqual(
            rectangular_pot_surface_area_m2(20.0, 20.0), 0.04, places=6,
        )

    def test_canonical_rectangle(self):
        # 60 × 20 cm = 1200 cm² = 0.12 m² (cassetta tipica).
        from fitosim.science.substrate import rectangular_pot_surface_area_m2
        self.assertAlmostEqual(
            rectangular_pot_surface_area_m2(60.0, 20.0), 0.12, places=6,
        )

    def test_commutativity(self):
        # length × width = width × length: funzione simmetrica.
        from fitosim.science.substrate import rectangular_pot_surface_area_m2
        self.assertAlmostEqual(
            rectangular_pot_surface_area_m2(35.0, 17.0),
            rectangular_pot_surface_area_m2(17.0, 35.0),
            places=10,
        )

    def test_rejects_non_positive_dimensions(self):
        from fitosim.science.substrate import rectangular_pot_surface_area_m2
        with self.assertRaises(ValueError):
            rectangular_pot_surface_area_m2(0.0, 20.0)
        with self.assertRaises(ValueError):
            rectangular_pot_surface_area_m2(20.0, -5.0)


class TestOvalPotSurface(unittest.TestCase):
    """
    Vaso ovale modellato come ellisse: area = π·a·b dove a e b sono i
    semiassi.
    """

    def test_oval_with_equal_axes_equals_circle(self):
        # Ellisse a semiassi uguali = cerchio. oval(d, d) = circular(d).
        from fitosim.science.substrate import (
            circular_pot_surface_area_m2,
            oval_pot_surface_area_m2,
        )
        for d in [12.0, 18.0, 25.0, 35.0]:
            with self.subTest(diameter_cm=d):
                self.assertAlmostEqual(
                    oval_pot_surface_area_m2(d, d),
                    circular_pot_surface_area_m2(d),
                    places=10,
                )

    def test_canonical_oval(self):
        # 30 × 20 cm: area = π·(0.15)·(0.10) = 0.04712... m².
        from fitosim.science.substrate import oval_pot_surface_area_m2
        area = oval_pot_surface_area_m2(30.0, 20.0)
        self.assertAlmostEqual(area, math.pi * 0.15 * 0.10, places=6)

    def test_oval_smaller_than_bounding_rectangle(self):
        # L'ellisse inscritta in un rettangolo di lati a, b ha area
        # π·(a/2)·(b/2) = (π/4)·a·b ≈ 0.785·a·b. Quindi sempre minore
        # del rettangolo che la contiene.
        from fitosim.science.substrate import (
            oval_pot_surface_area_m2,
            rectangular_pot_surface_area_m2,
        )
        rect = rectangular_pot_surface_area_m2(30.0, 20.0)
        oval = oval_pot_surface_area_m2(30.0, 20.0)
        self.assertLess(oval, rect)
        # Più precisamente: rapporto = π/4 ≈ 0.7854.
        self.assertAlmostEqual(oval / rect, math.pi / 4, places=6)

    def test_commutativity(self):
        from fitosim.science.substrate import oval_pot_surface_area_m2
        self.assertAlmostEqual(
            oval_pot_surface_area_m2(40.0, 25.0),
            oval_pot_surface_area_m2(25.0, 40.0),
            places=10,
        )

    def test_rejects_non_positive_axes(self):
        from fitosim.science.substrate import oval_pot_surface_area_m2
        with self.assertRaises(ValueError):
            oval_pot_surface_area_m2(0.0, 20.0)
        with self.assertRaises(ValueError):
            oval_pot_surface_area_m2(30.0, -10.0)


# =======================================================================
#  Fabbrica di substrati: composizione di materiali base
# =======================================================================
#
# Quattro famiglie di test che coprono il nuovo sistema di composizione
# di mix personalizzati a partire da materiali base:
#
#   1. Validazione dei BaseMaterial (vincoli fisici sui parametri).
#   2. Validazione dei MixComponent (frazione nel range corretto).
#   3. Calcolo del compose_substrate su mix noti, con verifica dei
#      valori prodotti contro la formula della media pesata.
#   4. Catalogo degli 8 materiali base: integrità, ordinamento,
#      copertura dei casi d'uso domestici e bonsaistici.

class TestBaseMaterialValidation(unittest.TestCase):
    """
    Vincoli fisici sui parametri di un BaseMaterial. Sono gli stessi
    vincoli che valgono per Substrate (θ_PWP < θ_FC, entrambi in [0,1]),
    ma li replichiamo qui perché BaseMaterial è un tipo distinto.
    """

    def test_valid_material_constructs_correctly(self):
        # Caso normale: parametri ben formati, non solleva eccezioni.
        from fitosim.science.substrate import BaseMaterial
        mat = BaseMaterial(
            name="test",
            theta_fc=0.40,
            theta_pwp=0.10,
        )
        self.assertEqual(mat.name, "test")
        self.assertEqual(mat.theta_fc, 0.40)
        self.assertEqual(mat.theta_pwp, 0.10)

    def test_pwp_must_be_less_than_fc(self):
        # Vincolo fisico fondamentale: il punto di appassimento deve
        # essere sotto la capacità di campo. Configurazioni invertite
        # non hanno senso fisico.
        from fitosim.science.substrate import BaseMaterial
        with self.assertRaises(ValueError):
            BaseMaterial(name="invertito",
                         theta_fc=0.10, theta_pwp=0.40)

    def test_pwp_equal_to_fc_rejected(self):
        # Anche l'uguaglianza è rifiutata: significherebbe un materiale
        # senza acqua disponibile per la pianta (TAW = 0).
        from fitosim.science.substrate import BaseMaterial
        with self.assertRaises(ValueError):
            BaseMaterial(name="degenere",
                         theta_fc=0.30, theta_pwp=0.30)

    def test_fc_above_one_rejected(self):
        from fitosim.science.substrate import BaseMaterial
        with self.assertRaises(ValueError):
            BaseMaterial(name="sovrasaturo",
                         theta_fc=1.10, theta_pwp=0.10)

    def test_pwp_below_zero_rejected(self):
        from fitosim.science.substrate import BaseMaterial
        with self.assertRaises(ValueError):
            BaseMaterial(name="impossibile",
                         theta_fc=0.30, theta_pwp=-0.05)


class TestMixComponentValidation(unittest.TestCase):
    """Vincoli sulla frazione di un componente di mix."""

    def test_valid_fraction(self):
        from fitosim.science.substrate import MixComponent, BIONDA_PEAT
        comp = MixComponent(material=BIONDA_PEAT, fraction=0.5)
        self.assertEqual(comp.fraction, 0.5)

    def test_fraction_zero_accepted(self):
        # 0.0 è accettato (componente "presente in ricetta ma con peso
        # zero"): il caso d'uso è di chi vuole tenere uno scaffolding
        # con tutti i materiali e poi attivarne solo alcuni.
        from fitosim.science.substrate import MixComponent, PERLITE
        comp = MixComponent(material=PERLITE, fraction=0.0)
        self.assertEqual(comp.fraction, 0.0)

    def test_fraction_one_accepted(self):
        # 1.0 è accettato: significa "100% di questo materiale". È un
        # mix degenere ma sintatticamente legittimo.
        from fitosim.science.substrate import MixComponent, BIONDA_PEAT
        comp = MixComponent(material=BIONDA_PEAT, fraction=1.0)
        self.assertEqual(comp.fraction, 1.0)

    def test_negative_fraction_rejected(self):
        from fitosim.science.substrate import MixComponent, BIONDA_PEAT
        with self.assertRaises(ValueError):
            MixComponent(material=BIONDA_PEAT, fraction=-0.1)

    def test_fraction_above_one_rejected(self):
        from fitosim.science.substrate import MixComponent, BIONDA_PEAT
        with self.assertRaises(ValueError):
            MixComponent(material=BIONDA_PEAT, fraction=1.5)


class TestComposeSubstrate(unittest.TestCase):
    """
    Calcolo della media pesata in compose_substrate. Test diretti su
    mix con valori facilmente verificabili a mano.
    """

    def test_pure_material_yields_same_parameters(self):
        # 100% di un singolo materiale: il substrato risultante deve
        # avere esattamente gli stessi θ del materiale.
        from fitosim.science.substrate import (
            BIONDA_PEAT, MixComponent, compose_substrate,
        )
        result = compose_substrate(
            components=[MixComponent(BIONDA_PEAT, 1.0)],
            name="solo torba bionda",
        )
        self.assertAlmostEqual(result.theta_fc, BIONDA_PEAT.theta_fc,
                               places=10)
        self.assertAlmostEqual(result.theta_pwp, BIONDA_PEAT.theta_pwp,
                               places=10)

    def test_50_50_mix_produces_arithmetic_mean(self):
        # 50% A + 50% B: media aritmetica esatta. Caso più semplice
        # per verificare la formula.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        result = compose_substrate(
            components=[
                MixComponent(BIONDA_PEAT, 0.5),
                MixComponent(PERLITE, 0.5),
            ],
            name="50/50",
        )
        expected_fc = (BIONDA_PEAT.theta_fc + PERLITE.theta_fc) / 2
        expected_pwp = (BIONDA_PEAT.theta_pwp + PERLITE.theta_pwp) / 2
        self.assertAlmostEqual(result.theta_fc, expected_fc, places=10)
        self.assertAlmostEqual(result.theta_pwp, expected_pwp, places=10)

    def test_70_30_mix_weighted_correctly(self):
        # 70% torba bionda + 30% perlite: media pesata.
        # θ_FC atteso: 0.70 × 0.58 + 0.30 × 0.08 = 0.406 + 0.024 = 0.430
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        result = compose_substrate(
            components=[
                MixComponent(BIONDA_PEAT, 0.70),
                MixComponent(PERLITE, 0.30),
            ],
            name="mix professionale",
        )
        expected_fc = 0.70 * BIONDA_PEAT.theta_fc + 0.30 * PERLITE.theta_fc
        self.assertAlmostEqual(result.theta_fc, expected_fc, places=10)

    def test_three_component_mix_works(self):
        # Mix bonsai italiano classico 40/30/30. Verifica che la media
        # pesata funzioni con più di due ingredienti.
        from fitosim.science.substrate import (
            AKADAMA, POMICE, LAPILLO, MixComponent, compose_substrate,
        )
        result = compose_substrate(
            components=[
                MixComponent(AKADAMA, 0.40),
                MixComponent(POMICE, 0.30),
                MixComponent(LAPILLO, 0.30),
            ],
            name="mix bonsai standard",
        )
        expected_fc = (
            0.40 * AKADAMA.theta_fc
            + 0.30 * POMICE.theta_fc
            + 0.30 * LAPILLO.theta_fc
        )
        expected_pwp = (
            0.40 * AKADAMA.theta_pwp
            + 0.30 * POMICE.theta_pwp
            + 0.30 * LAPILLO.theta_pwp
        )
        self.assertAlmostEqual(result.theta_fc, expected_fc, places=10)
        self.assertAlmostEqual(result.theta_pwp, expected_pwp, places=10)

    def test_returns_substrate_instance(self):
        # Il tipo restituito è proprio un Substrate utilizzabile dal
        # resto del sistema senza adattatori.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, Substrate, compose_substrate,
        )
        result = compose_substrate(
            components=[
                MixComponent(BIONDA_PEAT, 0.6),
                MixComponent(PERLITE, 0.4),
            ],
            name="test",
        )
        self.assertIsInstance(result, Substrate)
        self.assertEqual(result.name, "test")

    def test_default_name_when_omitted(self):
        # Il default "custom mix" è applicato quando il nome non
        # viene specificato.
        from fitosim.science.substrate import (
            BIONDA_PEAT, MixComponent, compose_substrate,
        )
        result = compose_substrate(
            components=[MixComponent(BIONDA_PEAT, 1.0)],
        )
        self.assertEqual(result.name, "custom mix")


class TestComposeSubstrateValidation(unittest.TestCase):
    """Validazione delle ricette di mix."""

    def test_empty_components_rejected(self):
        from fitosim.science.substrate import compose_substrate
        with self.assertRaises(ValueError):
            compose_substrate(components=[])

    def test_fractions_must_sum_to_one(self):
        # Somma 0.7 (mancano il 30%): rifiutata.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        with self.assertRaises(ValueError):
            compose_substrate(components=[
                MixComponent(BIONDA_PEAT, 0.4),
                MixComponent(PERLITE, 0.3),
            ])

    def test_fractions_summing_above_one_rejected(self):
        # Somma 1.2 (eccesso del 20%): rifiutata.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        with self.assertRaises(ValueError):
            compose_substrate(components=[
                MixComponent(BIONDA_PEAT, 0.7),
                MixComponent(PERLITE, 0.5),
            ])

    def test_small_rounding_errors_tolerated(self):
        # Somma 0.9995 (errore di arrotondamento microscopico, tipico
        # quando si scrivono percentuali con poche cifre decimali):
        # accettato entro la tolleranza di default 0.001.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        result = compose_substrate(components=[
            MixComponent(BIONDA_PEAT, 0.7000),
            MixComponent(PERLITE, 0.2995),  # somma 0.9995
        ])
        # Non solleva eccezioni: il risultato è prodotto.
        from fitosim.science.substrate import Substrate
        self.assertIsInstance(result, Substrate)

    def test_custom_tolerance_accepted(self):
        # Il chiamante può ammorbidire la tolleranza in casi specifici.
        from fitosim.science.substrate import (
            BIONDA_PEAT, PERLITE, MixComponent, compose_substrate,
        )
        # Somma 0.95: rifiutata con default, accettata con tolleranza 0.1.
        with self.assertRaises(ValueError):
            compose_substrate(components=[
                MixComponent(BIONDA_PEAT, 0.5),
                MixComponent(PERLITE, 0.45),
            ])
        # Stessa ricetta con tolleranza più larga: passa.
        result = compose_substrate(
            components=[
                MixComponent(BIONDA_PEAT, 0.5),
                MixComponent(PERLITE, 0.45),
            ],
            fraction_tolerance=0.1,
        )
        from fitosim.science.substrate import Substrate
        self.assertIsInstance(result, Substrate)


class TestBaseMaterialCatalog(unittest.TestCase):
    """Integrità del catalogo degli 8 materiali base."""

    def test_all_materials_in_catalog(self):
        # Verifica che ALL_BASE_MATERIALS contenga effettivamente
        # tutti gli 8 materiali esposti dal modulo.
        from fitosim.science.substrate import (
            ALL_BASE_MATERIALS,
            BIONDA_PEAT, BRUNA_PEAT, PERLITE, VERMICULITE,
            COCO_FIBER, POMICE, SAND, AKADAMA, LAPILLO,
        )
        expected = {
            BIONDA_PEAT, BRUNA_PEAT, PERLITE, VERMICULITE,
            COCO_FIBER, POMICE, SAND, AKADAMA, LAPILLO,
        }
        self.assertEqual(set(ALL_BASE_MATERIALS), expected)
        # Sono effettivamente nove (avevamo detto otto, ma includendo
        # entrambe le torbe sono nove).
        self.assertEqual(len(ALL_BASE_MATERIALS), 9)

    def test_all_materials_have_valid_parameters(self):
        # Tutti i materiali del catalogo hanno parametri fisici validi:
        # è la stessa garanzia che vale per il catalogo Substrate.
        from fitosim.science.substrate import ALL_BASE_MATERIALS
        for mat in ALL_BASE_MATERIALS:
            with self.subTest(material=mat.name):
                self.assertGreater(mat.theta_fc, mat.theta_pwp)
                self.assertGreaterEqual(mat.theta_pwp, 0.0)
                self.assertLessEqual(mat.theta_fc, 1.0)

    def test_drainage_materials_have_low_fc(self):
        # I materiali drenanti (perlite, pomice, sabbia, lapillo) devono
        # avere θ_FC bassa (<0.25). Questo è il loro ruolo.
        from fitosim.science.substrate import (
            PERLITE, POMICE, SAND, LAPILLO,
        )
        for mat in (PERLITE, POMICE, SAND, LAPILLO):
            with self.subTest(material=mat.name):
                self.assertLess(mat.theta_fc, 0.25)

    def test_water_retentive_materials_have_high_fc(self):
        # I materiali ritentivi (torba bionda, torba bruna, fibra di
        # cocco) devono avere θ_FC alta (>0.45).
        from fitosim.science.substrate import (
            BIONDA_PEAT, BRUNA_PEAT, COCO_FIBER,
        )
        for mat in (BIONDA_PEAT, BRUNA_PEAT, COCO_FIBER):
            with self.subTest(material=mat.name):
                self.assertGreater(mat.theta_fc, 0.45)

    def test_all_materials_have_descriptions(self):
        # La description è pensata per essere consultata; vogliamo
        # che ogni materiale ne abbia una, non quella vuota di default.
        from fitosim.science.substrate import ALL_BASE_MATERIALS
        for mat in ALL_BASE_MATERIALS:
            with self.subTest(material=mat.name):
                self.assertGreater(len(mat.description), 30)


if __name__ == "__main__":
    unittest.main()
