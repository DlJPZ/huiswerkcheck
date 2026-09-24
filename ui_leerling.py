import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import time
from config import HOOFDSTUKKEN, supabase
from auth import controleer_wachtwoord, hash_wachtwoord, is_sterk_wachtwoord, laad_gebruikers, bewaar_alle_gebruikers
from bestanden import get_leerjaar, haal_bestanden_op, lees_docx, haal_alle_resultaten_op, sla_resultaat_op
from ai_docent import genereer_toets_gecached, kijk_toets_na

def toon_leerling_paneel():
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
        # Anti-cheating block
        st.html("""
            <script>
            const parent = window.parent.document;
            parent.onpaste = function(e){
                if(e.target.tagName === 'TEXTAREA') {
                    e.preventDefault();
                }
            };
            parent.oncontextmenu = function(e){ e.preventDefault(); };
            parent.onselectstart = function(e){ e.preventDefault(); };
            </script>
        """)

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
                            # Fase 1: Vragen Genereren
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
                                            try:
                                                # Roep de nieuwe logica aan uit ai_docent.py
                                                totaal_score, volledige_feedback, ai_docent_tekst = kijk_toets_na(
                                                    st.session_state.niveau,
                                                    st.session_state.voornaam,
                                                    les_tekst,
                                                    st.session_state.vragen_data,
                                                    antwoorden
                                                )
                                                
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
                else:
                    st.info("Kies eerst een paragraaf in het dropdownmenu hierboven om de overhoring te starten.")

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

def toon_mini_game():
    st.divider()
    game_html = """
    <div style="text-align:center; font-family: sans-serif; color: #555; margin-top: 20px;">
        <p>Even wachten of pauze? Speel de <strong>Globe Runner</strong>! (Spatiebalk of tik op het speelveld om te springen)</p>
        <canvas id="gameCanvas" width="600" height="150" style="border:2px solid #ccc; border-radius: 10px; background-color: rgba(255,255,255,0.7); cursor: pointer; max-width: 100%;"></canvas>
    </div>
    <script>
        const canvas = document.getElementById("gameCanvas");
        const ctx = canvas.getContext("2d");
        
        let globe = { x: 50, y: 100, size: 24, vy: 0, gravity: 0.6, jump: -10, isGrounded: false };
        let obstacles = [];
        let score = 0;
        let gameOver = false;
        let frameCount = 0;
        let speed = 4;

        function resetGame() {
            globe.y = 100; globe.vy = 0;
            obstacles = []; score = 0; gameOver = false; speed = 4; frameCount = 0;
            loop();
        }

        function jump(e) {
            if(e && e.type === "keydown" && e.code === "Space") e.preventDefault(); 
            if (globe.isGrounded && !gameOver) {
                globe.vy = globe.jump;
                globe.isGrounded = false;
            } else if (gameOver) {
                resetGame();
            }
        }

        window.addEventListener("keydown", (e) => { if (e.code === "Space") jump(e); });
        canvas.addEventListener("mousedown", jump);
        canvas.addEventListener("touchstart", jump);

        function drawGlobe(x, y) { ctx.font = "24px sans-serif"; ctx.fillText("🌍", x, y); }
        function drawObstacle(x, y) { ctx.font = "24px sans-serif"; ctx.fillText("⛰️", x, y); }

        function loop() {
            if (gameOver) {
                ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fillRect(0,0,canvas.width, canvas.height);
                ctx.fillStyle = "#333"; ctx.font = "bold 20px Arial"; ctx.textAlign = "center";
                ctx.fillText("Game Over! Score: " + Math.floor(score), canvas.width/2, 70);
                ctx.font = "16px Arial";
                ctx.fillText("Klik of spatiebalk om opnieuw te spelen", canvas.width/2, 100);
                ctx.textAlign = "left";
                return;
            }

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            globe.vy += globe.gravity;
            globe.y += globe.vy;
            if (globe.y >= 100) { globe.y = 100; globe.isGrounded = true; globe.vy = 0; }

            frameCount++;
            if (frameCount % Math.floor(100 / (speed/4)) === 0) {
                obstacles.push({ x: canvas.width, y: 100 });
            }

            for (let i = 0; i < obstacles.length; i++) {
                obstacles[i].x -= speed;
                drawObstacle(obstacles[i].x, obstacles[i].y + 20);

                let dx = obstacles[i].x - globe.x;
                let dy = (obstacles[i].y+20) - (globe.y+20);
                let distance = Math.sqrt(dx*dx + dy*dy);
                if (distance < 20) { gameOver = true; }
            }

            obstacles = obstacles.filter(obs => obs.x > -30);

            drawGlobe(globe.x, globe.y + 20);

            score += 0.05;
            speed += 0.001;

            ctx.fillStyle = "#333"; ctx.font = "bold 16px Arial";
            ctx.fillText("Score: " + Math.floor(score), 480, 30);

            requestAnimationFrame(loop);
        }
        resetGame();
    </script>
    """
    components.html(game_html, height=220)
