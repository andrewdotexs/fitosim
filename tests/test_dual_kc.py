"""
Test per fitosim.science.dual_kc.

Quattro famiglie di test:
  1. evaporation_reduction_coefficient: comportamento a due fasi.
  2. kcmax e soil_evaporation_coefficient: coefficiente di evap.
  3. update_de: dinamica giornaliera della cumulative depletion.
  4. Validazione degli input (rifiuto di valori non sensati).
  5. Composizione: scenari realistici di asciugamento e ribagnatura.
"""

import unittest

from fitosim.science.dual_kc import (
    DEFAULT_FEW,
    KCMAX_DEFAULT,
    KCMAX_FLOOR_MARGIN,
    evaporation_reduction_coefficient,
    kcmax,
    soil_evaporation_coefficient,
    update_de,
)


# =======================================================================
#  1. evaporation_reduction_coefficient
# =======================================================================

class TestEvaporationReductionCoefficient(unittest.TestCase):
    """Comportamento a due fasi del coefficiente Kr (FAO-56 eq. 74)."""

    def test_phase_1_yields_unity(self):
        # Fase 1 (energy-limited): finché De ≤ REW, Kr = 1.
        # Substrato appena bagnato.
        self.assertEqual(
            evaporation_reduction_coefficient(0.0, 9.0, 22.0), 1.0,
        )
        # Anche a metà fase 1.
        self.assertEqual(
            evaporation_reduction_coefficient(5.0, 9.0, 22.0), 1.0,
        )
        # Esattamente al confine REW (deve essere ancora fase 1).
        self.assertEqual(
            evaporation_reduction_coefficient(9.0, 9.0, 22.0), 1.0,
        )

    def test_phase_2_decreases_linearly(self):
        # Fase 2 (falling-rate): Kr = (TEW - De) / (TEW - REW).
        # Esattamente a metà tra REW e TEW: Kr deve essere 0.5.
        rew, tew = 9.0, 22.0
        de_mid = (rew + tew) / 2  # 15.5
        self.assertAlmostEqual(
            evaporation_reduction_coefficient(de_mid, rew, tew), 0.5,
            places=10,
        )

    def test_phase_3_yields_zero(self):
        # Substrato superficiale completamente asciutto: Kr = 0.
        # Esattamente a TEW.
        self.assertEqual(
            evaporation_reduction_coefficient(22.0, 9.0, 22.0), 0.0,
        )
        # Oltre TEW (caso che non dovrebbe mai capitare in pratica
        # perché update_de satura De a TEW, ma il modello deve essere
        # robusto).
        self.assertEqual(
            evaporation_reduction_coefficient(50.0, 9.0, 22.0), 0.0,
        )

    def test_kr_monotonic_decreasing(self):
        # Mentre De aumenta, Kr non deve mai aumentare.
        rew, tew = 9.0, 22.0
        de_values = [0.0, 3.0, 9.0, 12.0, 15.0, 18.0, 21.0, 22.0, 25.0]
        kr_values = [
            evaporation_reduction_coefficient(de, rew, tew)
            for de in de_values
        ]
        for i in range(len(kr_values) - 1):
            with self.subTest(de_from=de_values[i],
                              de_to=de_values[i + 1]):
                self.assertGreaterEqual(kr_values[i], kr_values[i + 1])

    def test_realistic_substrate_values(self):
        # Substrato torba domestica: REW ~9, TEW ~22.
        # Dopo 5 giorni di asciugamento (De=12 mm) Kr deve essere
        # nettamente ridotto rispetto al valore iniziale.
        kr_dry = evaporation_reduction_coefficient(12.0, 9.0, 22.0)
        self.assertLess(kr_dry, 1.0)
        self.assertGreater(kr_dry, 0.0)
        # Stima qualitativa: con De a 1/4 della distanza tra REW e
        # TEW, Kr dovrebbe essere intorno a 0.77.
        self.assertAlmostEqual(kr_dry, (22 - 12) / (22 - 9), places=10)


# =======================================================================
#  2. kcmax e soil_evaporation_coefficient
# =======================================================================

class TestKcmax(unittest.TestCase):
    """Test della funzione kcmax."""

    def test_climate_baseline_dominates_for_low_kcb(self):
        # Per Kcb basso (tipico di colture in stadio iniziale), il
        # baseline climatico domina: Kcmax = max(1.20, 0.05+margin) = 1.20.
        self.assertAlmostEqual(kcmax(0.35), KCMAX_DEFAULT, places=10)
        self.assertAlmostEqual(kcmax(1.0), KCMAX_DEFAULT, places=10)

    def test_floor_dominates_for_high_kcb(self):
        # Per Kcb alto (colture di pieno sviluppo), il pavimento
        # Kcb + floor_margin diventa il termine attivo. Per Kcb=1.30,
        # max(1.20, 1.35) = 1.35.
        self.assertAlmostEqual(
            kcmax(1.30), 1.30 + KCMAX_FLOOR_MARGIN, places=10,
        )

    def test_custom_climate_baseline(self):
        # Per condizioni più aride (vento forte, umidità bassa) il
        # caller può alzare il baseline a 1.30.
        self.assertAlmostEqual(
            kcmax(0.5, climate_baseline=1.30), 1.30, places=10,
        )

    def test_custom_floor_margin(self):
        # Il pavimento può essere personalizzato; con Kcb=1.30 e
        # floor_margin=0.10, Kcmax = max(1.20, 1.40) = 1.40.
        self.assertAlmostEqual(
            kcmax(1.30, floor_margin=0.10), 1.40, places=10,
        )

    def test_rejects_invalid_kcb(self):
        with self.assertRaises(ValueError):
            kcmax(0.0)
        with self.assertRaises(ValueError):
            kcmax(-0.5)

    def test_rejects_negative_floor_margin(self):
        with self.assertRaises(ValueError):
            kcmax(1.0, floor_margin=-0.1)

    def test_rejects_invalid_climate_baseline(self):
        with self.assertRaises(ValueError):
            kcmax(1.0, climate_baseline=0.0)
        with self.assertRaises(ValueError):
            kcmax(1.0, climate_baseline=-0.5)


class TestSoilEvaporationCoefficient(unittest.TestCase):
    """Comportamento di Ke (FAO-56 eq. 71)."""

    def test_zero_kr_yields_zero_ke(self):
        # Substrato superficie asciutta (Kr=0): nessuna evaporazione.
        self.assertEqual(
            soil_evaporation_coefficient(kr=0.0, kcb=0.5), 0.0,
        )

    def test_full_kr_yields_significant_ke(self):
        # Kr=1: il substrato superficiale ha tutta l'acqua disponibile.
        # Ke = min(1.0 × (Kcmax - Kcb), few × Kcmax).
        # Con Kcb=0.5 e Kcmax=1.20, il primo termine è 0.70.
        # Il secondo è 1.0 × 1.20 = 1.20. Quindi Ke = 0.70 (primo
        # termine domina). Questo è il comportamento atteso per un
        # substrato appena bagnato sotto coltura giovane: l'evaporazione
        # superficiale è significativa, ben oltre la sola correzione 0.05.
        ke = soil_evaporation_coefficient(kr=1.0, kcb=0.5)
        expected = KCMAX_DEFAULT - 0.5  # 0.70
        self.assertAlmostEqual(ke, expected, places=10)

    def test_ke_proportional_to_kr(self):
        # In regime non-cap, Ke = Kr × (Kcmax - Kcb).
        # Il fattore di proporzionalità è la "riserva energetica
        # disponibile per evaporazione" data dal margine tra Kcmax
        # e Kcb. Per Kcb=0.6, questo margine vale 1.20 - 0.6 = 0.60.
        kcb = 0.6
        kcmax_minus_kcb = KCMAX_DEFAULT - kcb  # 0.60
        for kr in [0.0, 0.2, 0.5, 0.8, 1.0]:
            with self.subTest(kr=kr):
                ke = soil_evaporation_coefficient(kr=kr, kcb=kcb)
                expected = kr * kcmax_minus_kcb
                self.assertAlmostEqual(ke, expected, places=10)

    def test_few_caps_evaporation(self):
        # Il cap del secondo termine (few × Kcmax) entra in gioco
        # quando few è abbastanza piccolo. Con few=0.5, Kcb=0.5, Kr=1:
        # primo termine = 1.0 × (1.20 - 0.5) = 0.70
        # secondo termine = 0.5 × 1.20 = 0.60
        # Il min è 0.60: il cap energetico domina.
        ke = soil_evaporation_coefficient(kr=1.0, kcb=0.5, few=0.5)
        self.assertAlmostEqual(ke, 0.5 * KCMAX_DEFAULT, places=10)

    def test_high_kcb_reduces_ke_room(self):
        # Per colture di pieno sviluppo (Kcb alto), il margine
        # disponibile per evaporazione superficiale è piccolo perché
        # la chioma intercetta gran parte della radiazione. Per
        # Kcb=1.10 con Kr=1: Kcmax = max(1.20, 1.15) = 1.20, e
        # Ke = 1.0 × (1.20 - 1.10) = 0.10. È molto meno dei 0.70
        # del test precedente (Kcb basso): la coltura "ruba" energia
        # all'evaporazione del substrato.
        ke = soil_evaporation_coefficient(kr=1.0, kcb=1.10)
        self.assertAlmostEqual(ke, 0.10, places=10)

    def test_rejects_invalid_kr(self):
        with self.assertRaises(ValueError):
            soil_evaporation_coefficient(kr=-0.1, kcb=0.5)
        with self.assertRaises(ValueError):
            soil_evaporation_coefficient(kr=1.1, kcb=0.5)

    def test_rejects_invalid_few(self):
        with self.assertRaises(ValueError):
            soil_evaporation_coefficient(kr=1.0, kcb=0.5, few=0.0)
        with self.assertRaises(ValueError):
            soil_evaporation_coefficient(kr=1.0, kcb=0.5, few=1.5)


# =======================================================================
#  3. update_de: dinamica giornaliera
# =======================================================================

class TestUpdateDe(unittest.TestCase):
    """Aggiornamento giornaliero della cumulative depletion."""

    def test_evap_only_increases_de(self):
        # Senza input idrico, l'evaporazione fa salire De.
        new_de = update_de(
            de_mm_previous=5.0,
            evaporation_mm=2.0,
            water_input_mm=0.0,
            tew_mm=22.0,
        )
        self.assertEqual(new_de, 7.0)

    def test_input_only_decreases_de(self):
        # Input idrico abbondante (irrigazione/pioggia) azzera De.
        new_de = update_de(
            de_mm_previous=15.0,
            evaporation_mm=0.0,
            water_input_mm=20.0,
            tew_mm=22.0,
        )
        self.assertEqual(new_de, 0.0)

    def test_partial_input_partial_recharge(self):
        # Input parziale: De si riduce di quel tanto.
        new_de = update_de(
            de_mm_previous=10.0,
            evaporation_mm=2.0,
            water_input_mm=5.0,
            tew_mm=22.0,
        )
        # Bilancio: 10 + 2 - 5 = 7 mm.
        self.assertEqual(new_de, 7.0)

    def test_de_capped_at_tew(self):
        # Anche con grande evaporazione e De alto, non si va oltre TEW.
        new_de = update_de(
            de_mm_previous=20.0,
            evaporation_mm=10.0,
            water_input_mm=0.0,
            tew_mm=22.0,
        )
        self.assertEqual(new_de, 22.0)

    def test_de_floored_at_zero(self):
        # Anche con grande input e De basso, non si va sotto zero
        # (l'eccesso d'acqua è trattato dal water balance del bulk).
        new_de = update_de(
            de_mm_previous=2.0,
            evaporation_mm=0.0,
            water_input_mm=10.0,
            tew_mm=22.0,
        )
        self.assertEqual(new_de, 0.0)

    def test_rejects_negative_inputs(self):
        with self.assertRaises(ValueError):
            update_de(de_mm_previous=-1.0, evaporation_mm=0.0,
                      water_input_mm=0.0, tew_mm=22.0)
        with self.assertRaises(ValueError):
            update_de(de_mm_previous=0.0, evaporation_mm=-1.0,
                      water_input_mm=0.0, tew_mm=22.0)
        with self.assertRaises(ValueError):
            update_de(de_mm_previous=0.0, evaporation_mm=0.0,
                      water_input_mm=-1.0, tew_mm=22.0)


# =======================================================================
#  4. Composizione: scenari realistici
# =======================================================================

class TestRealisticScenarios(unittest.TestCase):
    """Scenari realistici di asciugamento e ribagnatura."""

    def test_drying_sequence_after_irrigation(self):
        # Sequenza completa: substrato appena bagnato, poi 7 giorni
        # di asciugamento senza pioggia. Verifichiamo che De cresca
        # monotonicamente e Kr decresca monotonicamente.
        rew, tew = 9.0, 22.0
        de = 0.0
        kr_history = []
        for day in range(7):
            kr = evaporation_reduction_coefficient(de, rew, tew)
            kr_history.append(kr)
            ke = soil_evaporation_coefficient(kr=kr, kcb=0.7)
            # Ipotizziamo ET₀ = 4 mm/giorno, quindi E_actual = ke × 4.
            evap = ke * 4.0
            de = update_de(de, evap, 0.0, tew)
        # Kr deve essere monotonico decrescente.
        for i in range(len(kr_history) - 1):
            with self.subTest(day_from=i, day_to=i + 1):
                self.assertGreaterEqual(kr_history[i], kr_history[i + 1])
        # Dopo 7 giorni De deve essere non-zero (asciugamento avvenuto).
        self.assertGreater(de, 0.0)

    def test_irrigation_resets_de(self):
        # Substrato a metà asciugamento (De=15 mm su TEW=22), poi
        # irrigazione abbondante: De si azzera.
        de_pre = 15.0
        de_post = update_de(
            de_mm_previous=de_pre,
            evaporation_mm=2.0,
            water_input_mm=20.0,
            tew_mm=22.0,
        )
        self.assertEqual(de_post, 0.0)
        # Dopo l'irrigazione, Kr torna a 1.
        kr = evaporation_reduction_coefficient(de_post, 9.0, 22.0)
        self.assertEqual(kr, 1.0)


if __name__ == "__main__":
    unittest.main()
