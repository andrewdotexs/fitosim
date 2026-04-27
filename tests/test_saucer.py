"""
Test per fitosim.science.saucer.

Quattro famiglie:
  1. capillary_transfer: comportamento del flusso vaso-sottovaso.
  2. saucer_evaporation: evaporazione del piattino.
  3. Validazione degli input (valori non fisicamente sensati).
  4. Composizione: comportamenti combinati delle due funzioni.
"""

import unittest

from fitosim.science.saucer import (
    DEFAULT_CAPILLARY_RATE,
    DEFAULT_SAUCER_EVAP_COEF,
    capillary_transfer,
    saucer_evaporation,
)


# =======================================================================
#  1. capillary_transfer
# =======================================================================

class TestCapillaryTransfer(unittest.TestCase):
    """Comportamento della funzione di risalita capillare."""

    def test_zero_deficit_yields_zero_transfer(self):
        # Substrato a FC: nessuna forza capillare netta, niente
        # trasferimento qualunque sia l'acqua nel piattino.
        self.assertEqual(capillary_transfer(10.0, 0.0), 0.0)
        self.assertEqual(capillary_transfer(100.0, 0.0), 0.0)

    def test_negative_deficit_treated_as_zero(self):
        # Substrato sopra FC (sovrasaturazione momentanea): forziamo
        # zero invece di un trasferimento "negativo" che non avrebbe
        # senso fisico.
        self.assertEqual(capillary_transfer(10.0, -2.0), 0.0)

    def test_empty_saucer_yields_zero_transfer(self):
        # Sottovaso vuoto, non importa il deficit.
        self.assertEqual(capillary_transfer(0.0, 50.0), 0.0)

    def test_transfer_proportional_to_deficit(self):
        # Con sottovaso "molto pieno" (non limitante), il trasferimento
        # è esattamente rate × deficit.
        rate = 0.4
        deficit = 20.0
        # Sottovaso con 100 mm: il limite operativo è il desired = 8 mm.
        result = capillary_transfer(100.0, deficit, rate=rate)
        self.assertAlmostEqual(result, rate * deficit, places=6)

    def test_transfer_limited_by_saucer_water(self):
        # Il sottovaso ha meno di quanto il modello vorrebbe trasferire:
        # il limite è l'acqua effettivamente disponibile.
        rate = 0.4
        deficit = 50.0  # desired = 20 mm
        saucer = 5.0    # ma ho solo 5 mm
        result = capillary_transfer(saucer, deficit, rate=rate)
        self.assertEqual(result, 5.0)

    def test_default_rate_used_when_omitted(self):
        # Verifica che il default sia esattamente DEFAULT_CAPILLARY_RATE.
        result = capillary_transfer(100.0, 10.0)
        self.assertAlmostEqual(
            result, DEFAULT_CAPILLARY_RATE * 10.0, places=10,
        )

    def test_transfer_never_exceeds_saucer_water(self):
        # Test di robustezza: per nessuna combinazione di parametri il
        # trasferimento può eccedere l'acqua disponibile.
        for sat in [0.0, 1.0, 5.0, 50.0]:
            for deficit in [0.0, 5.0, 20.0, 100.0]:
                for rate in [0.1, 0.4, 0.9]:
                    with self.subTest(saucer=sat, deficit=deficit, rate=rate):
                        out = capillary_transfer(sat, deficit, rate)
                        self.assertGreaterEqual(out, 0.0)
                        self.assertLessEqual(out, sat)


# =======================================================================
#  2. saucer_evaporation
# =======================================================================

class TestSaucerEvaporation(unittest.TestCase):
    """Comportamento dell'evaporazione del piattino."""

    def test_empty_saucer_yields_zero_evap(self):
        self.assertEqual(saucer_evaporation(0.0, 5.0), 0.0)

    def test_zero_et0_yields_zero_evap(self):
        # Atmosfera senza domanda evapotraspirativa: niente evaporazione
        # qualunque sia l'acqua nel sottovaso.
        self.assertEqual(saucer_evaporation(10.0, 0.0), 0.0)

    def test_evap_proportional_to_et0(self):
        # Con sottovaso "molto pieno" l'evap è coef × ET₀.
        coef = 0.4
        et0 = 5.0
        result = saucer_evaporation(100.0, et0, coef=coef)
        self.assertAlmostEqual(result, coef * et0, places=6)

    def test_evap_limited_by_saucer_water(self):
        # Sottovaso quasi vuoto: il limite è l'acqua disponibile.
        coef = 0.4
        et0 = 10.0  # desired = 4 mm
        saucer = 1.0  # ma ho solo 1 mm
        result = saucer_evaporation(saucer, et0, coef=coef)
        self.assertEqual(result, 1.0)

    def test_default_coef_used_when_omitted(self):
        # Verifica del default DEFAULT_SAUCER_EVAP_COEF.
        result = saucer_evaporation(100.0, 5.0)
        self.assertAlmostEqual(
            result, DEFAULT_SAUCER_EVAP_COEF * 5.0, places=10,
        )

    def test_evap_never_exceeds_saucer_water(self):
        for sat in [0.0, 1.0, 5.0, 50.0]:
            for et0 in [0.0, 1.0, 5.0, 15.0]:
                for coef in [0.0, 0.4, 0.8]:
                    with self.subTest(saucer=sat, et0=et0, coef=coef):
                        out = saucer_evaporation(sat, et0, coef)
                        self.assertGreaterEqual(out, 0.0)
                        self.assertLessEqual(out, sat)


# =======================================================================
#  3. Validazione degli input
# =======================================================================

class TestInputValidation(unittest.TestCase):
    """Le funzioni rifiutano valori non fisicamente sensati."""

    def test_capillary_rejects_negative_saucer(self):
        with self.assertRaises(ValueError):
            capillary_transfer(-1.0, 10.0)

    def test_capillary_rejects_zero_or_negative_rate(self):
        with self.assertRaises(ValueError):
            capillary_transfer(10.0, 5.0, rate=0.0)
        with self.assertRaises(ValueError):
            capillary_transfer(10.0, 5.0, rate=-0.5)

    def test_saucer_evap_rejects_negative_water(self):
        with self.assertRaises(ValueError):
            saucer_evaporation(-1.0, 5.0)

    def test_saucer_evap_rejects_negative_et0(self):
        with self.assertRaises(ValueError):
            saucer_evaporation(10.0, -2.0)

    def test_saucer_evap_rejects_negative_coef(self):
        with self.assertRaises(ValueError):
            saucer_evaporation(10.0, 5.0, coef=-0.1)

    def test_saucer_evap_accepts_zero_coef(self):
        # coef=0.0 significa "niente evaporazione del piattino" e va
        # accettato (configurazione del giardiniere che vuole disabilitare
        # quel pezzo del modello).
        self.assertEqual(saucer_evaporation(10.0, 5.0, coef=0.0), 0.0)


# =======================================================================
#  4. Composizione delle due funzioni
# =======================================================================

class TestSaucerComposition(unittest.TestCase):
    """
    Scenari realistici di composizione delle due funzioni: l'esempio
    classico è la dinamica giornaliera del sottovaso.
    """

    def test_daily_sequence_loses_then_transfers(self):
        # Il sottovaso ha 8 mm. Il giorno è caldo (ET₀=5 mm/giorno) e
        # il vaso è 10 mm sotto FC. Sequenza: prima l'evaporazione del
        # piattino, poi la risalita.
        saucer = 8.0
        # Evaporazione: 0.4 × 5 = 2 mm.
        evap = saucer_evaporation(saucer, et_0_mm=5.0)
        self.assertAlmostEqual(evap, 2.0, places=6)
        saucer_after_evap = saucer - evap  # = 6 mm
        # Risalita: min(6, 0.4 × 10) = min(6, 4) = 4 mm.
        transfer = capillary_transfer(
            saucer_after_evap, deficit_mm=10.0,
        )
        self.assertAlmostEqual(transfer, 4.0, places=6)
        # Stato finale del sottovoto: 6 − 4 = 2 mm.
        saucer_final = saucer_after_evap - transfer
        self.assertAlmostEqual(saucer_final, 2.0, places=6)

    def test_empty_saucer_after_long_drought(self):
        # Sottovaso che parte da 5 mm, simulazione di 7 giorni di
        # solo evaporazione (substrato già a FC, niente trasferimento).
        # Ogni giorno: evap = min(saucer, 0.4×ET₀). Verifica che il
        # sottovaso si svuoti monotonicamente fino a zero.
        saucer = 5.0
        for _ in range(7):
            evap = saucer_evaporation(saucer, et_0_mm=4.0)
            saucer = max(0.0, saucer - evap)
        self.assertAlmostEqual(saucer, 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
