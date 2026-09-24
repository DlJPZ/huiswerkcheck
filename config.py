import streamlit as st
from google import genai
import os
import requests
import datetime

# --- 1. VERSIEBEHEER & PAGINA ---
LAATSTE_UPDATE = "24 september 2026"
VERSIE = "3.0.12"

def setup_page():
    st.set_page_config(page_title="Huiswerkcontrole AK", layout="wide")

# --- 2. API & CLOUD INSTELLINGEN ---
def init_apis():
    # Gemini API instellen
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    
    api_key = st.secrets["GEMINI_API_KEY"].replace('"', '').replace("'", "").strip()
    os.environ["GEMINI_API_KEY"] = api_key
    
    if "ai_client" not in st.session_state:
        st.session_state.ai_client = genai.Client(api_key=api_key)
    
    # Supabase Connectie
    try:
        from supabase import create_client, Client
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
        supabase_client: Client = create_client(supabase_url, supabase_key)
        return st.session_state.ai_client, supabase_client
    except Exception as e:
        st.error(f"🚨 Fout bij initialiseren van Supabase. Controleer Streamlit Secrets. Error: {e}")
        st.stop()

# Initialiseer de clients zodat andere bestanden ze kunnen importeren
ai_client, supabase = init_apis()

# --- 3. DATALISTEN & STRUCTUUR ---
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

# --- 4. ACHTERGROND & STYLING ---
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

def pas_styling_toe():
    achtergrond_url = haal_wikimedia_potd_url_op()
    bg_opacity = st.session_state.get("bg_opacity", 0.85)

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
        background-color: rgba(255, 255, 255, {bg_opacity});
        padding: 2rem !important;
        border-radius: 15px;
        box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.1); 
        backdrop-filter: blur(8px); 
        margin-top: 2rem;
        margin-bottom: 2rem;
    }}
    html, body, p, li, label, .stMarkdown, .stChatInput textarea {{ font-size: 18px !important; }}
    </style>
    """
    st.markdown(achtergrond_css, unsafe_allow_html=True)
