import pandas as pd
import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials
import datetime
import functools
import time

# Configuration de la page Streamlit
st.set_page_config(
    page_title="CREM - Gestion des polys Tutorat",
    page_icon="logo.png"
)

# Cache pour les appels à Google Sheets
@st.cache_data(ttl=300)  # Mise en cache pendant 5 minutes
def get_sheet_data():
    """Récupère les données de Google Sheets avec mise en cache"""
    return sheet.get_all_records()

@st.cache_data(ttl=300)
def get_courses():
    """Récupère la liste des cours avec mise en cache"""
    return sheet.row_values(1)

# Fonction pour mesurer le temps d'exécution (utile pour optimisation)
def timing_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        if st.session_state.get('debug_mode', False):
            st.write(f"Fonction {func.__name__} exécutée en {end_time - start_time:.4f} secondes")
        return result
    return wrapper

# Configuration de l'authentification Google
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

# Connexion aux APIs Google une seule fois
@st.cache_resource
def get_gspread_client():
    """Initialise le client gspread avec mise en cache de ressource"""
    creds = Credentials.from_service_account_info(credentials, scopes=scopes)
    return gspread.authorize(creds)

# Initialisation des clients et feuilles
client = get_gspread_client()
sheet = client.open("1").sheet1

# Essayer de récupérer la feuille de logs une seule fois
try:
    log_sheet = client.open("1").worksheet("Logs")
except gspread.exceptions.WorksheetNotFound:
    log_sheet = client.open("1").add_worksheet(title="Logs", rows=1000, cols=6)
    log_sheet.append_row(["Date", "Heure", "Utilisateur", "Action", "Détails", "Statut"])

# Fonctions d'utilitaires
def log_activity(username, action, details, status):
    """Journalise les activités avec gestion d'erreur améliorée"""
    now = datetime.datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    time_str = now.strftime("%H:%M:%S")
    
    # Utilisation d'un batch update pour réduire les appels API
    try:
        log_sheet.append_row([date_str, time_str, username, action, details, status])
    except Exception as e:
        st.error(f"Erreur de journalisation: {e}")
        # Tentative de reconnexion en cas d'erreur d'expiration de token
        if "invalid token" in str(e).lower():
            global client, sheet, log_sheet
            st.cache_resource.clear()
            client = get_gspread_client()
            sheet = client.open("1").sheet1
            log_sheet = client.open("1").worksheet("Logs")
            # Réessayer une fois
            try:
                log_sheet.append_row([date_str, time_str, username, action, details, status])
            except Exception as retry_e:
                st.error(f"Échec de la tentative de reconnexion: {retry_e}")

def verifier_identifiants(utilisateur, mot_de_passe):
    """Vérifie les identifiants utilisateur"""
    utilisateurs = st.secrets["credentials"]
    return utilisateurs.get(utilisateur) == mot_de_passe

@timing_decorator
def enhance_for_low_light(image, alpha=1.5, beta=10):
    """Améliore le contraste pour les images en faible luminosité"""
    enhanced = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    return enhanced

@timing_decorator
def scan_barcode(image, night_mode=False):
    """Fonction optimisée de scan de code-barres avec différentes méthodes"""
    # Conversion en niveaux de gris
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Amélioration pour faible luminosité si nécessaire
    if night_mode:
        gray = enhance_for_low_light(gray, alpha=1.8, beta=30)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    
    # Redimensionner l'image si elle est trop grande (optimisation)
    height, width = gray.shape
    max_dimension = 1000
    if height > max_dimension or width > max_dimension:
        scale = max_dimension / max(height, width)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    
    # Méthode 1: Flou gaussien et décodage direct
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    results = decode(blurred)
    if results:
        return results, blurred
    
    # Méthode 2: Seuillage adaptatif
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 13 if night_mode else 11, 5 if night_mode else 2)
    results = decode(thresh)
    if results:
        return results, thresh
    
    # Méthode 3: Détection de contours
    edges = cv2.Canny(blurred, 30 if night_mode else 50, 150 if night_mode else 200, apertureSize=3)
    results = decode(edges)
    if results:
        return results, edges
    
    # Méthode 4: Opérations morphologiques
    kernel = np.ones((5, 5) if night_mode else (3, 3), np.uint8)
    dilated = cv2.dilate(blurred, kernel, iterations=2 if night_mode else 1)
    eroded = cv2.erode(dilated, kernel, iterations=1)
    results = decode(eroded)
    
    return results, eroded if night_mode else blurred

def find_student_by_id(student_id):
    """Recherche optimisée d'un étudiant par son ID"""
    try:
        cellule = sheet.find(student_id)
        return cellule
    except Exception as e:
        st.error(f"Erreur lors de la recherche de l'adhérent : {e}")
        log_activity(st.session_state.username, "Recherche adhérent",
                     f"ID: {student_id}, Erreur: {str(e)}", "Échec")
        return None

def update_course_for_student(student_row, course_name, courses):
    """Met à jour le statut de récupération d'un poly pour un étudiant"""
    if course_name in courses:
        colonne = courses.index(course_name) + 1
        try:
            current_value = sheet.cell(student_row, colonne).value
            
            if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                st.error("❌ Cet étudiant a déjà récupéré ce poly.")
                log_activity(st.session_state.username, "Enregistrement poly",
                             f"ID: {st.session_state.numero_adherent}, Cours: {course_name}, Déjà récupéré",
                             "Échec")
                return False
            else:
                sheet.update_cell(student_row, colonne, 1)
                st.success("✅ Mise à jour réussie dans Google Sheets !")
                log_activity(st.session_state.username, "Enregistrement poly",
                             f"ID: {st.session_state.numero_adherent}, Cours: {course_name}",
                             "Succès")
                return True
        except Exception as e:
            st.error(f"❌ Erreur lors de la mise à jour : {e}")
            log_activity(st.session_state.username, "Enregistrement poly",
                         f"ID: {st.session_state.numero_adherent}, Cours: {course_name}, Erreur: {str(e)}",
                         "Échec")
            return False
    else:
        st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
        log_activity(st.session_state.username, "Enregistrement poly",
                     f"ID: {st.session_state.numero_adherent}, Cours: {course_name} inexistant",
                     "Échec")
        return False

# Initialisation des variables de session
if "authentifie" not in st.session_state:
    st.session_state.authentifie = False
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.numero_adherent = None
    st.session_state.debug_mode = False

# Écran de connexion
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
            # Liste fixe des administrateurs pour plus d'efficacité
            st.session_state.is_admin = utilisateur in ["SirIsaac21", "vp_star", "sophie"]
            log_activity(utilisateur, "Connexion", "Connexion réussie", "Succès")
            st.success("✅ Connexion réussie !")
            st.rerun()
        else:
            log_activity(utilisateur, "Tentative de connexion", "Identifiants incorrects", "Échec")
            st.error("❌ Identifiants incorrects. Veuillez réessayer.")

    st.stop()

# Interface utilisateur régulier
if st.session_state.username not in ["SirIsaac21", "vp_star", "sophie"]:
    st.header(f"Coucou {st.session_state.username} !")
    
    st.subheader("1. Scanner un code-barres")
    night_mode = st.checkbox("Mode faible luminosité", 
                           help="Activez cette option si vous êtes dans un environnement peu éclairé")
    
    scan_tab, upload_tab = st.tabs(["Utiliser la caméra", "Importer une image"])
    
    with scan_tab:
        st.write("Préparez-vous, j'ai pas trouvé comment mettre la caméra arrière par défaut")
        img_file_buffer = st.camera_input("Prendre la photo")
        image_source = img_file_buffer
    
    with upload_tab:
        uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                       type=['jpg', 'jpeg', 'png', 'bmp'])
        image_source = uploaded_file
    
    # Traitement de l'image et scan du code-barres
    if image_source is not None:
        file_bytes = np.asarray(bytearray(image_source.read()), dtype=np.uint8)
        image = cv2.imdecode(file_bytes, 1)
        decoded_objs, processed_img = scan_barcode(image, night_mode)
    
        if decoded_objs:
            st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
            st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
            log_activity(st.session_state.username, "Scan de code-barres",
                       f"ID: {st.session_state.numero_adherent}", "Succès")
    
            if st.checkbox("Afficher l'image traitée"):
                st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
        else:
            st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
            st.info("Conseil: Assurez-vous que le code-barres est bien éclairé et centré dans l'image.")
            log_activity(st.session_state.username, "Scan de code-barres", "Échec de détection", "Échec")
    
            st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)
    
            if not night_mode:
                st.warning("💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")
    
    st.write("-" * 100)
    
    # Section de sélection du cours
    st.subheader("2. Sélectionner un cours")
    
    try:
        # Utilisation de la fonction mise en cache
        liste_cours = get_courses()
        if not liste_cours:
            st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
            log_activity(st.session_state.username, "Chargement des cours", "Aucun cours trouvé", "Échec")
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des cours : {e}")
        log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
        liste_cours = []
    
    cours_selectionne = st.selectbox("Choisissez un cours :", liste_cours)
    
    if st.button("Enregistrer la récupération du cours"):
        if st.session_state.numero_adherent is None:
            st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
            log_activity(st.session_state.username, "Enregistrement poly",
                       f"Cours: {cours_selectionne} - Aucun numéro d'adhérent", "Échec")
        else:
            cellule = find_student_by_id(st.session_state.numero_adherent)
            if cellule:
                ligne = cellule.row
                update_course_for_student(ligne, cours_selectionne, liste_cours)
            else:
                st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                log_activity(st.session_state.username, "Enregistrement poly",
                           f"ID: {st.session_state.numero_adherent} non trouvé", "Échec")

# Interface administrateur
else:
    tab1, tab2 = st.tabs(["🤓 Interface des tuteurs", "👑 Admin"])
    
    # Onglet interface des tuteurs (même interface que pour les utilisateurs réguliers)
    with tab1:
        st.subheader("1. Scanner un code-barres")
        night_mode = st.checkbox("Mode faible luminosité", 
                               help="Activez cette option si vous êtes dans un environnement peu éclairé")
        
        scan_tab, upload_tab = st.tabs(["Utiliser la caméra", "Importer une image"])
        
        with scan_tab:
            img_file_buffer = st.camera_input("Take a picture")
            image_source = img_file_buffer
        
        with upload_tab:
            uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                           type=['jpg', 'jpeg', 'png', 'bmp'])
            image_source = uploaded_file
        
        # Traitement de l'image et scan du code-barres
        if image_source is not None:
            file_bytes = np.asarray(bytearray(image_source.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            decoded_objs, processed_img = scan_barcode(image, night_mode)
        
            if decoded_objs:
                st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
                st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
                log_activity(st.session_state.username, "Scan de code-barres",
                           f"ID: {st.session_state.numero_adherent}", "Succès")
        
                if st.checkbox("Afficher l'image traitée"):
                    st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
            else:
                st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                st.info("Conseil: Assurez-vous que le code-barres est bien éclairé et centré dans l'image.")
                log_activity(st.session_state.username, "Scan de code-barres", "Échec de détection", "Échec")
        
                st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)
        
                if not night_mode:
                    st.warning("💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")
        
        st.write("-" * 100)
        
        st.subheader("2. Sélectionner un cours")
        
        try:
            liste_cours = get_courses()
            if not liste_cours:
                st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
                log_activity(st.session_state.username, "Chargement des cours", "Aucun cours trouvé", "Échec")
        except Exception as e:
            st.error(f"❌ Erreur lors de la récupération des cours : {e}")
            log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
            liste_cours = []
        
        cours_selectionne = st.selectbox("Choisissez un cours :", liste_cours)
        
        if st.button("Enregistrer la récupération du cours", key="admin_save_course"):
            if st.session_state.numero_adherent is None:
                st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
                log_activity(st.session_state.username, "Enregistrement poly",
                           f"Cours: {cours_selectionne} - Aucun numéro d'adhérent", "Échec")
            else:
                cellule = find_student_by_id(st.session_state.numero_adherent)
                if cellule:
                    ligne = cellule.row
                    update_course_for_student(ligne, cours_selectionne, liste_cours)
                else:
                    st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                    log_activity(st.session_state.username, "Enregistrement poly",
                               f"ID: {st.session_state.numero_adherent} non trouvé", "Échec")
        
    # Onglet administrateur
    with tab2:
        if not st.session_state.is_admin:
            st.error("⛔️ Accès non autorisé. Vous n'avez pas les droits d'administration.")
            st.info("Si tu n'es ni VP ni Sophie tu n'as pas accès à cette section.")
        else:
            st.success("👑 Bravo, t'es admin ! Sophie t'a adoubé ?")
            
            # Option de débogage pour les administrateurs
            st.session_state.debug_mode = st.checkbox("Mode débogage (afficher les temps d'exécution)")
            
            # Boutons d'exportation de données
            backup_cols = st.columns(2)
            with backup_cols[0]:
                if st.button("Télécharger toutes les données (CSV)"):
                    try:
                        # Utilisation de la fonction mise en cache
                        all_data = get_sheet_data()
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
        
            # Onglets d'administration
            admin_tabs = st.tabs(["Tableau de bord", "Journaux d'activité", "Gestion des utilisateurs",
                                  "Gestion des cours", "Recherche d'étudiants"])
        
            # 1. DASHBOARD TAB
            with admin_tabs[0]:
                st.header("Tableau de bord")
                try:
                    # Utiliser la version mise en cache pour optimiser les performances
                    all_data = get_sheet_data()
                    total_students = len(all_data)
                    
                    # Compter les polys distribués de manière optimisée
                    total_polys = sum(
                        sum(1 for col, val in row.items() if val == 1)
                        for row in all_data
                    )
                    
                    nbLAS, nbPOLY, tauxREUSSITE = st.columns(3)
        
                    with nbLAS:
                        st.metric("Total de LAS inscrits", total_students)
                    with nbPOLY:
                        st.metric("Total de polys distribués", total_polys)
                    with tauxREUSSITE:
                        all_logs = log_sheet.get_all_records()
        
                        # Comptage optimisé des taux de réussite/échec
                        success_count = sum(1 for log in all_logs if log['Statut'] == 'Succès')
                        total_actions = len(all_logs)
        
                        if total_actions > 0:
                            success_rate = (success_count / total_actions) * 100
                            st.metric("Taux de réussite", f"{success_rate:.1f}%")
                    
                    # Analyse des polys par cours - optimisé
                    course_counts = {}
                    first_field = sheet.cell(1, 1).value
                    
                    for row in all_data:
                        for course, val in row.items():
                            if val == 1 and course != first_field:
                                course_counts[course] = course_counts.get(course, 0) + 1
                    
                    # Analyse des activités par date - optimisé
                    all_logs = log_sheet.get_all_records()
                    activity_counts = {}
                    for log in all_logs:
                        date = log['Date']
                        activity_counts[date] = activity_counts.get(date, 0) + 1
        
                    chart_data = pd.DataFrame({
                        'Date': list(activity_counts.keys()),
                        'Activités': list(activity_counts.values())
                    })
        
                    st.subheader("Activité par jour")
                    st.bar_chart(chart_data.set_index('Date'))
                    
        
                except Exception as e:
                    st.error(f"Erreur d'affichage des statistiques: {e}")
                
                st.subheader("Activité récente")
                try:
                    # Récupérer et trier les logs de manière optimisée
                    all_logs = log_sheet.get_all_records()
                    recent_logs = sorted(
                        all_logs, 
                        key=lambda x: (
                            # Convertir la date au format datetime pour tri chronologique
                            datetime.datetime.strptime(x['Date'], "%d/%m/%Y").timestamp(),
                            x['Heure']
                        ), 
                        reverse=True
                    )[:10]  # Limiter aux 10 entrées les plus récentes
                    
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
        
                        # Extraction efficace des listes uniques
                        with col1:
                            usernames = sorted(set(log['Utilisateur'] for log in all_logs))
                            selected_user = st.selectbox("Filtrer par utilisateur:", ["Tous les utilisateurs"] + usernames)
        
                        with col2:
                            actions = sorted(set(log['Action'] for log in all_logs))
                            selected_action = st.selectbox("Filtrer par type d'action:", ["Toutes les actions"] + actions)
        
                        # Sélection de dates efficace
                        start_date, end_date = st.columns(2)
                        
                        # Calcul des dates min et max une seule fois
                        date_objects = [datetime.datetime.strptime(log['Date'], "%d/%m/%Y").date() for log in all_logs]
                        min_date = min(date_objects)
                        max_date = max(date_objects)
                        
                        with start_date:
                            date_debut = st.date_input("Date de début:", min_date)
        
                        with end_date:
                            date_fin = st.date_input("Date de fin:", max_date)
        
                        # Filtrage optimisé des logs
                        filtered_logs = []
                        
                        for log in all_logs:
                            # Appliquer les filtres
                            if selected_user != "Tous les utilisateurs" and log['Utilisateur'] != selected_user:
                                continue
                                
                            if selected_action != "Toutes les actions" and log['Action'] != selected_action:
                                continue
                                
                            log_date = datetime.datetime.strptime(log['Date'], "%d/%m/%Y").date()
                            if log_date < date_debut or log_date > date_fin:
                                continue
                                
                            filtered_logs.append(log)
        
                        if not filtered_logs:
                            st.warning("Aucune activité correspondant aux critères sélectionnés.")
                        else:
                            # Fonction pour colorer le statut
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
        
                # Affichage des utilisateurs optimisé
                st.subheader("Utilisateurs actuels")
                try:
                    # Récupération efficace des utilisateurs depuis les secrets
                    users = {user: {"password": pwd, "admin": user in ["SirIsaac21", "vp_star", "sophie"]}
                             for user, pwd in st.secrets["credentials"].items()}
        
                    # Création efficace du DataFrame
                    user_df = pd.DataFrame([
                        {"Utilisateur": user, "Statut": "Administrateur" if details["admin"] else "Utilisateur"}
                        for user, details in users.items()
                    ])
        
                    st.dataframe(user_df, use_container_width=True)
        
                    # Gestion utilisateur simplifiée
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
        
            # 4. COURSE MANAGEMENT TAB
            with admin_tabs[3]:
                st.header("Gestion des cours")
        
                try:
                    # Récupération efficace des cours
                    courses = get_courses()[1:]  # Exclure le premier élément (ID)
                    
                    # Calcul optimisé des statistiques par cours
                    @st.cache_data(ttl=60)  # Cache de 1 minute pour cette fonction
                    def get_course_stats():
                        course_data = []
                        for i, course in enumerate(courses):
                            # Utiliser un comptage optimisé avec list comprehension
                            count = len([1 for cell in sheet.col_values(i + 2)[1:] if cell == '1'])
                            course_data.append({"Cours": course, "Polys distribués": count})
                        return course_data
                    
                    course_data = get_course_stats()
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
                                    # Vider le cache pour forcer la mise à jour des données
                                    st.cache_data.clear()
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
                    # Utilisation de la fonction mise en cache
                    all_students = get_sheet_data()
                    id_field = sheet.cell(1, 1).value
        
                    # Interface de recherche optimisée
                    search_term = st.text_input("Rechercher un étudiant par numéro CREM")
        
                    if search_term:
                        # Recherche optimisée avec une seule boucle
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
                                courses = get_courses()[1:]  # Exclure le premier élément (ID)
        
                                st.write("Cochez les polys récupérés:")
                                # Affichage optimisé des cases à cocher avec colonnes
                                cols = st.columns(3)
                                updated_values = {}
        
                                for i, course in enumerate(courses):
                                    col_index = i % 3
                                    current_val = sheet.cell(student_row, i + 2).value
                                    with cols[col_index]:
                                        has_poly = st.checkbox(
                                            course,
                                            value=True if current_val == '1' else False,
                                            key=f"course_{course}_{student_id}"  # Clé unique pour éviter les conflits
                                        )
                                        updated_values[i + 2] = '1' if has_poly else ''
        
                                if st.button("Mettre à jour", key="update_student_courses"):
                                    # Mise à jour par lots pour réduire les appels API
                                    cells_to_update = []
                                    for col, val in updated_values.items():
                                        cells_to_update.append({
                                            'row': student_row,
                                            'col': col,
                                            'value': val
                                        })
                                    
                                    # Utiliser update_cells au lieu de multiples update_cell
                                    if cells_to_update:
                                        batch_size = 10  # Taille de lot raisonnable
                                        for i in range(0, len(cells_to_update), batch_size):
                                            batch = cells_to_update[i:i+batch_size]
                                            cell_list = []
                                            for cell_data in batch:
                                                cell = sheet.cell(cell_data['row'], cell_data['col'])
                                                cell.value = cell_data['value']
                                                cell_list.append(cell)
                                            sheet.update_cells(cell_list)
                                            
                                    log_activity(st.session_state.username, "Modification étudiant",
                                                 f"ID: {student_id}", "Succès")
                                    st.success("✅ Informations mises à jour!")
                        else:
                            st.warning("Aucun étudiant trouvé.")
        
                    # Formulaire d'ajout d'étudiant optimisé
                    with st.expander("Ajouter un nouvel étudiant"):
                        new_student_id = st.text_input("Numéro d'adhérent", key="new_student_id_input")
        
                        if st.button("Ajouter", key="add_new_student"):
                            if new_student_id:
                                try:
                                    # Vérification optimisée de l'existence de l'étudiant
                                    existing = None
                                    try:
                                        existing = sheet.find(new_student_id)
                                    except:
                                        pass
        
                                    if existing:
                                        st.error(f"Un étudiant avec l'ID '{new_student_id}' existe déjà!")
                                    else:
                                        # Ajouter l'étudiant avec des cellules vides pour tous les cours
                                        sheet.append_row([new_student_id] + [''] * (len(get_courses()) - 1))
                                        # Vider le cache pour refléter les changements
                                        st.cache_data.clear()
                                        log_activity(st.session_state.username, "Ajout étudiant",
                                                     f"ID: {new_student_id}", "Succès")
                                        st.success(f"✅ Étudiant '{new_student_id}' ajouté avec succès!")
                                except Exception as e:
                                    st.error(f"❌ Erreur: {e}")
                            else:
                                st.error("Veuillez saisir un numéro d'adhérent")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la recherche d'étudiants: {e}")

# Pied de page et déconnexion
st.write("-" * 100)
user, propos = st.columns(2)

with user:
    if st.button("Se déconnecter"):
        log_activity(st.session_state.username, "Déconnexion", "", "Succès")
        # Réinitialisation des variables de session et vidage du cache
        st.session_state.authentifie = False
        st.session_state.username = None
        st.session_state.is_admin = False
        st.session_state.numero_adherent = None
        st.cache_data.clear()
        st.rerun()

with propos:
    with st.expander("À propos"):
        st.write("### CREM - Gestion des polys Tutorat")
        st.write("Version: 2.0.0")
        st.write("Contact: web@crem.fr")
        st.write("<3")

# Nettoyage des ressources non utilisées
import gc
gc.collect()
