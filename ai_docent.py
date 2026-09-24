import streamlit as st
import re
import json
from config import ai_client

def extract_json(raw_text):
    """Filtert puur het JSON object uit de AI output, zelfs als de AI er markdown (```json) omheen zet."""
    match = re.search(r'```json(.*?)```', raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(raw_text.strip())

@st.cache_data(show_spinner=False)
def genereer_toets_gecached(les_tekst, niveau, versie):
    """Fase 1: Gebruikt Flash-Lite om een overhoring te genereren (gecached per les, niveau en versie)."""
    json_prompt = f"""Je bent docent aardrijkskunde (bovenbouw {niveau}). 
    Genereer toetsversie {versie} op basis van de theorie. Zorg dat de vragen wezenlijk anders zijn dan andere versies.
    
    EISEN:
    - Maak EXACT 4 meerkeuzevragen (Onthouden/Begrijpen). 4 opties (A, B, C, D). Geef het correcte antwoord (alleen de hoofdletter).
    - Maak EXACT 2 open vragen (Inzicht/Toepassing).
    
    UITVOERFORMAAT (Strikt JSON):
    {{
        "vragen": [
            {{"id": 1, "type": "mc", "vraag": "[vraagtekst]", "opties": ["A) [optie]", "B) [optie]", "C) [optie]", "D) [optie]"], "correct": "A"}},
            {{"id": 2, "type": "mc", "vraag": "[vraagtekst]", "opties": ["A) [optie]", "B) [optie]", "C) [optie]", "D) [optie]"], "correct": "B"}},
            {{"id": 3, "type": "mc", "vraag": "[vraagtekst]", "opties": ["A) [optie]", "B) [optie]", "C) [optie]", "D) [optie]"], "correct": "C"}},
            {{"id": 4, "type": "mc", "vraag": "[vraagtekst]", "opties": ["A) [optie]", "B) [optie]", "C) [optie]", "D) [optie]"], "correct": "D"}},
            {{"id": 5, "type": "open", "vraag": "[open vraag 1]"}},
            {{"id": 6, "type": "open", "vraag": "[open vraag 2]"}}
        ]
    }}

    --- THEORIE ---
    {les_tekst}
    """
    response = ai_client.models.generate_content(model='gemini-3.5-flash-lite', contents=json_prompt)
    return extract_json(response.text)

def kijk_toets_na(niveau, voornaam, les_tekst, vragen_data, antwoorden):
    """Fase 3: Kijkt MC lokaal na en gebruikt Gemini Pro voor de open vragen."""
    mc_score = 0.0
    mc_feedback = ""
    open_vragen_text = ""
    
    # 1. Kijk MC lokaal na via Python (1 pt per vraag)
    for idx, v in enumerate(vragen_data.get("vragen", [])):
        gegeven = antwoorden.get(v['id'], '')
        if v.get('type') == 'mc':
            correcte_letter = v.get('correct', '').strip().upper()
            is_goed = gegeven.strip().upper().startswith(correcte_letter)
            if is_goed:
                mc_score += 1.0
                mc_feedback += f"**Vraag {idx + 1} (MC):** ✅ Goed antwoord ({correcte_letter}).\n\n"
            else:
                mc_feedback += f"**Vraag {idx + 1} (MC):** ❌ Fout. Je koos '{gegeven}', het juiste antwoord was {correcte_letter}.\n\n"
        else:
            open_vragen_text += f"Vraag {idx + 1}: {v.get('vraag')}\nGegeven antwoord: {gegeven}\n\n"
            
    # 2. Laat AI (Pro model) de open vragen nakijken
    prompt_nakijken = f"""Je bent docent aardrijkskunde ({niveau}). Beoordeel onderstaande 2 open vragen van leerling {voornaam}.
    Elke open vraag is maximaal 3.0 punten waard. Wees coulant op begrip en synoniemen. Deel halve punten uit bij een deels correct antwoord. Trek 0.1 punt af per spelfout (max 1 pt aftrek).

    UITVOERFORMAAT (Strikt JSON):
    {{
        "beoordeling_open_vragen": "**Vraag 5 (Open):** [score]/3.0pt - [korte uitleg]\\n\\n**Vraag 6 (Open):** [score]/3.0pt - [korte uitleg]",
        "score_open_vragen_totaal": [getal tussen 0.0 en 6.0],
        "docenten_feedback": "[Max 2 zinnen met globale positieve feedback over de gehele inzet]"
    }}

    --- THEORIE ---
    {les_tekst}
    
    --- ANTWOORDEN ---
    {open_vragen_text}
    """
    
    resp = ai_client.models.generate_content(model='gemini-3.1-pro', contents=prompt_nakijken)
    ai_eval = extract_json(resp.text)
    
    open_score = float(ai_eval.get("score_open_vragen_totaal", 0.0))
    totaal_score = mc_score + open_score
    
    volledige_feedback = mc_feedback + ai_eval.get("beoordeling_open_vragen", "")
    ai_docent_tekst = ai_eval.get("docenten_feedback", "Toets afgerond.")
    
    return totaal_score, volledige_feedback, ai_docent_tekst
