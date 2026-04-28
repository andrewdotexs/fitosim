"""
Test del modulo science/fertigation.py (sotto-tappa C tappa 3 fascia 2).

Strategia di test
-----------------

Il modulo fertigation è composto da funzioni pure che prendono numeri
e restituiscono numeri. I test li trattano come funzioni matematiche:
calcoliamo il valore atteso a mano e verifichiamo che la funzione
restituisca quel valore, su una varietà di scenari fisicamente
significativi.

Quattro famiglie tematiche:

  1. **salt_balance_step**: bilancio della massa salina, con e senza
     drenaggio, in vari rapporti tra acqua presente e acqua entrante.

  2. **ph_after_mixing**: variazione del pH a seconda della CEC del
     substrato, del volume di soluzione entrante, dei pH coinvolti.
     Inchioda i tre comportamenti qualitativi documentati: CEC alta
     → smorzamento, CEC bassa → dominanza dell'input, volume zero →
     pH invariato.

  3. **fertigation_step**: la funzione facade che orchestra le due
     precedenti. Verifica che la composizione produca risultati
     coerenti con le funzioni sottostanti chiamate singolarmente.

  4. **validazione**: errori di input → ValueError con messaggi utili.
"""

import unittest
import math

from fitosim.science.fertigation import (
    EC_TO_MEQ_PER_LITER,
    PH_INPUT_WEIGHT_CALIBRATION,
    RAINFALL_EC_MSCM,
    RAINFALL_PH,
    TYPICAL_SUBSTRATE_DENSITY_KG_PER_L,
    FertigationStepResult,
    fertigation_step,
    ph_after_mixing,
    salt_balance_step,
)


# =======================================================================
#  Famiglia 1: salt_balance_step
# =======================================================================

class TestSaltBalanceStep(unittest.TestCase):
    """
    Bilancio della massa salina: mescolamento e drenaggio.
    """

    def test_no_input_no_change(self):
        # Nessun evento idrico (V_in=0): nulla cambia.
        salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=1.0,
            water_input_l=0.0,
            ec_input_mscm=0.0,
            fc_water_volume_l=1.5,
        )
        self.assertEqual(salt_final, 10.0)
        self.assertEqual(salt_drained, 0.0)
        self.assertEqual(salt_added, 0.0)
        self.assertEqual(water_drained, 0.0)

    def test_pure_water_input_no_drainage(self):
        # Acqua pura (EC=0) che non causa drenaggio: la massa salina
        # totale resta invariata, ma viene "diluita" nel maggior volume.
        # Il modulo non calcola la concentrazione (lo fa il Pot via
        # property), quindi controlliamo solo la massa.
        salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=0.5,
            water_input_l=0.5,        # 0.5 + 0.5 = 1.0 < 1.5 fc
            ec_input_mscm=0.0,        # acqua pura
            fc_water_volume_l=1.5,
        )
        self.assertEqual(salt_final, 10.0)  # nulla esce, nulla entra
        self.assertEqual(salt_added, 0.0)
        self.assertEqual(salt_drained, 0.0)
        self.assertEqual(water_drained, 0.0)

    def test_fertigation_no_drainage(self):
        # Fertirrigazione che non causa drenaggio: i sali entrano e
        # restano tutti nel vaso.
        salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=0.5,
            water_input_l=0.5,        # totale 1.0 < 1.5 fc
            ec_input_mscm=2.0,        # 2 × 0.5 × 10 = 10 meq aggiunti
            fc_water_volume_l=1.5,
        )
        self.assertEqual(salt_added, 10.0)
        self.assertEqual(salt_drained, 0.0)
        self.assertEqual(water_drained, 0.0)
        # 10 + 10 = 20 meq totali finali
        self.assertEqual(salt_final, 20.0)

    def test_fertigation_with_drainage_canonical_example(self):
        # IL TEST CANONICO della docstring del modulo. Vaso 1L acqua
        # con 10 meq, capacità 1.5 L, arriva 1L di soluzione a EC 2
        # (= 20 meq aggiunti). Totale post-mescolamento: 30 meq in 2L.
        # Drena 0.5 L = 25% del totale → 7.5 meq drenati.
        # Finale: 22.5 meq in 1.5 L (EC 1.5).
        salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=1.0,
            water_input_l=1.0,
            ec_input_mscm=2.0,
            fc_water_volume_l=1.5,
        )
        self.assertAlmostEqual(salt_added, 20.0, places=9)
        self.assertAlmostEqual(water_drained, 0.5, places=9)
        self.assertAlmostEqual(salt_drained, 7.5, places=9)
        self.assertAlmostEqual(salt_final, 22.5, places=9)

    def test_drainage_proportional_removal(self):
        # PROPRIETÀ FONDAMENTALE: il drenaggio rimuove una frazione
        # dei sali totali momentanei pari alla frazione di volume
        # drenato. Questo è il meccanismo di "lisciviazione" usato
        # dai giardinieri esperti.
        #
        # Costruiamo un caso dove drena esattamente metà del volume:
        # vaso a 0.5 L con 10 meq, fc=0.5 L. Arriva 0.5 L acqua pura.
        # Totale 1.0 L con 10 meq, drena 0.5 L = 50% → 5 meq drenati.
        salt_final, salt_drained, _, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=0.5,
            water_input_l=0.5,
            ec_input_mscm=0.0,         # acqua pura
            fc_water_volume_l=0.5,
        )
        self.assertAlmostEqual(water_drained, 0.5, places=9)
        self.assertAlmostEqual(salt_drained, 5.0, places=9)  # 50% rimossi
        self.assertAlmostEqual(salt_final, 5.0, places=9)

    def test_massive_flush_almost_all_salts_removed(self):
        # Innaffiatura molto abbondante con acqua pura: il vaso si
        # "lava" quasi completamente dei suoi sali. È il caso pratico
        # del giardiniere che vuole "resettare" un substrato salino.
        # Vaso a 1L con 50 meq, fc=1L. Arriva 9L acqua pura → totale
        # 10L, drenano 9L = 90% → 45 meq drenati, 5 meq finali.
        salt_final, salt_drained, _, water_drained = salt_balance_step(
            salt_mass_before_meq=50.0,
            water_volume_before_l=1.0,
            water_input_l=9.0,
            ec_input_mscm=0.0,
            fc_water_volume_l=1.0,
        )
        self.assertAlmostEqual(water_drained, 9.0, places=9)
        self.assertAlmostEqual(salt_drained, 45.0, places=9)
        self.assertAlmostEqual(salt_final, 5.0, places=9)

    def test_starting_from_dry_pot(self):
        # Vaso completamente asciutto al momento dell'evento.
        # La fertirrigazione riempie e il bilancio funziona normale.
        salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
            salt_mass_before_meq=0.0,
            water_volume_before_l=0.0,    # vaso secco
            water_input_l=1.0,
            ec_input_mscm=1.5,
            fc_water_volume_l=1.5,
        )
        self.assertAlmostEqual(salt_added, 15.0, places=9)
        self.assertAlmostEqual(water_drained, 0.0, places=9)  # 1.0 < 1.5
        self.assertAlmostEqual(salt_final, 15.0, places=9)

    def test_input_exactly_at_fc_no_drainage(self):
        # Caso al limite: il volume post-mescolamento coincide
        # esattamente con la fc. Niente drenaggio.
        salt_final, _, _, water_drained = salt_balance_step(
            salt_mass_before_meq=10.0,
            water_volume_before_l=1.0,
            water_input_l=0.5,           # 1.0 + 0.5 = 1.5 = fc
            ec_input_mscm=1.0,
            fc_water_volume_l=1.5,
        )
        self.assertEqual(water_drained, 0.0)
        # 10 + (1 × 0.5 × 10) = 15 meq, tutti rimasti
        self.assertAlmostEqual(salt_final, 15.0, places=9)


# =======================================================================
#  Famiglia 2: ph_after_mixing
# =======================================================================

class TestPhAfterMixing(unittest.TestCase):
    """
    Variazione del pH del substrato secondo la media pesata modulata
    da CEC.
    """

    def test_zero_input_no_change(self):
        # Nessun volume entrante: pH invariato (caso degenere).
        ph_new = ph_after_mixing(
            ph_before=6.5, ph_input=4.0,
            water_input_l=0.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertEqual(ph_new, 6.5)

    def test_canonical_example_basilico_ph_neutral_water(self):
        # ESEMPIO CANONICO della docstring:
        # vaso 2L basilico (0.8 kg substrato, CEC 50), pH iniziale 6.5,
        # innaffiatura 1L a pH 7.5 (acqua del rubinetto milanese).
        # peso_substrato = 50 * 0.8 = 40
        # peso_soluzione = 1.0 * 10 = 10
        # pH_after = (40*6.5 + 10*7.5) / 50 = 6.7
        ph_new = ph_after_mixing(
            ph_before=6.5, ph_input=7.5,
            water_input_l=1.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertAlmostEqual(ph_new, 6.7, places=9)

    def test_high_cec_dampens_ph_change(self):
        # SECONDO ESEMPIO della docstring: stesso vaso ma su substrato
        # per acidofile (CEC 140). pH iniziale 5.0, stessa innaffiatura.
        # peso_substrato = 140 * 0.8 = 112
        # peso_soluzione = 1.0 * 10 = 10
        # pH_after = (112*5.0 + 10*7.5) / 122 ≈ 5.205
        # Lo spostamento è solo 0.205 unità invece di 0.5+ che sarebbe
        # con CEC tipica.
        ph_new = ph_after_mixing(
            ph_before=5.0, ph_input=7.5,
            water_input_l=1.0,
            cec_meq_per_100g=140.0, substrate_dry_mass_kg=0.8,
        )
        # (112*5 + 10*7.5) / 122 = (560 + 75) / 122 = 635 / 122
        expected = 635.0 / 122.0
        self.assertAlmostEqual(ph_new, expected, places=9)
        # Verifichiamo qualitativamente: lo spostamento è < 0.25
        self.assertLess(abs(ph_new - 5.0), 0.25)

    def test_low_cec_amplifies_ph_change(self):
        # Substrato a CEC bassa (sabbia, CEC 10). Lo stesso evento
        # produce uno spostamento molto più grande.
        # peso_substrato = 10 * 0.8 = 8
        # peso_soluzione = 1.0 * 10 = 10
        # pH_after = (8*5.0 + 10*7.5) / 18 ≈ 6.39
        ph_new = ph_after_mixing(
            ph_before=5.0, ph_input=7.5,
            water_input_l=1.0,
            cec_meq_per_100g=10.0, substrate_dry_mass_kg=0.8,
        )
        expected = (8.0 * 5.0 + 10.0 * 7.5) / 18.0
        self.assertAlmostEqual(ph_new, expected, places=9)
        # Spostamento qualitativamente grande: > 1 unità
        self.assertGreater(abs(ph_new - 5.0), 1.0)

    def test_acidic_input_lowers_ph(self):
        # Fertilizzante BioBizz tipico: pH 6.0 entra in vaso a pH 7.0.
        # Direzione del cambiamento: verso il basso.
        ph_new = ph_after_mixing(
            ph_before=7.0, ph_input=6.0,
            water_input_l=1.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        # pH finale dev'essere tra 6.0 e 7.0 (media pesata)
        self.assertLess(ph_new, 7.0)
        self.assertGreater(ph_new, 6.0)

    def test_alkaline_input_raises_ph(self):
        # Acqua del rubinetto milanese (pH 7.8) in vaso un po' acido.
        # Direzione: verso l'alto.
        ph_new = ph_after_mixing(
            ph_before=6.0, ph_input=7.8,
            water_input_l=1.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertGreater(ph_new, 6.0)
        self.assertLess(ph_new, 7.8)

    def test_equal_pH_no_change(self):
        # Se il pH della soluzione è uguale al pH del substrato,
        # niente cambia indipendentemente dai pesi.
        ph_new = ph_after_mixing(
            ph_before=6.5, ph_input=6.5,
            water_input_l=2.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertAlmostEqual(ph_new, 6.5, places=9)

    def test_rainfall_on_alkaline_pot(self):
        # Pioggia naturale (pH 5.6) su un vaso alcalino. Il pH si
        # abbassa, è il fenomeno per cui le piogge prolungate
        # acidificano i substrati.
        ph_new = ph_after_mixing(
            ph_before=7.5, ph_input=RAINFALL_PH,
            water_input_l=2.0,                  # piogggia abbondante
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertLess(ph_new, 7.5)
        self.assertGreater(ph_new, RAINFALL_PH)

    def test_calibration_neutral_substrate_neutral_volume(self):
        # CALIBRAZIONE della costante PH_INPUT_WEIGHT_CALIBRATION:
        # con CEC default (50), massa default (0.8 kg per vaso 2L),
        # e volume entrante "confrontabile" col volume di acqua già
        # presente (~1 L), il pH finale deve essere a circa metà
        # strada tra i due. Lo verifichiamo numericamente.
        ph_before = 6.0
        ph_input = 8.0
        ph_new = ph_after_mixing(
            ph_before=ph_before, ph_input=ph_input,
            water_input_l=1.0,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        # peso_substrato = 40, peso_soluzione = 10
        # pH = (40*6 + 10*8) / 50 = 6.4
        # Lo spostamento è 0.4 sull'arco di 2 = 20%. Non è "metà strada"
        # esatto perché il calibration costante è 10 non 40, ma è il
        # comportamento documentato: la soluzione ha un peso che è
        # 1/4 del substrato per evento "tipico".
        self.assertAlmostEqual(ph_new, 6.4, places=9)


# =======================================================================
#  Famiglia 3: fertigation_step (orchestratore)
# =======================================================================

class TestFertigationStep(unittest.TestCase):
    """
    Funzione facade che chiama le due precedenti in sequenza.
    Verifica che la composizione sia consistente.
    """

    def test_returns_fertigation_step_result(self):
        # La firma del ritorno è il dataclass FertigationStepResult.
        result = fertigation_step(
            salt_mass_before_meq=10.0, ph_before=6.5,
            water_volume_before_l=1.0,
            water_input_l=0.5, ec_input_mscm=1.5, ph_input=6.0,
            fc_water_volume_l=1.5,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertIsInstance(result, FertigationStepResult)

    def test_consistency_with_underlying_functions(self):
        # Il risultato di fertigation_step deve coincidere con quello
        # ottenibile chiamando le due funzioni sottostanti separatamente.
        params = dict(
            salt_mass_before_meq=10.0,
            water_volume_before_l=1.0,
            water_input_l=0.7,
            ec_input_mscm=1.5,
            fc_water_volume_l=1.5,
        )
        ph_params = dict(
            ph_before=6.5, ph_input=6.0,
            water_input_l=0.7,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )

        salt_final, salt_drained, salt_added, water_drained = (
            salt_balance_step(**params)
        )
        ph_after = ph_after_mixing(**ph_params)

        # Risultato dalla facade
        result = fertigation_step(
            salt_mass_before_meq=10.0, ph_before=6.5,
            water_volume_before_l=1.0,
            water_input_l=0.7, ec_input_mscm=1.5, ph_input=6.0,
            fc_water_volume_l=1.5,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )

        self.assertAlmostEqual(
            result.salt_mass_after_meq, salt_final, places=9,
        )
        self.assertAlmostEqual(
            result.salt_mass_drained_meq, salt_drained, places=9,
        )
        self.assertAlmostEqual(
            result.salt_mass_added_meq, salt_added, places=9,
        )
        self.assertAlmostEqual(
            result.water_drained_l, water_drained, places=9,
        )
        self.assertAlmostEqual(result.ph_after, ph_after, places=9)

    def test_ph_delta_sign_correct(self):
        # ph_delta = ph_after - ph_before. Verifichiamo sia il segno
        # corretto in entrambe le direzioni.

        # Fertilizzante acido: pH cala → delta negativo
        result_down = fertigation_step(
            salt_mass_before_meq=10.0, ph_before=7.0,
            water_volume_before_l=1.0,
            water_input_l=1.0, ec_input_mscm=2.0, ph_input=5.5,
            fc_water_volume_l=1.5,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertLess(result_down.ph_delta, 0)

        # Acqua alcalina: pH sale → delta positivo
        result_up = fertigation_step(
            salt_mass_before_meq=10.0, ph_before=6.0,
            water_volume_before_l=1.0,
            water_input_l=1.0, ec_input_mscm=0.5, ph_input=8.0,
            fc_water_volume_l=1.5,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        self.assertGreater(result_up.ph_delta, 0)

    def test_rainfall_event_lowers_ec(self):
        # Pioggia naturale (EC=0, pH=5.6) su un vaso fertilizzato:
        # i sali totali NON aumentano (zero entrano), e se la pioggia
        # è abbondante drena anche un po' di sali. Il pH si avvicina
        # a quello della pioggia.
        result = fertigation_step(
            salt_mass_before_meq=20.0, ph_before=7.0,
            water_volume_before_l=1.0,
            water_input_l=1.0,                # totale 2.0, fc 1.5
            ec_input_mscm=RAINFALL_EC_MSCM,
            ph_input=RAINFALL_PH,
            fc_water_volume_l=1.5,
            cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
        )
        # Niente sali aggiunti
        self.assertEqual(result.salt_mass_added_meq, 0.0)
        # Drenaggio rimuove una frazione dei sali
        self.assertGreater(result.salt_mass_drained_meq, 0)
        # Massa salina finale è inferiore a quella iniziale
        self.assertLess(result.salt_mass_after_meq, 20.0)
        # pH si abbassa verso quello della pioggia
        self.assertLess(result.ph_after, 7.0)
        self.assertGreater(result.ph_after, RAINFALL_PH)


# =======================================================================
#  Famiglia 4: validazione degli input
# =======================================================================

class TestInputValidation(unittest.TestCase):
    """
    Le funzioni rifiutano valori fisicamente impossibili.
    """

    def test_salt_balance_rejects_negative_inputs(self):
        with self.assertRaises(ValueError):
            salt_balance_step(
                salt_mass_before_meq=-5.0,
                water_volume_before_l=1.0,
                water_input_l=1.0, ec_input_mscm=1.0,
                fc_water_volume_l=1.5,
            )
        with self.assertRaises(ValueError):
            salt_balance_step(
                salt_mass_before_meq=5.0,
                water_volume_before_l=-1.0,
                water_input_l=1.0, ec_input_mscm=1.0,
                fc_water_volume_l=1.5,
            )
        with self.assertRaises(ValueError):
            salt_balance_step(
                salt_mass_before_meq=5.0,
                water_volume_before_l=1.0,
                water_input_l=-1.0, ec_input_mscm=1.0,
                fc_water_volume_l=1.5,
            )
        with self.assertRaises(ValueError):
            salt_balance_step(
                salt_mass_before_meq=5.0,
                water_volume_before_l=1.0,
                water_input_l=1.0, ec_input_mscm=-0.5,
                fc_water_volume_l=1.5,
            )

    def test_salt_balance_rejects_zero_fc(self):
        # FC zero o negativa: senza capacità di campo non si può
        # calcolare il drenaggio.
        with self.assertRaises(ValueError):
            salt_balance_step(
                salt_mass_before_meq=5.0,
                water_volume_before_l=1.0,
                water_input_l=1.0, ec_input_mscm=1.0,
                fc_water_volume_l=0.0,
            )

    def test_ph_after_mixing_rejects_invalid_ph(self):
        # pH fuori scala chimica.
        with self.assertRaises(ValueError):
            ph_after_mixing(
                ph_before=15.0, ph_input=7.0,
                water_input_l=1.0,
                cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
            )
        with self.assertRaises(ValueError):
            ph_after_mixing(
                ph_before=6.5, ph_input=-1.0,
                water_input_l=1.0,
                cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.8,
            )

    def test_ph_after_mixing_rejects_zero_cec(self):
        # CEC zero o negativa: il modello non saprebbe come pesare
        # il substrato.
        with self.assertRaises(ValueError):
            ph_after_mixing(
                ph_before=6.5, ph_input=7.0,
                water_input_l=1.0,
                cec_meq_per_100g=0.0, substrate_dry_mass_kg=0.8,
            )

    def test_ph_after_mixing_rejects_zero_substrate_mass(self):
        with self.assertRaises(ValueError):
            ph_after_mixing(
                ph_before=6.5, ph_input=7.0,
                water_input_l=1.0,
                cec_meq_per_100g=50.0, substrate_dry_mass_kg=0.0,
            )


if __name__ == "__main__":
    unittest.main()
