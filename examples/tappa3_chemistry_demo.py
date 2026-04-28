"""
Demo della tappa 3 fascia 2: simulazione completa del modello chimico
di un vaso di basilico sul balcone milanese.

Cosa fa questo script
---------------------

Simula 30 giorni di vita di un singolo vaso di basilico sul tuo
terrazzino con eventi realistici alternati: piogge naturali, fertir-
rigazioni settimanali con BioBizz, qualche annaffiatura con acqua del
rubinetto, e calibrazioni periodiche dal sensore ATO. Lo scopo è
mostrare in azione tutte le funzionalità della tappa 3:

  * Chimica del substrato che evolve nel tempo (massa salina, pH).
  * EC come property derivata che cattura il fenomeno della
    concentrazione per evapotraspirazione.
  * Coefficiente nutrizionale Kn che modula l'evapotraspirazione
    quando lo stato chimico esce dai range ottimali del basilico.
  * Feedback loop chimico col sensore che corregge periodicamente
    le previsioni del modello.
  * Coefficiente di esposizione alla pioggia per modellare un vaso
    parzialmente coperto da un balcone superiore.
  * Comportamento differenziato di apply_fertigation_step (volume
    pieno) e apply_rainfall_step (volume modulato dall'esposizione).

Come eseguirlo
--------------

Dalla root del progetto fitosim::

    PYTHONPATH=src python examples/tappa3_chemistry_demo.py

L'esecuzione è deterministica (il random ha seed fissato) quindi
ottieni sempre la stessa simulazione. Cambia il seed nella variabile
RANDOM_SEED in cima al file per esplorare scenari diversi.

Output
------

Una tabella riga-per-giorno con valori chiave del modello (stato
idrico, EC, pH, Kn corrente) e simboli per gli eventi della giornata.
Alla fine una sintesi con i totali del periodo: pioggia ricevuta vs
intercettata, sali aggiunti vs drenati, drift chimico medio rispetto
al sensore.
"""

import random
from datetime import date, datetime, timedelta, timezone

from fitosim.domain.pot import Pot, Location
from fitosim.domain.species import Species
from fitosim.io.sensors import SoilReading
from fitosim.science.balance import stress_coefficient_ks
from fitosim.science.nutrition import nutritional_factor
from fitosim.science.substrate import Substrate

# =======================================================================
#  Parametri della simulazione
# =======================================================================

RANDOM_SEED = 42
SIMULATION_START = date(2026, 5, 1)
SIMULATION_DAYS = 30


# =======================================================================
#  Configurazione del vaso reale del balcone
# =======================================================================

def build_milan_basil_pot() -> Pot:
    """
    Costruisce il vaso di esempio: un basilico in terriccio universale
    su balcone milanese, posizionato sotto un balcone superiore quindi
    parzialmente riparato dalla pioggia (rainfall_exposure = 0.6).
    """
    # Substrato con caratterizzazione chimica completa.
    # CEC tipica per terriccio universale (50 meq/100g),
    # pH naturale del terriccio universale (~6.8, leggermente acido).
    universal_substrate = Substrate(
        name="terriccio universale",
        theta_fc=0.40,
        theta_pwp=0.10,
        cec_meq_per_100g=50.0,
        ph_typical=6.8,
    )

    # Specie con range chimici ottimali per il basilico.
    # Basilico: Kc tipico, EC ottimale 1.0-1.6, pH ottimale 6.0-7.0.
    basil_with_chemistry = Species(
        common_name="basilico",
        scientific_name="Ocimum basilicum",
        kc_initial=0.50,
        kc_mid=1.10,
        kc_late=0.85,
        ec_optimal_min_mscm=1.0,
        ec_optimal_max_mscm=1.6,
        ph_optimal_min=6.0,
        ph_optimal_max=7.0,
    )

    # Il vaso fisico: 2 L su balcone milanese, sotto balcone superiore
    # che intercetta circa il 40% della pioggia (rainfall_exposure 0.6).
    return Pot(
        label="basilico-balcone",
        species=basil_with_chemistry,
        substrate=universal_substrate,
        pot_volume_l=2.0,
        pot_diameter_cm=18.0,
        location=Location.OUTDOOR,
        planting_date=date(2026, 4, 1),
        rainfall_exposure=0.6,
        # Stato iniziale: vaso ben idratato (75% di FC) e ben dentro il
        # range ottimale di EC del basilico (~1.2 mS/cm). Questo ti
        # permette di vedere la transizione progressiva dell'EC dal
        # range ottimale verso lo stress nel corso dei 30 giorni.
        state_mm=30.0,
        salt_mass_meq=7.5,
    )


# =======================================================================
#  Generazione degli eventi della simulazione
# =======================================================================

def generate_daily_et0_mm(rng: random.Random) -> float:
    """
    Genera ET₀ giornaliera realistica per Milano in maggio: media 4.5
    mm/giorno con variabilità di 1.5 mm in più o in meno. Sono valori
    coerenti con i dati storici di una stazione meteo del nord Italia.
    """
    return rng.uniform(3.0, 6.0)


def generate_daily_rainfall_mm(rng: random.Random, day_index: int) -> float:
    """
    Modella un pattern realistico di piogge a maggio: la maggior parte
    dei giorni è asciutta, alcuni hanno piogge leggere (2-5 mm), pochi
    hanno piogge intense (10-20 mm). Il pattern non è puramente random
    ma alternato a periodi secchi e periodi piovosi per produrre
    dinamiche interessanti del modello.
    """
    # Settimana 1 (giorni 0-6): periodo secco di inizio mese
    if day_index < 7:
        return 0.0 if rng.random() < 0.85 else rng.uniform(1.0, 4.0)
    # Settimana 2 (giorni 7-13): periodo piovoso
    if day_index < 14:
        if rng.random() < 0.4:
            # 30% pioggia intensa, 70% leggera
            return rng.uniform(10.0, 18.0) if rng.random() < 0.3 else rng.uniform(2.0, 6.0)
        return 0.0
    # Settimana 3 (giorni 14-20): di nuovo asciutto
    if day_index < 21:
        return 0.0 if rng.random() < 0.9 else rng.uniform(1.0, 3.0)
    # Settimana 4 (giorni 21-29): variabile
    return rng.uniform(2.0, 8.0) if rng.random() < 0.35 else 0.0


def is_fertigation_day(day_index: int) -> bool:
    """Fertirrigazione settimanale ogni lunedì (giorni 0, 7, 14, 21, 28)."""
    return day_index % 7 == 0


def is_tap_water_day(day_index: int, rng: random.Random) -> bool:
    """
    Annaffiatura con acqua del rubinetto nei giorni asciutti caldi:
    metà del periodo, casuale, solo se non è giorno di fertirrigazione.
    """
    if is_fertigation_day(day_index):
        return False
    return rng.random() < 0.25


def is_sensor_calibration_day(day_index: int) -> bool:
    """Calibrazione settimanale del sensore: giorni 7, 14, 21, 28."""
    return day_index > 0 and day_index % 7 == 0


def needs_leaching_irrigation(pot: Pot) -> bool:
    """
    Regola del giardiniere virtuale: bagnatura di lavaggio quando l'EC
    supera una soglia derivata dal range ottimale della specie.

    La soglia è ec_optimal_max + 0.5 mS/cm. Per il basilico
    (range 1.0-1.6) la soglia di lavaggio è quindi 2.1 mS/cm. È un
    valore agronomicamente ragionevole: lascia un margine di tolleranza
    sopra il limite ottimale (la pianta non viene "lavata" appena entra
    in stress lieve) ma interviene prima che lo stress diventi
    drammatico e cronico.

    Concettualmente questa funzione è il proxy del comportamento di un
    giardiniere esperto che osserva il vaso e decide quando intervenire.
    Nella tappa 4 (Garden orchestratore + sistema di allerte) questa
    logica diventerà una "regola dichiarativa" del sistema di allerte,
    che potrà notificare al giardiniere quando intervenire invece di
    fare l'azione automaticamente.
    """
    if not pot.species.supports_chemistry_model:
        return False
    leaching_threshold = pot.species.ec_optimal_max_mscm + 0.5
    return pot.ec_substrate_mscm > leaching_threshold


# =======================================================================
#  Simulazione dei valori del sensore reale
# =======================================================================

def simulate_sensor_reading(
    pot: Pot,
    current_date: date,
    rng: random.Random,
) -> SoilReading:
    """
    Simula una lettura del sensore ATO 7-in-1, partendo dai valori
    "veri" del Pot e aggiungendo rumore di misura realistico:

      - θ volumetrico: rumore ±0.015 (tipico WH51 dopo aggregazione)
      - EC: rumore ±0.05 mS/cm (tipico ATO 7-in-1)
      - pH: rumore ±0.1 unità (tipico sensore pH industriale)

    In aggiunta simula una piccola "deriva sistematica" del modello:
    il sensore vede valori leggermente diversi da quelli che il modello
    prevede per via di approssimazioni del modello stesso. È esattamente
    quello che vedrai col tuo sensore reale e che il feedback loop
    chimico è progettato per correggere.
    """
    # Valori "veri" dal modello, con piccola deriva sistematica del +5%
    # sull'EC (il modello tende a sottostimare leggermente per via
    # delle approssimazioni della costante di conversione).
    drifted_ec = pot.ec_substrate_mscm * 1.05
    drifted_ph = pot.ph_substrate - 0.1  # modello sovrastima il pH
    return SoilReading(
        timestamp=datetime.combine(
            current_date, datetime.min.time(), tzinfo=timezone.utc,
        ).replace(hour=12),
        theta_volumetric=max(0.0, min(1.0,
            pot.state_theta + rng.uniform(-0.015, 0.015),
        )),
        temperature_c=18.0 + rng.uniform(-2.0, 4.0),
        ec_mscm=max(0.0, drifted_ec + rng.uniform(-0.05, 0.05)),
        ph=max(0.1, min(14.0,
            drifted_ph + rng.uniform(-0.1, 0.1),
        )),
    )


# =======================================================================
#  Funzione principale di simulazione
# =======================================================================

def run_simulation():
    """
    Esegue la simulazione di SIMULATION_DAYS giorni e stampa l'output
    riga-per-giorno con la sintesi finale.
    """
    rng = random.Random(RANDOM_SEED)
    pot = build_milan_basil_pot()

    # Accumulatori per la sintesi finale.
    total_rainfall_nominal_mm = 0.0
    total_rainfall_intercepted_mm = 0.0
    total_salt_added_meq = 0.0
    total_salt_drained_meq = 0.0
    sensor_calibrations_count = 0
    leaching_events_count = 0
    discrepancies_ec = []  # liste delle discrepanze sensore-modello
    discrepancies_ph = []

    # ----- Header di stampa -----
    print_header(pot)

    # ----- Loop giornaliero -----
    for day_idx in range(SIMULATION_DAYS):
        current_date = SIMULATION_START + timedelta(days=day_idx)
        et_0_mm = generate_daily_et0_mm(rng)

        # Eventi del giorno
        rain_mm = generate_daily_rainfall_mm(rng, day_idx)
        # Conversione mm di pioggia → litri sul vaso. La pioggia cade
        # in mm su tutta l'area orizzontale, e l'area di intercettazione
        # del vaso (apertura superiore) la converte in litri.
        # Formula: V[L] = pioggia[mm] × area[m²].
        rain_volume_nominal_l = rain_mm * pot.surface_area_m2

        # Eventi attivi della giornata
        do_fertigation = is_fertigation_day(day_idx)
        do_tap_water = is_tap_water_day(day_idx, rng)
        do_sensor_cal = is_sensor_calibration_day(day_idx)
        # Lavaggio reattivo: il giardiniere virtuale interviene solo
        # se NON è già previsto un altro evento di bagnatura nel giorno,
        # e solo se l'EC corrente supera la soglia di lavaggio.
        # Concretamente: priorità fertirrigazione > acqua rubinetto >
        # lavaggio reattivo. La soglia è derivata dal range della specie.
        do_leaching = (
            not do_fertigation
            and not do_tap_water
            and needs_leaching_irrigation(pot)
        )

        # Costruzione dei parametri per apply_step
        fert_volume_l = 0.0
        fert_ec_mscm = 0.0
        fert_ph = 7.0

        event_symbols = []

        if do_fertigation:
            # BioBizz Bio-Grow al dosaggio raccomandato:
            # EC ~2.0 mS/cm, pH ~6.2, volume 0.3 L per vaso 2 L
            fert_volume_l = 0.3
            fert_ec_mscm = 2.0
            fert_ph = 6.2
            event_symbols.append("FERT")
        elif do_tap_water:
            # Acqua del rubinetto milanese: EC ~0.5 mS/cm, pH ~7.5
            fert_volume_l = 0.2
            fert_ec_mscm = 0.5
            fert_ph = 7.5
            event_symbols.append("TAP")
        elif do_leaching:
            # Lavaggio del giardiniere: acqua quasi pura, volume
            # abbondante per provocare drenaggio significativo che
            # porti via i sali in eccesso. EC=0.1 (quasi distillata,
            # da deumidificatore o filtrata), pH=7.0 (neutro), volume
            # 0.5 L che con vaso 2 L garantisce drenaggio.
            fert_volume_l = 0.5
            fert_ec_mscm = 0.1
            fert_ph = 7.0
            event_symbols.append("LEACH")
            leaching_events_count += 1

        if rain_mm > 0:
            event_symbols.append(f"RAIN({rain_mm:.1f}mm)")

        # Applica il passo completo del modello
        result = pot.apply_step(
            et_0_mm=et_0_mm,
            current_date=current_date,
            fertigation_volume_l=fert_volume_l,
            fertigation_ec_mscm=fert_ec_mscm,
            fertigation_ph=fert_ph,
            rainfall_volume_l=rain_volume_nominal_l,
        )

        # Aggiornamento accumulatori
        total_rainfall_nominal_mm += rain_mm
        if result.rainfall_result is not None:
            total_rainfall_intercepted_mm += result.rainfall_result.volume_intercepted_mm
        if result.fertigation_result is not None:
            total_salt_added_meq += result.fertigation_result.salt_mass_added_meq
            total_salt_drained_meq += result.fertigation_result.salt_mass_drained_meq
        if result.rainfall_result is not None:
            total_salt_drained_meq += result.rainfall_result.salt_mass_drained_meq

        # Calibrazione sensore (DOPO il passo del giorno)
        sensor_result = None
        if do_sensor_cal:
            reading = simulate_sensor_reading(pot, current_date, rng)
            sensor_result = pot.update_from_sensor(reading=reading)
            sensor_calibrations_count += 1
            if sensor_result.discrepancy_ec_mscm is not None:
                discrepancies_ec.append(sensor_result.discrepancy_ec_mscm)
            if sensor_result.discrepancy_ph is not None:
                discrepancies_ph.append(sensor_result.discrepancy_ph)
            event_symbols.append("SENS")

        # Calcolo del Kn corrente (post-eventi del giorno)
        kn = nutritional_factor(
            species=pot.species,
            ec_substrate_mscm=pot.ec_substrate_mscm,
            ph_substrate=pot.ph_substrate,
        )
        # Calcolo del Ks corrente. Ks è il fattore di stress IDRICO
        # (non chimico): vale 1 quando il vaso è ben idratato e scende
        # verso 0 mano a mano che il substrato si avvicina al PWP.
        # È completamente indipendente dal Kn (stress chimico): un
        # vaso può essere ben idratato (Ks=1) ma in stress chimico
        # (Kn<1), oppure asciutto ma con chimica ottimale, oppure
        # tutti e due, oppure nessuno.
        ks = stress_coefficient_ks(
            current_theta=pot.state_theta,
            substrate=pot.substrate,
        )

        # Stampa la riga del giorno
        print_day_row(
            day_idx=day_idx, current_date=current_date,
            et_0_mm=et_0_mm, pot=pot, kn=kn, ks=ks,
            event_symbols=event_symbols,
            sensor_result=sensor_result,
        )

    # ----- Sintesi finale -----
    print_summary(
        pot=pot,
        total_rainfall_nominal_mm=total_rainfall_nominal_mm,
        total_rainfall_intercepted_mm=total_rainfall_intercepted_mm,
        total_salt_added_meq=total_salt_added_meq,
        total_salt_drained_meq=total_salt_drained_meq,
        sensor_calibrations_count=sensor_calibrations_count,
        leaching_events_count=leaching_events_count,
        discrepancies_ec=discrepancies_ec,
        discrepancies_ph=discrepancies_ph,
    )


# =======================================================================
#  Funzioni di stampa
# =======================================================================

def print_header(pot: Pot):
    """Stampa l'header introduttivo dello script."""
    print("=" * 78)
    print("  fitosim — Demo tappa 3 fascia 2")
    print("  Simulazione di 30 giorni di basilico sul balcone milanese")
    print("=" * 78)
    print()
    print(f"Vaso:               {pot.label}")
    print(f"Specie:             {pot.species.common_name} "
          f"(EC ottimale {pot.species.ec_optimal_min_mscm:.1f}-"
          f"{pot.species.ec_optimal_max_mscm:.1f} mS/cm, "
          f"pH {pot.species.ph_optimal_min:.1f}-{pot.species.ph_optimal_max:.1f})")
    print(f"Substrato:          {pot.substrate.name} "
          f"(CEC {pot.substrate.cec_meq_per_100g:.0f} meq/100g, "
          f"pH naturale {pot.substrate.ph_typical:.1f})")
    print(f"Volume vaso:        {pot.pot_volume_l:.1f} L")
    print(f"Esposizione pioggia: {pot.rainfall_exposure:.1f} "
          f"(sotto balcone, intercetta il {(1-pot.rainfall_exposure)*100:.0f}%)")
    print(f"Stato iniziale:     θ={pot.state_theta:.3f}, "
          f"EC={pot.ec_substrate_mscm:.2f} mS/cm, "
          f"pH={pot.ph_substrate:.2f}")
    print()
    print(f"Periodo:            {SIMULATION_START} + {SIMULATION_DAYS} giorni")
    print(f"Calibrazioni:       settimanali (giorni 7, 14, 21, 28)")
    print(f"Fertirrigazioni:    settimanali (lunedì, BioBizz Bio-Grow)")
    print()
    print("-" * 78)
    print(f"{'Giorno':>6} {'Data':>11} {'ET0':>5} {'θ':>6} {'EC':>5} "
          f"{'pH':>4} {'Ks':>4} {'Kn':>4}  {'Eventi'}")
    print(f"{'':>6} {'':>11} {'(mm)':>5} {'':>6} {'mS/cm':>5} "
          f"{'':>4} {'idr.':>4} {'chim.':>4}")
    print("-" * 78)


def print_day_row(
    day_idx, current_date, et_0_mm, pot, kn, ks,
    event_symbols, sensor_result,
):
    """
    Stampa una riga compatta per il giorno con stato del modello e
    eventi.

    Marker di stress nelle colonne Ks e Kn:
      'k' = stress idrico (Ks < 0.95, vaso troppo asciutto)
      'n' = stress chimico (Kn < 0.95, EC o pH fuori range)
      ' ' (spazio) = nessuno stress

    Vedere entrambi i marker (kn) significa che il vaso è in entrambi
    gli stress simultaneamente — situazione critica.
    """
    events_str = " ".join(event_symbols) if event_symbols else "—"
    ks_marker = "k" if ks < 0.95 else " "
    kn_marker = "n" if kn < 0.95 else " "
    print(
        f"{day_idx+1:>6} {current_date.isoformat():>11} "
        f"{et_0_mm:>5.2f} "
        f"{pot.state_theta:>6.3f} "
        f"{pot.ec_substrate_mscm:>5.2f} "
        f"{pot.ph_substrate:>4.2f} "
        f"{ks:>4.2f}{ks_marker} "
        f"{kn:>4.2f}{kn_marker} "
        f"{events_str}"
    )


def print_summary(
    pot, total_rainfall_nominal_mm, total_rainfall_intercepted_mm,
    total_salt_added_meq, total_salt_drained_meq,
    sensor_calibrations_count, leaching_events_count,
    discrepancies_ec, discrepancies_ph,
):
    """Stampa la sintesi finale del periodo simulato."""
    print("-" * 78)
    print()
    print("=" * 78)
    print("  Sintesi del periodo")
    print("=" * 78)
    print()

    print("Bilancio idrico-pluviometrico")
    print(f"  Pioggia caduta sull'area aperta:  "
          f"{total_rainfall_nominal_mm:>6.1f} mm")
    print(f"  Pioggia intercettata da copertura: "
          f"{total_rainfall_intercepted_mm:>6.1f} mm "
          f"({total_rainfall_intercepted_mm/max(0.001,total_rainfall_nominal_mm)*100:.0f}%)")
    print(f"  Pioggia entrata nel vaso:          "
          f"{total_rainfall_nominal_mm-total_rainfall_intercepted_mm:>6.1f} mm")
    print()

    print("Eventi del giardiniere virtuale")
    print(f"  Bagnature di lavaggio reattive:    "
          f"{leaching_events_count:>3d} (scattate quando EC > "
          f"{pot.species.ec_optimal_max_mscm + 0.5:.1f} mS/cm)")
    print()

    print("Bilancio chimico")
    print(f"  Sali aggiunti (fertirrigazioni):    "
          f"{total_salt_added_meq:>6.2f} meq")
    print(f"  Sali drenati (lisciviazione):       "
          f"{total_salt_drained_meq:>6.2f} meq")
    net_salt_change = total_salt_added_meq - total_salt_drained_meq
    print(f"  Bilancio netto del periodo:         "
          f"{net_salt_change:>+6.2f} meq")
    print()

    print("Stato finale del vaso")
    print(f"  Umidità θ:    {pot.state_theta:.3f} "
          f"({pot.state_theta/pot.substrate.theta_fc*100:.0f}% di FC)")
    print(f"  EC:           {pot.ec_substrate_mscm:.2f} mS/cm "
          f"(range ottimale {pot.species.ec_optimal_min_mscm}-"
          f"{pot.species.ec_optimal_max_mscm})")
    print(f"  pH substrato: {pot.ph_substrate:.2f} "
          f"(range ottimale {pot.species.ph_optimal_min}-"
          f"{pot.species.ph_optimal_max})")
    print()

    if discrepancies_ec:
        avg_disc_ec = sum(discrepancies_ec) / len(discrepancies_ec)
        avg_disc_ph = sum(discrepancies_ph) / len(discrepancies_ph)
        print("Discrepanze sensore-modello")
        print(f"  Calibrazioni effettuate: {sensor_calibrations_count}")
        print(f"  Discrepanza media EC:   "
              f"{avg_disc_ec:>+5.3f} mS/cm "
              f"(modello {'sottostima' if avg_disc_ec > 0 else 'sovrastima'} "
              f"l'EC reale)")
        print(f"  Discrepanza media pH:   "
              f"{avg_disc_ph:>+5.3f} unità "
              f"(modello {'sottostima' if avg_disc_ph > 0 else 'sovrastima'} "
              f"il pH reale)")
        print()

    print("Note interpretative")
    print("  I due marker di stress nelle colonne Ks e Kn distinguono")
    print("  fenomeni fisiologici diversi:")
    print()
    print("    'k' su Ks = STRESS IDRICO. Il vaso si sta avvicinando")
    print("                al PWP, la pianta fatica a estrarre acqua")
    print("                per l'aumento del potenziale matriciale.")
    print("                Si risolve con un'irrigazione (di qualunque")
    print("                tipo: acqua pura, fertirrigazione, pioggia).")
    print()
    print("    'n' su Kn = STRESS CHIMICO. EC fuori range (effetto")
    print("                osmotico inverso) o pH fuori range")
    print("                (carenze nutrizionali). Si risolve con un")
    print("                LAVAGGIO con acqua pura per ridurre i sali,")
    print("                non con fertirrigazione che peggiorerebbe.")
    print()
    print("  Vedere entrambi i marker (kn) significa che il vaso è")
    print("  in entrambi gli stress contemporaneamente — situazione")
    print("  critica che richiede intervento immediato.")
    print()
    print("  In questo esempio il giardiniere virtuale interviene")
    print("  automaticamente con bagnature di lavaggio quando l'EC")
    print(f"  supera la soglia di {pot.species.ec_optimal_max_mscm + 0.5:.1f} mS/cm. "
          "Nell'output noterai")
    print("  che il marker 'n' di stress chimico si attiva e disattiva")
    print("  in base al bilancio tra fertirrigazioni (che alzano EC)")
    print("  e lavaggi/piogge (che la abbassano).")
    print()
    print("  La discrepanza media tra sensore e modello è il segnale")
    print("  primario per la calibrazione dei parametri del modello.")
    print("  Una discrepanza sistematica (sempre dello stesso segno)")
    print("  indica un bias del modello da correggere; una discrepanza")
    print("  che oscilla intorno allo zero indica solo rumore di misura.")
    print()


if __name__ == "__main__":
    run_simulation()
