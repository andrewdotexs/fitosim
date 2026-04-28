"""
Bilancio chimico del substrato per un singolo evento idrico.

Il modulo implementa la chimica del substrato per la sotto-tappa C
della tappa 3 della fascia 2: cosa succede al substrato di un vaso
quando vi entra un volume di soluzione (fertirrigazione, pioggia
naturale, acqua del rubinetto) caratterizzato da una propria
conducibilità elettrica e da un proprio pH. Il risultato è una
nuova massa salina nel vaso, un nuovo pH del substrato, e un volume
eventualmente drenato dal foro del fondo che si porta con sé una
parte dei sali.

Cosa NON fa questo modulo
-------------------------

Questo modulo NON gestisce il bilancio idrico del vaso (per quello
c'è `science/balance.py`). NON gestisce il modello fenologico, il
dual-Kc, il sottovaso. È un blocco a sé stante che si occupa
esclusivamente della chimica del substrato di fronte a un singolo
evento di input idrico: data la situazione "prima" e le caratte-
ristiche del volume entrante, calcola la situazione "dopo".

L'orchestrazione tra bilancio idrico e bilancio chimico vive nel
metodo `Pot.apply_step` (sotto-tappa C punto 3) che chiama in
sequenza le due funzioni nel giusto ordine e gestisce gli effetti
incrociati (es. il drenaggio idrico è anche drenaggio salino, il che
richiede coerenza tra le due chiamate).

I tre passi fisici di un evento idrico
--------------------------------------

Quando il giardiniere versa una soluzione (di qualunque tipo: acqua
pura, fertirrigazione, pioggia) sul vaso, succedono in sequenza:

  1. **Mescolamento istantaneo**: la soluzione in arrivo si mescola
     con la soluzione interstiziale già presente. La massa salina
     totale è la somma delle due (conservazione), il volume totale
     è la somma dei due, l'EC della miscela è la media pesata sui
     volumi, e il pH segue una media pesata modulata dalla CEC del
     substrato (vedi `ph_after_mixing` qui sotto per la formula
     esatta).

  2. **Eventuale drenaggio dell'eccesso**: se il volume totale
     dopo mescolamento eccede la capacità di campo del vaso,
     l'eccesso fuoriesce dal foro inferiore portando con sé una
     frazione di sali proporzionale al volume drenato sul totale.
     È il meccanismo principale di "lavaggio" del substrato.

  3. **Aggiornamento dello stato chimico finale**: il vaso resta
     con un volume di acqua pari alla capacità di campo (se c'è
     stato drenaggio) o pari al volume post-mescolamento (se non
     c'è stato), e con la massa salina ridotta dalla quota uscita
     col drenaggio.

Il **terzo passo non viene fatto da questo modulo**: lui calcola
solo le quantità (massa salina finale, drenaggio, nuovo pH) e
restituisce. È compito del chiamante (cioè del `Pot`) applicare
queste quantità ai propri stati.

Filosofia delle unità
---------------------

Tutto il modulo lavora in unità SI naturali per la chimica del
suolo:

  - volumi in litri (L)
  - masse saline in milli-equivalenti (meq)
  - EC in milliSiemens per cm a 25°C (mS/cm)
  - pH adimensionale, scala 0-14
  - CEC in milli-equivalenti per 100 g (meq/100g)
  - massa secca del substrato in chilogrammi (kg)

La conversione canonica EC ↔ concentrazione di milli-equivalenti per
litro è il fattore 10: una soluzione a 1 mS/cm contiene circa 10
meq/L di sali totali, valida per soluzioni "tipiche" di terreno con
cationi misti dominanti (calcio, magnesio, potassio).
"""

from __future__ import annotations

from dataclasses import dataclass


# Costante di conversione tra concentrazione molare equivalente e
# conducibilità elettrica. Documentata anche in pot.py dove viene
# usata nel calcolo della property ec_substrate_mscm.
EC_TO_MEQ_PER_LITER = 10.0


# Densità tipica dei terricci da giardinaggio domestico, in kg/L.
# I terricci sono parecchio più leggeri della terra agricola "vera"
# per via dell'alta percentuale di torba e materia organica. Usiamo
# 0.4 come valore di riferimento per il calcolo della massa secca
# del substrato a partire dal volume del vaso, che entra come peso
# del substrato nella formula del buffering del pH.
TYPICAL_SUBSTRATE_DENSITY_KG_PER_L = 0.4


# Costante di calibrazione del peso della soluzione entrante nel
# calcolo del buffering del pH. È stata scelta in modo che con CEC
# "tipica" (50 meq/100g) e con un evento idrico di volume confrontabile
# col volume di acqua già presente, il pH finale risulti a circa metà
# strada tra il pH iniziale e quello in arrivo, comportamento
# intuitivo per il giardiniere. Dettagli nel commento di
# `ph_after_mixing`.
PH_INPUT_WEIGHT_CALIBRATION = 10.0


# pH della pioggia naturale "letterario", che corrisponde all'equilibrio
# dell'acqua pura con la CO₂ atmosferica. La pioggia urbana milanese
# può essere leggermente più acida (5.0-5.5) per via degli ossidi di
# azoto del traffico, ma 5.6 è il valore convenzionale dei manuali di
# chimica del suolo.
RAINFALL_PH = 5.6


# EC della pioggia naturale: praticamente nulla, l'acqua piovana è
# essenzialmente acqua distillata dal punto di vista del bilancio
# salino. Usiamo 0.0 esatto per coerenza, anche se in realtà c'è
# qualche ppm di sali da spray marino o aerosol.
RAINFALL_EC_MSCM = 0.0


# =======================================================================
#  Risultato di un passo di bilancio chimico
# =======================================================================

@dataclass(frozen=True)
class FertigationStepResult:
    """
    Esito di un passo di bilancio chimico per un singolo evento idrico.

    Parallelo concettuale al `BalanceStepResult` di balance.py: contiene
    tutti i dati prodotti dal calcolo della chimica, in modo che il
    chiamante possa fare logging, detezione di anomalie, allerte, e
    naturalmente aggiornare lo stato del vaso.

    Attributi
    ---------
    salt_mass_after_meq : float
        Massa salina totale finale del substrato dopo l'evento, in
        milli-equivalenti. È la somma della massa iniziale + sali
        entranti, meno i sali drenati. Sempre non-negativa.
    salt_mass_drained_meq : float
        Massa salina che è uscita dal vaso col drenaggio, in
        milli-equivalenti. Zero se il volume totale post-mescolamento
        non eccedeva la capacità di campo. Sempre non-negativa.
    salt_mass_added_meq : float
        Massa salina entrata nel vaso con la soluzione, in
        milli-equivalenti. Calcolata come `EC_in × V_in × 10`. Zero
        per la pioggia naturale. Sempre non-negativa.
    water_drained_l : float
        Volume di acqua drenata, in litri. Zero se l'evento non ha
        fatto eccedere la capacità di campo. Coincide con la quantità
        che `science/balance.py` chiamerebbe `drainage`. È riportato
        qui per comodità del chiamante.
    ph_after : float
        pH del substrato dopo il mescolamento, scala 0-14. Calcolato
        secondo la formula del buffering modulato da CEC.
    ph_delta : float
        Variazione di pH (= ph_after - ph_before), con segno. Positivo
        se la fertirrigazione ha alzato il pH, negativo se l'ha
        abbassato. Utile per il logging e per allerte tipo "il pH ha
        avuto un salto sospetto".
    """

    salt_mass_after_meq: float
    salt_mass_drained_meq: float
    salt_mass_added_meq: float
    water_drained_l: float
    ph_after: float
    ph_delta: float


# =======================================================================
#  Funzione 1: bilancio della massa salina
# =======================================================================

def salt_balance_step(
    *,
    salt_mass_before_meq: float,
    water_volume_before_l: float,
    water_input_l: float,
    ec_input_mscm: float,
    fc_water_volume_l: float,
) -> tuple[float, float, float, float]:
    """
    Calcola il bilancio della massa salina per un singolo evento
    idrico, applicando in sequenza mescolamento e drenaggio.

    Il modello in formule
    ---------------------

    Definizioni preliminari::

        V_before = water_volume_before_l           [L, acqua già presente]
        V_in     = water_input_l                   [L, acqua in arrivo]
        EC_in    = ec_input_mscm                   [mS/cm]
        S_before = salt_mass_before_meq            [meq, sali già presenti]
        V_fc     = fc_water_volume_l               [L, capacità di campo]

    Passo 1: massa salina entrante::

        S_added = EC_in × V_in × 10

        (la conversione EC → meq/L è il fattore 10; vedi costante
         EC_TO_MEQ_PER_LITER. Questa è una semplificazione valida per
         soluzioni "tipiche" di terreno con cationi misti.)

    Passo 2: situazione dopo il mescolamento istantaneo (prima del
    drenaggio)::

        V_after_mixing = V_before + V_in
        S_after_mixing = S_before + S_added

    Passo 3: drenaggio dell'eccesso oltre la capacità di campo::

        V_drained = max(0, V_after_mixing - V_fc)

        S_drained = S_after_mixing × (V_drained / V_after_mixing)

        (il drenaggio rimuove sali in proporzione al volume drenato
         rispetto al volume totale momentaneo, cioè con la concentrazione
         istantanea della soluzione mescolata.)

    Passo 4: stato finale del vaso::

        S_final = S_after_mixing - S_drained
        V_final = min(V_after_mixing, V_fc)
                = V_after_mixing - V_drained

    Conseguenza importante per il giardiniere
    -----------------------------------------

    Il drenaggio è l'unico meccanismo di rimozione dei sali dal vaso
    in questo modello (trascuriamo l'assorbimento radicale). Quindi
    una bagnatura abbondante che produce drenaggio del 30-50% rimuove
    la stessa frazione dei sali totali, "resettando" parzialmente il
    substrato. Questo è il meccanismo agronomico canonico per la
    "lisciviazione" dei substrati che hanno accumulato troppi sali.

    Parametri
    ---------
    salt_mass_before_meq : float
        Massa salina presente nel vaso prima dell'evento, in
        milli-equivalenti. Non-negativa.
    water_volume_before_l : float
        Volume di acqua già presente nel substrato prima dell'evento,
        in litri. Non-negativo.
    water_input_l : float
        Volume di soluzione in arrivo, in litri. Non-negativo.
    ec_input_mscm : float
        Conducibilità elettrica della soluzione in arrivo, in mS/cm
        a 25°C. Non-negativa. Zero per pioggia naturale o acqua
        distillata.
    fc_water_volume_l : float
        Volume di acqua corrispondente alla capacità di campo del
        vaso, in litri. Strettamente positivo. Sopra questo valore
        l'acqua eccedente drena.

    Ritorna
    -------
    tuple di quattro float (S_final, S_drained, S_added, V_drained):
        - S_final: massa salina finale del vaso, in meq.
        - S_drained: massa salina uscita col drenaggio, in meq.
        - S_added: massa salina entrata con la soluzione, in meq.
        - V_drained: volume di acqua drenato, in litri.

    Solleva
    -------
    ValueError
        Se uno qualsiasi dei parametri ha valore fisicamente impossibile
        (negativi, fc zero o negativo).

    Esempi
    --------
    Vaso con 1 L di acqua a EC moderata, capacità di campo 1.5 L.
    Arriva 1 L di fertilizzante a EC 2 mS/cm. Niente drenaggio
    perché 1+1=2 supera 1.5: drena 0.5 L portando con sé un terzo
    dei sali totali momentanei::

        >>> S_final, S_drained, S_added, V_drained = salt_balance_step(
        ...     salt_mass_before_meq=10.0,    # 10 meq → EC 1.0 in 1L
        ...     water_volume_before_l=1.0,
        ...     water_input_l=1.0,
        ...     ec_input_mscm=2.0,            # → 20 meq entranti
        ...     fc_water_volume_l=1.5,
        ... )
        >>> # 30 meq totali post-mescolamento in 2 L
        >>> # 0.5 L drenati = 25% del totale → 7.5 meq drenati
        >>> # 22.5 meq finali in 1.5 L (=15 meq/L = EC 1.5)
        >>> assert abs(S_final - 22.5) < 1e-9
    """
    # Validazione dei parametri di input. Errori qui sono di
    # programmazione, non di runtime: il chiamante ha sbagliato a
    # passare un valore impossibile.
    if salt_mass_before_meq < 0:
        raise ValueError(
            f"salt_mass_before_meq deve essere non-negativa "
            f"(ricevuto {salt_mass_before_meq})."
        )
    if water_volume_before_l < 0:
        raise ValueError(
            f"water_volume_before_l deve essere non-negativo "
            f"(ricevuto {water_volume_before_l})."
        )
    if water_input_l < 0:
        raise ValueError(
            f"water_input_l deve essere non-negativo "
            f"(ricevuto {water_input_l})."
        )
    if ec_input_mscm < 0:
        raise ValueError(
            f"ec_input_mscm deve essere non-negativa "
            f"(ricevuto {ec_input_mscm})."
        )
    if fc_water_volume_l <= 0:
        raise ValueError(
            f"fc_water_volume_l deve essere strettamente positivo "
            f"(ricevuto {fc_water_volume_l}). Senza capacità di "
            f"campo non c'è soglia di drenaggio."
        )

    # Passo 1: massa salina entrante con la soluzione.
    salt_added = ec_input_mscm * water_input_l * EC_TO_MEQ_PER_LITER

    # Passo 2: situazione dopo il mescolamento.
    water_after_mixing = water_volume_before_l + water_input_l
    salt_after_mixing = salt_mass_before_meq + salt_added

    # Passo 3: drenaggio dell'eccesso. Il caso `water_after_mixing == 0`
    # (entrambi vuoti, che capita se il chiamante chiama la funzione
    # con tutti zero per qualche test patologico) lo gestiamo
    # esplicitamente per evitare ZeroDivisionError.
    if water_after_mixing > 0 and water_after_mixing > fc_water_volume_l:
        water_drained = water_after_mixing - fc_water_volume_l
        # Frazione del totale che esce col drenaggio. Sicuramente in
        # (0, 1] perché water_drained < water_after_mixing per costruzione.
        drainage_fraction = water_drained / water_after_mixing
        salt_drained = salt_after_mixing * drainage_fraction
    else:
        water_drained = 0.0
        salt_drained = 0.0

    # Passo 4: stato finale.
    salt_final = salt_after_mixing - salt_drained

    return salt_final, salt_drained, salt_added, water_drained


# =======================================================================
#  Funzione 2: bilancio del pH del substrato
# =======================================================================

def ph_after_mixing(
    *,
    ph_before: float,
    ph_input: float,
    water_input_l: float,
    cec_meq_per_100g: float,
    substrate_dry_mass_kg: float,
) -> float:
    """
    Calcola il pH del substrato dopo un singolo evento di mescolamento
    con una soluzione in arrivo, secondo la formula della media pesata
    modulata dalla CEC.

    Il modello in formule
    ---------------------

    Il pH del substrato dopo il mescolamento è una **media pesata**
    tra il pH iniziale del substrato e il pH della soluzione in
    arrivo, dove i pesi rappresentano la "capacità di influenza" di
    ciascuna delle due:

        pH_after  =  (W_substrate × pH_before  +  W_input × pH_input)
                     ─────────────────────────────────────────────
                                W_substrate + W_input

    I due pesi sono::

        W_substrate = CEC_meq_per_100g × substrate_dry_mass_kg

        W_input     = water_input_l × PH_INPUT_WEIGHT_CALIBRATION

    Significato fisico
    ------------------

    Il peso del substrato è proporzionale a **quanti meq di siti di
    scambio cationico ci sono nel vaso**: la CEC di laboratorio è
    espressa per unità di massa secca, quindi moltiplicandola per la
    massa di substrato nel vaso si ottiene la "capacità di buffering"
    totale. Più CEC ha il substrato e più è massiccio, più resiste
    alle variazioni di pH.

    Il peso della soluzione è proporzionale al volume entrante,
    moltiplicato per una costante di calibrazione `PH_INPUT_WEIGHT_CALIBRATION`
    che è stata scelta in modo che con CEC "tipica" (50 meq/100g) e
    un volume entrante confrontabile col volume di acqua già presente,
    il pH finale sia a circa metà strada tra i due — comportamento
    intuitivo per il giardiniere.

    Conseguenze qualitative
    -----------------------

    Substrato con CEC alta (torba acida, 100-150 meq/100g):
        Il peso del substrato è ~3 volte quello di un substrato
        tipico, quindi la fertirrigazione sposta il pH solo di poco.
        L'azalea pianta in torba acida resta intorno al suo pH 5
        anche se il giardiniere innaffia con acqua del rubinetto a
        pH 7.5: vedrebbe forse uno spostamento di 0.2-0.3 unità per
        evento, da assorbire nei giorni successivi.

    Substrato con CEC bassa (sabbia, lapillo, 5-15 meq/100g):
        Il peso del substrato è basso, la soluzione entrante domina.
        Il pH finale tende a quello in arrivo, e ogni fertirrigazione
        "scrive sopra" il pH precedente. È la ragione per cui le
        coltivazioni in idroponica su substrati inerti richiedono
        controllo più stretto del pH della soluzione nutritiva.

    Parametri
    ---------
    ph_before : float
        pH del substrato prima dell'evento, scala 0-14.
    ph_input : float
        pH della soluzione in arrivo, scala 0-14.
    water_input_l : float
        Volume di soluzione in arrivo, in litri. Non-negativo.
        Se zero, il pH finale coincide con quello iniziale.
    cec_meq_per_100g : float
        Capacità di scambio cationico del substrato, in meq/100g.
        Strettamente positiva.
    substrate_dry_mass_kg : float
        Massa secca del substrato nel vaso, in kg. Strettamente
        positiva. Tipicamente calcolata come `volume_vaso_L × densità`
        dove la densità di un terriccio tipico è circa 0.4 kg/L
        (vedi TYPICAL_SUBSTRATE_DENSITY_KG_PER_L).

    Ritorna
    -------
    float
        pH del substrato dopo il mescolamento, scala 0-14.

    Solleva
    -------
    ValueError
        Per parametri fisicamente impossibili.

    Esempi
    --------
    Vaso da 2 L di basilico in terriccio universale (CEC 50, massa
    0.8 kg). Innaffiatura da 1 L di acqua del rubinetto a pH 7.5,
    pH attuale del substrato 6.5::

        >>> ph_new = ph_after_mixing(
        ...     ph_before=6.5,
        ...     ph_input=7.5,
        ...     water_input_l=1.0,
        ...     cec_meq_per_100g=50.0,
        ...     substrate_dry_mass_kg=0.8,
        ... )
        >>> # peso_substrato = 50 * 0.8 = 40
        >>> # peso_soluzione = 1.0 * 10 = 10
        >>> # pH_after = (40*6.5 + 10*7.5) / 50 = 6.7
        >>> assert abs(ph_new - 6.7) < 1e-9

    Stesso vaso ma su substrato per acidofile (CEC 140 meq/100g):
    la fertirrigazione sposta il pH molto meno::

        >>> ph_new = ph_after_mixing(
        ...     ph_before=5.0,
        ...     ph_input=7.5,
        ...     water_input_l=1.0,
        ...     cec_meq_per_100g=140.0,
        ...     substrate_dry_mass_kg=0.8,
        ... )
        >>> # peso_substrato = 140 * 0.8 = 112
        >>> # peso_soluzione = 1.0 * 10 = 10
        >>> # pH_after = (112*5.0 + 10*7.5) / 122 ≈ 5.20
        >>> # solo 0.20 unità di spostamento
        >>> assert abs(ph_new - 5.205) < 0.01
    """
    # Validazione dei parametri.
    if not 0.0 < ph_before <= 14.0:
        raise ValueError(
            f"ph_before deve essere in (0, 14] "
            f"(ricevuto {ph_before})."
        )
    if not 0.0 < ph_input <= 14.0:
        raise ValueError(
            f"ph_input deve essere in (0, 14] "
            f"(ricevuto {ph_input})."
        )
    if water_input_l < 0:
        raise ValueError(
            f"water_input_l deve essere non-negativo "
            f"(ricevuto {water_input_l})."
        )
    if cec_meq_per_100g <= 0:
        raise ValueError(
            f"cec_meq_per_100g deve essere strettamente positiva "
            f"(ricevuto {cec_meq_per_100g})."
        )
    if substrate_dry_mass_kg <= 0:
        raise ValueError(
            f"substrate_dry_mass_kg deve essere strettamente positiva "
            f"(ricevuto {substrate_dry_mass_kg})."
        )

    # Caso degenere: nessuna soluzione in arrivo → pH invariato.
    # Lo gestiamo esplicitamente perché la formula generale
    # produrrebbe ph_before × peso_substrato / peso_substrato che è
    # comunque ph_before, ma è più chiaro essere espliciti.
    if water_input_l == 0:
        return ph_before

    # Calcolo dei due pesi secondo la formula documentata.
    weight_substrate = cec_meq_per_100g * substrate_dry_mass_kg
    weight_input = water_input_l * PH_INPUT_WEIGHT_CALIBRATION

    # Media pesata.
    total_weight = weight_substrate + weight_input
    ph_after = (
        weight_substrate * ph_before + weight_input * ph_input
    ) / total_weight

    return ph_after


# =======================================================================
#  Funzione orchestratrice: bilancio chimico completo
# =======================================================================

def fertigation_step(
    *,
    salt_mass_before_meq: float,
    ph_before: float,
    water_volume_before_l: float,
    water_input_l: float,
    ec_input_mscm: float,
    ph_input: float,
    fc_water_volume_l: float,
    cec_meq_per_100g: float,
    substrate_dry_mass_kg: float,
) -> FertigationStepResult:
    """
    Calcolo completo del bilancio chimico per un evento idrico,
    chiamando in sequenza salt_balance_step e ph_after_mixing.

    Questa è la funzione "facade" che il `Pot` usa per orchestrare il
    bilancio chimico completo. Restituisce un `FertigationStepResult`
    con tutti i dati prodotti, in modo che il chiamante possa fare
    logging, allerte, e applicare lo stato finale al vaso.

    Cosa fa
    -------

    Esegue in sequenza:

      1. Calcola il bilancio salino con `salt_balance_step`, ottenendo
         massa finale, drenaggio salino, sali aggiunti, acqua drenata.

      2. Calcola il nuovo pH con `ph_after_mixing`. Importante: il
         calcolo del pH usa il **volume di soluzione entrante**, non
         il volume residuo dopo il drenaggio. Questo perché il
         mescolamento avviene PRIMA del drenaggio: la soluzione si
         mescola integralmente col substrato, e solo dopo l'eccesso
         drena. La parte drenata si porta via la sua quota di sali
         ma il pH del substrato è già stato influenzato dal
         mescolamento integrale.

      3. Costruisce e ritorna il FertigationStepResult.

    Parametri
    ---------
    Vedi documentazione di salt_balance_step e ph_after_mixing per
    il significato di ogni parametro. Sono tutti gli input richiesti
    dalle due funzioni sottostanti, riuniti qui in un'unica firma.

    Ritorna
    -------
    FertigationStepResult
        Tutti i dati prodotti dal calcolo chimico.
    """
    # Bilancio salino: applica mescolamento + drenaggio.
    salt_final, salt_drained, salt_added, water_drained = salt_balance_step(
        salt_mass_before_meq=salt_mass_before_meq,
        water_volume_before_l=water_volume_before_l,
        water_input_l=water_input_l,
        ec_input_mscm=ec_input_mscm,
        fc_water_volume_l=fc_water_volume_l,
    )

    # Bilancio del pH: usa il volume entrante completo (vedi docstring).
    ph_after = ph_after_mixing(
        ph_before=ph_before,
        ph_input=ph_input,
        water_input_l=water_input_l,
        cec_meq_per_100g=cec_meq_per_100g,
        substrate_dry_mass_kg=substrate_dry_mass_kg,
    )

    return FertigationStepResult(
        salt_mass_after_meq=salt_final,
        salt_mass_drained_meq=salt_drained,
        salt_mass_added_meq=salt_added,
        water_drained_l=water_drained,
        ph_after=ph_after,
        ph_delta=ph_after - ph_before,
    )
