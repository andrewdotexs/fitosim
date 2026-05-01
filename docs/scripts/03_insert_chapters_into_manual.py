"""
Inserimento dei nuovi capitoli (cap. 17 + 18 della tappa 5) nel manuale
fitosim_user_manual.docx già decompattato in /home/claude/manual_unpacked/.

Prerequisiti:
  1) Aver decompattato il manuale originale con:
       python3 /mnt/skills/public/docx/scripts/office/unpack.py \
           /percorso/fitosim_user_manual.docx /home/claude/manual_unpacked/
  2) Aver generato il blocco XML dei nuovi capitoli con:
       python3 02_build_new_chapters.py
     che produce /home/claude/new_chapters.xml.
  3) Aver applicato i piccoli str_replace puntuali al document.xml
     (sottotitolo della copertina, numeri di test, mappa del manuale,
     FAQ "Le mie piante sono indoor"). Vedi 04_manual_str_replaces.md.

Cosa fa questo script:
  - Localizza nel document.xml il paragrafo che contiene "17 — Domande
    frequenti" (il vecchio capitolo FAQ).
  - Cambia il numero del titolo da "17 —" a "19 —".
  - Inserisce il blocco XML dei due nuovi capitoli IMMEDIATAMENTE PRIMA
    del paragrafo del cap FAQ.
  - Salva in place il document.xml modificato.

Dopo questo script:
  python3 /mnt/skills/public/docx/scripts/office/pack.py \
      /home/claude/manual_unpacked/ /percorso/fitosim_user_manual.docx \
      --original /percorso/fitosim_user_manual_originale.docx
"""

DOC_PATH = "/home/claude/manual_unpacked/word/document.xml"
NEW_CHAPTERS_PATH = "/home/claude/new_chapters.xml"


def main() -> None:
    with open(DOC_PATH, "r", encoding="utf-8") as f:
        doc_xml = f.read()

    with open(NEW_CHAPTERS_PATH, "r", encoding="utf-8") as f:
        new_xml = f.read()

    # ------------------------------------------------------------------
    # Step 1 — localizzo il paragrafo del vecchio cap "17 — Domande
    # frequenti". Il marker include il trattino lungo (—, U+2014).
    # ------------------------------------------------------------------
    marker = "<w:t>17 — Domande frequenti</w:t>"
    occ = doc_xml.count(marker)
    assert occ == 1, f"Marker trovato {occ} volte (atteso: 1)."

    # Il <w:p> che contiene quel marker ha un paraId univoco che il
    # manuale originale ha generato. Lo uso come ancora per trovare
    # l'inizio dell'intero paragrafo.
    faq_p_start_marker = '<w:p w14:paraId="09724AA4"'
    occ2 = doc_xml.count(faq_p_start_marker)
    assert occ2 == 1, f"Ancora paraId trovata {occ2} volte (atteso: 1)."

    # ------------------------------------------------------------------
    # Step 2 — rinumero il titolo del cap FAQ: "17 —" → "19 —".
    # Lo faccio prima dell'inserzione perché lavora su un marker corto
    # e univoco; dopo l'inserzione il marker sarebbe duplicato (i nuovi
    # capitoli si chiamano "17 —" e "18 —").
    # ------------------------------------------------------------------
    new_marker = "<w:t>19 — Domande frequenti</w:t>"
    doc_xml = doc_xml.replace(marker, new_marker)
    assert doc_xml.count(new_marker) == 1
    assert doc_xml.count(marker) == 0

    # ------------------------------------------------------------------
    # Step 3 — inserisco il blocco dei nuovi capitoli IMMEDIATAMENTE
    # PRIMA del paragrafo del cap FAQ (che è ancora individuabile dal
    # paraId, perché ho cambiato solo il <w:t>, non il paraId del <w:p>).
    #
    # Strategia: trovo l'inizio della riga in cui inizia il <w:p> del
    # cap FAQ (per preservare l'indentazione XML del file) e inserisco
    # il blocco esattamente lì. Le righe di new_chapters.xml sono già
    # indentate con 4 spazi, che è la stessa indentazione del manuale.
    # ------------------------------------------------------------------
    faq_p_start = doc_xml.find(faq_p_start_marker)
    line_start = doc_xml.rfind("\n", 0, faq_p_start) + 1

    doc_xml_new = (
        doc_xml[:line_start]
        + new_xml
        + doc_xml[line_start:]
    )

    # ------------------------------------------------------------------
    # Step 4 — salvo in place.
    # ------------------------------------------------------------------
    with open(DOC_PATH, "w", encoding="utf-8") as f:
        f.write(doc_xml_new)

    print(f"Documento aggiornato:")
    print(f"  prima:  {len(doc_xml):>9} caratteri")
    print(f"  dopo:   {len(doc_xml_new):>9} caratteri")
    print(f"  delta:  +{len(doc_xml_new) - len(doc_xml):>8} caratteri "
          f"(blocco inserito: {len(new_xml)})")


if __name__ == "__main__":
    main()
