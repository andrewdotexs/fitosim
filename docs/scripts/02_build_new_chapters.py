"""
Genera il blocco XML dei due nuovi capitoli del manuale per la tappa 5:
  Cap. 17 — Il selettore di evapotraspirazione "best available"
  Cap. 18 — Vasi indoor: Room, microclima e sensore WN31

Lo stile segue il pattern del manuale esistente: Titolo1 con pageBreakBefore
per i capitoli, Titolo2 per le sotto-sezioni, paragrafi normali con
spacing after=160, blocchi di codice con Courier New 20pt e ind left=360.
"""

# Helper per produrre paragrafi formattati. Usiamo solo entity HTML per
# le smart quotes per essere coerenti con quanto fatto da unpack.

def escape(text: str) -> str:
    """Encode <, >, & e converte smart quotes in entity HTML."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = (text
            .replace("\u2019", "&#x2019;")  # right single
            .replace("\u2018", "&#x2018;")  # left single
            .replace("\u201C", "&#x201C;")  # left double
            .replace("\u201D", "&#x201D;")  # right double
            .replace("\u00E0", "&#xE0;")    # à
            .replace("\u00E8", "&#xE8;")    # è
            .replace("\u00E9", "&#xE9;")    # é
            .replace("\u00EC", "&#xEC;")    # ì
            .replace("\u00F2", "&#xF2;")    # ò
            .replace("\u00F9", "&#xF9;")    # ù
            .replace("\u00B0", "&#xB0;")    # °
            .replace("\u00B2", "&#xB2;")    # ²
            .replace("\u00B3", "&#xB3;")    # ³
            .replace("\u2080", "&#x2080;")  # ₀ subscript
            .replace("\u2192", "&#x2192;")  # →
            .replace("\u00D7", "&#xD7;")    # ×
            .replace("\u2014", "&#x2014;")  # —
            )
    return text


def h1(text: str) -> str:
    """Heading 1 con pageBreakBefore (inizio capitolo)."""
    return f"""    <w:p>
      <w:pPr>
        <w:pStyle w:val="Titolo1"/>
        <w:pageBreakBefore/>
      </w:pPr>
      <w:r>
        <w:lastRenderedPageBreak/>
        <w:t>{escape(text)}</w:t>
      </w:r>
    </w:p>
"""


def h2(text: str) -> str:
    """Heading 2."""
    return f"""    <w:p>
      <w:pPr>
        <w:pStyle w:val="Titolo2"/>
      </w:pPr>
      <w:r>
        <w:t>{escape(text)}</w:t>
      </w:r>
    </w:p>
"""


def p(text: str) -> str:
    """Paragrafo normale con spacing after=160 (stile del manuale)."""
    return f"""    <w:p>
      <w:pPr>
        <w:spacing w:after="160"/>
      </w:pPr>
      <w:r>
        <w:t xml:space="preserve">{escape(text)}</w:t>
      </w:r>
    </w:p>
"""


def code(text: str) -> str:
    """Blocco di codice indentato con font Courier New 20pt."""
    return f"""    <w:p>
      <w:pPr>
        <w:spacing w:after="40"/>
        <w:ind w:left="360"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:rFonts w:ascii="Courier New" w:eastAsia="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>
          <w:sz w:val="20"/>
          <w:szCs w:val="20"/>
        </w:rPr>
        <w:t xml:space="preserve">{escape(text)}</w:t>
      </w:r>
    </w:p>
"""


# =====================================================================
#  CAPITOLO 17 — Il selettore di evapotraspirazione "best available"
# =====================================================================

xml_parts = []
xml_parts.append(h1('17 — Il selettore di evapotraspirazione "best available"'))

xml_parts.append(p(
    "Fino al capitolo 16 fitosim ha usato un solo modo di calcolare "
    "l'evapotraspirazione di riferimento ET₀: la formula di Hargreaves-Samani, "
    "scelta perché richiede solo la temperatura minima e massima della giornata "
    "ed è quindi sempre applicabile anche con dati meteo minimi. Hargreaves è "
    "robusto ma può sbagliare del 10-20% rispetto al \"gold standard\" della "
    "FAO che è Penman-Monteith, una formula fisica che combina temperatura, "
    "umidità relativa, velocità del vento e radiazione solare in un'equazione "
    "rigorosa. La tappa 5 della fascia 2 ha introdotto Penman-Monteith e un "
    "selettore automatico che sceglie tra le formule disponibili in funzione "
    "dei dati meteo che hai e dei parametri della specie che stai modellando."
))

xml_parts.append(p(
    "Questo capitolo ti spiega come usare il selettore in pratica e quali "
    "decisioni prende internamente. Non entra nei dettagli matematici delle "
    "formule (per quelli vedi la pubblicazione FAO-56 nel repository, in "
    "docs/FAO-56.pdf): il taglio è operativo, mostra come passare dal modello "
    "Hargreaves-only del capitolo 8 al modello \"best available\" della tappa 5 "
    "senza dover capire l'equazione fisica nel dettaglio."
))

xml_parts.append(h2('Le tre formule e quando si applicano'))

xml_parts.append(p(
    "Il selettore può scegliere tra tre formule, in ordine di preferenza:"
))

xml_parts.append(p(
    "Penman-Monteith fisico (PENMAN_MONTEITH_PHYSICAL nell'enum EtMethod) è la "
    "scelta migliore quando disponibile. Applica direttamente l'equazione di "
    "Penman-Monteith alla specie usando la sua resistenza stomatica e altezza "
    "colturale, e produce direttamente l'evapotraspirazione effettiva ET della "
    "specie (NON ET₀ di riferimento). Il chiamante che riceve un risultato "
    "PENMAN_MONTEITH_PHYSICAL non deve moltiplicare per il Kc: il risultato è "
    "già specifico per la pianta. Richiede tutti i dati meteo (T_min, T_max, "
    "umidità relativa, vento, radiazione solare) e i parametri specie "
    "(stomatal_resistance_s_m, crop_height_m) popolati."
))

xml_parts.append(p(
    "Penman-Monteith standard FAO-56 (PENMAN_MONTEITH_STANDARD) è il fallback "
    "quando la specie non ha la resistenza stomatica popolata ma i dati meteo "
    "sono completi. Applica l'equazione con i parametri della coltura di "
    "riferimento standard FAO-56 (rs=70 s/m, h=0.12 m) e produce ET₀ di "
    "riferimento, da moltiplicare per il Kc della specie come si fa con "
    "Hargreaves. Richiede tutti i dati meteo, ma niente sulla specie."
))

xml_parts.append(p(
    "Hargreaves-Samani 1985 (HARGREAVES_SAMANI) è il fallback finale quando "
    "mancano dati meteo (umidità, vento, radiazione). Richiede solo la "
    "temperatura minima e massima della giornata e produce ET₀, da moltiplicare "
    "per il Kc della specie. È la formula \"di emergenza\" che funziona sempre "
    "ma è meno precisa delle altre due."
))

xml_parts.append(h2('Usare il selettore: la funzione compute_et'))

xml_parts.append(p(
    "L'API del selettore vive nel modulo science/et0.py ed è la funzione "
    "compute_et. Riceve i dati meteo disponibili come argomenti opzionali e "
    "restituisce un EtResult che contiene il valore numerico in mm/giorno e il "
    "metodo effettivamente usato. Esempio minimo di chiamata diretta:"
))

xml_parts.append(code(
    "from fitosim.science.et0 import compute_et"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "result = compute_et("
))
xml_parts.append(code(
    "    t_min=18.0, t_max=28.0,"
))
xml_parts.append(code(
    "    latitude_deg=45.46, j=200,  # giorno dell'anno"
))
xml_parts.append(code(
    "    humidity_relative=0.55,    # opzionale"
))
xml_parts.append(code(
    "    wind_speed_m_s=2.5,        # opzionale"
))
xml_parts.append(code(
    "    solar_radiation_mj_m2_day=22.0,  # opzionale"
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    "print(result.value_mm)   # es. 5.27"
))
xml_parts.append(code(
    "print(result.method)     # EtMethod.PENMAN_MONTEITH_STANDARD"
))

xml_parts.append(p(
    "Se passi solo t_min, t_max, latitude_deg e j, ricadi automaticamente su "
    "Hargreaves. Se passi anche umidità, vento e radiazione, il selettore "
    "salirà a Penman-Monteith standard. Se passi anche stomatal_resistance_s_m "
    "e crop_height_m della specie, salirà a Penman-Monteith fisico. La "
    "tracciabilità del metodo nel risultato ti permette di fare diagnostica "
    "(\"oggi quale formula è stata usata?\") e calibrazione (\"questi vasi "
    "girano sempre con Hargreaves perché manca la radiazione, dovrei "
    "configurare Open-Meteo come fonte di radiazione\")."
))

xml_parts.append(h2('Integrazione automatica nel Pot e nel Garden'))

xml_parts.append(p(
    "Nella pratica del dashboard giornaliero non chiamerai compute_et "
    "direttamente: la libreria offre due metodi di alto livello che invocano "
    "il selettore per te in modo trasparente. Sul Pot c'è "
    "apply_balance_step_from_weather(weather, current_date), che riceve un "
    "WeatherDay (la dataclass meteo del giorno, definita in domain/weather.py) "
    "e applica internamente compute_et con i dati appropriati e i parametri "
    "della specie. Sul Garden c'è apply_step_all_from_weather(weather, "
    "current_date) che fa la stessa cosa per tutti i vasi outdoor del giardino "
    "in un colpo solo. Esempio:"
))

xml_parts.append(code(
    "from datetime import date"
))
xml_parts.append(code(
    "from fitosim.domain.weather import WeatherDay"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "meteo_oggi = WeatherDay("
))
xml_parts.append(code(
    "    date_=date(2026, 7, 19),"
))
xml_parts.append(code(
    "    t_min=18.0, t_max=28.0,"
))
xml_parts.append(code(
    "    humidity_relative=0.55,"
))
xml_parts.append(code(
    "    wind_speed_m_s=2.5,"
))
xml_parts.append(code(
    "    solar_radiation_mj_m2_day=22.0,"
))
xml_parts.append(code(
    "    rainfall_mm=0.0,"
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    "garden.apply_step_all_from_weather(meteo_oggi, current_date=date(2026, 7, 19))"
))

xml_parts.append(p(
    "Il vecchio metodo apply_step_all(et_0_mm, current_date, rainfall_mm) "
    "continua a funzionare invariato per retrocompatibilità: se hai già "
    "calcolato ET₀ da una fonte esterna (per esempio dall'API Ecowitt), puoi "
    "passarlo direttamente come prima. La differenza è che il nuovo metodo "
    "_from_weather sfrutta il selettore \"best available\" e produce un "
    "risultato più accurato quando hai i dati meteo completi."
))

xml_parts.append(h2('Quando ti serve il Penman-Monteith fisico'))

xml_parts.append(p(
    "Il fisico è l'opzione più accurata in assoluto, ma richiede che la specie "
    "abbia popolati i campi stomatal_resistance_s_m e crop_height_m. Nel "
    "catalogo predefinito di fitosim queste informazioni sono presenti per le "
    "specie principali (BASIL ha rs=200 s/m e h=0.40 m, TOMATO ha rs=120 s/m "
    "e h=1.50 m, ROSEMARY ha rs=300 s/m e h=0.60 m, CACTUS ha rs=600 s/m e "
    "h=0.30 m per riflettere la fisiologia CAM, ecc.); se stai costruendo una "
    "Species custom, puoi popolarli usando la letteratura agronomica o "
    "lasciarli a None per ricadere automaticamente sul Penman-Monteith standard."
))

xml_parts.append(p(
    "La differenza tra fisico e standard è particolarmente significativa per "
    "specie con fisiologia atipica come succulente e cactacee a metabolismo "
    "CAM, dove la resistenza stomatica elevata produce un'evapotraspirazione "
    "molto più bassa di quanto Hargreaves o Penman-Monteith standard "
    "predirebbero. Per queste specie il fisico è quasi obbligatorio se vuoi "
    "previsioni realistiche; per specie a metabolismo C3 standard (basilico, "
    "rosmarino, pomodoro) lo standard è quasi altrettanto buono."
))

xml_parts.append(h2('Diagnostica della formula scelta'))

xml_parts.append(p(
    "Quando vuoi sapere quale formula sta usando il selettore per un dato vaso "
    "in una data giornata, puoi chiamare compute_et direttamente con gli "
    "stessi argomenti che il Pot userebbe, e ispezionare il campo method del "
    "risultato. Più operativamente, la demo dell'appartamento (sotto-tappa 5-E) "
    "produce una heatmap PNG che mostra giorno per giorno e vaso per vaso "
    "quale metodo è stato usato, ed è un buon punto di partenza per costruire "
    "la stessa visualizzazione nel tuo dashboard."
))


# =====================================================================
#  CAPITOLO 18 — Vasi indoor: Room, microclima e sensore WN31
# =====================================================================

xml_parts.append(h1('18 — Vasi indoor: Room, microclima e sensore WN31'))

xml_parts.append(p(
    "Fino al capitolo 17 il manuale ha trattato implicitamente vasi outdoor: "
    "vasi che vivono sul balcone o in giardino, ricevono pioggia, sono esposti "
    "al sole e al vento, e il loro bilancio idrico è alimentato dai dati meteo "
    "esterni. Per i vasi indoor — quelli che vivono dentro casa, in salotto, "
    "in cucina, in camera da letto — il quadro è completamente diverso: non "
    "ricevono pioggia, il vento è quello eventualmente generato da un "
    "ventilatore, l'umidità relativa è quella della stanza non quella del "
    "balcone, la temperatura è quella della stanza, e la radiazione solare è "
    "una piccola frazione di quella outdoor che dipende dalla posizione del "
    "vaso rispetto alle finestre."
))

xml_parts.append(p(
    "La tappa 5 della fascia 2 ha introdotto un modello dedicato per i vasi "
    "indoor, basato su una nuova entità di dominio chiamata Room che "
    "rappresenta lo spazio fisico (una stanza o una zona di una stanza) in cui "
    "vivono uno o più vasi indoor con il loro microclima condiviso. Questo "
    "capitolo ti spiega come modellare il tuo appartamento con fitosim: come "
    "creare le Room, come associarvi i vasi, come alimentare il modello dal "
    "sensore ambientale WN31 di Ecowitt, come parametrizzare l'esposizione "
    "luminosa di ogni vaso."
))

xml_parts.append(h2('Perché esiste l\'entità Room'))

xml_parts.append(p(
    "L'introduzione della Room non è una sofisticazione gratuita ma una "
    "conseguenza fisica del fatto che il sensore WN31 di Ecowitt (alias "
    "commerciale WH31, lo stesso prodotto con due nomi) non è una sonda "
    "dedicata al singolo vaso ma un trasmettitore ambientale che misura il "
    "microclima di una stanza intera. Cinque vasi che condividono il salotto "
    "condividono lo stesso microclima ambientale; un sesto vaso in camera da "
    "letto richiede un secondo WN31 per quella stanza."
))

xml_parts.append(p(
    "Il modello rispecchia questa fisica esplicitamente attraverso l'entità "
    "Room invece di duplicare i dati meteo per ogni vaso. Ogni Room ha un "
    "room_id univoco (una stringa scelta da te, per esempio \"salotto\"), un "
    "nome leggibile per UI e log, l'eventuale channel_id del WN31 mappato, il "
    "microclima corrente come stato mutabile, e un default_wind_m_s di 0.5 m/s "
    "per rappresentare il vento minimo convettivo della stanza. I Pot indoor "
    "si associano alla loro Room tramite il campo opzionale room_id."
))

xml_parts.append(h2('Costruire le Room del tuo appartamento'))

xml_parts.append(p(
    "Il punto di partenza è creare le Room corrispondenti alle stanze "
    "dell'appartamento e aggiungerle al Garden con add_room. Esempio per un "
    "appartamento con vasi in salotto e in camera da letto:"
))

xml_parts.append(code(
    "from fitosim.domain.garden import Garden"
))
xml_parts.append(code(
    "from fitosim.domain.room import Room"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "appartamento = Garden(name=\"appartamento-milano\")"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "salotto = Room("
))
xml_parts.append(code(
    "    room_id=\"salotto\","
))
xml_parts.append(code(
    "    name=\"Salotto\","
))
xml_parts.append(code(
    "    wn31_channel_id=\"1\",  # canale WN31 della stanza"
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    "camera = Room("
))
xml_parts.append(code(
    "    room_id=\"camera\","
))
xml_parts.append(code(
    "    name=\"Camera da letto\","
))
xml_parts.append(code(
    "    wn31_channel_id=\"2\","
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "appartamento.add_room(salotto)"
))
xml_parts.append(code(
    "appartamento.add_room(camera)"
))

xml_parts.append(p(
    "Se non hai ancora il sensore WN31 collegato puoi lasciare "
    "wn31_channel_id=None e popolare manualmente il microclima della Room "
    "passando i dati che osservi. Se hai un ventilatore acceso costantemente "
    "in una stanza, puoi sovrascrivere il default_wind_m_s con il valore "
    "stimato (per esempio 1.5 m/s per un ventilatore a velocità media a un "
    "metro dai vasi)."
))

xml_parts.append(h2('Associare i vasi alle Room e parametrizzare la luce'))

xml_parts.append(p(
    "Ogni vaso indoor si associa alla sua Room tramite il campo room_id, e "
    "deve dichiarare il suo livello di esposizione luminosa tramite il campo "
    "light_exposure (enum LightExposure con tre livelli). La scelta del "
    "livello è qualitativa e attribuibile per osservazione diretta: DARK per "
    "vasi lontani dalle finestre o in stanze poco luminose (Pothos in un "
    "angolo del salotto), INDIRECT_BRIGHT per vasi vicini a una finestra ma "
    "senza sole diretto (basilico sul ripiano della cucina, lontano dalla "
    "finestra), DIRECT_SUN per vasi sul davanzale di una finestra a sud o "
    "ovest con qualche ora di sole diretto al giorno (rosmarino sul davanzale "
    "del salotto)."
))

xml_parts.append(code(
    "from fitosim.domain.pot import Location, Pot"
))
xml_parts.append(code(
    "from fitosim.domain.room import LightExposure"
))
xml_parts.append(code(
    "from fitosim.domain.species import BASIL"
))
xml_parts.append(code(
    "from fitosim.science.substrate import UNIVERSAL_POTTING_SOIL"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "vaso_basilico = Pot("
))
xml_parts.append(code(
    "    label=\"basilico-cucina\","
))
xml_parts.append(code(
    "    species=BASIL,"
))
xml_parts.append(code(
    "    substrate=UNIVERSAL_POTTING_SOIL,"
))
xml_parts.append(code(
    "    pot_volume_l=1.5,"
))
xml_parts.append(code(
    "    pot_diameter_cm=14.0,"
))
xml_parts.append(code(
    "    location=Location.INDOOR,"
))
xml_parts.append(code(
    "    planting_date=date(2026, 4, 1),"
))
xml_parts.append(code(
    "    room_id=\"salotto\",            # appartiene al salotto"
))
xml_parts.append(code(
    "    light_exposure=LightExposure.INDIRECT_BRIGHT,"
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    "appartamento.add_pot(vaso_basilico)"
))

xml_parts.append(p(
    "I vasi outdoor continuano a vivere nel giardino senza room_id e senza "
    "light_exposure (entrambi sono opzionali e None per default). Puoi avere "
    "un Garden ibrido che mescola vasi outdoor sul balcone e vasi indoor in "
    "salotto, e il sistema gestisce correttamente ognuno con il suo modello."
))

xml_parts.append(h2('Aggiornare il microclima dal sensore WN31'))

xml_parts.append(p(
    "Quando hai il sensore WN31 collegato, puoi alimentare il microclima delle "
    "Room dal sensore in modo automatico tramite l'adapter EcowittAmbientSensor. "
    "L'adapter espone due metodi: current_state(channel_id) per la lettura "
    "istantanea (kind=INSTANT, usata dal dashboard per mostrare lo stato "
    "corrente della stanza), e daily_aggregate(channel_id, target_date) per "
    "l'aggregato giornaliero (kind=DAILY, con t_min, t_max e umidità media; "
    "usato dal bilancio idrico)."
))

xml_parts.append(code(
    "from datetime import date"
))
xml_parts.append(code(
    "from fitosim.io.sensors.ecowitt import EcowittAmbientSensor"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "sensor = EcowittAmbientSensor.from_env()  # legge le credenziali da .env"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "# Microclima istantaneo per il dashboard"
))
xml_parts.append(code(
    "m_now = sensor.current_state(channel_id=\"1\")"
))
xml_parts.append(code(
    "salotto.update_current_microclimate(m_now)"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "# Aggregato giornaliero per il bilancio idrico"
))
xml_parts.append(code(
    "m_daily = sensor.daily_aggregate("
))
xml_parts.append(code(
    "    channel_id=\"1\", target_date=date(2026, 7, 19),"
))
xml_parts.append(code(
    ")"
))
xml_parts.append(code(
    "appartamento.apply_step_all_from_indoor("
))
xml_parts.append(code(
    "    microclimate=m_daily,"
))
xml_parts.append(code(
    "    room_id=\"salotto\","
))
xml_parts.append(code(
    "    current_date=date(2026, 7, 19),"
))
xml_parts.append(code(
    ")"
))

xml_parts.append(p(
    "Il metodo apply_step_all_from_indoor del Garden applica il bilancio "
    "idrico a tutti i vasi della Room specificata usando il microclima "
    "giornaliero passato come argomento. Internamente invoca il selettore "
    "compute_et configurato per la Room (con il vento minimo convettivo della "
    "stanza al posto del vento outdoor, con la radiazione indoor stimata dal "
    "LightExposure del vaso al posto della radiazione globale outdoor) e "
    "produce un risultato realistico per ognuno dei vasi della stanza."
))

xml_parts.append(h2('La radiazione indoor: categoriale o continua'))

xml_parts.append(p(
    "Il modulo science/indoor.py offre due modi per stimare la radiazione "
    "indoor di un vaso: il modo categoriale e il modo continuo. Sceglie il "
    "modo automaticamente in funzione dei dati che hai a disposizione, ma è "
    "utile sapere quale dei due sta usando."
))

xml_parts.append(p(
    "Il modo categoriale associa al LightExposure tre valori fissi indipendenti "
    "dalla stagione: DARK = 1.5 MJ/m²/giorno, INDIRECT_BRIGHT = 4.0, DIRECT_SUN "
    "= 8.0. Sono valori medi annuali per una casa di latitudine padana, "
    "calibrati su letteratura agronomica generica. È il fallback semplice che "
    "funziona sempre, anche quando non hai dati outdoor."
))

xml_parts.append(p(
    "Il modo continuo stima la radiazione indoor come una frazione della "
    "radiazione globale outdoor del giorno: DARK = 5% di outdoor, "
    "INDIRECT_BRIGHT = 15%, DIRECT_SUN = 40%. È più accurato del categoriale "
    "perché cattura naturalmente la stagionalità (un vaso DIRECT_SUN riceve "
    "molto meno sole in inverno che in estate, perché la radiazione outdoor è "
    "stagionalmente più bassa) e anche le variazioni giornaliere (giorno "
    "nuvoloso vs sereno). Richiede però che tu abbia anche i dati di radiazione "
    "outdoor del giorno, tipicamente dal piranometro della tua stazione "
    "Ecowitt esterna."
))

xml_parts.append(p(
    "Per usare il modo continuo, basta passare anche il dato outdoor al metodo "
    "apply_step_all_from_indoor tramite il parametro "
    "outdoor_solar_radiation_mj_m2_day. Se lo lasci a None, il sistema usa "
    "automaticamente il modo categoriale."
))

xml_parts.append(h2('Il sensore di substrato WH52'))

xml_parts.append(p(
    "La tappa 5 ha aggiunto anche il supporto al sensore di substrato WH52, "
    "che è l'upgrade del WH51 e misura non solo l'umidità volumetrica del "
    "substrato (come il WH51) ma anche la sua temperatura e l'EC. Per "
    "fitosim il WH52 è gestito dallo stesso adapter del WH51, "
    "EcowittWH51SoilSensor, parametrizzato col modello del sensore. Esempio:"
))

xml_parts.append(code(
    "from fitosim.io.sensors.ecowitt import EcowittWH51SoilSensor"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "# Sensore WH51 (default)"
))
xml_parts.append(code(
    "sensor51 = EcowittWH51SoilSensor.from_env()"
))
xml_parts.append(code(
    ""
))
xml_parts.append(code(
    "# Sensore WH52 (parametrizzato)"
))
xml_parts.append(code(
    "sensor52 = EcowittWH51SoilSensor.from_env(model=\"WH52\")"
))

xml_parts.append(p(
    "Le letture del WH52 popolano i campi temperature_c ed ec_mscm del "
    "SoilReading, mentre quelle del WH51 lasciano questi campi a None. Il Pot "
    "che riceve la lettura via update_from_sensor usa i campi popolati per "
    "raffinare la diagnostica del modello chimico (per esempio, una EC "
    "misurata dal WH52 può essere confrontata con la EC predetta dal modello "
    "interno del Pot, e la differenza è un indicatore di calibrazione del "
    "modello chimico). Il WH51 continua a essere supportato indefinitamente "
    "per chi ce l'ha già installato; il WH52 è un upgrade opzionale che "
    "fornisce più dati ai vasi che lo hanno."
))

xml_parts.append(h2('Una ricetta dell\'appartamento'))

xml_parts.append(p(
    "Per vedere il modello indoor in azione su uno scenario realistico, lancia "
    "lo script tappa5_E_appartamento_demo.py nella cartella examples/ del "
    "repository. Simula un appartamento invernale con tre vasi indoor sparsi "
    "tra salotto (Room \"salotto\" con due vasi: un'orchidea su una finestra "
    "INDIRECT_BRIGHT e un Pothos in posizione DARK) e camera da letto (Room "
    "\"camera\" con una sansevieria su davanzale DIRECT_SUN, fisiologia CAM). "
    "Lo script mostra in azione la selezione automatica del metodo ET "
    "(diversa per ognuno dei tre vasi a seconda dei parametri specie), la "
    "persistenza completa delle Room nel database SQLite, e produce quattro "
    "grafici PNG che danno un'idea concreta del tipo di analisi che il modello "
    "indoor permette: andamento idrico per vaso, bilancio idrico per ambiente, "
    "heatmap dei metodi ET selezionati giorno per giorno, e confronto dei "
    "metodi su una settimana di scenario."
))

xml_parts.append(p(
    "Lo script gira in pochi secondi senza hardware reale (usa fixture CSV per "
    "simulare il microclima delle due Room) ed è un buon punto di partenza per "
    "costruire la tua versione personalizzata sostituendo le fixture con "
    "EcowittAmbientSensor.daily_aggregate quando avrai i tuoi WN31 collegati."
))


# =====================================================================
#  Salvo il blocco completo
# =====================================================================

xml_block = "".join(xml_parts)
with open("/home/claude/new_chapters.xml", "w", encoding="utf-8") as f:
    f.write(xml_block)
print(f"Blocco XML scritto: {len(xml_block)} caratteri, {xml_block.count('<w:p')} paragrafi")
