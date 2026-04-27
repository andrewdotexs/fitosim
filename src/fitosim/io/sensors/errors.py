"""
Gerarchia delle eccezioni per il livello sensori di fitosim.

Questo modulo definisce le eccezioni che gli adapter dei sensori
sollevano in caso di problemi. La struttura a tre livelli (transitorio /
permanente / qualità del dato) permette al chiamante di scegliere la
politica di fallback appropriata senza dover catturare ogni dettaglio
specifico del provider.

Filosofia
---------

Tutti gli adapter — Open-Meteo, Ecowitt, ATO 7-in-1, e qualsiasi
sensore custom futuro — sollevano eccezioni di queste tre categorie,
mai eccezioni native del provider sottostante. Questo isolamento
garantisce che il codice utente possa gestire gli errori in modo
uniforme: se domani sostituisci una sorgente con un'altra, la logica di
gestione errori resta invariata.

L'idea di base è che ci sono *tre situazioni qualitativamente diverse*
in cui un sensore può "non rispondere come previsto", e queste tre
situazioni richiedono politiche di reazione diverse:

  1. **Errore transitorio**: la rete è momentaneamente giù, il server
     ha avuto un picco di carico, la batteria è temporaneamente bassa.
     La cosa giusta da fare è ritentare più tardi, oppure usare l'ultima
     lettura cache come fallback. Il sensore in sé sta bene.

  2. **Errore permanente**: le credenziali sono sbagliate, il sensore è
     guasto fisicamente, la calibrazione è andata persa. Ritentare non
     serve a niente; serve un intervento esterno (correggere la config,
     sostituire l'hardware, ricalibrare). Il chiamante deve avvisare il
     giardiniere.

  3. **Qualità del dato compromessa**: il sensore *ha risposto*, ma il
     numero che ha dato è palesemente non plausibile (θ negativo, pH
     fuori dal range 0-14, EC con valori assurdi). I dati esistono ma
     sono inaffidabili. Tipicamente serve ricalibrare o sostituire il
     sensore, ma in modo meno urgente di un guasto.
"""

from __future__ import annotations


class SensorError(Exception):
    """
    Classe base per tutti gli errori sollevati dagli adapter dei sensori.

    Il chiamante che vuole gestire genericamente "qualcosa è andato
    storto col sensore" cattura questa classe; chi vuole differenziare
    le politiche di reazione cattura le sottoclassi specifiche.

    Parametri
    ---------
    message : str
        Messaggio descrittivo dell'errore, leggibile dall'utente.
    provider : str | None
        Nome del provider che ha originato l'errore (es. "ecowitt",
        "openmeteo"). Utile per log strutturati e diagnostica.
    """

    def __init__(self, message: str, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class SensorTemporaryError(SensorError):
    """
    Errore transitorio: ritentare più tardi può risolvere.

    Esempi tipici:
      - Timeout di rete sull'API cloud del provider.
      - Server del provider che restituisce 5xx o è temporaneamente
        irraggiungibile.
      - Sensore wireless che ha mancato il check-in di questa ora ma
        riapparirà alla prossima.
      - Rate limiting del provider (429 Too Many Requests).

    Politica di fallback raccomandata: usare l'ultima lettura disponibile
    in cache se non troppo vecchia (tipicamente <24 ore per dati
    ambientali, <4 ore per sensori del suolo); ritentare alla prossima
    iterazione del loop di update.
    """


class SensorPermanentError(SensorError):
    """
    Errore permanente: ritentare non serve, occorre intervento.

    Esempi tipici:
      - Credenziali API errate o scadute.
      - Sensore fisicamente guasto (batteria a zero, hardware rotto).
      - Configurazione del sensore corrotta lato provider (canale
        scollegato dalla base station).
      - URL del provider deprecato che non esiste più.

    Politica di fallback raccomandata: avvisare il giardiniere con un
    messaggio esplicito che indica il problema e l'azione necessaria
    (controlla credenziali, sostituisci batteria, etc.). Sospendere
    l'uso del sensore dal ciclo di update finché il problema non è
    risolto manualmente.
    """


class SensorDataQualityError(SensorError):
    """
    Errore di qualità del dato: il sensore ha risposto ma il valore non è plausibile.

    Esempi tipici:
      - θ < 0 o > 1 (impossibile fisicamente, indica drift).
      - pH fuori dal range 0-14 (sensore scalibrato).
      - EC negativa (corruzione del segnale).
      - Temperatura del substrato di -50 °C o +200 °C (sonda staccata).

    Distinto dagli errori di comunicazione perché richiede una politica
    diversa: i dati arrivano ma sono inaffidabili. Tipicamente è il
    segnale che il sensore va ricalibrato (per il pH), o sostituito
    se il problema è ricorrente.

    Politica di fallback raccomandata: scartare la lettura corrente,
    usare l'ultima cache valida, alertare il giardiniere che la
    calibrazione del sensore è da verificare. È meno urgente di un
    SensorPermanentError ma comunque richiede attenzione.
    """
