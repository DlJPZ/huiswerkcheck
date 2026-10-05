import streamlit as st
import hmac
import uuid

# 1. Pagina Setup (Dit MOET het eerste Streamlit commando zijn)
from config import setup_page
setup_page()

# 2. Importeer alle afhankelijkheden uit onze nieuwe blokken
from config import pas_styling_toe, LAATSTE_UPDATE, VERSIE, ALLE_CLUSTERS, NIVEAUS
from auth import (
    check_lockout, registreer_fout_inlog, reset_login_pogingen, controleer_wachtwoord,
    haal_gebruiker, haal_docent, account_bestaat, maak_account,
    hash_wachtwoord, is_sterk_wachtwoord, check_server_lockout,
    registreer_server_fout_inlog, reset_server_login_pogingen
)
from ui_beheer import toon_docent_paneel, toon_admin_paneel
from ui_leerling import toon_leerling_paneel, toon_mini_game
from storingen import maak_storing

# Pas dynamische achtergrond styling toe
pas_styling_toe()

# --- ZIJBALK: DOCENTEN LOGIN & STATUS ---
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
                    docent_id = d_login.strip()
                    if check_server_lockout("docent", docent_id):
                        st.stop()

                    admin_hash = str(st.secrets.get("ADMIN_WACHTWOORD_HASH", "")).strip()
                    admin_ww = str(st.secrets.get("ADMIN_WACHTWOORD", "")).strip()
                    admin_ok = False
                    if docent_id.lower() == "admin":
                        if admin_hash:
                            admin_ok = controleer_wachtwoord(d_ww, admin_hash)
                        elif admin_ww:
                            # Tijdelijke compatibiliteit; vervang door ADMIN_WACHTWOORD_HASH.
                            admin_ok = hmac.compare_digest(d_ww.encode("utf-8"), admin_ww.encode("utf-8"))

                    if admin_ok:
                        reset_login_pogingen("docent")
                        reset_server_login_pogingen("docent", docent_id)
                        st.session_state.ingelogd = True
                        st.session_state.rol = "admin"
                        st.session_state.docent_naam = "Beheerder"
                        st.rerun()

                    docent = None if docent_id.lower() == "admin" else haal_docent(docent_id)
                    if not docent or not controleer_wachtwoord(d_ww, docent.get("WachtwoordHash")):
                        registreer_fout_inlog("docent")
                        registreer_server_fout_inlog("docent", docent_id)
                        st.error("Onjuiste inloggegevens.")
                    elif docent.get("Goedgekeurd") == "Ja":
                        reset_login_pogingen("docent")
                        reset_server_login_pogingen("docent", docent_id)
                        st.session_state.ingelogd = True
                        st.session_state.rol = "docent"
                        st.session_state.docent_id = docent_id
                        st.session_state.docent_naam = docent["Naam"]
                        st.session_state.docent_klassen = docent["Klassen"]
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
            
            if st.form_submit_button("Maak docentaccount aan"):
                if not reg_d_naam or not reg_d_login or not reg_d_ww or not reg_d_klassen:
                    st.error("Vul alles in en kies minimaal 1 klas.")
                else:
                    is_sterk, fout = is_sterk_wachtwoord(reg_d_ww)
                    if not is_sterk:
                        st.error(fout)
                    else:
                        docent_id = reg_d_login.strip()
                        if docent_id.lower() == "admin" or account_bestaat("docenten", "DocentID", docent_id):
                            st.error("Gebruikersnaam al bezet.")
                        else:
                            maak_account("docenten", "DocentID", docent_id, {
                                "WachtwoordHash": hash_wachtwoord(reg_d_ww),
                                "Naam": reg_d_naam.strip(),
                                "Klassen": reg_d_klassen,
                                "Goedgekeurd": "Nee"
                            })
                            st.success("Account gemaakt! Je account moet nog worden goedgekeurd door de beheerder.")

elif st.session_state.get("rol") in ["docent", "admin"]:
    st.sidebar.success(f"Ingelogd als: {st.session_state.docent_naam}")
    if st.sidebar.button("🚪 Uitloggen", key="d_uitlog"):
        st.session_state.clear()
        st.rerun()

# --- HOOFDSCHERM ROUTING ---

# Route 1: Docent is ingelogd
if st.session_state.get("ingelogd") and st.session_state.get("rol") == "docent":
    toon_docent_paneel()
    
# Route 2: Admin is ingelogd
elif st.session_state.get("ingelogd") and st.session_state.get("rol") == "admin":
    toon_admin_paneel()
    
# Route 3: Leerling / Gast is ingelogd
elif st.session_state.get("ingelogd") and st.session_state.get("rol") == "leerling":
    toon_leerling_paneel()
    
# Route 4: Niemand is ingelogd (Toon inlogscherm leerlingen)
elif not st.session_state.get("ingelogd"):
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
                    gebruikersnaam = login_gn.strip()
                    if check_server_lockout("leerling", gebruikersnaam):
                        st.stop()
                    gebruiker = haal_gebruiker(gebruikersnaam)
                    if not gebruiker or not controleer_wachtwoord(login_ww, gebruiker.get("WachtwoordHash")):
                        registreer_fout_inlog("leerling")
                        registreer_server_fout_inlog("leerling", gebruikersnaam)
                        st.error("❌ Onjuiste inloggegevens.")
                    else:
                        if gebruiker.get("Goedgekeurd", "Ja") == "Ja":
                            reset_login_pogingen("leerling")
                            reset_server_login_pogingen("leerling", gebruikersnaam)
                            st.session_state.ingelogd = True
                            st.session_state.rol = "leerling"
                            st.session_state.is_gast = False
                            st.session_state.gebruikersnaam = gebruikersnaam
                            st.session_state.voornaam = gebruiker["Voornaam"]
                            st.session_state.niveau = gebruiker["Niveau"]
                            st.session_state.cluster = gebruiker["Cluster"]
                            st.session_state.nummer = gebruiker.get("Nummer", "999")
                            st.rerun()
                        else:
                            st.warning("⏳ Je account is nog niet goedgekeurd door je docent.")

        st.divider()
        with st.expander("Wachtwoord of inlognaam vergeten?"):
            st.write("Meld hier het probleem. De beheerder ziet dit in het storingenoverzicht; er wordt geen externe maildienst gebruikt.")
            with st.form("ww_vergeten_form"):
                vergeten_naam = st.text_input("Jouw voornaam:")
                vergeten_klas = st.selectbox("Jouw klas:", ALLE_CLUSTERS)
                vergeten_uitleg = st.text_area("Wat gaat er mis?", placeholder="Bijv. ik weet mijn gebruikersnaam niet meer of mijn wachtwoord werkt niet.")

                if st.form_submit_button("Meld inlogprobleem", type="primary"):
                    if not vergeten_naam.strip() or len(vergeten_uitleg.strip()) < 10:
                        st.error("Vul je naam en een korte omschrijving van minimaal 10 tekens in.")
                    else:
                        try:
                            maak_storing(
                                titel=f"Inlogprobleem - {vergeten_naam.strip()}",
                                omschrijving=vergeten_uitleg.strip(),
                                categorie="Inloggen/account",
                                voornaam=vergeten_naam.strip(),
                                gebruikersnaam="",
                                cluster=vergeten_klas,
                            )
                            st.success("✅ Je melding is verstuurd naar de beheerder.")
                        except Exception:
                            st.error("De melding kon niet worden verstuurd. Probeer het later opnieuw.")

    with tab_reg:
        st.subheader("Nieuw account aanmaken")
        st.warning("⚠️ **Privacy Waarschuwing:** Gebruik **géén herleidbare persoonsgegevens** in je inlognaam of wachtwoord.")
        reg_niveau = st.selectbox("Jouw niveau:", list(NIVEAUS.keys()), key="reg_niveau_ll")
        
        with st.form("leerling_reg_form"):
            reg_voornaam = st.text_input("Wat is je voornaam?")
            reg_cluster = st.selectbox("Jouw klas:", NIVEAUS[reg_niveau], key="reg_cluster_ll")
            reg_gn = st.text_input("Bedenk een inlognaam:")
            reg_ww = st.text_input("Bedenk een wachtwoord (Min 10 tekens, 1 cijfer, 1 speciaal teken):", type="password")
            reg_ww2 = st.text_input("Herhaal je wachtwoord:", type="password")
            
            if st.form_submit_button("Account Aanmaken"):
                if not reg_voornaam or not reg_gn or not reg_ww: 
                    st.error("Vul alle velden in.")
                elif reg_ww != reg_ww2: 
                    st.error("Wachtwoorden komen niet overeen!")
                else:
                    is_sterk, fout = is_sterk_wachtwoord(reg_ww)
                    if not is_sterk: 
                        st.error(fout)
                    else:
                        gebruikersnaam = reg_gn.strip()
                        if account_bestaat("gebruikers", "Gebruikersnaam", gebruikersnaam):
                            st.error("❌ Deze inlognaam is al bezet.")
                        else:
                            maak_account("gebruikers", "Gebruikersnaam", gebruikersnaam, {
                                "WachtwoordHash": hash_wachtwoord(reg_ww),
                                "Voornaam": reg_voornaam.strip(),
                                "Niveau": reg_niveau,
                                "Cluster": reg_cluster,
                                "Goedgekeurd": "Nee",
                                "Nummer": "999"
                            })
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
                    reset_login_pogingen("leerling")
                    st.session_state.ingelogd = True
                    st.session_state.rol = "leerling"
                    st.session_state.is_gast = True
                    st.session_state.gebruikersnaam = f"gast_{uuid.uuid4().hex[:6]}"
                    st.session_state.voornaam = f"{gast_voornaam.strip()} (Gast)"
                    st.session_state.niveau = gast_niveau
                    st.session_state.cluster = gast_cluster
                    st.session_state.nummer = "Gast"
                    st.rerun()

    # Render de minigame uit ui_leerling
    toon_mini_game()

# --- FOOTER ZIJBALK ---
st.sidebar.divider()
if not st.session_state.get("ingelogd") or st.session_state.get("rol") == "leerling":
    st.sidebar.slider("🎨 Achtergrond paneel dekking", min_value=0.0, max_value=1.0, value=0.85, step=0.05, key="bg_opacity", help="0.0 = volledig doorzichtig, 1.0 = volledig wit")
st.sidebar.caption(f"🔄 Laatste update app: {LAATSTE_UPDATE} | v{VERSIE}")
