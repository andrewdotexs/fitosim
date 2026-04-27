"""
Test per fitosim.science.pot_physics.

Cinque famiglie:
  1. Validazione delle tabelle per ciascun enum.
  2. Funzioni di lookup individuali.
  3. Composizione del pot_correction_factor (associatività e commutatività).
  4. Range plausibili: nessun fattore esce da limiti fisicamente sensati.
  5. Casi estremi: vaso peggiore (terracotta nera al sole) e migliore
     (plastica chiara all'ombra) producono valori coerenti col significato.
"""

import unittest

from fitosim.science.pot_physics import (
    NEUTRAL_POT_CORRECTION,
    PotColor,
    PotMaterial,
    SunExposure,
    color_correction_factor,
    exposure_correction_factor,
    material_correction_factor,
    pot_correction_factor,
)


# =======================================================================
#  1. Validazione delle tabelle
# =======================================================================

class TestMaterialFactorTable(unittest.TestCase):
    """
    Le tabelle interne devono coprire ogni valore dell'enum. Un nuovo
    membro dell'enum aggiunto senza aggiornare la tabella produrrebbe
    un KeyError in produzione: vogliamo accorgerci subito.
    """

    def test_all_materials_have_a_factor(self):
        for mat in PotMaterial:
            with self.subTest(material=mat):
                # Non deve sollevare KeyError per nessun valore.
                value = material_correction_factor(mat)
                self.assertIsInstance(value, float)

    def test_plastic_is_the_neutral_reference(self):
        # La plastica è il riferimento neutro per il materiale: 1.00.
        # Se questo valore cambia, vuol dire che è cambiata la convenzione
        # di base e bisogna ri-tarare anche tutti i test integrati.
        self.assertEqual(material_correction_factor(PotMaterial.PLASTIC), 1.00)

    def test_terracotta_loses_more_water_than_plastic(self):
        # Il fenomeno fisico chiave: terracotta porosa = +25-40% di
        # evaporazione. Questo test cattura la *direzione* della
        # correzione, non un valore esatto, perché 1.30 è una
        # stima ragionevole non un numero misurato.
        self.assertGreater(
            material_correction_factor(PotMaterial.TERRACOTTA),
            material_correction_factor(PotMaterial.PLASTIC),
        )

    def test_glazed_ceramic_close_to_plastic(self):
        # Ceramica smaltata e plastica sono entrambe sostanzialmente
        # impermeabili: i due fattori devono essere molto vicini.
        plastic = material_correction_factor(PotMaterial.PLASTIC)
        glazed = material_correction_factor(PotMaterial.GLAZED_CERAMIC)
        self.assertLess(abs(plastic - glazed), 0.10)


class TestColorFactorTable(unittest.TestCase):
    def test_all_colors_have_a_factor(self):
        for col in PotColor:
            with self.subTest(color=col):
                value = color_correction_factor(col)
                self.assertIsInstance(value, float)

    def test_medium_is_the_neutral_reference(self):
        # Il colore medio è il riferimento neutro: 1.00.
        self.assertEqual(color_correction_factor(PotColor.MEDIUM), 1.00)

    def test_dark_absorbs_more_than_light(self):
        # Effetto fisico atteso: il colore scuro assorbe più radiazione
        # solare e quindi aumenta la domanda evapotraspirativa.
        self.assertGreater(
            color_correction_factor(PotColor.DARK),
            color_correction_factor(PotColor.LIGHT),
        )

    def test_color_effect_is_modest(self):
        # L'effetto del colore è atteso del 5-15%, non drammatico.
        # Verifico che dark e light non si discostino di oltre il 30%
        # dal riferimento medium, altrimenti sarebbe un valore
        # implausibile da rivedere.
        for col in (PotColor.DARK, PotColor.LIGHT):
            with self.subTest(color=col):
                factor = color_correction_factor(col)
                self.assertGreater(factor, 0.7)
                self.assertLess(factor, 1.3)


class TestExposureFactorTable(unittest.TestCase):
    def test_all_exposures_have_a_factor(self):
        for exp in SunExposure:
            with self.subTest(exposure=exp):
                value = exposure_correction_factor(exp)
                self.assertIsInstance(value, float)

    def test_full_sun_is_the_reference(self):
        # Pieno sole = riferimento (1.00). Le altre esposizioni
        # riducono ET_c rispetto a questo riferimento, perché
        # arriva meno radiazione effettiva sul vaso.
        self.assertEqual(exposure_correction_factor(SunExposure.FULL_SUN), 1.00)

    def test_shade_lower_than_partial_lower_than_full_sun(self):
        # Ordinamento monotono atteso: full > partial > shade.
        # Questo è l'invariante fisico più forte di tutto il modulo.
        full = exposure_correction_factor(SunExposure.FULL_SUN)
        partial = exposure_correction_factor(SunExposure.PARTIAL_SHADE)
        shade = exposure_correction_factor(SunExposure.SHADE)
        self.assertGreater(full, partial)
        self.assertGreater(partial, shade)

    def test_exposure_is_the_strongest_effect(self):
        # L'esposizione è documentata come l'effetto fisico più
        # importante dei tre. Verifico che il range dei suoi fattori
        # sia più ampio di quello degli altri due.
        exp_range = (exposure_correction_factor(SunExposure.FULL_SUN)
                     - exposure_correction_factor(SunExposure.SHADE))
        col_range = (color_correction_factor(PotColor.DARK)
                     - color_correction_factor(PotColor.LIGHT))
        self.assertGreater(exp_range, col_range)


# =======================================================================
#  2. Test della composizione
# =======================================================================

class TestPotCorrectionFactor(unittest.TestCase):
    """
    pot_correction_factor combina i tre sotto-fattori. Voglio verificare
    le proprietà matematiche basilari: è effettivamente il prodotto
    delle tre, e i casi neutri producono il neutro globale.
    """

    def test_neutral_pot_yields_unity(self):
        # Il vaso "neutro" (plastica, colore medio, pieno sole) è il
        # riferimento del modello FAO-56 base. Kp deve essere 1.00.
        kp = pot_correction_factor(
            material=PotMaterial.PLASTIC,
            color=PotColor.MEDIUM,
            exposure=SunExposure.FULL_SUN,
        )
        self.assertEqual(kp, 1.00)
        self.assertEqual(kp, NEUTRAL_POT_CORRECTION)

    def test_factorization_property(self):
        # Kp = f_material × f_color × f_exposure. Verifica esplicita
        # della proprietà di prodotto: prendo i tre singoli e li
        # moltiplico, deve coincidere con la chiamata alla composita.
        for mat in PotMaterial:
            for col in PotColor:
                for exp in SunExposure:
                    with self.subTest(material=mat, color=col, exposure=exp):
                        composed = pot_correction_factor(mat, col, exp)
                        manual = (
                            material_correction_factor(mat)
                            * color_correction_factor(col)
                            * exposure_correction_factor(exp)
                        )
                        self.assertAlmostEqual(composed, manual, places=10)

    def test_worst_case_is_terracotta_dark_full_sun(self):
        # Caso più assetato attesto: terracotta nera al sole. Tutti e
        # tre i fattori >= 1, quindi il prodotto >= 1. Inoltre deve
        # essere il valore massimo tra tutte le combinazioni possibili.
        worst = pot_correction_factor(
            material=PotMaterial.TERRACOTTA,
            color=PotColor.DARK,
            exposure=SunExposure.FULL_SUN,
        )
        self.assertGreater(worst, 1.0)
        # Cerco esplicitamente il massimo nel dominio.
        all_kps = [
            pot_correction_factor(m, c, e)
            for m in PotMaterial for c in PotColor for e in SunExposure
        ]
        self.assertEqual(worst, max(all_kps))

    def test_best_case_is_glazed_light_shade(self):
        # Caso meno assetato: ceramica smaltata (o simile, < 1) chiara
        # all'ombra. Il prodotto deve essere il minimo tra le combinazioni.
        best = pot_correction_factor(
            material=PotMaterial.GLAZED_CERAMIC,
            color=PotColor.LIGHT,
            exposure=SunExposure.SHADE,
        )
        self.assertLess(best, 1.0)
        all_kps = [
            pot_correction_factor(m, c, e)
            for m in PotMaterial for c in PotColor for e in SunExposure
        ]
        self.assertEqual(best, min(all_kps))


# =======================================================================
#  3. Range fisicamente sensato
# =======================================================================

class TestRanges(unittest.TestCase):
    """
    Test difensivi: nessuna combinazione di parametri produce valori
    di Kp fuori dal range fisicamente plausibile. Un Kp di 5.0 o di
    0.01 sarebbe un bug di tabella.
    """

    def test_all_combinations_within_plausible_range(self):
        # Range plausibile per Kp di un vaso domestico: [0.3, 2.0].
        # Più stretto di così sarebbe arbitrario; più largo
        # accetterebbe configurazioni implausibili.
        for mat in PotMaterial:
            for col in PotColor:
                for exp in SunExposure:
                    with self.subTest(material=mat, color=col, exposure=exp):
                        kp = pot_correction_factor(mat, col, exp)
                        self.assertGreaterEqual(kp, 0.3)
                        self.assertLessEqual(kp, 2.0)

    def test_individual_factors_strictly_positive(self):
        # Nessun singolo fattore deve essere zero o negativo.
        for mat in PotMaterial:
            self.assertGreater(material_correction_factor(mat), 0.0)
        for col in PotColor:
            self.assertGreater(color_correction_factor(col), 0.0)
        for exp in SunExposure:
            self.assertGreater(exposure_correction_factor(exp), 0.0)


# =======================================================================
#  4. Casi d'uso reali (sanity check)
# =======================================================================

class TestRealisticScenarios(unittest.TestCase):
    """
    Scenari realistici descritti a parole, che traducono in numeri il
    "buon senso del giardiniere" e verificano che il modello concordi.
    """

    def test_basilico_terracotta_vs_plastica(self):
        # Caso classico: lo stesso basilico in terracotta richiede
        # irrigazioni più frequenti che in plastica. Tutti gli altri
        # parametri uguali, terracotta deve avere Kp maggiore.
        kp_terra = pot_correction_factor(
            PotMaterial.TERRACOTTA, PotColor.MEDIUM, SunExposure.FULL_SUN,
        )
        kp_plastica = pot_correction_factor(
            PotMaterial.PLASTIC, PotColor.MEDIUM, SunExposure.FULL_SUN,
        )
        self.assertGreater(kp_terra, kp_plastica)

    def test_cortile_ombroso_dimezza_consumo(self):
        # Una pianta in cortile ombroso (esposizione SHADE) consuma
        # circa la metà di una in pieno sole, a parità di vaso. Il
        # rapporto deve essere intorno a 0.5 (con tolleranza).
        kp_sole = pot_correction_factor(
            PotMaterial.PLASTIC, PotColor.MEDIUM, SunExposure.FULL_SUN,
        )
        kp_ombra = pot_correction_factor(
            PotMaterial.PLASTIC, PotColor.MEDIUM, SunExposure.SHADE,
        )
        ratio = kp_ombra / kp_sole
        self.assertGreater(ratio, 0.30)
        self.assertLess(ratio, 0.65)

    def test_balcone_milanese_estivo_tipico(self):
        # Configurazione tipica di un balcone a Milano al sud:
        # vaso di terracotta scura (le terracotte stagionate prendono
        # un colore scuro), pieno sole estivo. Kp deve essere
        # nettamente sopra 1, perché tutti gli effetti si sommano.
        kp = pot_correction_factor(
            PotMaterial.TERRACOTTA, PotColor.DARK, SunExposure.FULL_SUN,
        )
        # Almeno +30% rispetto al riferimento neutro.
        self.assertGreater(kp, 1.30)


if __name__ == "__main__":
    unittest.main()
