import streamlit as st
from google import genai
import datetime
import os
import docx
import pandas as pd
import re
import requests # Nodig voor de dagelijkse foto

# 1. API instellen
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# Functie om de Picture of the Day op te halen
@st.cache_data(ttl=43200) # Sla de foto 12 uur op in het geheugen
def haal_wikimedia_potd_url_op():
    vandaag = datetime.datetime.now().strftime('%Y-%m-%d')
    api_url = f"https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&generator=images&titles=Template:Potd/{vandaag}&iiprop=url"
    standaard_bg = "https://images.unsplash.com/photo-1614730321146-b6fa6a46bcb4?q=80&w=2000&auto=format&fit=crop"
    
    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id, info in pages.items():
                if "imageinfo" in info:
                    url = info["imageinfo"][0].get("url")
                    if url:
                        return url
    except Exception:
        pass
        
    return standaard_bg

achtergrond_url = haal_wikimedia_potd_url_op()

# CSS voor de dynamische achtergrond
achtergrond_css = f"""
<style>
.stApp {{
    background-image: linear-gradient(rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.85)), url("{achtergrond_url}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}}
</style>
"""
st.markdown(achtergrond_css, unsafe_allow_html=True)

# --- HELPER FUNCTIES ---
def lees_docx(file_path):
    doc = docx.Document(file_path)
    volledige_tekst = [para.text for para in doc.paragraphs]
    return "\n".join(volledige_tekst)

def sla_resultaat_op(cluster, voornaam, gekozen_les, cijfer, beoordeling):
    excel_bestand = f"Resultaten_{cluster}.xlsx"
    tabblad_naam = re.sub(r'[\[\]\:\*\?/\\]', '', gekozen_les.replace('.docx', ''))[:31]
    
    nieuw_resultaat = pd.DataFrame([{
        "Tijdstip": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        "Voornaam": voornaam,
        "Les": gekozen_les,
        "Cijfer": cijfer,
        "Beoordeling (Feedback AI)": beoordeling
    }])
    
    if os.path.exists(excel_bestand):
        try:
            alle_data = pd.read_excel(excel_bestand, sheet_name=None)
            if tabblad_naam in alle_data:
                alle_data[tabblad_naam] = pd.concat([alle_data[tabblad_naam], nieuw_resultaat], ignore_index=True)
            else:
                alle_data[tabblad_naam] = nieuw_resultaat
        except Exception:
            alle_data = {tabblad_naam: nieuw_resultaat}
    else:
        alle_data = {tabblad_naam: nieuw_resultaat}
        
    with pd.ExcelWriter(excel_bestand, engine='openpyxl') as writer:
        for sheet_name, df_sheet in alle_data.items():
            df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)

# --- ZIJBALK: STUDENTEN VOORTGANG & INLEVEREN ---
if "actieve_voornaam" in st.session_state and st.session_state.actieve_voornaam:
    st.sidebar.header("🎓 Jouw Voortgang")
    huidig_cijfer = st.session_state.get("huidig_cijfer", 10.0)
    st.sidebar.metric(label="Voorlopig cijfer", value=f"{huidig_cijfer:.1f}")
    
    if st.sidebar.button("📥 Nu Inleveren", type="primary"):
        # Verzamel laatste AI bericht als beoordeling
        laatste_beoordeling = "Geen verdere feedback."
        if "berichten" in st.session_state and len(st.session_state.berichten) > 0:
            for rol, tekst in reversed(st.session_state.berichten):
                if rol == "assistant":
                    laatste_beoordeling = re.sub(r'\[(VOORLOPIG_)?CIJFER:\s*([\-\d\,\.]+)\]', '', tekst).replace("[EINDE_OVERHORING]", "").strip()
                    break
        
        sla_resultaat_op(
            st.session_state.actief_cluster,
            st.session_state.actieve_voornaam,
            st.session_state.huidige_les,
            huidig_cijfer,
            laatste_beoordeling
        )
        if huidig_cijfer >= 6.0:
            st.sidebar.success("✅ Ingeleverd! Je resultaat is opgeslagen.")
            st.balloons()
        else:
            st.sidebar.success("✅ Ingeleverd! Je resultaat is opgeslagen.")

# --- HOOFDSCHERM ---
st.title("🗺️ Formatieve toets Aardrijkskunde (Havo)")
st.markdown("Welkom! Vul je gegevens hieronder in om te beginnen met je overhoring.")

les_map = "lesmateriaal Havo"
if not os.path.exists(les_map):
    os.makedirs(les_map)

beschikbare_bestanden = [f for f in os.listdir(les_map) if f.endswith('.docx')]

if not beschikbare_bestanden:
    st.warning("Er is op dit moment geen lesmateriaal beschikbaar. Stuur even een mailtje naar je docent.")
else:
    st.header("📝 Jouw Gegevens")
    gekozen_les = st.selectbox("Kies de les die je wilt oefenen:", beschikbare_bestanden)
    
    cluster_opties = ["4Hak1", "4Hak2", "4Hak3", "4Hak4", "5Hak1", "5Hak2", "5Hak3"]
    cluster = st.selectbox("Kies je cluster:", cluster_opties)
    
    voornaam = st.text_input("Vul je voornaam in om te beginnen:")
    
    st.divider()

    if voornaam and cluster and gekozen_les:
        if ("huidige_les" not in st.session_state or 
            st.session_state.huidige_les != gekozen_les or 
            st.session_state.get("actieve_voornaam") != voornaam or
            st.session_state.get("actief_cluster") != cluster):
            
            st.session_state.huidige_les = gekozen_les
            st.session_state.actieve_voornaam = voornaam
            st.session_state.actief_cluster = cluster
            st.session_state.berichten = [] 
            st.session_state.chat = None
            st.session_state.huidig_cijfer = 10.0 # Reset het cijfer
            
            les_pad = os.path.join(les_map, gekozen_les)
            les_tekst = ""

            with st.spinner("De docent neemt de theorie door... Een moment geduld aub."):
                try:
                    les_tekst = lees_docx(les_pad)
                except Exception as e:
                    st.error(f"Er ging iets mis met het lezen van het bestand: {e}")

            if les_tekst:
                eerste_input = f"""
Je bent docent aardrijkskunde (bovenbouw Havo). Toon: professioneel, zakelijk, maar wel aanmoedigend.
Baseer de ONDERWERPEN op de theorie. Geef NOOIT zelf direct het antwoord (behalve als een leerling een vraag definitief fout heeft).

--- START THEORIE ---
{les_tekst}
--- EINDE THEORIE ---

Volg EXACT deze chronologische structuur:

**Fase 1: Intro**
1. Zakelijke groet.
2. Geef een duidelijke waarschuwing: "Let op: let goed op je spelling, want spelfouten leiden tot puntaftrek!"
3. Vraag daarna of het boek dicht is door de leerling deze 3 opties te geven in een lijstje:
   [A] Ik heb de stof bestudeerd en ik ga het helemaal zelf doen.
   [B] Ik heb de stof niet bestudeerd, maar ik ga het gewoon proberen.
   [C] Nee, ik wil stoppen.
   Vraag de leerling expliciet om 'A', 'B' of 'C' te typen. Wacht op het antwoord voor je verdergaat.

**Fase 2: Overhoring (EXACT 5 vragen: 2 reproductie, 3 inzicht)**
- ZET ONDERAAN ELK BERICHT HET HUIDIGE CIJFER: Dit doe je EXACT als volgt: [VOORLOPIG_CIJFER: X] (waarbij X het huidige cijfer is). Start op 10.0.
- STOPPEN: Kiest de leerling optie C of typt hij "stop"? Breek alles dan af! Zeg UITSLUITEND: "Ga de stof nogmaals bestuderen en probeer het dan nog eens! [EINDE_OVERHORING]"
- CIJFER BIJHOUDEN: Start op 10.0. Helemaal fout = -2. Spelfout = -0.5 (max -2 aftrek voor spelling in totaal). Cijfer mag negatief zijn.
- COULANT NAKIJKEN (HUISWERKCONTROLE): Dit is een huiswerkcontrole, geen formele toets. Reken een antwoord GOED (geen aftrek) als de leerling laat zien dat hij/zij het snapt, zelfs als het antwoord niet helemáál volledig is. Geef in dat geval wél direct als feedback wat het volledige antwoord had moeten zijn, en ga daarna door naar de volgende vraag.
- ZINSBOUW: Een antwoord is qua formulering akkoord zolang het minimaal een onderwerp en één of meerdere werkwoorden bevat.
- Reproductie: Vraag ALTIJD "Wat betekent [begrip]?".
- 1 vraag tegelijk. Wacht op antwoord.
- SPELLING: Corrigeer spelfouten direct, benoem ze kort, en tel de aftrek mee.
- FOUT: Is het antwoord echt onjuist? De leerling krijgt 1 herkansing per vraag. Wéér fout? Reken fout (-2), geef het goede antwoord en ga door naar de VOLGENDE vraag. Altijd 5 vragen behandelen.

**Fase 3: Afronding**
1. Zodra alle 5 vragen zijn geweest, vraag je EERST hoe de leerling de toets gemaakt heeft met deze 2 opties:
   [A] Ik heb het helemaal op eigen kracht gedaan.
   [B] Ik heb helaas vals moeten spelen om het te halen.
   Vraag de leerling om 'A' of 'B' te typen en wacht op antwoord.
2. Na hun antwoord: Geef gerichte feedback en laat de score-berekening zien.
3. Sluit je bericht af met EXACT: [EINDE_OVERHORING].
"""
                try:
                    chat = client.chats.create(model="gemini-1.5-flash")
                    st.session_state.chat = chat
                    response = chat.send_message(eerste_input)
                    st.session_state.berichten.append(("assistant", response.text))
                except Exception as e:
                    st.error(f"🚨 Fout bij het starten van de AI-docent: {e}")
                    st.info("Tip: Controleer of je API-key correct is ingesteld in de Streamlit Secrets.")
                    st.session_state.chat = None
                    st.stop()

        if "berichten" in st.session_state:
            for role, text in st.session_state.berichten:
                avatar_icoon = "🧑‍🏫" if role == "assistant" else "🎓"
                # Verberg de tags voor de gebruiker
                weergave_tekst = re.sub(r'\[(VOORLOPIG_)?CIJFER:\s*([\-\d\,\.]+)\]', '', text)
                weergave_tekst = weergave_tekst.replace("[EINDE_OVERHORING]", "")
                with st.chat_message(role, avatar=avatar_icoon):
                    st.markdown(weergave_tekst.strip())

        prompt = st.chat_input("Typ hier je antwoord of keuze...")

        if prompt and "chat" in st.session_state and st.session_state.chat is not None:
            st.session_state.berichten.append(("user", prompt))
            with st.chat_message("user", avatar="🎓"):
                st.markdown(prompt)
            
            with st.spinner("De docent schrijft een reactie..."):
                try:
                    vervolg_response = st.session_state.chat.send_message(prompt)
                    output_tekst = vervolg_response.text
                except Exception as e:
                    st.error(f"🚨 Oeps, de verbinding met de AI haperde even: {e}")
                    st.stop()
            
            st.session_state.berichten.append(("assistant", output_tekst))
            
            # Controleer of er een voorlopig cijfer in zit
            cijfer_match = re.search(r'\[VOORLOPIG_CIJFER:\s*([\-\d\,\.]+)\]', output_tekst)
            if cijfer_match:
                try:
                    st.session_state.huidig_cijfer = float(cijfer_match.group(1).replace(',', '.'))
                except ValueError:
                    pass

            # Opschonen voor weergave
            weergave_tekst_bot = re.sub(r'\[(VOORLOPIG_)?CIJFER:\s*([\-\d\,\.]+)\]', '', output_tekst)
            weergave_tekst_bot = weergave_tekst_bot.replace("[EINDE_OVERHORING]", "")
            
            with st.chat_message("assistant", avatar="🧑‍🏫"):
                st.markdown(weergave_tekst_bot.strip())
                
            # Automatisch opslaan bij einde overhoring
            if "[EINDE_OVERHORING]" in output_tekst:
                schone_beoordeling = weergave_tekst_bot.strip()
                cijfer = st.session_state.huidig_cijfer
                
                sla_resultaat_op(cluster, voornaam, gekozen_les, cijfer, schone_beoordeling)
                
                if "Ga de stof nogmaals bestuderen" in output_tekst:
                    st.info("De overhoring is afgebroken. Succes met studeren en tot de volgende keer!")
                else:
                    if cijfer >= 6.0:
                        st.balloons()
                        st.success("🎉 Goed gewerkt, je hebt een voldoende! Je resultaten zijn automatisch opgeslagen.")
                    else:
                        st.success("✅ Je resultaten zijn automatisch opgeslagen. Volgende keer gaat het vast beter!")
            
            # Trik om de UI te updaten (cijfer in zijbalk)
            st.rerun()

# --- DOCENTENPANEEL ---
st.sidebar.divider()
st.sidebar.header("👨‍🏫 Docentenpaneel (Havo)")

wachtwoord = st.sidebar.text_input("Wachtwoord docent:", type="password")

if wachtwoord == "PieterZandt2026!": 
    
    st.sidebar.subheader("📊 Resultaten Beheren")
    beheer_cluster = st.sidebar.selectbox("Kies het cluster dat je wilt bekijken:", cluster_opties)
    
    excel_bestand = f"Resultaten_{beheer_cluster}.xlsx"

    if os.path.exists(excel_bestand):
        try:
            alle_data = pd.read_excel(excel_bestand, sheet_name=None)
            df_all = pd.concat(alle_data.values(), ignore_index=True)
            df_all['Cijfer'] = pd.to_numeric(df_all['Cijfer'], errors='coerce')
            
            gemiddelde = df_all['Cijfer'].mean()
            st.sidebar.metric(label=f"Gemiddeld Cijfer ({beheer_cluster})", value=f"{gemiddelde:.1f}")
            
            st.sidebar.write("**Aantal deelnames per paragraaf/les:**")
            st.sidebar.dataframe(df_all['Les'].value_counts(), use_container_width=True)
            
            st.sidebar.divider()
            
            st.sidebar.subheader("📥 Exporteren")
            with open(excel_bestand, "rb") as file:
                st.sidebar.download_button(
                    label=f"Download Resultaten {beheer_cluster}",
                    data=file,
                    file_name=f"Resultaten_{beheer_cluster}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
            st.sidebar.divider()
            
            st.sidebar.subheader("🗑️ Wissen")
            st.sidebar.write(f"Verwijder alle oude resultaten van **{beheer_cluster}** om opnieuw te beginnen.")
            
            bevestiging = st.sidebar.checkbox(f"Ja, ik wil de resultaten van {beheer_cluster} wissen")
            
            if bevestiging:
                if st.sidebar.button(f"🚨 Wis {beheer_cluster} resultaten", type="primary"):
                    os.remove(excel_bestand)
                    st.sidebar.success(f"Resultaten van {beheer_cluster} succesvol gewist!")
                    st.rerun()

        except Exception as e:
            st.sidebar.error(f"Fout bij het lezen van Excel: {e}")
            if st.sidebar.button("Forceer wissen corrupt bestand"):
                os.remove(excel_bestand)
                st.rerun()
    else:
        st.sidebar.info(f"Er zijn nog geen resultaten voor cluster {beheer_cluster}.")

    st.sidebar.divider()

    st.sidebar.subheader("📄 Nieuwe Havo les uploaden")
    st.sidebar.write("Voeg direct een nieuw Word-document toe aan het keuzemenu.")
    
    uploaded_file = st.sidebar.file_uploader("Kies een .docx bestand", type=["docx"])
    
    if uploaded_file is not None:
        file_path = os.path.join(les_map, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        st.sidebar.success(f"✅ '{uploaded_file.name}' is geüpload!")
        
        if st.sidebar.button("Vernieuw app om les te tonen"):
            st.rerun()

elif wachtwoord != "":
    st.sidebar.error("Onjuist wachtwoord.")
