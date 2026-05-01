// Generatore dello status report di fitosim — versione fine tappa 5.
//
// Mantiene la stessa struttura editoriale del file precedente
// (Executive summary, Quadro quantitativo, Fascia 1, Fascia 2 con Tappe 1-5,
// Decisioni architetturali, Roadmap, Storico delle consegne, Quadro
// operativo, Considerazioni finali) ma aggiorna tutti i numeri e
// trasforma la sezione "Cosa farà la tappa 5" in consuntivo della tappa
// completata, aggiungendo l'articolazione delle 5 sotto-tappe con i loro
// risultati e lo storico esteso delle consegne v0_19 → v0_19_6.

const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, Header, Footer, PageBreak, ImageRun,
} = require('docx');

// =====================================================================
//  Helper di stile
// =====================================================================

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 120, line: 320 },
    alignment: opts.align || AlignmentType.JUSTIFIED,
    children: [new TextRun({ text, ...opts.run })],
  });
}

function pRich(runs, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 120, line: 320 },
    alignment: opts.align || AlignmentType.JUSTIFIED,
    children: runs,
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 180 },
    children: [new TextRun(text)],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 140 },
    children: [new TextRun(text)],
  });
}

function bullet(text, runs = null) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    spacing: { before: 30, after: 80, line: 320 },
    children: runs || [new TextRun(text)],
  });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: '99B4D1' };
const borders = { top: border, bottom: border, left: border, right: border };

function makeTable(headers, rows, columnWidths) {
  const totalWidth = columnWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((text, i) =>
          new TableCell({
            borders,
            width: { size: columnWidths[i], type: WidthType.DXA },
            shading: { fill: 'D5E8F0', type: ShadingType.CLEAR },
            margins: { top: 100, bottom: 100, left: 120, right: 120 },
            children: [new Paragraph({
              spacing: { before: 0, after: 0 },
              children: [new TextRun({ text, bold: true })],
            })],
          })
        ),
      }),
      ...rows.map(row =>
        new TableRow({
          children: row.map((text, i) =>
            new TableCell({
              borders,
              width: { size: columnWidths[i], type: WidthType.DXA },
              margins: { top: 80, bottom: 80, left: 120, right: 120 },
              children: [new Paragraph({
                spacing: { before: 0, after: 0 },
                children: [new TextRun(text)],
              })],
            })
          ),
        })
      ),
    ],
  });
}

// =====================================================================
//  Contenuto del documento
// =====================================================================

const children = [];

// ---------- Frontespizio ----------
children.push(new Paragraph({
  spacing: { before: 0, after: 120 },
  children: [new TextRun({ text: 'fitosim — Status Report', bold: true, size: 36 })],
}));

children.push(new Paragraph({
  spacing: { before: 0, after: 60 },
  children: [new TextRun({
    text: 'Stato dello sviluppo della libreria di simulazione FAO-56',
    italics: true, size: 22,
  })],
}));

children.push(new Paragraph({
  spacing: { before: 0, after: 360 },
  children: [new TextRun({
    text: 'Maggio 2026 — Aggiornato a fine tappa 5 fascia 2 (chiusura fascia 2)',
    italics: true, size: 22, color: '666666',
  })],
}));

// ---------- Executive summary ----------
children.push(h1('Executive summary'));

children.push(p(
  'fitosim è la libreria Python che stai costruendo per modellare il bilancio idrico ' +
  'e chimico del tuo balcone milanese, basata sulla metodologia FAO-56 estesa con ' +
  'componenti specifici per la coltivazione in vaso. Il progetto è suddiviso in due ' +
  'fasce di lavoro distinte: la fascia 1 ha costruito il modello idrico completo del ' +
  'singolo vaso ed è chiusa da diverso tempo; la fascia 2 ha esteso la libreria con ' +
  'sensoristica reale, modello chimico, architettura applicativa e raffinamento ' +
  'scientifico, ed è ora completa al 100% (cinque tappe complete su cinque).'
));

children.push(p(
  'Lo stato attuale è una libreria a 1007 test verdi (più 1 skipped intenzionale e ' +
  '357 sub-test) che integra: il modello idrico FAO-56 con dual-Kc; gestione del ' +
  'sottovaso; calibrazione da sensore; sensori reali via HTTP/JSON con gateway ESP32; ' +
  'modello chimico completo del substrato (massa salina, pH, EC come grandezza ' +
  'derivata); coefficiente nutrizionale Kn che modula l\u2019evapotraspirazione in ' +
  'funzione dello stato chimico; coefficiente di esposizione alla pioggia per i vasi ' +
  'parzialmente coperti. Da fine tappa 4 si aggiunge il dashboard operativo completo: ' +
  'il Garden come orchestratore di più vasi, la persistenza SQLite con storia completa, ' +
  'il formato di trasporto JSON, l\u2019integrazione dei sensori reali in batch, gli ' +
  'eventi pianificati con previsioni a N giorni, e il sistema di allerte derivato dallo stato.'
));

children.push(p(
  'La tappa 5, completata alla chiusura della fascia 2, ha aggiunto un raffinamento ' +
  'sostanziale del modello scientifico articolato in cinque sotto-tappe progressive ' +
  'per un totale di 142 test verdi nuovi: introduzione di Penman-Monteith come funzioni ' +
  'pure (versione fisica con resistenza stomatica della specie e versione FAO-56 ' +
  'standard, accanto a Hargreaves-Samani); selettore "best available" che sceglie ' +
  'automaticamente tra le tre formule in funzione dei dati meteo e dei parametri ' +
  'specie disponibili, con tracciabilità del metodo via EtResult; integrazione del ' +
  'selettore nel ciclo di vita del Pot e del Garden tramite WeatherDay e i nuovi ' +
  'metodi apply_balance_step_from_weather e apply_step_all_from_weather; modello ' +
  'completo dei vasi indoor con la nuova entità Room, IndoorMicroclimate, ' +
  'LightExposure a tre livelli, modulo science/indoor.py per la radiazione, ' +
  'EcowittAmbientSensor per il sensore WN31, supporto WH52 nel ' +
  'EcowittWH51SoilSensor, persistenza delle Room nel database SQLite; demo end-to-end ' +
  'di un appartamento invernale con tre vasi indoor in due Room diverse.'
));

children.push(p(
  'Con la fascia 2 chiusa, il progetto è pronto per aprire la fascia 3 di calibrazione ' +
  'contro i dati reali del tuo balcone. La fascia 3 sarà concettualmente diversa dalle ' +
  'precedenti: meno "costruzione di nuove API" e più "messa a punto e validazione contro ' +
  'realtà". I dati raccolti dalla stazione Ecowitt nei prossimi mesi saranno usati per ' +
  'raffinare le frazioni della radiazione indoor, i parametri Kc del catalogo specie, ' +
  'le soglie del selettore "best available", la resistenza stomatica delle specie. ' +
  'Lo scopo è trasformare fitosim da "libreria genericamente plausibile" a "libreria ' +
  'calibrata per il TUO balcone milanese".'
));

// ---------- Quadro quantitativo ----------
children.push(h1('Quadro quantitativo del progetto'));

children.push(p(
  'Lo stato della libreria può essere riassunto con qualche numero che dà la misura del ' +
  'lavoro accumulato e della copertura della suite di test.'
));

children.push(makeTable(
  ['Metrica', 'Valore', 'Note'],
  [
    ['Test verdi totali',         '1007',           '+ 1 skipped intenzionale'],
    ['Sub-test verdi',            '357',            'via subTest di unittest'],
    ['Test fascia 1 (storici)',   '423',            'non toccati dalla fascia 2'],
    ['Test fascia 2 (nuovi)',     '584',            '263 tappe 1-3 + 179 tappa 4 + 142 tappa 5'],
    ['Tempo esecuzione suite',    '\u2248 11 sec', 'su laptop standard, no parallelismo'],
    ['Moduli science/',           '11',             'aggiunto indoor.py (tappa 5)'],
    ['Moduli domain/',            '7',              'Pot, Species, Garden, scheduling, alerts, room, weather'],
    ['Moduli io/',                '11',             'Protocol + 5 adapter + persistence + serialization (3 classi Ecowitt)'],
    ['Schema SQLite',             'v3',             '8 tabelle + estensione per Room (tappa 5)'],
    ['Linguaggio',                'Python \u2265 3.10', 'no dipendenze esterne nel core'],
    ['Firmware ESP32',            '5 file Arduino', 'esempio per gateway HTTP-Modbus'],
    ['Esempi e demo',             '20+',            'incluse 4 demo della tappa 5 (A, B, C, E)'],
  ],
  [2880, 1800, 4680],
));

// ---------- Fascia 1 ----------
children.push(h1('Fascia 1: modello idrico completo (chiusa)'));

children.push(p(
  'La fascia 1 è stata completata in sei tappe ed ha costruito il cuore idrico del ' +
  'modello: il bilancio FAO-56 standard nel vaso, esteso con componenti specifiche del ' +
  'giardinaggio domestico. È chiusa da tempo, non viene toccata dalle tappe successive, ' +
  'e i suoi 423 test continuano a passare al byte ad ogni nuova consegna della fascia 2.'
));

children.push(h2('Cosa contiene la fascia 1'));

children.push(p('Le sei tappe completate hanno introdotto progressivamente:'));

children.push(bullet(
  'La caratterizzazione fisica del vaso come contenitore: volume, diametro, forma ' +
  '(cilindrica, rettangolare, ovale), materiale (plastica, terracotta, ceramica), ' +
  'colore (chiaro, medio, scuro) ed esposizione solare. Il coefficiente Kp di vaso ' +
  'modula l\u2019evapotraspirazione in base a queste caratteristiche.'
));
children.push(bullet(
  'Il modello del sottovaso opzionale come componente di stato distinto, con ' +
  'trasferimento capillare verso il substrato, evaporazione propria, e capacità di ' +
  'drenaggio dell\u2019eccesso idrico.'
));
children.push(bullet(
  'L\u2019astrazione del substrato di coltivazione con i parametri idrici \u03B8_FC ' +
  '(capacità di campo) e \u03B8_PWP (punto di appassimento permanente), più i ' +
  'parametri opzionali REW/TEW per il modello dual-Kc.'
));
children.push(bullet(
  'Il modello dual-Kc di FAO-56 capitolo 7 che separa il coefficiente colturale in ' +
  'componente basale (traspirazione) ed evaporazione superficiale. Si attiva ' +
  'automaticamente quando specie e substrato sono entrambi caratterizzati per il ' +
  'dual-Kc, ricadendo sul single-Kc in caso contrario.'
));
children.push(bullet(
  'Il sistema di calibrazione e diagnostica delle deviazioni del modello dalle ' +
  'osservazioni, che fornisce il framework per il tuning fine dei parametri del ' +
  'singolo vaso.'
));
children.push(bullet(
  'Il feedback loop sensore-modello via il metodo update_from_sensor del Pot, che ' +
  'permette di agganciare la previsione alla realtà osservata e produrre diagnostica ' +
  'strutturata della discrepanza.'
));

// ---------- Fascia 2 ----------
children.push(h1('Fascia 2: sensori, chimica, architettura applicativa, raffinamento scientifico'));

children.push(p(
  'La fascia 2 estende fitosim oltre il bilancio idrico puro per includere la ' +
  'sensoristica reale del balcone, la chimica del substrato, l\u2019architettura ' +
  'applicativa del dashboard, e il raffinamento scientifico del modello di ' +
  'evapotraspirazione e del bilancio indoor. È strutturata in cinque tappe, tutte ' +
  'completate alla data di questo report.'
));

children.push(p(
  'L\u2019aspetto importante della fascia 2 è che è completamente opt-in: ogni ' +
  'estensione che introduce è retrocompatibile per costruzione, e la fascia 1 non si è ' +
  'accorta di nulla. Le 423 prove originarie continuano a girare identiche, e il ' +
  'chiamante che vuole le nuove funzionalità le attiva esplicitamente configurando i ' +
  'nuovi parametri delle dataclass o importando i nuovi moduli.'
));

// Tappe 1, 2, 3 (invariate)
children.push(h2('Tappa 1: astrazione dei sensori (completata)'));
children.push(p(
  'La prima tappa ha costruito l\u2019astrazione di sensore di fitosim come Protocol ' +
  'Python, separando il modello scientifico dai dettagli di acquisizione dei dati. Il ' +
  'Protocol SoilSensor definisce l\u2019interfaccia che qualsiasi sensore deve ' +
  'implementare: un metodo current_state(channel_id) che ritorna un SoilReading ' +
  'strutturato. La stessa cosa per i sensori ambientali tramite il Protocol ' +
  'EnvironmentSensor.'
));
children.push(p(
  'I tipi di ritorno EnvironmentReading e SoilReading raccolgono in dataclass frozen ' +
  'tutte le grandezze fisiche che un sensore può misurare, tutte con timestamp UTC ' +
  'aware obbligatorio. La gerarchia di eccezioni canoniche (SensorTemporaryError, ' +
  'SensorPermanentError, SensorDataQualityError) classifica gli errori in base alla ' +
  'loro recuperabilità, permettendo al chiamante di reagire differenziatamente.'
));

children.push(h2('Tappa 2: gateway hardware-to-HTTP (completata)'));
children.push(p(
  'La seconda tappa ha aggiunto il primo sensore di suolo "ricco" che misura non solo ' +
  '\u03B8 ma anche temperatura del substrato, EC e pH. Il pattern adottato è generico ' +
  'e disaccoppiato: invece di scrivere un adapter dedicato a un sensore specifico, ' +
  'abbiamo costruito un adapter HTTP JSON generico che parla con un gateway esterno. ' +
  'Il gateway si occupa dei dettagli hardware (Modbus RTU su bus RS485 nel caso ATO) e ' +
  'li espone come endpoint REST con uno schema JSON V1 ben documentato.'
));

children.push(h2('Tappa 3: modello chimico del substrato (completata)'));
children.push(p(
  'La terza tappa ha esteso il Pot col modello chimico completo: massa salina come ' +
  'stato canonico (salt_mass_meq), pH del substrato come stato indipendente ' +
  '(ph_substrate), e EC come property derivata dal rapporto sali/acqua. Il fenomeno ' +
  'della concentrazione per evapotraspirazione emerge automaticamente: meno acqua a ' +
  'parità di sali significa EC più alta, senza nessuna riga di codice che lo gestisce ' +
  'esplicitamente.'
));
children.push(p(
  'Il coefficiente nutrizionale Kn modula l\u2019evapotraspirazione effettiva in ' +
  'funzione dello stato chimico: vaso in range chimico ottimale ha Kn=1, vaso in ' +
  'stress chimico totale ha Kn=0.30 (la pianta consuma molto meno perché la sua ' +
  'fisiologia ne soffre). Implementato come funzione triangolare lineare a tratti, ' +
  'semplice e debugabile, calibrabile in fascia 3.'
));
children.push(p(
  'Il rainfall_exposure (frazione 0..1) modella la copertura ambientale del vaso. Vasi ' +
  'sotto balcone o sotto chioma di alberi ricevono solo una frazione della pioggia ' +
  'caduta sull\u2019area aperta — fenomeno che per i vasi outdoor produce ' +
  'salinizzazione differenziale di lungo termine, importante per la calibrazione ' +
  'futura del modello.'
));

children.push(h2('Tappa 4: dashboard operativo completo (completata)'));
children.push(p(
  'La quarta tappa è la più sostanziosa della fascia 2 in termini di scope ' +
  'architetturale: trasforma fitosim da "libreria scientifica per singolo vaso" a ' +
  '"sistema operativo per il dashboard del giardiniere". È strutturata in cinque ' +
  'sotto-tappe, ognuna con un focus specifico, e in totale ha aggiunto 179 test verdi ' +
  'alla suite portandola a 865.'
));

children.push(makeTable(
  ['Sotto-tappa', 'Capacità', 'Test nuovi'],
  [
    ['A: Garden in-memory',     'Orchestrazione di più vasi come unità coerente',           '+30'],
    ['B fase 1: SQLite',        'Persistenza con storia completa degli stati',              '+32'],
    ['B fase 2: JSON',          'Formato di trasporto per backup e migrazione',             '+20'],
    ['C: integrazione sensori', 'Update batch dai sensori reali con robustezza errori',     '+23'],
    ['D: forecast e eventi',    'Eventi pianificati e proiezione dello stato a N giorni',   '+36'],
    ['E: sistema di allerte',   'Allerte derivate dallo stato per dashboard proattivo',     '+38'],
  ],
  [2160, 5400, 1800],
));

children.push(p(
  'Il Garden della sotto-tappa A è un orchestratore puro: contiene una collezione di ' +
  'Pot indicizzati per label, e i suoi metodi (apply_step_all, ' +
  'update_all_from_sensors, forecast) iterano sui vasi senza aggiungere logica ' +
  'scientifica al modello. Una proprietà inchiodata da test specifici è che ' +
  'apply_step_all su un Garden con un vaso solo produce stati identici a apply_step ' +
  'chiamato direttamente sul Pot.'
));

children.push(p(
  'La persistenza SQLite della sotto-tappa B fase 1 ha introdotto uno schema a otto ' +
  'tabelle (schema_metadata, species, base_materials, substrates, ' +
  'substrate_components, gardens, pots, pot_states, events) con la convenzione ' +
  '"id come PK sintetica e <tabella>_id come FK". Lo schema è alla versione 3 e la ' +
  'classe GardenPersistence applica automaticamente le migrazioni v1\u2192v2 ' +
  '(channel_id) e v2\u2192v3 (scheduled_events) ai database esistenti.'
));

children.push(p(
  'Le altre sotto-tappe della 4 (B fase 2 JSON disaccoppiato dalla persistenza SQLite, ' +
  'C integrazione sensori in batch con gestione errori a tre livelli, D eventi ' +
  'pianificati e forecast su deep copy del Garden, E sistema di allerte come funzioni ' +
  'pure in cinque categorie e tre severità) hanno consolidato l\u2019architettura ' +
  'applicativa del dashboard.'
));

// ---------- TAPPA 5 - CONSUNTIVO (PEZZO NUOVO) ----------
children.push(h2('Tappa 5: Penman-Monteith fisico e modello indoor (completata)'));

children.push(p(
  'La quinta e ultima tappa della fascia 2 ha raffinato sostanzialmente il modello ' +
  'scientifico in due direzioni complementari: l\u2019introduzione di Penman-Monteith ' +
  'come formula di evapotraspirazione (in due varianti, fisica e standard FAO-56) con ' +
  'un selettore "best available" che sceglie automaticamente tra le formule disponibili, ' +
  'e il modello completo dei vasi indoor con l\u2019entità Room come spazio fisico con ' +
  'microclima condiviso. La tappa è strutturata in cinque sotto-tappe progressive che ' +
  'in totale hanno aggiunto 142 test verdi alla suite portandola a 1007.'
));

children.push(makeTable(
  ['Sotto-tappa', 'Capacità', 'Test nuovi'],
  [
    ['A: Penman-Monteith come funzioni pure',
     'Penman-Monteith fisico (con resistenza stomatica della specie) e standard FAO-56 nel modulo science/et0.py, accanto a Hargreaves-Samani. Tutte funzioni pure ben testate contro i casi di letteratura FAO-56.',
     '+25'],
    ['B: selettore "best available"',
     'compute_et sceglie automaticamente Penman-Monteith fisico \u2192 standard \u2192 Hargreaves in funzione dei dati meteo e dei parametri specie disponibili. Tracciabilità del metodo via EtResult e EtMethod.',
     '+17'],
    ['C: integrazione nel Pot e nel Garden',
     'WeatherDay come dataclass meteo giornaliera; apply_balance_step_from_weather sul Pot e apply_step_all_from_weather sul Garden, che invocano il selettore al posto di un ET\u2080 pre-calcolato.',
     '+30'],
    ['D: modello indoor',
     'Entit\u00E0 Room, IndoorMicroclimate (varianti istantanea/giornaliera), LightExposure a tre livelli, modulo science/indoor.py per la radiazione (categoriale e continua), EcowittAmbientSensor per il WN31, supporto WH52 nel EcowittWH51SoilSensor, persistenza delle Room nel database SQLite.',
     '+64'],
    ['E: demo end-to-end appartamento',
     'Script eseguibile (tappa5_E_appartamento_demo.py) che simula un appartamento invernale con tre vasi indoor in due Room diverse, mostra in azione la selezione automatica del metodo ET, la persistenza delle Room, e produce quattro grafici PNG di analisi.',
     '+6'],
  ],
  [2160, 5400, 1800],
));

children.push(p(
  'La sotto-tappa A ha introdotto Penman-Monteith come funzioni pure in due varianti: ' +
  'compute_et0_penman_monteith calcola l\u2019ET\u2080 di riferimento usando i ' +
  'parametri della coltura standard FAO-56 (rs=70 s/m, h=0.12 m), da moltiplicare per ' +
  'il Kc della specie come si fa con Hargreaves; compute_et_penman_monteith_physical ' +
  'calcola direttamente l\u2019ET applicando l\u2019equazione alla specie usando la ' +
  'sua resistenza stomatica e altezza colturale, producendo un valore già specifico ' +
  'per la pianta che NON va moltiplicato per il Kc. La distinzione tra le due varianti ' +
  'è semanticamente cruciale: confondere ET\u2080 e ET introducerebbe errori del ' +
  '100-200%.'
));

children.push(p(
  'La sotto-tappa B ha introdotto il selettore "best available" come funzione ' +
  'compute_et che riceve i dati meteo disponibili (temperature minima e massima, ' +
  'umidità relativa, vento, radiazione) e i parametri specie (resistenza stomatica e ' +
  'altezza colturale opzionali) e sceglie automaticamente la formula migliore ' +
  'disponibile: prima Penman-Monteith fisico se la specie ha la resistenza stomatica ' +
  'e tutti i dati meteo sono presenti, poi Penman-Monteith standard FAO-56 se solo i ' +
  'dati meteo sono completi, infine Hargreaves-Samani come fallback robusto che ' +
  'richiede solo le temperature. Il risultato include la tracciabilità del metodo ' +
  'usato (EtResult.method) per permettere al chiamante di fare diagnostica del modello.'
));

children.push(p(
  'La sotto-tappa C ha integrato il selettore nel ciclo di vita del Pot e del Garden ' +
  'tramite la nuova dataclass WeatherDay (modulo domain/weather.py) che incapsula i ' +
  'dati meteo giornalieri completi, e i nuovi metodi apply_balance_step_from_weather ' +
  '(sul Pot) e apply_step_all_from_weather (sul Garden) che invocano internamente ' +
  'compute_et con i dati appropriati. I metodi precedenti apply_balance_step e ' +
  'apply_step_all che ricevono ET\u2080 pre-calcolato continuano a funzionare invariati ' +
  'per retrocompatibilità.'
));

children.push(p(
  'La sotto-tappa D è la più sostanziosa della tappa 5 e ha introdotto il modello ' +
  'indoor in tre fasi articolate. La fase 1 ha aggiunto le entità di dominio Room ' +
  '(spazio fisico con microclima condiviso) e IndoorMicroclimate (lettura del ' +
  'microclima con varianti INSTANT per il dashboard e DAILY per il bilancio idrico), ' +
  'più l\u2019enum LightExposure a tre livelli (DARK, INDIRECT_BRIGHT, DIRECT_SUN) e ' +
  'il modulo science/indoor.py per la radiazione indoor (modi categoriale e continuo). ' +
  'La fase 2 ha esteso il Pot col campo room_id (riferimento alla Room di ' +
  'appartenenza) e light_exposure, e ha aggiunto il metodo ' +
  'apply_balance_step_from_indoor che alimenta il bilancio idrico dal microclima della ' +
  'stanza invece che dal meteo esterno. La fase 3 ha aggiunto l\u2019EcowittAmbientSensor ' +
  'per il sensore WN31 ambientale e il supporto al sensore di substrato WH52 nel ' +
  'EcowittWH51SoilSensor parametrizzato; ha esteso la persistenza SQLite con la ' +
  'tabella delle Room e la mappa Pot \u2192 room_id; ha aggiunto al Garden i metodi ' +
  'di gestione delle Room (add_room, get_room, pots_in_room, ecc.) e il metodo ' +
  'apply_step_all_from_indoor.'
));

children.push(p(
  'La sotto-tappa E ha consolidato il lavoro con uno script demo end-to-end ' +
  '(tappa5_E_appartamento_demo.py) che simula un appartamento invernale con tre vasi ' +
  'indoor sparsi tra salotto (Room "salotto" con due vasi) e camera da letto (Room ' +
  '"camera" con un vaso), mostra in azione la selezione automatica del metodo ET, la ' +
  'persistenza completa delle Room nel database SQLite, e produce quattro grafici PNG ' +
  'di analisi (andamento idrico per vaso, bilancio idrico per Room, heatmap dei metodi ' +
  'ET selezionati, confronto dei metodi). I sei test di integrazione associati ' +
  'verificano che lo script gira senza errori, che produce i PNG attesi, che le sezioni ' +
  'di output contengono i pattern attesi, e che la persistenza è round-trip.'
));

children.push(h2('Decisioni architetturali consolidate'));

children.push(p(
  'Le scelte di design fatte nelle tappe 4 e 5 hanno consolidato le proprietà ' +
  'strutturali che rendono fitosim manutenibile.'
));

children.push(bullet(
  'Disaccoppiamento netto tra layer: il modello scientifico vive in science/ e ' +
  'domain/Pot; l\u2019orchestrazione vive in domain/Garden; la persistenza vive in ' +
  'io/persistence e io/serialization che non si conoscono tra loro; le allerte vivono ' +
  'in domain/alerts come funzioni pure indipendenti dal Garden. Ogni layer può essere ' +
  'usato senza i layer superiori.'
));
children.push(bullet(
  'Persistenza esplicita e non magica: il Garden in-memory non ha autosave; il ' +
  'chiamante decide quando chiamare persistence.save_garden(). È più verboso ma non ' +
  'sorprendente, e permette ai test del modello scientifico di restare semplici senza ' +
  'dipendenze SQLite.'
));
children.push(bullet(
  'Selettore "best available" con tracciabilità: la tappa 5 ha applicato lo stesso ' +
  'pattern del catalogo specie (cascata di parametri opzionali con fallback ' +
  'automatici) al calcolo di evapotraspirazione. EtResult include il metodo usato ' +
  'così il chiamante può fare diagnostica e calibrazione, e il modello rimane ' +
  'utilizzabile anche con dati meteo incompleti.'
));
children.push(bullet(
  'Room come entità di dominio fisica, non logica: la Room non è un raggruppamento ' +
  'arbitrario di vasi ma rispecchia il fatto fisico che il sensore WN31 di Ecowitt ' +
  'misura il microclima di una stanza intera. Cinque vasi che condividono il salotto ' +
  'condividono lo stesso WN31, lo stesso microclima, la stessa Room nel modello.'
));
children.push(bullet(
  'Distinzione semantica ET\u2080 vs ET: il modello distingue rigorosamente tra ' +
  'evapotraspirazione di riferimento (da moltiplicare per Kc) e evapotraspirazione ' +
  'effettiva della specie (già specifica). EtMethod cattura la distinzione e il Pot la ' +
  'gestisce automaticamente, ma il chiamante che consuma direttamente il selettore ' +
  'deve guardare il metodo per decidere se moltiplicare per Kc.'
));
children.push(bullet(
  'Idempotenza dei register_*: chiamare register_species, register_base_material, ' +
  'register_substrate o register_room su un oggetto già registrato aggiorna ' +
  'silenziosamente i parametri. Permette al codice del chiamante di restare lineare ' +
  'senza condizioni speciali.'
));
children.push(bullet(
  'Schema versioning con migrazioni automatiche: il database SQLite si aggiorna alla ' +
  'nuova versione del codice senza intervento del chiamante. Il pattern è rodato ' +
  '(v1\u2192v2 channel_id, v2\u2192v3 scheduled_events) e l\u2019estensione per le ' +
  'Room della tappa 5 è stata aggiunta con la stessa logica.'
));
children.push(bullet(
  'Allerte come vista derivata, non come dato: niente persistenza, niente ' +
  'serializzazione, niente add/cancel. Aggiungere una nuova categoria di allerta in ' +
  'futuro è una funzione pura in più nel modulo alerts.py e una sua aggiunta a ' +
  'ALL_RULES, niente migrazione di schema.'
));
children.push(bullet(
  'Forecast su deep copy senza side effects: il Garden può essere interrogato "se le ' +
  'cose andassero così cosa succederebbe?" senza compromettere il suo stato corrente. ' +
  'È la proprietà che permette al dashboard di mostrare scenari alternativi al ' +
  'giardiniere.'
));

// ---------- Roadmap aggiornata ----------
children.push(h1('Roadmap della fascia 2'));

children.push(p(
  'La fascia 2 è ora completa al 100%. Tutte le cinque tappe sono state portate a ' +
  'termine; non ci sono lavori in sospeso a livello di tappa. Il prossimo passo ' +
  'naturale è l\u2019apertura della fascia 3 di calibrazione contro dati reali.'
));

children.push(makeTable(
  ['Tappa', 'Contenuto', 'Stato'],
  [
    ['Tappa 1', 'Astrazione sensori, Protocol, eccezioni canoniche, adapter Open-Meteo/Ecowitt',           'Completa'],
    ['Tappa 2', 'HttpJsonSoilSensor + firmware ESP32 di esempio',                                          'Completa'],
    ['Tappa 3', 'Modello chimico completo: substrato, fertirrigazione, Kn, feedback loop',                 'Completa'],
    ['Tappa 4', 'Garden orchestratore, persistenza SQLite/JSON, sensori in batch, forecast, allerte',      'Completa'],
    ['Tappa 5', 'Penman-Monteith fisico e standard, selettore "best available", modello indoor con Room, sensori WN31 e WH52, demo appartamento', 'Completa'],
  ],
  [1440, 6480, 1440],
));

children.push(h2('Cosa ha portato la tappa 5'));

children.push(p(
  'La tappa 5 ha chiuso la fascia 2 con un raffinamento del modello scientifico in ' +
  'cinque sotto-tappe progressive. Lo scope della tappa è stato volutamente scientifico ' +
  '— non ha aggiunto nuove capacità applicative ma ha raffinato la qualità delle ' +
  'previsioni del modello esistente, con un\u2019enfasi particolare sui vasi indoor che ' +
  'fino a tappa 4 erano trattati come outdoor con risultati poco realistici. Le ' +
  'capacità nuove introdotte sono articolate in due gruppi complementari: il selettore ' +
  '"best available" dell\u2019evapotraspirazione, e il modello completo dei vasi ' +
  'indoor con la nuova entità Room.'
));

children.push(p(
  'Il primo gruppo riguarda l\u2019introduzione del modello Penman-Monteith per il ' +
  'calcolo dell\u2019evapotraspirazione. La libreria fino a tappa 4 usava la formula ' +
  'di Hargreaves-Samani, robusta perché richiede solo la temperatura ma con un errore ' +
  'tipico del 10-20% rispetto al Penman-Monteith che combina temperatura, umidità ' +
  'relativa, velocità del vento e radiazione solare in un\u2019equazione fisica. La ' +
  'tappa 5 ha introdotto Penman-Monteith in due varianti: la versione FAO-56 standard ' +
  'che produce ET\u2080 da moltiplicare per il Kc della specie, e la versione fisica ' +
  'che applica direttamente l\u2019equazione alla specie usando la sua resistenza ' +
  'stomatica e produce ET senza bisogno del Kc. Il selettore compute_et sceglie ' +
  'automaticamente la formula migliore disponibile in funzione dei dati meteo e dei ' +
  'parametri specie presenti, seguendo il pattern "best available" raccomandato dalla ' +
  'pubblicazione FAO-56.'
));

children.push(p(
  'Il secondo gruppo riguarda il modello completo dei vasi indoor. La novità ' +
  'architetturale principale è la nuova entità Room nel modulo domain/room.py, che ' +
  'rappresenta lo spazio fisico (una stanza, una zona di una stanza) in cui vivono uno ' +
  'o più vasi indoor con il loro microclima condiviso. La Room ha un room_id univoco, ' +
  'un nome leggibile, l\u2019eventuale channel_id del sensore WN31 mappato, il ' +
  'microclima corrente come stato mutabile, e un default_wind_m_s di 0.5 m/s per ' +
  'rappresentare il vento minimo convettivo della stanza. Il Pot indoor acquisisce un ' +
  'campo opzionale room_id che lo associa alla sua Room di appartenenza, e un campo ' +
  'opzionale light_exposure che cattura il livello di esposizione luminosa (DARK, ' +
  'INDIRECT_BRIGHT, DIRECT_SUN). Il Garden mantiene una collezione di Room parallela ' +
  'alla collezione di Pot, con i metodi di gestione (add_room, get_room, has_room, ' +
  'remove_room, room_ids, iter_rooms, pots_in_room, num_rooms) e il nuovo metodo ' +
  'apply_step_all_from_indoor che alimenta il bilancio idrico dei vasi indoor dal ' +
  'microclima delle Room invece che dal meteo esterno.'
));

children.push(p(
  'La tappa 5 ha anche aggiunto il supporto al sensore WH52, che è l\u2019upgrade del ' +
  'WH51 e misura non solo l\u2019umidità volumetrica ma anche la temperatura e ' +
  'l\u2019EC del substrato. L\u2019adapter EcowittWH51SoilSensor è parametrizzato con ' +
  'l\u2019argomento model="WH51" o model="WH52" e popola i campi aggiuntivi del ' +
  'SoilReading solo quando il modello è il WH52. Il WH51 continua a essere supportato ' +
  'indefinitamente per compatibilità con chi ce l\u2019ha già installato. Per il ' +
  'sensore ambientale WN31, è stato aggiunto un adapter dedicato ' +
  'EcowittAmbientSensor con due metodi: current_state(channel_id) per la lettura ' +
  'istantanea (kind=INSTANT), e daily_aggregate(channel_id, target_date) per ' +
  'l\u2019aggregato giornaliero (kind=DAILY) che alimenta il bilancio idrico indoor.'
));

children.push(p(
  'Le raffinatezze del modello indoor sono state affrontate con un meccanismo di ' +
  'fallback automatico verso la formula più semplice quando i parametri non sono ' +
  'disponibili. Il riscaldamento è catturato indirettamente attraverso la temperatura ' +
  'misurata dal WN31 (niente da modellare esplicitamente). La ventilazione, che in ' +
  'stanza chiusa è zero, è gestita come "vento minimo convettivo" di 0.5 m/s ' +
  '(default_wind_m_s della Room) per evitare evapotraspirazione irrealisticamente ' +
  'bassa, sovrascrivibile dal chiamante. L\u2019esposizione luminosa è parametrizzata ' +
  'come radiazione solare media giornaliera in MJ/m\u00B2/giorno, con tre livelli ' +
  'preimpostati (DARK \u2248 1.5, INDIRECT_BRIGHT \u2248 4.0, DIRECT_SUN \u2248 8.0) ' +
  'che il giardiniere attribuisce a ogni vaso in base all\u2019osservazione, con la ' +
  'possibilità di passare alla modalità continua (frazione della radiazione outdoor) ' +
  'quando i dati outdoor sono disponibili.'
));

// ---------- Storico delle consegne ESTESO ----------
children.push(h1('Storico delle consegne'));

children.push(p(
  'Lungo la fascia 2 sono stati prodotti diversi pacchetti zip che hanno permesso di ' +
  'sincronizzare progressivamente il repository sul tuo PC con lo stato di sviluppo. ' +
  'Le consegne attuali sono le seguenti, in ordine cronologico.'
));

children.push(makeTable(
  ['Pacchetto / Tag git', 'Tappa', 'Contenuto'],
  [
    ['fitosim_tappa1_fascia2_v2.zip',         '1',     'Astrazione sensori, adapter Open-Meteo, Ecowitt, fixture CSV'],
    ['fitosim_tappa2_fascia2.zip',            '2',     'HttpJsonSoilSensor + firmware ESP32 in 5 file Arduino'],
    ['fitosim_tappa3_complete_fascia2.zip',   '3 A-E', 'Tappa 3 completa: 5 sotto-tappe, 6 file modificati'],
    ['fitosim_tappa3_F_fascia2.zip',          '3 F',   'Coefficiente esposizione pioggia, 2 file modificati'],
    ['fitosim_tappa4_A_fascia2.zip',          '4 A',   'Garden in-memory orchestratore'],
    ['fitosim_tappa4_B1_fascia2.zip',         '4 B1',  'Persistenza SQLite con schema a 8 tabelle'],
    ['fitosim_tappa4_B2_fascia2.zip',         '4 B2',  'Serializzazione JSON come trasporto'],
    ['fitosim_tappa4_C_fascia2.zip',          '4 C',   'Integrazione sensori in batch + migrazione schema v2'],
    ['fitosim_tappa4_D_fascia2.zip',          '4 D',   'Eventi pianificati e forecast + migrazione schema v3'],
    ['fitosim_tappa4_E_fascia2.zip',          '4 E',   'Sistema di allerte con cinque categorie'],
    ['fitosim_tappa4_demo.zip',               'Demo',  'Esempio end-to-end della tappa 4 completa'],
    ['v0_19  (tag git)',                      '5 A',   'Penman-Monteith ET\u2080 come funzioni pure (FAO-56 standard e fisico)'],
    ['v0_19_1 (tag git)',                     '5 B',   'Selettore "best available" compute_et con EtResult/EtMethod'],
    ['v0_19_2 (tag git)',                     '5 C',   'Integrazione del selettore nel Pot e nel Garden via WeatherDay'],
    ['v0_19_3 (tag git)',                     '5 D-1', 'Entit\u00E0 Room con IndoorMicroclimate, MicroclimateKind, LightExposure'],
    ['v0_19_4 (tag git)',                     '5 D-2', 'Bilancio idrico indoor: apply_balance_step_from_indoor sul Pot, modulo science/indoor.py'],
    ['v0_19_5 (tag git)',                     '5 D-3', 'Persistenza Room, EcowittAmbientSensor (WN31), supporto WH52'],
    ['v0_19_6 (tag git)',                     '5 E',   'Demo end-to-end appartamento invernale con quattro grafici PNG di analisi'],
  ],
  [3960, 1080, 4320],
));

children.push(p(
  'I tag git della tappa 5 corrispondono alle sotto-tappe progressive: ognuno aggiunge ' +
  'capacità senza rompere quelle precedenti, esattamente come avveniva con i pacchetti ' +
  'incrementali della tappa 4. Per integrare l\u2019ultimo stato del codice nel ' +
  'repository, basta fare git checkout v0_19_6 (o checkout di main se il main è stato ' +
  'aggiornato). I quattro PNG prodotti dalla demo della sotto-tappa E vivono in ' +
  'examples/ (tappa5_E_andamento_idrico.png, tappa5_E_bilancio_per_ambiente.png, ' +
  'tappa5_E_heatmap_et.png, tappa5_E_metodi_et.png) e mostrano in modo immediato il ' +
  'tipo di analisi che il modello indoor permette.'
));

// ---------- Quadro operativo per il balcone ----------
children.push(h1('Quadro operativo per il tuo balcone (e per il tuo appartamento)'));

children.push(p(
  'Lo stato attuale della libreria ti permette di costruire un dashboard operativo ' +
  'completo non solo per il balcone outdoor ma anche per i vasi indoor sparsi tra le ' +
  'stanze dell\u2019appartamento, con tutte le capacità necessarie. Concretamente puoi ' +
  'fare le cose seguenti.'
));

children.push(p(
  'Puoi creare un Garden col nome del tuo balcone (oppure del tuo appartamento, oppure ' +
  'un Garden ibrido che li copre entrambi) e aggiungere i tuoi vasi reali con tutte le ' +
  'loro caratteristiche (volume, diametro, esposizione al sole, esposizione alla ' +
  'pioggia per i vasi outdoor; room_id e light_exposure per i vasi indoor). Per ogni ' +
  'vaso puoi configurare la specie e il substrato (anche con misture personalizzate), ' +
  'il modello chimico se la specie ha i range definiti, e mappare il vaso al canale ' +
  'del sensore di substrato se ne ha uno collegato (WH51 per il modello base, WH52 ' +
  'per il modello con temperatura ed EC del substrato).'
));

children.push(p(
  'Per i vasi indoor, puoi creare le Room corrispondenti alle stanze del tuo ' +
  'appartamento (per esempio "salotto", "camera-da-letto", "studio") con il loro nome, ' +
  'il channel_id del sensore WN31 ambientale di quella stanza, e l\u2019eventuale ' +
  'default_wind_m_s personalizzato se hai un ventilatore acceso costantemente. I vasi ' +
  'indoor si associano alla loro Room tramite il campo room_id; la libreria gestisce ' +
  'automaticamente l\u2019aggiornamento del microclima della Room dal sensore WN31 e ' +
  'l\u2019applicazione del bilancio idrico ai vasi della Room dal microclima della stanza.'
));

children.push(p(
  'Puoi salvare il Garden in un database SQLite locale che vivrà sul tuo Raspberry Pi ' +
  '5 o sull\u2019Android in Termux. Ogni save_garden aggiunge uno snapshot dello stato ' +
  'dei vasi alla tabella pot_states, preservando la storia per i grafici di evoluzione. ' +
  'Il database persiste anche le Room con i loro parametri e le mappe Pot \u2192 ' +
  'room_id; il Garden può essere esportato in JSON per backup o per migrare tra ' +
  'ambienti, e ricaricato senza perdita di informazioni.'
));

children.push(p(
  'Puoi aggiornare in batch tutti i vasi mappati dai sensori reali con una singola ' +
  'chiamata a update_all_from_sensors, e gestire automaticamente gli errori transitori ' +
  '(batteria scarica del WH51) senza bloccare il sistema. Per i vasi indoor, puoi ' +
  'aggiornare le Room dai sensori WN31 in modo simmetrico tramite ' +
  'EcowittAmbientSensor.daily_aggregate, e poi applicare il bilancio idrico ai vasi ' +
  'della Room con apply_step_all_from_indoor. Puoi pianificare fertirrigazioni e altri ' +
  'eventi futuri come ScheduledEvent, e produrre una previsione dello stato dei vasi a ' +
  'N giorni che incorpora gli eventi pianificati e il forecast meteo da Open-Meteo.'
));

children.push(p(
  'Puoi infine ottenere allerte strutturate sullo stato corrente del giardino ' +
  '(current_alerts), con cinque categorie e tre severità, e allerte previste nei ' +
  'prossimi giorni (forecast_alerts) per una gestione proattiva. Il dashboard "Il Mio ' +
  'Giardino" può presentare al giardiniere queste allerte come notifiche con icone ' +
  'diverse per severità, ognuna con un message descrittivo e una recommended_action ' +
  'concreta da fare.'
));

children.push(p(
  'Quando avrai dati reali raccolti dai tuoi sensori per qualche settimana, ' +
  'cominceremo le prime calibrazioni della fascia 3: confronto sistematico tra ' +
  'previsioni del modello e letture del sensore, identificazione dei parametri (CEC, ' +
  'densità del substrato, range di Kc, frazioni della radiazione indoor, resistenza ' +
  'stomatica delle specie) che producono il fit migliore. È questo che trasforma ' +
  'fitosim da "libreria genericamente plausibile" a "libreria calibrata per il TUO ' +
  'balcone milanese".'
));

// ---------- Considerazioni finali ----------
children.push(h1('Considerazioni finali'));

children.push(p(
  'Il progetto è in salute, e la fascia 2 si chiude in uno stato pulito e coerente. La ' +
  'copertura dei test è alta (1007 verdi, 1 skipped intenzionale, 357 sub-test) e la ' +
  'suite continua a girare in poco più di dieci secondi; la retrocompatibilità è ' +
  'preservata strettamente attraverso tutte le tappe (le 423 prove originali della ' +
  'fascia 1 continuano a passare al byte ad ogni nuova consegna, così come i 442 ' +
  'test delle tappe 1-4); l\u2019architettura modulare con separazione rigorosa tra ' +
  'modello scientifico (modulo science/), oggetti di dominio (modulo domain/) e ' +
  'adapter di acquisizione e persistenza (modulo io/) ha pagato concretamente nelle ' +
  'tappe più complesse, in particolare nella tappa 5 dove l\u2019introduzione di ' +
  'Penman-Monteith e del modello indoor avrebbe richiesto refactoring profondi se ' +
  'l\u2019architettura non fosse stata modulare.'
));

children.push(p(
  'L\u2019aspetto che merita di essere sottolineato dopo la chiusura della fascia 2 ' +
  'è che le decisioni di design prese nelle prime tappe stanno rendendo possibili le ' +
  'tappe successive senza frizioni. Il Protocol dei sensori della tappa 1 ha reso ' +
  'meccanica la scrittura dell\u2019orchestratore update_all_from_sensors della ' +
  'sotto-tappa 4-C, e la stessa cosa è successa per il sensore WN31 ambientale e per ' +
  'l\u2019aggiornamento del microclima delle Room nella sotto-tappa 5-D. La separazione ' +
  'tra apply_balance_step (idrico) e apply_step (orchestratore) ha permesso al forecast ' +
  'della sotto-tappa 4-D di applicare tutti gli eventi del giorno simulato senza ' +
  'riimplementare nessuna logica scientifica, e ha permesso al apply_balance_step_from_indoor ' +
  'della sotto-tappa 5-D di alimentare il bilancio idrico dal microclima della Room ' +
  'senza toccare nulla del modello scientifico sottostante. È un esempio concreto di ' +
  'come il lavoro architetturale ben fatto all\u2019inizio paghi nel medio termine.'
));

children.push(p(
  'I prossimi passi sono nell\u2019ordine di importanza decrescente. Il primo è ' +
  'consolidare lo stato attuale facendolo girare in produzione sul Raspberry Pi 5 (o ' +
  'sull\u2019Android in Termux) con i vasi reali del tuo balcone e del tuo ' +
  'appartamento, e raccogliere dati dai sensori reali per qualche settimana. Il ' +
  'secondo è eseguire la demo end-to-end dell\u2019appartamento invernale ' +
  '(tappa5_E_appartamento_demo.py) per avere un\u2019intuizione concreta di come il ' +
  'modello indoor risponde a scenari diversi (microclima freddo vs caldo, esposizione ' +
  'luminosa diversa, presenza/assenza di sensori). Il terzo è cominciare a costruire ' +
  'il dashboard operativo "Il Mio Giardino" con i vasi reali, salvando lo stato in ' +
  'SQLite e raccogliendo i primi dati dal sensore ATO via gateway ESP32 quando ' +
  'l\u2019hardware sarà operativo. Il quarto è aprire la fascia 3 di calibrazione ' +
  'quando avremo qualche mese di dati reali raccolti, per raffinare i numeri specifici ' +
  'del modello (frazioni della radiazione indoor, parametri Kc del catalogo specie, ' +
  'soglie del selettore, resistenza stomatica delle specie con dati reali) e ' +
  'trasformare fitosim da "libreria genericamente plausibile" a "libreria calibrata ' +
  'per il TUO balcone milanese".'
));

// =====================================================================
//  Costruzione del documento
// =====================================================================

const doc = new Document({
  creator: 'Andrea Ceriani',
  title: 'fitosim — Status Report (fine tappa 5)',
  description: 'Rapporto di stato del progetto fitosim, fine tappa 5 fascia 2',
  styles: {
    default: { document: { run: { font: 'Calibri', size: 22 } } },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal',
        quickFormat: true,
        run: { size: 32, bold: true, font: 'Calibri', color: '1F3864' },
        paragraph: { spacing: { before: 360, after: 180 }, outlineLevel: 0 },
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal',
        quickFormat: true,
        run: { size: 26, bold: true, font: 'Calibri', color: '2E75B6' },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 },
      },
    ],
  },
  numbering: {
    config: [{
      reference: 'bullets',
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: '\u2022',
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },  // A4
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/home/claude/fitosim/fitosim/docs/fitosim_status_report.docx', buf);
  console.log('Status report scritto: ' + buf.length + ' byte');
});
