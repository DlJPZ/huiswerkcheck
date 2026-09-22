import streamlit as st
from google import genai
import datetime
import os
import docx
import pandas as pd
import re
import uuid
import bcrypt
import time
import json
import hmac

# 0. Paginainstellingen & Constanten
st.set_page_config(page_title="Huiswerkcontrole AK", layout="wide")
LAATSTE_UPDATE = "22 september 2026"
VERSIE = "3.0.8"

# 1. API & Cloud instellen
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

api_key = st.secrets["GEMINI_API_KEY"].replace('"', '').replace("'", "").strip()
os.environ["GEMINI_API_KEY"] = api_key

if "ai_client" not in st.session_state:
    st.session_state.ai_client = genai.Client(api_key=api_key)
client = st.session_state.ai_client

# 2. Supabase Connectie (Strikt Vereist)
try:
    from supabase import create_client, Client
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"🚨 Fout bij initialiseren van Supabase. Controleer Streamlit Secrets. Error: {e}")
    st.stop()

# --- STRUCTUUR DEFINIËREN ---
NIVEAUS = {
    "Havo": ["4Hak1", "4Hak2", "4Hak3", "4Hak4", "5Hak1", "5Hak2", "5Hak3"],
    "VWO": ["4Vak1", "5Vak1", "5Vak2", "6Vak1"],
    "Test": ["testklas"]
}
ALLE_CLUSTERS = [klas for klassen in NIVEAUS.values() for klas in klassen]

LEERJAREN_CLUSTERS = {
    "4Havo": ["4Hak1", "4Hak2", "4Hak3", "4Hak4"],
    "5Havo": ["5Hak1", "5Hak2", "5Hak3"],
    "4VWO": ["4Vak1"],
    "5VWO": ["5Vak1", "5Vak2"],
    "6VWO": ["6Vak1"],
    "Testjaar": ["testklas"]
}

HOOFDSTUKKEN = {
    "4Havo": ["H4H1", "H4H2", "H4H3", "H4H4", "H5H1"],
    "5Havo": ["H5H2", "H5H3", "HExamentraining"],
    "4VWO": ["V5H1", "V5H2", "V5H3", "V5H4"],
    "5VWO": ["V4H1", "V4H2", "V4H3", "V6H1"],
    "6VWO": ["V6H2", "V6H3", "VExamentraining"],
    "Testjaar": ["TestMap"]
}

# --- HELPER FUNCTIES CLOUD & DATA ---
def get_leerjaar(cluster_naam):
    for lj, clusters in LEERJAREN_CLUSTERS.items():
        if cluster_naam in clusters:
            return lj
    return None

def haal_bestanden_op(leerjaar, hoofdstuk):
    try:
        pad = f"{leerjaar}/{hoofdstuk}"
        bestanden = supabase.storage.from_("lesmateriaal").list(pad)
        return [b["name"] for b in bestanden if b["name"].endswith('.docx')]
    except Exception:
        return []

def lees_docx(leerjaar, hoofdstuk, bestandsnaam):
    try:
        pad = f"{leerjaar}/{hoofdstuk}/{bestandsnaam}"
        response = supabase.storage.from_("lesmateriaal").download(pad)
        doc = docx.Document(io.BytesIO(response))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        st.error(f"Fout bij lezen uit Supabase: {e}")
        return ""

def haal_alle_resultaten_op():
    try:
        resp = supabase.table("resultaten").select("*").execute()
        return pd.DataFrame(resp.data)
    except Exception as e:
        st.error(f"Fout bij ophalen resultaten: {e}")
        return pd.DataFrame()

def sla_resultaat_op(niveau, cluster, nummer, voornaam, gebruikersnaam, gekozen_les, cijfer, beoordeling, boek_dicht):
    tijdstip = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    poging_id = str(uuid.uuid4())[:8] 
    
    data = {
        "PogingID": poging_id,
        "Tijdstip": tijdstip,
        "Niveau": niveau,
        "Cluster": cluster,
        "Nummer": nummer,
        "Gebruikersnaam": gebruikersnaam,
        "Voornaam": voornaam,
        "Les": gekozen_les,
        "Cijfer": cijfer,
        "Beoordeling": beoordeling,
        "DocentReactie": "",
        "ReactieGelezen": "True",
        "BoekDicht": boek_dicht
    }
    try:
        supabase.table("resultaten").insert(data).execute()
        return True, ""
    except Exception as e:
        return False, str(e)

# --- ACCOUNT & SECURITY FUNCTIES ---
def hash_wachtwoord(wachtwoord):
    return bcrypt.hashpw(wachtwoord.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def controleer_wachtwoord(ingevoerd_wachtwoord, opgeslagen_hash):
    try:
        return bcrypt.checkpw(ingevoerd_wachtwoord.encode('utf-8'), opgeslagen_hash.encode('utf-8'))
    except ValueError:
        return False 

def is_sterk_wachtwoord(wachtwoord):
    if len(wachtwoord) < 8: return False, "Minimaal 8 tekens lang."
    if not re.search(r'\d', wachtwoord): return False, "Minimaal 1 cijfer vereist."
    if not re.search(r'[^a-zA-Z0-9]', wachtwoord): return False, "Minimaal 1 speciaal teken vereist."
    return True, ""

def init_lockout_keys(prefix):
    if f"login_pogingen_{prefix}" not in st.session_state:
        st.session_state[f"login_pogingen_{prefix}"] = 0
    if f"lockout_time_{prefix}" not in st.session_state:
        st.session_state[f"lockout_time_{prefix}"] = 0

def check_lockout(prefix):
    init_lockout_keys(prefix)
    if st.session_state[f"login_pogingen_{prefix}"] >= 5:
        if time.time() < st.session_state[f"lockout_time_{prefix}"]:
            resterend = int(st.session_state[f"lockout_time_{prefix}"] - time.time())
            st.error(f"🔒 Te veel mislukte inlogpogingen. Probeer het over {resterend} seconden opnieuw.")
            return True
        else:
            st.session_state[f"login_pogingen_{prefix}"] = 0
            st.session_state[f"lockout_time_{prefix}"] = 0
    return False

def registreer_fout_inlog(prefix):
    init_lockout_keys(prefix)
    st.session_state[f"login_pogingen_{prefix}"] += 1
    if st.session_state[f"login_pogingen_{prefix}"] >= 5:
        st.session_state[f"lockout_time_{prefix}"] = time.time() + 300 

def laad_gebruikers():
    try:
        response = supabase.table('gebruikers').select("*").execute()
        users = {}
        for row in response.data:
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            if "Nummer" not in row: row["Nummer"] = "999"
            users[row["Gebruikersnaam"]] = row
        return users
    except Exception as e:
        st.warning(f"Cloud gebruikers ophalen mislukt: {e}")
        return {}

def bewaar_alle_gebruikers(users_dict):
    fouten = []
    for user in users_dict.values():
        try:
            supabase.table('gebruikers').upsert(user).execute()
        except Exception as e:
            fouten.append(str(e))
    if fouten:
        st.error(f"🚨 Supabase Fout bij opslaan gebruikers: {fouten[0]}")

def laad_docenten():
    try:
        response = supabase.table('docenten').select("*").execute()
        docs = {}
        for row in response.data:
            k = row.get("Klassen", "")
            if isinstance(k, str):
                row["Klassen"] = k.split(",") if k else []
            elif isinstance(k, list):
                row["Klassen"] = k
            else:
                row["Klassen"] = []
                
            if "Goedgekeurd" not in row: row["Goedgekeurd"] = "Ja"
            docs[row["DocentID"]] = row
        return docs
    except Exception as e:
        st.warning(f"Cloud docenten ophalen mislukt: {e}")
        return {}

def bewaar_alle_docenten(docs_dict):
    fouten = []
    for doc_data in docs_dict.values():
        save_data = doc_data.copy()
        if isinstance(save_data.get("Klassen"), list):
            save_data["Klassen"] = ",".join(save_data["Klassen"])
        try:
            supabase.table('docenten').upsert(save_data).execute()
        except Exception as e:
            fouten.append(str(e))
    if fouten:
        st.error(f"Cloud opslag fout (Docenten): {fouten[0]}")

def extract_json(raw_text):
    match = re.search(r'```json(.*?)```', raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())
    return json.loads(raw_text.strip())

@st.cache_data(show_spinner=False)
def genereer_toets_gecached(les_tekst, niveau, versie):
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
    # FASE 1: Gebruikt de snelle, voordelige Flash-Lite voor formatteren
    response = client.models.generate_content(model='gemini-3.5-flash-lite', contents=json_prompt)
    return extract_json(response.text)

# Functie om de Picture of the Day op te halen
@st.cache_data(ttl=43200)
def haal_wikimedia_potd_url_op():
    vandaag = datetime.datetime.now().strftime('%Y-%m-%d')
    api_url = f"https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&generator=images&titles=Template:Potd/{vandaag}&iiprop=url"
    standaard_bg = "https://images.unsplash.com/photo-1614730321146-b6fa6a46bcb4?q=80&w=2000&auto=format&fit=crop"
    
    headers = {'User-Agent': 'HuiswerkCheckerApp/1.0 (docent@voorbeeld.nl)'}
    try:
        response = requests.get(api_url, headers=headers, timeout=5)
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

# --- OPTIE 1: Frosted Glass Achtergrond CSS ---
achtergrond_css = f"""
<style>
.stApp {{
    background-image: url("{achtergrond_url}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}}
.block-container {{ 
    max-width: 1100px !important; 
    background-color: rgba(255, 255, 255, 0.85); /* Semi-transparant vlak achter de content */
    padding: 2rem !important;
    border-radius: 15px;
    box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.1); /* Subtiele schaduw */
    backdrop-filter: blur(8px); /* Maakt de achtergrond onder het tekstvlak wazig */
    margin-top: 2rem;
    margin-bottom: 2rem;
}}
html, body, p, li, label, .stMarkdown, .stChatInput textarea {{ font-size: 18px !important; }}
</style>
"""
st.markdown(achtergrond_css, unsafe_allow_html=True)

# --- ZIJBALK: VOORTGANG & INLOGGEN DOCENTEN ---
if st.session_state.get("ingelogd") and st.session_state.get("rol") == "leerling":
    st.sidebar.markdown(f"## 👋 Welkom {st.session_state.voornaam}!")
    st.sidebar.write(f"Klas: **{st.session_state.cluster}**")
            
    if st.sidebar.button("🚪 Uitloggen"):
        st.session_state.clear()
        st.rerun()

elif not st.session_state.get("ingelogd"):
    st.sidebar.divider()
    st.sidebar.header("👨‍🏫 Docentenpaneel")
    
    tab_d_inlog, tab_d_reg = st.sidebar.tabs(["Inloggen", "Registreren"])
    
    with tab_d_inlog:
        if check_lockout("docent"):
            st.info("Wacht tot de beveiligingsblokkade is opgeheven.")
        else:
            with st.form("docent_login_form"):
                d_login = st.text_input("Docent Gebruikersnaam:", key="d_login")
                d_ww = st.text_input("Wachtwoord:", type="password", key="d_ww")
                submitted_docent = st.form_submit_button("Log in als docent")
                
                if submitted_docent:
                    admin_ww = str(st.secrets.get("ADMIN_WACHTWOORD", "")).strip()
                    if d_login.strip().lower() == "admin" and hmac.compare_digest(d_ww.encode("utf-8"), admin_ww.encode("utf-8")):
                        st.session_state["login_pogingen_docent"] = 0 
                        st.session_state.ingelogd = True
                        st.session_state.rol = "admin"
                        st.session_state.docent_naam = "Beheerder"
                        st.rerun()
                    else:
                        docs = laad_docenten()
                        if d_login not in docs:
                            registreer_fout_inlog("docent")
                            st.error(f"Onjuiste inloggegevens. Gebruikersnaam onbekend. Poging {st.session_state['login_pogingen_docent']}/5")
                        elif not controleer_wachtwoord(d_ww, docs[d_login]["WachtwoordHash"]):
                            registreer_fout_inlog("docent")
                            st.error(f"Onjuiste inloggegevens. Wachtwoord onjuist. Poging {st.session_state['login_pogingen_docent']}/5")
                        elif docs[d_login].get("Goedgekeurd") == "Ja":
                            st.session_state["login_pogingen_docent"] = 0 
                            st.session_state.ingelogd = True
                            st.session_state.rol = "docent"
                            st.session_state.docent_id = d_login
                            st.session_state.docent_naam = docs[d_login]["Naam"]
                            st.session_state.docent_klassen = docs[d_login]["Klassen"]
                            st.rerun()
                        else:
                            st.error("Je account wacht nog op goedkeuring van de beheerder.")
                
    with tab_d_reg:
        with st.form("docent_reg_form"):
            st.write("Nieuwe docent aanmelden")
            reg_d_naam = st.text_input("Naam (bijv. Dhr. de Vries):")
            reg_d_login = st.text_input("Kies gebruikersnaam:")
            reg_d_ww = st.text_input("Kies wachtwoord:", type="password", key="reg_d_ww")
            reg_d_klassen = st.multiselect("Aan welke klassen geef jij les?", ALLE_CLUSTERS, key="reg_docent_klassen")
            
            submitted_d_reg = st.form_submit_button("Maak docentaccount aan")
            if submitted_d_reg:
                if not reg_d_naam or not reg_d_login or not reg_d_ww or not reg_d_klassen:
                    st.error("Vul alles in en kies minimaal 1 klas.")
                else:
                    docs = laad_docenten()
                    if reg_d_login in docs:
                        st.error("Gebruikersnaam al bezet.")
                    else:
                        docs[reg_d_login] = {
                            "DocentID": reg_d_login,
                            "WachtwoordHash": hash_wachtwoord(reg_d_ww),
                            "Naam": reg_d_naam,
                            "Klassen": reg_d_klassen,
                            "Goedgekeurd": "Nee"
                        }
                        bewaar_alle_docenten(docs)
                        st.success("Account gemaakt! Je account moet nog worden goedgekeurd door de beheerder.")

elif st.session_state.get("rol") in ["docent", "admin"]:
    st.sidebar.success(f"Ingelogd als: {st.session_state.docent_naam}")
    if st.sidebar.button("🚪 Uitloggen", key="d_uitlog"):
        st.session_state.clear()
        st.rerun()

# --- HOOFDSCHERM LOGICA ---

if st.session_state.get("ingelogd") and st.session_state.get("rol") == "docent":
    # ---------------- DOCENTEN PANEEL ----------------
    st.title(f"👨‍🏫 Docentenomgeving - Welkom {st.session_state.docent_naam}")
    mijn_klassen = st.session_state.docent_klassen
    
    if not mijn_klassen:
        st.warning("Je hebt nog geen klassen geselecteerd in je profiel.")
    else:
        docent_klas = st.selectbox("👉 Kies de klas die je wilt bekijken:", mijn_klassen, key="docent_dashboard_klas")
        st.divider()
        tab_res, tab_check, tab_up, tab_keuren = st.tabs(["📊 Resultaten & Feedback", "📋 Controle Inleveringen", "📄 Lesmateriaal Uploaden", "✅ Leerlingen Keuren"])
        
        alle_gebruikers = laad_gebruikers()
        
        with tab_res:
            ll_ruw = {gn: data for gn, data in alle_gebruikers.items() if data.get("Cluster") == docent_klas and data.get("Goedgekeurd", "Ja") == "Ja"}
            ll_sorted = sorted(ll_ruw.items(), key=lambda x: int(re.sub(r'\D', '', str(x[1].get("Nummer", "999"))) or 999))
            leerlingen_in_klas = {gn: f"{data.get('Nummer', '-')} | {data['Voornaam']}" for gn, data in ll_sorted}
            
            if leerlingen_in_klas:
                gekozen_leerling_gn = st.selectbox("Kies leerling:", list(leerlingen_in_klas.keys()), format_func=lambda x: leerlingen_in_klas[x], key="res_leerling_select")
                df_docent = haal_alle_resultaten_op()
                if not df_docent.empty and "Gebruikersnaam" in df_docent.columns:
                    mijn_data = df_docent[(df_docent["Gebruikersnaam"] == gekozen_leerling_gn) & (df_docent["Cluster"] == docent_klas)].copy()
                    if not mijn_data.empty:
                        st.write(f"**Resultaten {leerlingen_in_klas[gekozen_leerling_gn]}:**")
                        for index, row in mijn_data.iterrows():
                            with st.expander(f"{row['Les']} - Cijfer: {row['Cijfer']}"):
                                boek_dicht_weergave = row.get('BoekDicht', 'Onbekend')
                                st.write(f"**Boek dicht (volgens leerling):** {boek_dicht_weergave}")
                                st.write(f"**AI Beoordeling:**\n{row['Beoordeling']}")
                                huidige_reactie = row.get("DocentReactie", "")
                                if pd.isna(huidige_reactie): huidige_reactie = ""
                                nieuwe_reactie = st.text_area("Plaats een reactie voor de leerling:", value=huidige_reactie, key=f"reactie_{row['PogingID']}")
                                
                                if st.button("Opslaan", key=f"btn_{row['PogingID']}"):
                                    try:
                                        supabase.table("resultaten").update({"DocentReactie": nieuwe_reactie, "ReactieGelezen": "False"}).eq("PogingID", row["PogingID"]).execute()
                                        st.success("Reactie opgeslagen!")
                                    except Exception as e:
                                        st.error(f"Fout in cloud update: {e}")
                    else:
                        st.info("Deze leerling heeft nog niets ingeleverd.")
                else:
                    st.info("Nog geen systeemdata beschikbaar.")
            else:
                st.info(f"Geen goedgekeurde leerlingen in {docent_klas}.")
                
        with tab_check:
            st.write("**Controleer inleveringen per les**")
            lj = get_leerjaar(docent_klas)
            if not lj:
                st.error("Geen leerjaar gevonden voor deze klas.")
            else:
                check_hst = st.selectbox("Kies hoofdstuk:", HOOFDSTUKKEN[lj], key="check_hst_select")
                beschikbare_bestanden = haal_bestanden_op(lj, check_hst)
                if beschikbare_bestanden:
                    check_les = st.selectbox("Kies de les:", beschikbare_bestanden, key="check_les_select")
                    if st.button("Check status", type="primary"):
                        gemaakt_gn = set()
                        df_check = haal_alle_resultaten_op()
                        if not df_check.empty and "Gebruikersnaam" in df_check.columns and "Les" in df_check.columns:
                            gelukt = df_check[(df_check["Cluster"] == docent_klas) & (df_check["Les"] == check_les)]
                            gemaakt_gn = set(gelukt["Gebruikersnaam"].dropna().tolist())
                            
                        alle_gn_in_klas = set(gn for gn, d in ll_sorted)
                        niet_gemaakt_gn = alle_gn_in_klas - gemaakt_gn
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.success(f"✅ **Gemaakt ({len(gemaakt_gn)}):**")
                            for gn, d in ll_sorted:
                                if gn in gemaakt_gn: 
                                    st.write(f"- {d.get('Nummer', '-')} | {d['Voornaam']}")
                        with col2:
                            st.error(f"❌ **Nog NIET gemaakt ({len(niet_gemaakt_gn)}):**")
                            for gn, d in ll_sorted:
                                if gn in niet_gemaakt_gn:
                                    st.write(f"- {d.get('Nummer', '-')} | {d['Voornaam']}")
                else:
                    st.info("Geen lesmateriaal in deze map.")

        with tab_up:
            col1, col2 = st.columns(2)
            with col1: up_leerjaar = st.selectbox("Kies leerjaar:", list(HOOFDSTUKKEN.keys()), key="up_lj_select")
            with col2: up_hst = st.selectbox("Kies hoofdstuk:", HOOFDSTUKKEN[up_leerjaar], key="up_hst_select")
            
            st.divider()
            st.write(f"**Huidige lesmaterialen in {up_leerjaar} / {up_hst}:**")
            huidige_bestanden = haal_bestanden_op(up_leerjaar, up_hst)
            
            if huidige_bestanden:
                for b in huidige_bestanden:
                    col_file, col_del = st.columns([8, 1])
                    with col_file:
                        st.write(f"📄 {b}")
                    with col_del:
                        if st.button("❌", key=f"del_file_{up_leerjaar}_{up_hst}_{b}", help="Verwijder dit bestand"):
                            try:
                                supabase.storage.from_("lesmateriaal").remove([f"{up_leerjaar}/{up_hst}/{b}"])
                                st.success(f"Verwijderd: {b}")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fout bij verwijderen: {e}")
            else:
                st.info("Nog geen lesmateriaal geüpload in deze map.")
                
            st.divider()
            
            if "upload_key" not in st.session_state:
                st.session_state.upload_key = 0
                
            uploaded_files = st.file_uploader(f"Nieuwe les(sen) uploaden (.docx)", type=["docx"], accept_multiple_files=True, key=f"uploader_{st.session_state.upload_key}")
            
            if uploaded_files:
                if st.button("Opslaan & Uploaden", type="primary"):
                    success_count = 0
                    for uploaded_file in uploaded_files:
                        pad = f"{up_leerjaar}/{up_hst}/{uploaded_file.name}"
                        try:
                            supabase.storage.from_("lesmateriaal").upload(
                                file=uploaded_file.getvalue(),
                                path=pad,
                                file_options={"upsert": "true", "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                            )
                            success_count += 1
                        except Exception as e:
                            st.error(f"Cloud upload mislukt voor {uploaded_file.name}: {e}")
                            
                    if success_count > 0:
                        st.success(f"✅ {success_count} bestand(en) succesvol geüpload naar {up_leerjaar}/{up_hst}!")
                        time.sleep(1.5)
                        st.session_state.upload_key += 1
                        st.rerun()

        with tab_keuren:
            st.write("**Nieuwe aanvragen per klas**")
            if not mijn_klassen:
                st.info("Je hebt nog geen klassen toegewezen gekregen.")
            else:
                keuze_klas_keuren = st.selectbox("Kies een klas om aanvragen te bekijken:", mijn_klassen, key="keuze_klas_keuren")
                te_keuren = {gn: d for gn, d in alle_gebruikers.items() if d.get("Cluster") == keuze_klas_keuren and d.get("Goedgekeurd", "Ja") == "Nee"}
                
                if not te_keuren:
                    st.info(f"Er zijn op dit moment geen openstaande aanvragen voor {keuze_klas_keuren}.")
                else:
                    with st.form("batch_keuren_form"):
                        st.write("Vink aan of je een leerling wilt **goedkeuren** of **weigeren**. Vul bij goedkeuren direct het klassennummer in. Klik daarna onderaan op 'Verwerk selectie'.")
                        
                        col_h1, col_h2, col_h3, col_h4 = st.columns([3, 1, 1, 1])
                        col_h1.caption("Leerling")
                        col_h2.caption("Nummer")
                        col_h3.caption("Goedkeuren")
                        col_h4.caption("Weigeren")
                        
                        acties = {}
                        for gn, d_info in te_keuren.items():
                            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                            with c1:
                                st.write(f"🎓 **{d_info['Voornaam']}** (`{gn}`)")
                            with c2:
                                nr = st.text_input("Nr", key=f"nr_{gn}", label_visibility="collapsed", placeholder="Bijv. 1")
                            with c3:
                                ok = st.checkbox("✅", key=f"ok_{gn}")
                            with c4:
                                weiger = st.checkbox("❌", key=f"weiger_{gn}")
                                
                            acties[gn] = {"nr": nr, "ok": ok, "weiger": weiger, "naam": d_info['Voornaam']}
                            
                        if st.form_submit_button("Verwerk selectie", type="primary"):
                            gewijzigd = False
                            verwerkte_namen = []
                            
                            for gn, actie in acties.items():
                                if actie["ok"] and actie["weiger"]:
                                    st.warning(f"⚠️ {actie['naam']} overgeslagen: Je kunt niet tegelijk goedkeuren en weigeren.")
                                    continue
                                    
                                if actie["ok"]:
                                    alle_gebruikers[gn]["Goedgekeurd"] = "Ja"
                                    alle_gebruikers[gn]["Nummer"] = actie["nr"] if actie["nr"] else "999"
                                    gewijzigd = True
                                    verwerkte_namen.append(f"{actie['naam']} (Goedgekeurd)")
                                elif actie["weiger"]:
                                    try:
                                        supabase.table("gebruikers").delete().eq("Gebruikersnaam", gn).execute()
                                    except Exception:
                                        pass
                                    del alle_gebruikers[gn]
                                    gewijzigd = True
                                    verwerkte_namen.append(f"{actie['naam']} (Geweigerd)")
                                    
                            if gewijzigd:
                                bewaar_alle_gebruikers(alle_gebruikers)
                                st.success(f"✅ {len(verwerkte_namen)} aanvragen succesvol verwerkt!")
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                st.info("Je hebt geen acties geselecteerd om te verwerken.")

elif st.session_state.get("ingelogd") and st.session_state.get("rol") == "admin":
    # ---------------- ADMIN PANEEL ----------------
    st.title("⚙️ Beheerderspaneel")
    admin_tab_1, admin_tab_2, admin_tab_3 = st.tabs(["Nieuwe Aanvragen", "Beheer Leerlingen", "Beheer Docenten"])
    
    with admin_tab_1:
        st.write("**Aanvragen Docentenaccounts**")
        docs = laad_docenten()
        te_keuren = {k: v for k, v in docs.items() if v.get("Goedgekeurd") == "Nee"}
        if not te_keuren:
            st.info("Er zijn geen openstaande aanvragen.")
        else:
            for d_id, d_info in te_keuren.items():
                st.write(f"👨‍🏫 **{d_info['Naam']}** ({d_id})")
                st.caption(f"Klassen: {', '.join(d_info['Klassen'])}")
                col1, col2 = st.columns([1, 8])
                with col1:
                    if st.button("✅ Goedkeuren", key=f"ok_{d_id}"):
                        docs[d_id]["Goedgekeurd"] = "Ja"
                        bewaar_alle_docenten(docs)
                        st.success(f"{d_info['Naam']} goedgekeurd!")
                        st.rerun()
                with col2:
                    if st.button("❌ Weigeren", key=f"del_{d_id}"):
                        del docs[d_id]
                        bewaar_alle_docenten(docs)
                        st.warning("Account verwijderd.")
                        st.rerun()

    with admin_tab_2:
        st.write("**Overzicht Leerlingen**")
        alle_gebruikers = laad_gebruikers()
        if alle_gebruikers:
            clusters = sorted(list(set(data["Cluster"] for data in alle_gebruikers.values())))
            kies_admin_klas = st.selectbox("Kies een klas:", clusters, key="admin_klas_select")
            leerlingen_in_admin_klas = {gn: data for gn, data in alle_gebruikers.items() if data["Cluster"] == kies_admin_klas}
            
            if leerlingen_in_admin_klas:
                st.write(f"Er zijn **{len(leerlingen_in_admin_klas)}** leerlingen geregistreerd in {kies_admin_klas}.")
                
                ll_sorted_admin = sorted(leerlingen_in_admin_klas.items(), key=lambda x: int(re.sub(r'\D', '', str(x[1].get("Nummer", "999"))) or 999))
                
                # --- DOWNLOAD LIJST ---
                export_data = []
                for gn, ll_data in ll_sorted_admin:
                    export_data.append({
                        "Nummer": ll_data.get("Nummer", "999"),
                        "Voornaam": ll_data.get("Voornaam", ""),
                        "Inlognaam": gn
                    })
                df_export = pd.DataFrame(export_data)
                csv_export = df_export.to_csv(index=False, sep=";").encode('utf-8')
                
                st.download_button(
                    label=f"📥 Download inloglijst {kies_admin_klas} (CSV)",
                    data=csv_export,
                    file_name=f"inloglijst_{kies_admin_klas}.csv",
                    mime="text/csv",
                )
                
                # --- BULK VERWIJDER PANEEL ---
                st.write("### 🗑️ Bulk Verwijderen")
                select_all = st.checkbox("Selecteer ALLE leerlingen in deze klas")
                
                if select_all:
                    te_verwijderen = list(leerlingen_in_admin_klas.keys())
                    st.info(f"{len(te_verwijderen)} leerlingen geselecteerd.")
                else:
                    te_verwijderen = st.multiselect("Of selecteer specifieke leerlingen om te verwijderen:", list(leerlingen_in_admin_klas.keys()), format_func=lambda x: f"{leerlingen_in_admin_klas[x]['Voornaam']} ({x})")
                    
                if te_verwijderen:
                    if st.button(f"🚨 Verwijder {len(te_verwijderen)} geselecteerde leerling(en) definitief", type="primary"):
                        for gn in te_verwijderen:
                            try:
                                supabase.table("gebruikers").delete().eq("Gebruikersnaam", gn).execute()
                            except Exception:
                                pass 
                            if gn in alle_gebruikers:
                                del alle_gebruikers[gn]
                                
                        st.success(f"✅ {len(te_verwijderen)} account(s) succesvol verwijderd!")
                        time.sleep(1.5)
                        st.rerun()
                        
                st.divider()
                st.write("### ✏️ Gegevens Aanpassen")
                
                col_h1, col_h2, col_h3, col_h4, col_h5, col_h6 = st.columns([2, 1, 2, 2, 2, 1])
                col_h1.caption("Naam & Gebruikersnaam")
                col_h2.caption("Nummer")
                col_h3.caption("Pas voornaam aan")
                col_h4.caption("Pas klas aan")
                col_h5.caption("Nieuw wachtwoord")
                col_h6.caption("Opslaan")
                
                for gn, ll_data in ll_sorted_admin:
                    col_naam, col_nr, col_edit_vn, col_edit_klas, col_edit_ww, col_save = st.columns([2, 1, 2, 2, 2, 1])
                    
                    with col_naam:
                        status = "✅" if ll_data.get("Goedgekeurd", "Ja") == "Ja" else "⏳ Wachtend"
                        st.markdown(f"**{ll_data['Voornaam']}** ({status})  \n`{gn}`")
                        
                    with col_nr:
                        nw_nr = st.text_input("Nummer", value=ll_data.get("Nummer", ""), key=f"admin_nr_{gn}", label_visibility="collapsed")    
                        
                    with col_edit_vn:
                        nw_vn = st.text_input("Voornaam", value=ll_data["Voornaam"], key=f"vn_{gn}", label_visibility="collapsed")
                        
                    with col_edit_klas:
                        huidige_klas = ll_data.get("Cluster", "")
                        idx = ALLE_CLUSTERS.index(huidige_klas) if huidige_klas in ALLE_CLUSTERS else 0
                        nw_klas = st.selectbox("Klas", options=ALLE_CLUSTERS, index=idx, key=f"klas_{gn}", label_visibility="collapsed")
                        
                    with col_edit_ww:
                        nw_ww = st.text_input("Wachtwoord", placeholder="Nieuw ww...", type="password", key=f"ww_{gn}", label_visibility="collapsed")
                        
                    with col_save:
                        if st.button("💾", key=f"save_{gn}", help="Sla wijzigingen voor deze leerling op"):
                            changed = False
                            if nw_nr != ll_data.get("Nummer", ""):
                                alle_gebruikers[gn]["Nummer"] = nw_nr
                                changed = True
                            if nw_vn != ll_data["Voornaam"]:
                                alle_gebruikers[gn]["Voornaam"] = nw_vn
                                changed = True
                            if nw_klas != ll_data.get("Cluster", ""):
                                alle_gebruikers[gn]["Cluster"] = nw_klas
                                for niv, klassenlijst in NIVEAUS.items():
                                    if nw_klas in klassenlijst:
                                        alle_gebruikers[gn]["Niveau"] = niv
                                        break
                                changed = True
                            if nw_ww:
                                is_sterk, fout = is_sterk_wachtwoord(nw_ww)
                                if not is_sterk:
                                    st.error(fout)
                                else:
                                    alle_gebruikers[gn]["WachtwoordHash"] = hash_wachtwoord(nw_ww)
                                    changed = True
                            if changed:
                                bewaar_alle_gebruikers(alle_gebruikers)
                                st.success("Opgeslagen!")
                                time.sleep(1)
                                st.rerun()
                    st.divider()
            else:
                st.info("Geen leerlingen in deze klas.")
                
        st.write("**Handmatig nieuwe leerling toevoegen**")
        with st.form("admin_maak_ll_form"):
            colA, colB, colC = st.columns(3)
            with colA:
                nieuw_niv = st.selectbox("Niveau:", list(NIVEAUS.keys()))
            with colB:
                nieuw_klas = st.selectbox("Klas:", NIVEAUS[nieuw_niv])
            with colC:
                nieuw_nr = st.text_input("Klassennummer (optioneel):")
            
            nieuw_vn = st.text_input("Voornaam leerling:")
            nieuw_gn = st.text_input("Kies gebruikersnaam:")
            nieuw_ww = st.text_input("Kies wachtwoord (Min 8 tekens, 1 cijfer, 1 speciaal teken):", type="password")
            
            if st.form_submit_button("Voeg leerling toe"):
                if nieuw_gn in alle_gebruikers:
                    st.error("❌ Gebruikersnaam is al in gebruik. Kies een andere.")
                elif not nieuw_vn or not nieuw_gn or not nieuw_ww:
                    st.error("❌ Vul alle velden in.")
                else:
                    is_sterk, fout = is_sterk_wachtwoord(nieuw_ww)
                    if not is_sterk:
                        st.error(f"❌ {fout}")
                    else:
                        alle_gebruikers[nieuw_gn] = {
                            "Gebruikersnaam": nieuw_gn,
                            "WachtwoordHash": hash_wachtwoord(nieuw_ww),
                            "Voornaam": nieuw_vn,
                            "Niveau": nieuw_niv,
                            "Cluster": nieuw_klas,
                            "Goedgekeurd": "Ja",
                            "Nummer": nieuw_nr if nieuw_nr else "999"
                        }
                        try:
                            bewaar_alle_gebruikers(alle_gebruikers)
                            st.success(f"✅ Account voor {nieuw_vn} succesvol aangemaakt en direct goedgekeurd!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout bij opslaan: {e}")

    with admin_tab_3:
        st.write("**Overzicht Docenten**")
        docs = laad_docenten()
        goedgekeurde_docenten = {k: v for k, v in docs.items() if v.get("Goedgekeurd") == "Ja"}
        if goedgekeurde_docenten:
            kies_admin_doc = st.selectbox("Kies een docent:", list(goedgekeurde_docenten.keys()), format_func=lambda x: f"{goedgekeurde_docenten[x]['Naam']} ({x})", key="admin_doc_select")
            doc_data = goedgekeurde_docenten[kies_admin_doc]
            
            with st.form("admin_docent_bewerk"):
                st.write(f"Gegevens van **{doc_data['Naam']}** ({kies_admin_doc}):")
                
                huidige_klassen = [k for k in doc_data.get('Klassen', []) if k in ALLE_CLUSTERS]
                nieuwe_klassen = st.multiselect("Toegewezen klassen:", ALLE_CLUSTERS, default=huidige_klassen, key="admin_doc_klassen")
                
                nieuw_doc_ww = st.text_input("Nieuw wachtwoord (laat leeg om niet te wijzigen):", type="password", key="admin_doc_ww")
                
                if st.form_submit_button("Sla wijzigingen op", type="primary"):
                    changed = False
                    
                    if set(nieuwe_klassen) != set(huidige_klassen):
                        docs[kies_admin_doc]["Klassen"] = nieuwe_klassen
                        changed = True
                        
                    if nieuw_doc_ww:
                        docs[kies_admin_doc]["WachtwoordHash"] = hash_wachtwoord(nieuw_doc_ww)
                        changed = True
                        
                    if changed:
                        bewaar_alle_docenten(docs)
                        st.success(f"Wijzigingen succesvol opgeslagen!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.info("Geen wijzigingen gedetecteerd.")
        else:
            st.info("Er zijn geen goedgekeurde docenten.")

elif not st.session_state.get("ingelogd"):
    # ---------------- LEERLING / GAST LOGIN (NIET INGELOGD) ----------------
    st.title("🗺️ Huiswerkcontrole AK")
    st.markdown("Welkom! Ben je een leerling? Log hieronder in of ga direct aan de slag als gast.")
    
    tab_inlog, tab_reg, tab_gast = st.tabs(["🔐 Inloggen", "📝 Account Aanmaken", "🚀 Gasttoegang"])
    
    with tab_inlog:
        st.subheader("Inloggen")
        if check_lockout("leerling"):
            st.info("Wacht tot de beveiligingsblokkade is opgeheven.")
        else:
            with st.form("leerling_login_form"):
                login_gn = st.text_input("Jouw gebruikersnaam:", key="login_gn")
                login_ww = st.text_input("Wachtwoord:", type="password", key="login_ww")
                submitted_login = st.form_submit_button("Inloggen")
                
                if submitted_login:
                    gebruikers = laad_gebruikers()
                    if login_gn not in gebruikers:
                        registreer_fout_inlog("leerling")
                        st.error("❌ De ingevulde inlognaam is onbekend in het systeem. Let op typefouten of maak een nieuw account aan.")
                    elif not controleer_wachtwoord(login_ww, gebruikers[login_gn]["WachtwoordHash"]):
                        registreer_fout_inlog("leerling")
                        st.error("❌ Het ingevulde wachtwoord is onjuist.")
                    else:
                        if gebruikers[login_gn].get("Goedgekeurd", "Ja") == "Ja":
                            st.session_state["login_pogingen_leerling"] = 0 
                            st.session_state.ingelogd = True
                            st.session_state.rol = "leerling"
                            st.session_state.gebruikersnaam = login_gn
                            st.session_state.voornaam = gebruikers[login_gn]["Voornaam"]
                            st.session_state.niveau = gebruikers[login_gn]["Niveau"]
                            st.session_state.cluster = gebruikers[login_gn]["Cluster"]
                            st.session_state.nummer = gebruikers[login_gn].get("Nummer", "999")
                            st.rerun()
                        else:
                            st.warning("⏳ Je account is nog niet goedgekeurd door je docent. Werk zolang via het tabblad 'Gasttoegang'.")

        st.divider()
        with st.expander("Wachtwoord of inlognaam vergeten?"):
            st.write("Vul hier je gegevens in om de docent te waarschuwen dat je een probleem hebt met inloggen.")
            with st.form("ww_vergeten_form"):
                vergeten_naam = st.text_input("Jouw voornaam:")
                vergeten_klas = st.selectbox("Jouw klas:", ALLE_CLUSTERS)
                
                if st.form_submit_button("Stuur bericht naar docent", type="primary"):
                    if not vergeten_naam.strip():
                        st.error("Vul eerst je naam in.")
                    else:
                        try:
                            post_data = {
                                "name": f"{vergeten_naam} ({vergeten_klas})",
                                "message": f"Leerling {vergeten_naam} uit klas {vergeten_klas} kan niet inloggen.",
                                "_subject": f"🚨 Wachtwoord reset aangevraagd: {vergeten_naam} ({vergeten_klas})"
                            }
                            requests.post("https://formsubmit.co/ajax/jjvddool@pieterzandt.nl", data=post_data)
                            st.success("✅ Aanvraag is verstuurd!")
                        except Exception as e:
                            st.error("Er ging iets mis met het versturen.")

    with tab_reg:
        st.subheader("Nieuw account aanmaken")
        st.warning("⚠️ **Privacy Waarschuwing:** Gebruik **géén herleidbare persoonsgegevens** in je inlognaam of wachtwoord.")
        reg_niveau = st.selectbox("Jouw niveau:", list(NIVEAUS.keys()), key="reg_niveau_ll")
        
        with st.form("leerling_reg_form"):
            reg_voornaam = st.text_input("Wat is je voornaam?")
            reg_cluster = st.selectbox("Jouw klas:", NIVEAUS[reg_niveau], key="reg_cluster_ll")
            reg_gn = st.text_input("Bedenk een inlognaam:")
            reg_ww = st.text_input("Bedenk een wachtwoord (Min 8 tekens, 1 cijfer, 1 speciaal teken):", type="password")
            reg_ww2 = st.text_input("Herhaal je wachtwoord:", type="password")
            
            submitted_reg = st.form_submit_button("Account Aanmaken")
            if submitted_reg:
                if not reg_voornaam or not reg_gn or not reg_ww: 
                    st.error("Vul alle velden in.")
                elif reg_ww != reg_ww2: 
                    st.error("Wachtwoorden komen niet overeen!")
                else:
                    is_sterk, fout = is_sterk_wachtwoord(reg_ww)
                    if not is_sterk: 
                        st.error(fout)
                    else:
                        gebruikers = laad_gebruikers()
                        if reg_gn in gebruikers: 
                            st.error("❌ Deze inlognaam is al bezet.")
                        else:
                            gebruikers[reg_gn] = {
                                "Gebruikersnaam": reg_gn,
                                "WachtwoordHash": hash_wachtwoord(reg_ww),
                                "Voornaam": reg_voornaam,
                                "Niveau": reg_niveau,
                                "Cluster": reg_cluster,
                                "Goedgekeurd": "Nee",
                                "Nummer": "999"
                            }
                            bewaar_alle_gebruikers(gebruikers)
                            st.success("✅ Account succesvol aangemaakt! Wacht op goedkeuring van de docent.")
                                
    with tab_gast:
        st.subheader("Snel Oefenen als Gast")
        st.write("Wil je direct aan de slag zonder account? Vul je gegevens in.")
        gast_niveau = st.selectbox("Jouw niveau (Gast):", list(NIVEAUS.keys()), key="gast_niveau_select")
        
        with st.form("gast_login_form"):
            gast_voornaam = st.text_input("Wat is je voornaam?")
            gast_cluster = st.selectbox("Jouw klas:", NIVEAUS[gast_niveau], key="gast_cluster_select")
            if st.form_submit_button("Start als Gast"):
                if not gast_voornaam.strip():
                    st.error("Vul je voornaam in.")
                else:
                    st.session_state["login_pogingen_leerling"] = 0 
                    st.session_state.ingelogd = True
                    st.session_state.rol = "leerling"
                    st.session_state.gebruikersnaam = f"gast_{uuid.uuid4().hex[:6]}"
                    st.session_state.voornaam = f"{gast_voornaam.strip()} (Gast)"
                    st.session_state.niveau = gast_niveau
                    st.session_state.cluster = gast_cluster
                    st.session_state.nummer = "Gast"
                    st.rerun()

elif st.session_state.get("rol") == "leerling":
    # ---------------- LEERLING PANEEL OEFENEN ----------------
    st.title("🗺️ Huiswerkcontrole AK")
    
    # 1. Haal uitsluitend uit Supabase de geschiedenis van deze leerling
    if "mijn_data_geschiedenis" not in st.session_state:
        st.session_state.mijn_data_geschiedenis = haal_alle_resultaten_op()

    if not st.session_state.mijn_data_geschiedenis.empty:
        df_mijn = st.session_state.mijn_data_geschiedenis[st.session_state.mijn_data_geschiedenis["Gebruikersnaam"] == st.session_state.gebruikersnaam]
        if not df_mijn.empty and "ReactieGelezen" in df_mijn.columns:
            if any((df_mijn["ReactieGelezen"] == "False") | (df_mijn["ReactieGelezen"] == False)):
                st.error("🚨 **Nieuw bericht!** Je docent heeft feedback achtergelaten. Kijk in het tabblad 'Mijn Resultaten'.")

    tab_oefen, tab_geschiedenis, tab_instellingen = st.tabs(["🗺️ Oefenen", "📊 Mijn Resultaten", "⚙️ Instellingen"])
    
    with tab_oefen:
        st.write(f"Klas: **{st.session_state.cluster}**")
        lj = get_leerjaar(st.session_state.cluster)
        
        if not lj:
            st.error("Oeps, we konden je klas niet koppelen aan een leerjaar.")
        else:
            kies_hst = st.selectbox("1. Kies het hoofdstuk:", HOOFDSTUKKEN[lj], key="ll_kies_hst")
            beschikbare_bestanden = haal_bestanden_op(lj, kies_hst)

            if not beschikbare_bestanden:
                st.warning("Er is nog geen lesmateriaal beschikbaar voor dit hoofdstuk.")
            else:
                opties_les = ["-- Kies een paragraaf --"] + beschikbare_bestanden
                gekozen_les = st.selectbox("2. Kies de paragraaf die je wilt oefenen:", opties_les, key="ll_kies_les")
                st.divider()

                if gekozen_les != "-- Kies een paragraaf --":
                    # Controleer of de leerling aan zijn max zit via Supabase
                    df_all = haal_alle_resultaten_op()
                    aantal_pogingen = 0
                    if not df_all.empty and not "Gast" in st.session_state.voornaam:
                        df_les = df_all[(df_all["Gebruikersnaam"] == st.session_state.gebruikersnaam) & (df_all["Les"] == gekozen_les)]
                        aantal_pogingen = len(df_les)
                    
                    if aantal_pogingen >= 3:
                        st.error("Je hebt het maximale aantal pogingen (3) voor deze les bereikt. Bestudeer je gemaakte fouten in het resultaten-tabblad.")
                    else:
                        versie = aantal_pogingen + 1
                        if not "Gast" in st.session_state.voornaam:
                            st.info(f"Dit is poging {versie} van 3 voor deze les.")
                        
                        if st.session_state.get("huidige_les") != gekozen_les or st.session_state.get("huidige_versie") != versie:
                            st.session_state.huidige_les = gekozen_les
                            st.session_state.huidige_versie = versie
                            st.session_state.vragen_data = None
                            st.session_state.nakijk_resultaat = None
                            st.session_state.huidig_cijfer = 0.0
                            st.session_state.toets_ingeleverd = False
                            
                        les_tekst = lees_docx(lj, kies_hst, gekozen_les)

                        if les_tekst:
                            # Fase 1: Vragen Genereren (Gecached op tekst, niveau en versie)
                            if not st.session_state.get("vragen_data"):
                                with st.spinner(f"De docent bereidt versie {versie} voor... Dit duurt enkele seconden."):
                                    try:
                                        vragen_dict = genereer_toets_gecached(les_tekst, st.session_state.niveau, versie)
                                        if "vragen" in vragen_dict:
                                            st.session_state.vragen_data = vragen_dict
                                            st.rerun()
                                        else:
                                            st.error("Ongeldig toetsformaat ontvangen. Herlaad de pagina.")
                                    except Exception as e:
                                        st.error(f"🚨 Fout bij genereren toets: {e}")

                            # Fase 2: De Leerling Interface
                            if st.session_state.get("vragen_data") and not st.session_state.get("nakijk_resultaat"):
                                st.success("💡 De vragen zijn gegenereerd! Vul de antwoorden hieronder in en klik op 'Lever in'.")
                                
                                boek_dicht_keuze = st.radio("Voordat je begint: Heb je het boek gesloten?", ["Ja, ik ga de vragen uit mijn hoofd maken", "Nee, ik gebruik mijn boek als hulp"])
                                
                                with st.form("overhoring_form"):
                                    antwoorden = {}
                                    for idx, v in enumerate(st.session_state.vragen_data.get("vragen", [])):
                                        st.markdown(f"**Vraag {idx + 1}**")
                                        if v.get('type') == 'mc':
                                            antwoorden[v['id']] = st.radio(v.get('vraag', 'Vraag?'), v.get('opties', []), key=f"q_{v['id']}")
                                        else:
                                            antwoorden[v['id']] = st.text_area(v.get('vraag', 'Open Vraag?'), key=f"q_{v['id']}")
                                        st.write("") 
                                        
                                    submitted = st.form_submit_button("Lever in", type="primary")
                                    
                                    # Fase 3: Nakijken & Feedback
                                    if submitted:
                                        with st.spinner("De docent kijkt je werk na..."):
                                            # 1. Kijk MC lokaal na (1 pt per vraag)
                                            mc_score = 0.0
                                            mc_feedback = ""
                                            open_vragen_text = ""
                                            
                                            for idx, v in enumerate(st.session_state.vragen_data.get("vragen", [])):
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
                                            prompt_nakijken = f"""Je bent docent aardrijkskunde ({st.session_state.niveau}). Beoordeel onderstaande 2 open vragen.
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
                                            
                                            try:
                                                # FASE 3: Gebruikt de krachtige Pro voor nauwkeurig en coulant nakijken
                                                resp = client.models.generate_content(model='gemini-3.1-pro', contents=prompt_nakijken)
                                                ai_eval = extract_json(resp.text)
                                                
                                                open_score = float(ai_eval.get("score_open_vragen_totaal", 0.0))
                                                totaal_score = mc_score + open_score
                                                
                                                # Bouw weergave tekst
                                                volledige_feedback = mc_feedback + ai_eval.get("beoordeling_open_vragen", "")
                                                ai_docent_tekst = ai_eval.get("docenten_feedback", "Toets afgerond.")
                                                
                                                boek_dicht_status = "Ja" if "Ja" in boek_dicht_keuze else "Nee"
                                                
                                                # Resultaat wegschrijven
                                                success, err_msg = sla_resultaat_op(
                                                    st.session_state.niveau, 
                                                    st.session_state.cluster, 
                                                    st.session_state.get("nummer", "999"), 
                                                    st.session_state.voornaam,
                                                    st.session_state.gebruikersnaam, 
                                                    gekozen_les, 
                                                    totaal_score, 
                                                    volledige_feedback, 
                                                    boek_dicht_status
                                                )
                                                
                                                if success:
                                                    st.session_state.nakijk_resultaat = volledige_feedback
                                                    st.session_state.huidig_cijfer = totaal_score
                                                    st.session_state.docenten_feedback = ai_docent_tekst
                                                    st.rerun()
                                                else:
                                                    st.error(f"🚨 De database weigerde het resultaat op te slaan. Je antwoorden zijn nog bewaard in de invulvelden hierboven. Druk zo nogmaals op inleveren. (Fout: {err_msg})")
                                                    
                                            except Exception as e:
                                                st.error(f"🚨 Verbinding met nakijk-model haperde: {e}")

                            # Feedback overzicht tonen
                            if st.session_state.get("nakijk_resultaat"):
                                st.success("✅ Toets succesvol ingeleverd in Supabase!")
                                if st.session_state.huidig_cijfer >= 6.0: st.balloons()
                                
                                st.markdown(f"### Eindcijfer: {st.session_state.huidig_cijfer:.1f} / 10.0")
                                st.info(f"👨‍🏫 **Docent:** {st.session_state.get('docenten_feedback', '')}")
                                
                                st.markdown("### 📝 Specificatie per vraag")
                                st.markdown(st.session_state.nakijk_resultaat)
                                
                                if st.session_state.huidig_cijfer < 5.5:
                                    leer_link = "https://aivoorleerlingen.nl/vwo/leren" if st.session_state.niveau == "VWO" else "https://aivoorleerlingen.nl/havo/aardrijkskunde/leren"
                                    st.warning(f"Het is nog geen voldoende. Bestudeer de theorie beter en kijk voor leertips op: [Leertips Aardrijkskunde]({leer_link})")
                                
                                if st.button("⬅️ Terug / Andere les oefenen", type="primary"):
                                    st.session_state.huidige_les = None
                                    st.session_state.vragen_data = None
                                    st.session_state.nakijk_resultaat = None
                                    st.session_state.huidig_cijfer = 0.0
                                    st.rerun()

    with tab_geschiedenis:
        st.subheader("Mijn Resultaten & Feedback")
        if "Gast" in st.session_state.voornaam:
            st.info("💡 Resultaten uit gast-sessies worden hier niet weergegeven.")
        else:
            df_hist = haal_alle_resultaten_op()
            if not df_hist.empty:
                df_mijn = df_hist[df_hist["Gebruikersnaam"] == str(st.session_state.gebruikersnaam)]
                if not df_mijn.empty:
                    for index, row in df_mijn.iterrows():
                        is_ongelezen = (str(row.get("ReactieGelezen", "True")) == "False")
                        heeft_reactie = pd.notna(row.get("DocentReactie")) and str(row.get("DocentReactie")).strip() != ""
                        titel_prefix = "🚨 " if is_ongelezen else "💬 " if heeft_reactie else "📄 "
                        
                        with st.expander(f"{titel_prefix} {row['Les']} | Cijfer: {row['Cijfer']}"):
                            st.write(f"Gemaakt op: {row['Tijdstip']}")
                            st.markdown(row['Beoordeling'])
                            if heeft_reactie:
                                st.info(f"**Reactie van docent:**\n\n{row['DocentReactie']}")
                                if is_ongelezen:
                                    if st.button("Markeer als gelezen", key=f"gelezen_{row['PogingID']}"):
                                        try:
                                            supabase.table("resultaten").update({"ReactieGelezen": "True"}).eq("PogingID", row["PogingID"]).execute()
                                            st.rerun()
                                        except Exception:
                                            pass
                            else:
                                st.write("*De docent heeft nog geen extra reactie achtergelaten.*")
                else:
                    st.info("Je hebt nog geen overhoringen ingeleverd.")

    with tab_instellingen:
        if "Gast" in st.session_state.voornaam:
            st.warning("Gasten hebben geen instellingen.")
        else:
            st.subheader("Wachtwoord Wijzigen")
            with st.form("ww_wijzig_form"):
                oud_ww = st.text_input("Oud wachtwoord:", type="password")
                nieuw_ww = st.text_input("Nieuw wachtwoord:", type="password")
                nieuw_ww2 = st.text_input("Herhaal nieuw:", type="password")
                
                if st.form_submit_button("Wijzig Wachtwoord"):
                    gebruikers = laad_gebruikers()
                    oude_gn = st.session_state.gebruikersnaam
                    if not controleer_wachtwoord(oud_ww, gebruikers[oude_gn]["WachtwoordHash"]): 
                        st.error("Oud wachtwoord onjuist.")
                    elif nieuw_ww != nieuw_ww2: 
                        st.error("Wachtwoorden komen niet overeen.")
                    else:
                        is_sterk, fout = is_sterk_wachtwoord(nieuw_ww)
                        if not is_sterk: 
                            st.error(fout)
                        else:
                            gebruikers[oude_gn]["WachtwoordHash"] = hash_wachtwoord(nieuw_ww)
                            try:
                                supabase.table('gebruikers').upsert(gebruikers[oude_gn]).execute()
                                st.success("✅ Wachtwoord succesvol gewijzigd!")
                            except Exception as e:
                                st.error(f"Fout bij wijzigen wachtwoord: {e}")

st.sidebar.divider()
st.sidebar.caption(f"🔄 Laatste update app: {LAATSTE_UPDATE} | v{VERSIE}")
