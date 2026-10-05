import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import time
from config import HOOFDSTUKKEN, supabase
from auth import controleer_wachtwoord, hash_wachtwoord, is_sterk_wachtwoord, haal_gebruiker, update_account_velden
from bestanden import get_leerjaar, haal_bestanden_op, lees_docx, haal_resultaten_leerling, sla_resultaat_op, les_id, les_resultaat_mask, markeer_reactie_gelezen
from ai_docent import genereer_toets_gecached, kijk_toets_na
from storingen import haal_storingen, maak_storing, bevestig_storing

def toon_leerling_paneel():
    st.title("🗺️ Huiswerkcontrole AK")
    
    # Haal alleen data van de ingelogde leerling op. Gastresultaten worden niet opgeslagen.
    is_gast = st.session_state.get("is_gast", False)
    if is_gast:
        df_mijn = pd.DataFrame()
    else:
        df_mijn = haal_resultaten_leerling(st.session_state.gebruikersnaam)
    st.session_state.mijn_data_geschiedenis = df_mijn

    if not df_mijn.empty and "ReactieGelezen" in df_mijn.columns:
        if any((df_mijn["ReactieGelezen"] == "False") | (df_mijn["ReactieGelezen"] == False)):
            st.error("🚨 **Nieuw bericht!** Je docent heeft feedback achtergelaten. Kijk in het tabblad 'Mijn Resultaten'.")

    tab_oefen, tab_geschiedenis, tab_storingen, tab_instellingen = st.tabs(["🗺️ Oefenen", "📊 Mijn Resultaten", "🛠️ Storingen", "⚙️ Instellingen"])
    
    with tab_oefen:
        # Anti-cheating block
        st.html("""
            <script>
            if (!window.huiswerkPlakBlokkade) {
              window.huiswerkPlakBlokkade = true;
              const inToets = target => {
                const form = target.closest('[data-testid="stForm"]');
                return form && [...form.querySelectorAll('button')].some(
                  button => button.textContent.trim() === 'Lever in');
              };
              document.addEventListener('paste', function(e){
                if(inToets(e.target) && e.target.tagName === 'TEXTAREA') {
                    e.preventDefault();
                }
              });
              for (const type of ['contextmenu', 'selectstart']) {
                document.addEventListener(type, function(e){
                  if(inToets(e.target) && !e.target.closest('input, textarea')) e.preventDefault();
                });
              }
            }
            </script>
        """, unsafe_allow_javascript=True)

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
                    gekozen_les_id = les_id(lj, kies_hst, gekozen_les)
                    # Gebruik de al opgehaalde resultaten van alleen deze leerling.
                    aantal_pogingen = 0
                    if not df_mijn.empty and not is_gast:
                        df_leerling = df_mijn[df_mijn["Cluster"] == st.session_state.cluster]
                        df_les = df_leerling[les_resultaat_mask(df_leerling["Les"], lj, kies_hst, gekozen_les)]
                        aantal_pogingen = len(df_les)
                    
                    afgerond = (st.session_state.get("huidige_les") == gekozen_les_id
                                and st.session_state.get("toets_ingeleverd", False))
                    if aantal_pogingen >= 3 and not afgerond:
                        st.error("Je hebt het maximale aantal pogingen (3) voor deze les bereikt. Bestudeer je gemaakte fouten in het resultaten-tabblad.")
                    else:
                        versie = st.session_state.huidige_versie if afgerond else aantal_pogingen + 1
                        if not is_gast:
                            st.info(f"Dit is poging {versie} van 3 voor deze les.")
                        
                        if st.session_state.get("huidige_les") != gekozen_les_id or st.session_state.get("huidige_versie") != versie:
                            for sleutel in list(st.session_state):
                                if sleutel.startswith("q_"):
                                    del st.session_state[sleutel]
                            st.session_state.huidige_les = gekozen_les_id
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
                                        st.error("🚨 De toets kon niet worden gegenereerd. Probeer het opnieuw.")

                            # Fase 2: De Leerling Interface
                            if st.session_state.get("vragen_data") and not st.session_state.get("nakijk_resultaat"):
                                st.success("💡 De vragen zijn gegenereerd! Vul de antwoorden hieronder in en klik op 'Lever in'.")
                                
                                boek_dicht_keuze = st.radio("Voordat je begint: Heb je het boek gesloten?", ["Ja, ik ga de vragen uit mijn hoofd maken", "Nee, ik gebruik mijn boek als hulp"])
                                
                                with st.form("overhoring_form"):
                                    antwoorden = {}
                                    for idx, v in enumerate(st.session_state.vragen_data.get("vragen", [])):
                                        st.markdown(f"**Vraag {idx + 1}**")
                                        if v.get('type') == 'mc':
                                            antwoorden[v['id']] = st.radio(v.get('vraag', 'Vraag?'), v.get('opties', []), key=f"q_{gekozen_les_id}_{versie}_{v['id']}")
                                        else:
                                            antwoorden[v['id']] = st.text_area(v.get('vraag', 'Open Vraag?'), key=f"q_{gekozen_les_id}_{versie}_{v['id']}")
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
                                                
                                                # Gastresultaten blijven uitsluitend in de sessie; zo vervuilt de database niet.
                                                if is_gast:
                                                    success, err_msg = True, ""
                                                else:
                                                    success, err_msg = sla_resultaat_op(
                                                        st.session_state.niveau,
                                                        st.session_state.cluster,
                                                        st.session_state.get("nummer", "999"),
                                                        st.session_state.voornaam,
                                                        st.session_state.gebruikersnaam,
                                                        gekozen_les_id,
                                                        totaal_score,
                                                        volledige_feedback,
                                                        boek_dicht_status
                                                    )
                                                
                                                if success:
                                                    st.session_state.toets_ingeleverd = True
                                                    st.session_state.nakijk_resultaat = volledige_feedback
                                                    st.session_state.huidig_cijfer = totaal_score
                                                    st.session_state.docenten_feedback = ai_docent_tekst
                                                    st.rerun()
                                                else:
                                                    st.error("🚨 Het resultaat kon niet worden opgeslagen. Je antwoorden zijn nog bewaard in de invulvelden hierboven. Probeer zo opnieuw in te leveren.")
                                                    
                                            except Exception as e:
                                                st.error("🚨 Het nakijken is tijdelijk mislukt. Je antwoorden blijven staan; probeer zo opnieuw.")

                            # Feedback overzicht tonen
                            if st.session_state.get("nakijk_resultaat"):
                                st.success("✅ Toets succesvol nagekeken!" if is_gast else "✅ Toets succesvol ingeleverd!")
                                if st.session_state.huidig_cijfer >= 6.0: st.balloons()
                                
                                st.markdown(f"### Eindcijfer: {st.session_state.huidig_cijfer:.1f} / 10.0")
                                st.info(f"👨‍🏫 **Docent:** {st.session_state.get('docenten_feedback', '')}")
                                
                                st.markdown("### 📝 Specificatie per vraag")
                                st.markdown(st.session_state.nakijk_resultaat)

                                # Gastresultaten worden niet opgeslagen. De leerling stuurt daarom
                                # zelf een schermafbeelding van het resultaat naar de docent.
                                if is_gast:
                                    st.warning(
                                        "📧 **Gastmodus: stuur je resultaat naar je docent.**\n\n"
                                        "Je resultaat wordt in de gastmodus niet in de database opgeslagen. "
                                        "Maak daarom een schermafbeelding waarop **je eindcijfer en de specificatie per vraag** zichtbaar zijn "
                                        "en mail die als bijlage naar je docent.\n\n"
                                        "**Windows:** druk op **Windows + Shift + S**, selecteer het gedeelte met je resultaat en sla de afbeelding op. "
                                        "[Bekijk de officiële Microsoft-instructie voor een schermafbeelding](https://support.microsoft.com/nl-nl/windows/apps/use-snipping-tool-to-capture-screenshots)."
                                    )
                                    st.info(
                                        f"Zet in je e-mail bij voorkeur je naam, klas **{st.session_state.cluster}** "
                                        f"en de les **{gekozen_les_id}**. Voeg daarna de schermafbeelding als bijlage toe."
                                    )

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
        if is_gast:
            st.info("💡 Resultaten uit gast-sessies worden hier niet weergegeven.")
        else:
            df_hist = df_mijn
            if not df_hist.empty:
                for index, row in df_hist.iterrows():
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
                                            if markeer_reactie_gelezen(row["PogingID"], st.session_state.gebruikersnaam):
                                                st.rerun()
                                            else:
                                                st.error("De reactie kon niet als gelezen worden gemarkeerd.")
                                        except Exception as e:
                                            st.error("Markeren als gelezen is mislukt. Probeer het later opnieuw.")
                            else:
                                st.write("*De docent heeft nog geen extra reactie achtergelaten.*")
                else:
                    st.info("Je hebt nog geen overhoringen ingeleverd.")

    with tab_storingen:
        st.subheader("🛠️ Storingen melden")
        st.info(
            "Bekijk eerst of jouw storing al is gemeld. Zo voorkomen we dat dezelfde fout meerdere keren wordt doorgegeven."
        )

        try:
            df_storingen = haal_storingen()
        except Exception as e:
            st.error("Storingen konden niet worden opgehaald. Probeer het later opnieuw.")
            df_storingen = pd.DataFrame()

        if df_storingen.empty:
            st.success("Er zijn op dit moment geen gemelde storingen.")
        else:
            open_df = df_storingen[df_storingen["Status"] == "in behandeling"]
            opgelost_df = df_storingen[df_storingen["Status"] == "opgelost"]

            st.markdown(f"**In behandeling: {len(open_df)}**  •  **Opgelost: {len(opgelost_df)}**")
            for _, storing in df_storingen.head(25).iterrows():
                status = str(storing.get("Status", "in behandeling"))
                icoon = "🟠" if status == "in behandeling" else "✅"
                titel = str(storing.get("Titel", "Storing"))
                categorie = str(storing.get("Categorie", "Overig"))
                with st.expander(f"{icoon} {titel} — {status}"):
                    aantal_meldingen = int(storing.get("MeldingenAantal", 1) or 1)
                    st.caption(f"Categorie: {categorie} | Gemeld: {storing.get('Aangemaakt', '')} | {aantal_meldingen} leerling(en) ervaren dit")
                    st.write(str(storing.get("Omschrijving", "")))
                    if status == "in behandeling":
                        if st.button("Ik heb dit probleem ook", key=f"bevestig_storing_{storing.get('StoringID')}"):
                            try:
                                nieuw = bevestig_storing(
                                    storing.get("StoringID"),
                                    st.session_state.get("gebruikersnaam", "anoniem"),
                                )
                                if nieuw:
                                    st.success("Dank je. Je bevestiging is toegevoegd.")
                                    st.rerun()
                                else:
                                    st.info("Je had deze storing al bevestigd.")
                            except Exception:
                                st.error("Je bevestiging kon niet worden opgeslagen. Probeer het later opnieuw.")
                    admin_notitie = storing.get("AdminNotitie", "")
                    if pd.notna(admin_notitie) and str(admin_notitie).strip():
                        st.info(f"**Reactie beheerder:** {admin_notitie}")

        st.divider()
        st.markdown("### Nieuwe storing melden")
        st.caption("De melding wordt direct zichtbaar voor andere leerlingen met de status 'in behandeling'. Je naam en bijlage zijn alleen voor de beheerder zichtbaar.")

        with st.form("storing_melden_form", clear_on_submit=True):
            categorie = st.selectbox(
                "Waar gaat de storing over?",
                ["Inloggen/account", "Toets genereren", "Nakijken/resultaat", "Lesmateriaal", "Weergave/bediening", "Overig"],
            )
            titel = st.text_input("Korte titel", max_chars=160, placeholder="Bijv. Toets blijft laden bij inleveren")
            omschrijving = st.text_area(
                "Wat gaat er mis?",
                max_chars=4000,
                placeholder="Beschrijf wat je deed, wat je verwachtte en welke foutmelding je zag.",
            )
            bijlage = st.file_uploader(
                "Bijlage met foutmelding (optioneel)",
                type=["png", "jpg", "jpeg", "webp", "pdf"],
                help="Maximaal 8 MB. Bij voorkeur een screenshot van de foutmelding.",
            )
            gecontroleerd = st.checkbox("Ik heb hierboven gecontroleerd of deze storing al gemeld is.")
            submit_storing = st.form_submit_button("Storing melden", type="primary")

        if submit_storing:
            if not gecontroleerd:
                st.error("Controleer eerst of dezelfde storing al gemeld is.")
            else:
                try:
                    maak_storing(
                        titel=titel,
                        omschrijving=omschrijving,
                        categorie=categorie,
                        voornaam=st.session_state.get("voornaam", ""),
                        gebruikersnaam=st.session_state.get("gebruikersnaam", ""),
                        cluster=st.session_state.get("cluster", ""),
                        uploaded_file=bijlage,
                    )
                    st.success("✅ Storing gemeld. De status is nu 'in behandeling'.")
                    st.rerun()
                except Exception as e:
                    st.error("De storing kon niet worden gemeld. Controleer de invoer en probeer opnieuw.")

    with tab_instellingen:
        if is_gast:
            st.warning("Gasten hebben geen instellingen.")
        else:
            st.subheader("Wachtwoord Wijzigen")
            with st.form("ww_wijzig_form"):
                oud_ww = st.text_input("Oud wachtwoord:", type="password")
                nieuw_ww = st.text_input("Nieuw wachtwoord:", type="password")
                nieuw_ww2 = st.text_input("Herhaal nieuw:", type="password")
                
                if st.form_submit_button("Wijzig Wachtwoord"):
                    oude_gn = st.session_state.gebruikersnaam
                    gebruiker = haal_gebruiker(oude_gn)
                    if not gebruiker:
                        st.error("Je account is niet meer beschikbaar. Log opnieuw in.")
                    elif not controleer_wachtwoord(oud_ww, gebruiker.get("WachtwoordHash")):
                        st.error("Oud wachtwoord onjuist.")
                    elif nieuw_ww != nieuw_ww2:
                        st.error("Wachtwoorden komen niet overeen.")
                    else:
                        is_sterk, fout = is_sterk_wachtwoord(nieuw_ww)
                        if not is_sterk:
                            st.error(fout)
                        else:
                            try:
                                update_account_velden(
                                    "gebruikers", "Gebruikersnaam", oude_gn,
                                    {"WachtwoordHash": hash_wachtwoord(nieuw_ww)}
                                )
                                st.success("✅ Wachtwoord succesvol gewijzigd!")
                            except Exception as e:
                                st.error("Het wachtwoord kon niet worden gewijzigd. Probeer het later opnieuw.")

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
