import pandas as pd
import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials
import datetime

# pompompidou


st.set_page_config(
    page_title="CREM - Gestion des polys Tutorat",
    page_icon="logo.png"  # logo du crem ou du tut ?
)

# pompompidou

scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

credentials = {
    "type": st.secrets["gcp_service_account"]["type"],
    "project_id": st.secrets["gcp_service_account"]["project_id"],
    "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
    "private_key": st.secrets["gcp_service_account"]["private_key"],
    "client_email": st.secrets["gcp_service_account"]["client_email"],
    "client_id": st.secrets["gcp_service_account"]["client_id"],
    "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
    "token_uri": st.secrets["gcp_service_account"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["gcp_service_account"]["client_x509_cert_url"]
}

creds = Credentials.from_service_account_info(credentials, scopes=scopes)
client = gspread.authorize(creds)
sheet = client.open("1").sheet1

try:
    log_sheet = client.open("1").worksheet("Logs")
except gspread.exceptions.WorksheetNotFound:
    log_sheet = client.open("1").add_worksheet(title="Logs", rows=1000, cols=6)
    log_sheet.append_row(["Date", "Heure", "Utilisateur", "Action", "Détails", "Statut"])


def log_activity(username, action, details, status):
    now = datetime.datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M:%S")
    try:
        log_sheet.append_row([date_str, time_str, username, action, details, status])
    except Exception as e:
        st.error(f"Erreur de journalisation: {e}")


def verifier_identifiants(utilisateur, mot_de_passe):
    utilisateurs = st.secrets["credentials"]
    return utilisateurs.get(utilisateur) == mot_de_passe


def enhance_for_low_light(image, alpha=1.5, beta=10):
    enhanced = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    return enhanced


def scan_barcode(image, night_mode=False):
    """
    Enhanced barcode scanning with improved preprocessing.
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Enhanced preprocessing for different lighting conditions
    if night_mode:
        # Apply CLAHE for better contrast in low light
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # Enhanced brightness/contrast for night mode
        gray = cv2.convertScaleAbs(gray, alpha=2.0, beta=30)

    # Apply noise reduction (reduces camera noise impact)
    denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

    # Apply Gaussian blur
    blurred = cv2.GaussianBlur(denoised, (5, 5), 0)

    # Try decoding the preprocessed image
    results = decode(blurred)
    if results:
        return results, blurred

    # Try with adaptive thresholding
    block_size = 15 if night_mode else 11
    c_value = 7 if night_mode else 2

    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, block_size, c_value
    )

    results = decode(thresh)
    if results:
        return results, thresh

    # Try inverted threshold (often helps with certain barcodes)
    thresh_inv = cv2.bitwise_not(thresh)
    results = decode(thresh_inv)
    if results:
        return results, thresh_inv

    # Try edge detection
    edges = cv2.Canny(blurred, 30 if night_mode else 50, 150 if night_mode else 200)
    results = decode(edges)
    if results:
        return results, edges

    # Try morphological operations as last resort
    kernel = np.ones((5, 5) if night_mode else (3, 3), np.uint8)
    closing = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    results = decode(closing)
    if results:
        return results, closing

    # If all methods fail
    return None, blurred


if "authentifie" not in st.session_state:
    st.session_state.authentifie = False
    st.session_state.username = None
    st.session_state.is_admin = False

if not st.session_state.authentifie:
    col1, col2, col3 = st.columns(3)

    with col1:
        st.write(' ')

    with col2:
        st.image("logo.png")

    with col3:
        st.write(' ')

    st.title("Connexion")
    utilisateur = st.text_input("Identifiant")
    mot_de_passe = st.text_input("Mot de passe", type="password")
    connexion_bouton = st.button("Se connecter")
    if connexion_bouton:
        if verifier_identifiants(utilisateur, mot_de_passe):
            st.session_state.authentifie = True
            st.session_state.username = utilisateur
            st.session_state.is_admin = ["SirIsaac21", "vp_star", "sophie"]
            log_activity(utilisateur, "Connexion", "Connexion réussie", "Succès")
            st.success("✅ Connexion réussie !")
            st.rerun()
        else:
            log_activity(utilisateur, "Tentative de connexion", "Identifiants incorrects", "Échec")
            st.error("❌ Identifiants incorrects. Veuillez réessayer.")

    st.stop()

# For the non-admin user interface
if st.session_state.username not in st.session_state.is_admin:
    st.header(f"Coucou {st.session_state.username} !")

    # 1. COURSE SELECTION - MOVED TO FIRST POSITION
    st.subheader("1. Sélectionner un cours")

    try:
        liste_cours = sheet.row_values(1)
        if not liste_cours:
            st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
            log_activity(st.session_state.username, "Chargement des cours", "Aucun cours trouvé", "Échec")
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des cours : {e}")
        log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
        liste_cours = []

    cours_selectionne = st.selectbox("Choisissez un cours :", liste_cours)

    # Store the selected course in session state
    if "cours_selectionne" not in st.session_state:
        st.session_state.cours_selectionne = None

    st.session_state.cours_selectionne = cours_selectionne

    st.write(
        "-------------------------------------------------------------------------------------------------------------------------")

    # 2. BARCODE SCANNING - NOW SECOND
    st.subheader("2. Scanner un code-barres")

    night_mode = st.checkbox("Mode faible luminosité",
                             help="Activez cette option si vous êtes dans un environnement peu éclairé")

    scan_tab, upload_tab = st.tabs(["Utiliser la caméra", "Importer une image"])

    # Camera scanning with immediate processing
    with scan_tab:
        st.write("Préparez-vous à scanner le code-barres de l'étudiant")
        img_file_buffer = st.camera_input("Prendre la photo et enregistrer", key="camera_input")

        if img_file_buffer:
            # Process image immediately when camera input is received
            file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            decoded_objs, processed_img = scan_barcode(image, night_mode)

            if decoded_objs:
                barcode_data = decoded_objs[0].data.decode("utf-8")
                st.session_state.numero_adherent = barcode_data

                # Display success message with extracted information
                st.success(f"✅ Code détecté: {barcode_data}")

                # Immediately try to register the course pickup
                try:
                    cellule = sheet.find(barcode_data)

                    if cellule:
                        ligne = cellule.row
                        if cours_selectionne in liste_cours:
                            colonne = liste_cours.index(cours_selectionne) + 1
                            try:
                                current_value = sheet.cell(ligne, colonne).value

                                if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                                    st.error(f"❌ Cet étudiant a déjà récupéré le poly {cours_selectionne}.")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}, Déjà récupéré",
                                                 "Échec")
                                else:
                                    sheet.update_cell(ligne, colonne, 1)
                                    st.success(f"✅ Poly {cours_selectionne} attribué à l'étudiant {barcode_data} !")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}",
                                                 "Succès")
                            except Exception as e:
                                st.error(f"❌ Erreur lors de la mise à jour : {e}")
                                log_activity(st.session_state.username, "Enregistrement poly",
                                             f"ID: {barcode_data}, Cours: {cours_selectionne}, Erreur: {str(e)}",
                                             "Échec")
                        else:
                            st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
                            log_activity(st.session_state.username, "Enregistrement poly",
                                         f"ID: {barcode_data}, Cours: {cours_selectionne} inexistant",
                                         "Échec")
                    else:
                        st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                        log_activity(st.session_state.username, "Enregistrement poly",
                                     f"ID: {barcode_data} non trouvé", "Échec")
                except Exception as e:
                    st.error(f"❌ Erreur lors du traitement : {e}")
            else:
                st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)

                if not night_mode:
                    st.warning(
                        "💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")

    # Upload image with immediate processing
    with upload_tab:
        uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                         type=['jpg', 'jpeg', 'png', 'bmp'])

        if uploaded_file:
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            decoded_objs, processed_img = scan_barcode(image, night_mode)

            if decoded_objs:
                barcode_data = decoded_objs[0].data.decode("utf-8")
                st.session_state.numero_adherent = barcode_data
                st.success(f"✅ Code détecté: {barcode_data}")

                # Same processing as camera input
                # Immediate registration of course pickup
                try:
                    cellule = sheet.find(barcode_data)

                    if cellule:
                        ligne = cellule.row
                        if cours_selectionne in liste_cours:
                            colonne = liste_cours.index(cours_selectionne) + 1
                            try:
                                current_value = sheet.cell(ligne, colonne).value

                                if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                                    st.error(f"❌ Cet étudiant a déjà récupéré le poly {cours_selectionne}.")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}, Déjà récupéré",
                                                 "Échec")
                                else:
                                    sheet.update_cell(ligne, colonne, 1)
                                    st.success(f"✅ Poly {cours_selectionne} attribué à l'étudiant {barcode_data} !")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}",
                                                 "Succès")
                            except Exception as e:
                                st.error(f"❌ Erreur lors de la mise à jour : {e}")
                                log_activity(st.session_state.username, "Enregistrement poly",
                                             f"ID: {barcode_data}, Cours: {cours_selectionne}, Erreur: {str(e)}",
                                             "Échec")
                        else:
                            st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
                            log_activity(st.session_state.username, "Enregistrement poly",
                                         f"ID: {barcode_data}, Cours: {cours_selectionne} inexistant",
                                         "Échec")
                    else:
                        st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                        log_activity(st.session_state.username, "Enregistrement poly",
                                     f"ID: {barcode_data} non trouvé", "Échec")
                except Exception as e:
                    st.error(f"❌ Erreur lors du traitement : {e}")
            else:
                st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)


if st.session_state.username in st.session_state.is_admin:
    tab1, tab2 = st.tabs(["🤓 Interface des tuteurs", "👑 Admin"])
    with tab1:

        st.subheader("1. Sélectionner un cours")

        try:
            liste_cours = sheet.row_values(1)
            if not liste_cours:
                st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
                log_activity(st.session_state.username, "Chargement des cours", "Aucun cours trouvé", "Échec")
        except Exception as e:
            st.error(f"❌ Erreur lors de la récupération des cours : {e}")
            log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
            liste_cours = []

        cours_selectionne = st.selectbox("Choisissez un cours :", liste_cours)

        # Store the selected course in session state
        if "cours_selectionne" not in st.session_state:
            st.session_state.cours_selectionne = None

        st.session_state.cours_selectionne = cours_selectionne

        st.write(
            "-------------------------------------------------------------------------------------------------------------------------")

        # 2. BARCODE SCANNING - NOW SECOND
        st.subheader("2. Scanner un code-barres")

        night_mode = st.checkbox("Mode faible luminosité",
                                 help="Activez cette option si vous êtes dans un environnement peu éclairé")

        scan_tab, upload_tab = st.tabs(["Utiliser la caméra", "Importer une image"])

        # Camera scanning with immediate processing
        with scan_tab:
            st.write("Préparez-vous à scanner le code-barres de l'étudiant")
            img_file_buffer = st.camera_input("Prendre la photo et enregistrer", key="camera_input")

            if img_file_buffer:
                # Process image immediately when camera input is received
                file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
                image = cv2.imdecode(file_bytes, 1)
                decoded_objs, processed_img = scan_barcode(image, night_mode)

                if decoded_objs:
                    barcode_data = decoded_objs[0].data.decode("utf-8")
                    st.session_state.numero_adherent = barcode_data

                    # Display success message with extracted information
                    st.success(f"✅ Code détecté: {barcode_data}")

                    # Immediately try to register the course pickup
                    try:
                        cellule = sheet.find(barcode_data)

                        if cellule:
                            ligne = cellule.row
                            if cours_selectionne in liste_cours:
                                colonne = liste_cours.index(cours_selectionne) + 1
                                try:
                                    current_value = sheet.cell(ligne, colonne).value

                                    if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                                        st.error(f"❌ Cet étudiant a déjà récupéré le poly {cours_selectionne}.")
                                        log_activity(st.session_state.username, "Enregistrement poly",
                                                     f"ID: {barcode_data}, Cours: {cours_selectionne}, Déjà récupéré",
                                                     "Échec")
                                    else:
                                        sheet.update_cell(ligne, colonne, 1)
                                        st.success(f"✅ Poly {cours_selectionne} attribué à l'étudiant {barcode_data} !")
                                        log_activity(st.session_state.username, "Enregistrement poly",
                                                     f"ID: {barcode_data}, Cours: {cours_selectionne}",
                                                     "Succès")
                                except Exception as e:
                                    st.error(f"❌ Erreur lors de la mise à jour : {e}")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}, Erreur: {str(e)}",
                                                 "Échec")
                            else:
                                st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
                                log_activity(st.session_state.username, "Enregistrement poly",
                                             f"ID: {barcode_data}, Cours: {cours_selectionne} inexistant",
                                             "Échec")
                        else:
                            st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                            log_activity(st.session_state.username, "Enregistrement poly",
                                         f"ID: {barcode_data} non trouvé", "Échec")
                    except Exception as e:
                        st.error(f"❌ Erreur lors du traitement : {e}")
                else:
                    st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                    st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)

                    if not night_mode:
                        st.warning(
                            "💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")

        # Upload image with immediate processing
        with upload_tab:
            uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                             type=['jpg', 'jpeg', 'png', 'bmp'])

            if uploaded_file:
                file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
                image = cv2.imdecode(file_bytes, 1)
                decoded_objs, processed_img = scan_barcode(image, night_mode)

                if decoded_objs:
                    barcode_data = decoded_objs[0].data.decode("utf-8")
                    st.session_state.numero_adherent = barcode_data
                    st.success(f"✅ Code détecté: {barcode_data}")

                    # Same processing as camera input
                    # Immediate registration of course pickup
                    try:
                        cellule = sheet.find(barcode_data)

                        if cellule:
                            ligne = cellule.row
                            if cours_selectionne in liste_cours:
                                colonne = liste_cours.index(cours_selectionne) + 1
                                try:
                                    current_value = sheet.cell(ligne, colonne).value

                                    if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                                        st.error(f"❌ Cet étudiant a déjà récupéré le poly {cours_selectionne}.")
                                        log_activity(st.session_state.username, "Enregistrement poly",
                                                     f"ID: {barcode_data}, Cours: {cours_selectionne}, Déjà récupéré",
                                                     "Échec")
                                    else:
                                        sheet.update_cell(ligne, colonne, 1)
                                        st.success(f"✅ Poly {cours_selectionne} attribué à l'étudiant {barcode_data} !")
                                        log_activity(st.session_state.username, "Enregistrement poly",
                                                     f"ID: {barcode_data}, Cours: {cours_selectionne}",
                                                     "Succès")
                                except Exception as e:
                                    st.error(f"❌ Erreur lors de la mise à jour : {e}")
                                    log_activity(st.session_state.username, "Enregistrement poly",
                                                 f"ID: {barcode_data}, Cours: {cours_selectionne}, Erreur: {str(e)}",
                                                 "Échec")
                            else:
                                st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
                                log_activity(st.session_state.username, "Enregistrement poly",
                                             f"ID: {barcode_data}, Cours: {cours_selectionne} inexistant",
                                             "Échec")
                        else:
                            st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                            log_activity(st.session_state.username, "Enregistrement poly",
                                         f"ID: {barcode_data} non trouvé", "Échec")
                    except Exception as e:
                        st.error(f"❌ Erreur lors du traitement : {e}")
                else:
                    st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                    st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)

    with tab2:
        if st.session_state.username not in st.session_state.is_admin:
            st.error("⛔️ Accès non autorisé. Vous n'avez pas les droits d'administration.")
            st.info("Si tu n'es ni VP ni Sophie tu n'as pas accès à cette section.")
        else:
            st.success("👑 Bravo, t'es admin ! Sophie t'a adoubé ?")
            backup_cols = st.columns(2)
            with backup_cols[0]:
                if st.button("Télécharger toutes les données (CSV)"):
                    try:
                        all_data = sheet.get_all_records()
                        df = pd.DataFrame(all_data)
                        st.download_button(
                            "Confirmer le téléchargement",
                            data=df.to_csv(index=False).encode('utf-8'),
                            file_name=f"CREM_data_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                        log_activity(st.session_state.username, "Export données", "Téléchargement CSV", "Succès")
                    except Exception as e:
                        st.error(f"Erreur d'export: {e}")

            with backup_cols[1]:
                if st.button("Télécharger les journaux d'activité"):
                    try:
                        all_logs = log_sheet.get_all_records()
                        df_logs = pd.DataFrame(all_logs)
                        st.download_button(
                            "Confirmer le téléchargement",
                            data=df_logs.to_csv(index=False).encode('utf-8'),
                            file_name=f"CREM_logs_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                    except Exception as e:
                        st.error(f"Erreur d'export: {e}")

            admin_tabs = st.tabs(["Tableau de bord", "Journaux d'activité", "Gestion des utilisateurs",
                                  "Gestion des cours", "Recherche d'étudiants"])
            # pompompidou

            # 1. DASHBOARD TAB
            with admin_tabs[0]:
                st.header("Tableau de bord")
                try:
                    all_data = sheet.get_all_records()
                    total_students = len(all_data)
                    total_polys = sum(1 for row in all_data for col, val in row.items() if val == 1)
                    nbLAS, nbPOLY, tauxREUSSITE = st.columns(3)

                    with nbLAS:
                        st.metric("Total de LAS inscrits", total_students)
                    with nbPOLY:
                        st.metric("Total de polys distribués", total_polys)
                    with tauxREUSSITE:
                        all_logs = log_sheet.get_all_records()

                        success_count = len([log for log in all_logs if log['Statut'] == 'Succès'])
                        failure_count = len([log for log in all_logs if log['Statut'] == 'Échec'])
                        total_actions = len(all_logs)

                        if total_actions > 0:
                            success_rate = (success_count / total_actions) * 100
                            st.metric("Taux de réussite", f"{success_rate:.1f}%")

                    course_counts = {}
                    for row in all_data:
                        for course, val in row.items():
                            if val == 1 and course != sheet.cell(1, 1).value:
                                course_counts[course] = course_counts.get(course, 0) + 1
                    all_logs = log_sheet.get_all_records()
                    activity_counts = {}
                    for log in all_logs:
                        date = log['Date']
                        activity_counts[date] = activity_counts.get(date, 0) + 1

                    chart_data = pd.DataFrame({
                        'Date': activity_counts.keys(),
                        'Activités': activity_counts.values()
                    })

                    st.subheader("Activité par jour")
                    st.bar_chart(chart_data.set_index('Date'))


                except Exception as e:
                    st.error(f"Erreur d'affichage des statistiques: {e}")
                st.subheader("Activité récente")
                try:
                    recent_logs = sorted(all_logs, key=lambda x: (x['Date'], x['Heure']), reverse=True)[:10]
                    st.dataframe(pd.DataFrame(recent_logs), use_container_width=True)
                except Exception as e:
                    st.error(f"Erreur lors de l'affichage de l'activité récente: {e}")

            # 2. ACTIVITY LOGS TAB
            with admin_tabs[1]:
                st.header("Journal d'activité")

                try:
                    all_logs = log_sheet.get_all_records()

                    if not all_logs:
                        st.info("Aucune activité enregistrée pour le moment.")
                    else:
                        col1, col2 = st.columns(2)

                        with col1:
                            usernames = list(set(log['Utilisateur'] for log in all_logs))
                            selected_user = st.selectbox("Filtrer par utilisateur:",
                                                         ["Tous les utilisateurs"] + usernames)

                        with col2:
                            actions = list(set(log['Action'] for log in all_logs))
                            selected_action = st.selectbox("Filtrer par type d'action:",
                                                           ["Toutes les actions"] + actions)

                        start_date, end_date = st.columns(2)
                        with start_date:
                            min_date = datetime.datetime.strptime(min(log['Date'] for log in all_logs),
                                                                  "%d/%m/%Y").date()
                            date_debut = st.date_input("Date de début:", min_date)

                        with end_date:
                            max_date = datetime.datetime.strptime(max(log['Date'] for log in all_logs),
                                                                  "%d/%m/%Y").date()
                            date_fin = st.date_input("Date de fin:", max_date)
                        # pompompidou

                        filtered_logs = all_logs

                        if selected_user != "Tous les utilisateurs":
                            filtered_logs = [log for log in filtered_logs if log['Utilisateur'] == selected_user]

                        if selected_action != "Toutes les actions":
                            filtered_logs = [log for log in filtered_logs if log['Action'] == selected_action]

                        filtered_logs = [
                            log for log in filtered_logs
                            if datetime.datetime.strptime(log['Date'], "%d/%m/%Y").date() >= date_debut
                               and datetime.datetime.strptime(log['Date'], "%d/%m/%Y").date() <= date_fin
                        ]

                        if not filtered_logs:
                            st.warning("Aucune activité correspondant aux critères sélectionnés.")
                        else:
                            def color_status(status):
                                if status == "Succès":
                                    return "background-color: #CCFFCC"
                                elif status == "Échec":
                                    return "background-color: #FFCCCC"
                                return ""


                            df_logs = pd.DataFrame(filtered_logs)
                            st.dataframe(df_logs.style.applymap(color_status, subset=['Statut']),
                                         height=400, use_container_width=True)

                            st.download_button(
                                label="📥 Télécharger les logs filtrés (CSV)",
                                data=df_logs.to_csv(index=False).encode('utf-8'),
                                file_name=f"logs_CREM_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                mime="text/csv")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la récupération des logs: {e}")

            # 3. USER MANAGEMENT TAB
            with admin_tabs[2]:
                st.header("Gestion des utilisateurs")

                # Display current users
                st.subheader("Utilisateurs actuels")
                try:
                    users = {user: {"password": pwd, "admin": user == st.session_state.username}
                             for user, pwd in st.secrets["credentials"].items()}

                    user_df = pd.DataFrame([
                        {"Utilisateur": user, "Statut": "Administrateur" if details["admin"] else "Utilisateur"}
                        for user, details in users.items()
                    ])

                    st.dataframe(user_df, use_container_width=True)

                    # User management form
                    with st.expander("Ajouter/Modifier un utilisateur"):
                        st.write(
                            "⚠️ Note: Les modifications apportées ici nécessitent une implémentation côté serveur pour être persistantes.")

                        new_user = st.text_input("Nom d'utilisateur")
                        new_password = st.text_input("Mot de passe", type="password")
                        is_admin = st.checkbox("Administrateur")

                        if st.button("Enregistrer"):
                            st.warning(
                                "Cette fonctionnalité nécessite une implémentation côté serveur pour modifier secrets.toml")
                            st.info(
                                "Les modifications des utilisateurs ne peuvent pas être appliquées directement depuis l'interface web.")
                            log_activity(st.session_state.username, "Tentative de modification utilisateur",
                                         f"Utilisateur: {new_user}", "Information")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la gestion des utilisateurs: {e}")
            # pompompidou

            # 4. COURSE MANAGEMENT TAB
            with admin_tabs[3]:
                st.header("Gestion des cours")

                try:
                    courses = sheet.row_values(1)[1:]

                    course_data = []
                    for i, course in enumerate(courses):
                        count = len([1 for cell in sheet.col_values(i + 2)[1:] if cell == '1'])
                        course_data.append({"Cours": course, "Polys distribués": count})

                    st.dataframe(pd.DataFrame(course_data), use_container_width=True)

                    st.subheader("Ajouter un nouveau cours")
                    new_course = st.text_input("Nom du nouveau cours")
                    if st.button("Ajouter ce cours"):
                        if new_course:
                            try:
                                if new_course in courses:
                                    st.error(f"Le cours '{new_course}' existe déjà!")
                                else:
                                    sheet.update_cell(1, len(courses) + 2, new_course)
                                    log_activity(st.session_state.username, "Ajout de cours", f"Cours: {new_course}",
                                                 "Succès")
                                    st.success(f"✅ Cours '{new_course}' ajouté avec succès!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erreur: {e}")
                                log_activity(st.session_state.username, "Ajout de cours",
                                             f"Cours: {new_course}, Erreur: {str(e)}", "Échec")
                        else:
                            st.error("Veuillez saisir un nom de cours")
                except Exception as e:
                    st.error(f"❌ Erreur lors du chargement des cours: {e}")

            # 5. STUDENT SEARCH TAB
            with admin_tabs[4]:
                st.header("Recherche et gestion d'étudiants")

                try:
                    all_students = sheet.get_all_records()
                    id_field = sheet.cell(1, 1).value

                    search_term = st.text_input("Rechercher un étudiant par numéro CREM")

                    if search_term:
                        results = [student for student in all_students
                                   if search_term.lower() in str(student.get(id_field, '')).lower()]

                        if results:
                            st.write(f"{len(results)} résultat(s) trouvé(s)")
                            st.dataframe(pd.DataFrame(results), use_container_width=True)

                            student_id = st.selectbox(
                                "Modifier les polys récupérés:",
                                [str(s.get(id_field)) for s in results]
                            )

                            if student_id:
                                student_row = sheet.find(student_id).row
                                courses = sheet.row_values(1)[1:]

                                st.write("Cochez les polys récupérés:")
                                cols = st.columns(3)
                                updated_values = {}

                                for i, course in enumerate(courses):
                                    col_index = i % 3
                                    current_val = sheet.cell(student_row, i + 2).value
                                    with cols[col_index]:
                                        has_poly = st.checkbox(
                                            course,
                                            value=True if current_val == '1' else False
                                        )
                                        updated_values[i + 2] = '1' if has_poly else ''

                                if st.button("Mettre à jour"):
                                    for col, val in updated_values.items():
                                        sheet.update_cell(student_row, col, val)
                                    log_activity(st.session_state.username, "Modification étudiant",
                                                 f"ID: {student_id}", "Succès")
                                    st.success("✅ Informations mises à jour!")
                        else:
                            st.warning("Aucun étudiant trouvé.")
                    # pompompidou

                    with st.expander("Ajouter un nouvel étudiant"):
                        new_student_id = st.text_input("Numéro d'adhérent")

                        if st.button("Ajouter"):
                            if new_student_id:
                                try:
                                    existing = None
                                    try:
                                        existing = sheet.find(new_student_id)
                                    except:
                                        pass

                                    if existing:
                                        st.error(f"Un étudiant avec l'ID '{new_student_id}' existe déjà!")
                                    else:
                                        sheet.append_row([new_student_id] + [''] * (len(sheet.row_values(1)) - 1))
                                        log_activity(st.session_state.username, "Ajout étudiant",
                                                     f"ID: {new_student_id}", "Succès")
                                        st.success(f"✅ Étudiant '{new_student_id}' ajouté avec succès!")
                                except Exception as e:
                                    st.error(f"❌ Erreur: {e}")
                            else:
                                st.error("Veuillez saisir un numéro d'adhérent")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la recherche d'étudiants: {e}")
# pompompidou

st.write(
    "-------------------------------------------------------------------------------------------------------------------------")
user, propos = st.columns(2)

with user:
    if st.button("Se déconnecter"):
        log_activity(st.session_state.username, "Déconnexion", "", "Succès")
        st.session_state.authentifie = False
        st.session_state.username = None
        st.session_state.is_admin = False
        st.rerun()

with propos:
    with st.expander("À propos"):
        st.write("### CREM - Gestion des polys Tutorat")
        st.write("Version: 1.0.0")
        st.write("Contact: web@crem.fr")
        st.write("<3")

# Mathéo Milley-Arjaliès, Webmaster au CREM, référent SHS au Tutorat
