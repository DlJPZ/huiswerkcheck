import streamlit as st
import pandas as pd
import re
import time
from config import supabase, HOOFDSTUKKEN, ALLE_CLUSTERS, NIVEAUS, LEERJAREN_CLUSTERS
from auth import laad_gebruikers, bewaar_alle_gebruikers, laad_docenten, bewaar_alle_docenten, hash_wachtwoord, is_sterk_wachtwoord
from bestanden import haal_alle_resultaten_op, haal_bestanden_op

# Helper functie om leerjaar te bepalen
def get_leerjaar(cluster_naam):
    for lj, clusters in LEERJAREN_CLUSTERS.items():
        if cluster_naam in clusters:
            return lj
    return None

def toon_docent_paneel():
    st.title(f"👨‍🏫 Docentenomgeving - Welkom {st.session_state.docent_naam}")
    mijn_klassen = st.session_state.docent_klassen
    
    if not mijn_klassen:
        st.warning("Je hebt nog geen klassen geselecteerd in je profiel.")
        return

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
                        # Upload uitsluitend naar Supabase Storage (geen lokale opslag meer)
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
                            if gn in alle_gebruikers:
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


def toon_admin_paneel():
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
                    if st.button("✅ Goedkeuren", key=f"ok_doc_{d_id}"):
                        docs[d_id]["Goedgekeurd"] = "Ja"
                        bewaar_alle_docenten(docs)
                        st.success(f"{d_info['Naam']} goedgekeurd!")
                        time.sleep(1)
                        st.rerun()
                with col2:
                    if st.button("❌ Weigeren", key=f"del_doc_{d_id}"):
                        if d_id in docs:
                            del docs[d_id]
                            try:
                                supabase.table("docenten").delete().eq("DocentID", d_id).execute()
                            except:
                                pass
                        bewaar_alle_docenten(docs)
                        st.warning("Account verwijderd.")
                        time.sleep(1)
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
