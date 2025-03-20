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
import base64
from io import BytesIO
from PIL import Image, ImageDraw
import threading
import re
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase, RTCConfiguration
import queue
import av

# Configuration de la page Streamlit
st.set_page_config(
    page_title="CREM - Gestion des polys Tutorat",
    page_icon="logo.png",
    layout="wide"  # Utilisation maximale de l'espace disponible
)

# ---------- FONCTIONS DE CACHE ET UTILITAIRES ---------- #

# Cache pour les appels à Google Sheets
@st.cache_data(ttl=300)  # Mise en cache pendant 5 minutes
def get_sheet_data():
    """Récupère les données de Google Sheets avec mise en cache"""
    return sheet.get_all_records()

@st.cache_data(ttl=300)
def get_courses():
    """Récupère la liste des cours avec mise en cache"""
    return sheet.row_values(1)

# Fonction pour mesurer le temps d'exécution
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

# ---------- FONCTIONS DE TRAITEMENT D'IMAGE ET SCAN ---------- #

# Classe pour la détection continue de code-barres
class VideoTransformer(VideoTransformerBase):
    def __init__(self, result_queue):
        self.result_queue = result_queue
        self.last_detection_time = 0
        self.detection_cooldown = 2.0  # Secondes entre chaque détection
        self.frame_counter = 0
        self.process_every_n_frames = 3  # Traiter une image sur trois pour économiser des ressources

    def draw_barcode_guides(self, frame):
        """Ajoute des guides visuels pour aider au positionnement du code-barres"""
        height, width = frame.shape[:2]
        
        # Dessiner des lignes de guide centrales
        center_x, center_y = width // 2, height // 2
        guide_width, guide_height = width // 2, height // 3
        
        # Créer un rectangle de guidage
        cv2.rectangle(
            frame,
            (center_x - guide_width // 2, center_y - guide_height // 2),
            (center_x + guide_width // 2, center_y + guide_height // 2),
            (0, 255, 0), 2
        )
        
        # Ajouter un texte d'instruction
        cv2.putText(
            frame,
            "Centrez le code-barres ici",
            (center_x - 120, center_y - guide_height // 2 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
        )
        
        return frame

    def transform(self, frame):
        self.frame_counter += 1
        current_time = time.time()
        img = frame.to_ndarray(format="bgr24")
        
        # Dessiner les guides sur chaque frame
        img_with_guides = self.draw_barcode_guides(img.copy())
        
        # Ne traiter qu'une image sur n pour les performances
        if self.frame_counter % self.process_every_n_frames == 0:
            # Si assez de temps s'est écoulé depuis la dernière détection
            if current_time - self.last_detection_time > self.detection_cooldown:
                # Convertir en niveaux de gris et appliquer un flou
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                
                # Détecter les codes-barres
                barcodes = decode(blurred)
                
                if barcodes:
                    for barcode in barcodes:
                        # Extraire et dessiner un rectangle autour du code-barres
                        barcode_data = barcode.data.decode("utf-8")
                        barcode_type = barcode.type
                        
                        (x, y, w, h) = barcode.rect
                        cv2.rectangle(img_with_guides, (x, y), (x + w, y + h), (0, 0, 255), 4)
                        
                        # Ajouter un texte avec la valeur du code-barres
                        text = f"{barcode_data} ({barcode_type})"
                        cv2.putText(img_with_guides, text, (x, y - 10), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                        
                        # Envoyer le résultat dans la queue
                        if not self.result_queue.full():
                            self.result_queue.put(barcode_data)
                            self.last_detection_time = current_time
        
        return av.VideoFrame.from_ndarray(img_with_guides, format="bgr24")

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

# ---------- FONCTIONS D'INTERACTION AVEC LA BASE DE DONNÉES ---------- #

def log_activity(username, action, details, status):
    """Journalise les activités avec gestion d'erreur améliorée"""
    global client, sheet, log_sheet
    
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

def find_student_by_name(name_query):
    """Recherche un étudiant par son nom/prénom"""
    try:
        # Récupérer toutes les données
        all_data = get_sheet_data()
        
        # Rechercher dans toutes les colonnes qui pourraient contenir un nom/prénom
        results = []
        name_query = name_query.lower()
        
        for row in all_data:
            # Chercher dans chaque colonne qui pourrait contenir un nom
            # Adapter ceci en fonction de la structure réelle des données
            for key, value in row.items():
                if isinstance(value, str) and name_query in value.lower():
                    results.append(row)
                    break
        
        return results
    except Exception as e:
        st.error(f"Erreur lors de la recherche par nom : {e}")
        log_activity(st.session_state.username, "Recherche par nom",
                     f"Nom: {name_query}, Erreur: {str(e)}", "Échec")
        return []

def get_most_distributed_course():
    """Détermine le cours le plus fréquemment distribué"""
    try:
        all_data = get_sheet_data()
        first_field = sheet.cell(1, 1).value  # Champ ID
        courses = get_courses()[1:]  # Exclure le premier champ (ID)
        
        course_counts = {course: 0 for course in courses}
        
        for row in all_data:
            for course in courses:
                if row.get(course) == 1:
                    course_counts[course] += 1
        
        # Trouver le cours avec le plus de distributions
        if course_counts:
            most_distributed = max(course_counts.items(), key=lambda x: x[1])
            return most_distributed[0]
        
        # Si aucun cours n'a été distribué, retourner le premier
        return courses[0] if courses else None
        
    except Exception as e:
        if st.session_state.get('debug_mode', False):
            st.error(f"Erreur lors de la détermination du cours le plus distribué : {e}")
        # En cas d'erreur, retourner None
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

# ---------- FONCTIONS D'INTERFACE UTILISATEUR ---------- #

def create_success_sound():
    """Génère un son de succès en base64 pour jouer après un scan réussi"""
    # Cette fonction simule un son de confirmation simple
    # Dans une version réelle, vous pourriez inclure un vrai fichier audio
    
    # Ici nous renvoyons simplement un placeholder
    audio_base64 = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="
    return audio_base64

def play_success_sound():
    """Joue un son de succès"""
    success_sound = create_success_sound()
    st.markdown(
        f"""
        <audio autoplay="true">
            <source src="{success_sound}" type="audio/wav">
        </audio>
        """,
        unsafe_allow_html=True
    )

def display_confirmation_animation():
    """Affiche une animation visuelle de confirmation"""
    st.balloons()

def add_barcode_guide_overlay(image):
    """Ajoute un guide visuel pour le placement du code-barres"""
    # Convertir l'image CV2 en PIL pour faciliter le dessin
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    
    width, height = pil_img.size
    center_x, center_y = width // 2, height // 2
    
    # Calculer la taille du rectangle de guidage
    guide_width = width // 2
    guide_height = height // 3
    
    # Dessiner un rectangle en pointillés
    left = center_x - guide_width // 2
    top = center_y - guide_height // 2
    right = center_x + guide_width // 2
    bottom = center_y + guide_height // 2
    
    # Dessiner les lignes en pointillés
    dash_length = 10
    for i in range(left, right, dash_length * 2):
        draw.line([(i, top), (min(i + dash_length, right), top)], fill=(0, 255, 0), width=2)
        draw.line([(i, bottom), (min(i + dash_length, right), bottom)], fill=(0, 255, 0), width=2)
    
    for i in range(top, bottom, dash_length * 2):
        draw.line([(left, i), (left, min(i + dash_length, bottom))], fill=(0, 255, 0), width=2)
        draw.line([(right, i), (right, min(i + dash_length, bottom))], fill=(0, 255, 0), width=2)
    
    # Ajouter un texte d'instruction
    draw.text((center_x - 100, top - 30), "Centrez le code-barres ici", fill=(0, 255, 0))
    
    # Reconvertir en format CV2
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

# Initialisation des variables de session
if "authentifie" not in st.session_state:
    st.session_state.authentifie = False
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.numero_adherent = None
    st.session_state.debug_mode = False
    st.session_state.continuous_scan_active = False
    st.session_state.barcode_result_queue = queue.Queue(maxsize=5)

# ---------- APPLICATION PRINCIPALE ---------- #

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

# Interface utilisateur après connexion
st.sidebar.title(f"Bonjour {st.session_state.username} 👋")

# Options de navigation dans la sidebar
page = st.sidebar.radio(
    "Navigation", 
    [
        "📱 Scanner Rapide", 
        "📚 Distribution Standard", 
        "🔍 Recherche Étudiant",
        "⚙️ Paramètres"
    ]
)

# Récupération des cours pour utilisation dans différentes pages
try:
    liste_cours = get_courses()
    most_frequent_course = get_most_distributed_course()
except Exception as e:
    st.error(f"❌ Erreur lors de la récupération des cours : {e}")
    liste_cours = []
    most_frequent_course = None

# ========== PAGE SCANNER RAPIDE ==========
if page == "📱 Scanner Rapide":
    st.title("Scanner Rapide")
    st.write("Scannez et enregistrez un poly en un seul clic")
    
    # Sélection du cours à distribuer avec présélection du plus fréquent
    default_course_index = liste_cours.index(most_frequent_course) if most_frequent_course in liste_cours else 0
    selected_course = st.selectbox(
        "Sélectionnez le cours à distribuer:",
        liste_cours,
        index=default_course_index
    )
    
    scan_tabs = st.tabs(["Scanner continu", "Photo unique", "Importer une image"])
    
    # Onglet de scan continu
    with scan_tabs[0]:
        st.write("📷 Placez le code-barres de la carte devant la caméra")
        
        # Configuration WebRTC pour le scan continu
        rtc_config = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})
        
        # Initialize a queue for barcode results
        if "barcode_result_queue" not in st.session_state:
            st.session_state.barcode_result_queue = queue.Queue(maxsize=5)
        
        # Create the webRTC streamer
        webrtc_ctx = webrtc_streamer(
            key="barcode-scanner",
            video_transformer_factory=lambda: VideoTransformer(st.session_state.barcode_result_queue),
            rtc_configuration=rtc_config,
            media_stream_constraints={"video": True, "audio": False},
            async_processing=True,
        )
        
        # UI for scan status
        scan_status = st.empty()
        scan_status.info("En attente de détection...")
        
        # Processing the barcode results
        if webrtc_ctx.state.playing:
            while True:
                try:
                    # Non-blocking queue get
                    barcode_value = st.session_state.barcode_result_queue.get(block=False)
                    
                    # Update the UI with the detected barcode
                    scan_status.success(f"✅ Code-barres détecté: {barcode_value}")
                    st.session_state.numero_adherent = barcode_value
                    
                    # Vibration/son de succès
                    play_success_sound()
                    
                    # Confirmation visuelle
                    display_confirmation_animation()
                    
                    # Tenter d'enregistrer automatiquement
                    cellule = find_student_by_id(barcode_value)
                    if cellule:
                        if update_course_for_student(cellule.row, selected_course, liste_cours):
                            st.success(f"✅ Enregistrement du poly '{selected_course}' pour l'étudiant #{barcode_value}")
                        break
                    else:
                        st.error(f"❌ Étudiant avec ID {barcode_value} non trouvé dans la base")
                        break
                        
                except queue.Empty:
                    # No barcode detected yet, continue
                    break
                except Exception as e:
                    st.error(f"Erreur: {e}")
                    break
    
    # Onglet photo unique
    with scan_tabs[1]:
        st.write("📸 Prenez une photo du code-barres")
        img_file_buffer = st.camera_input("Prendre la photo")
        
        if img_file_buffer:
            # Traitement de l'image
            file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            
            # Ajouter le guide visuel
            image_with_guide = add_barcode_guide_overlay(image)
            
            # Scan du code-barres
            night_mode = st.checkbox("Mode faible luminosité", value=False)
            decoded_objs, processed_img = scan_barcode(image, night_mode)
            
            if decoded_objs:
                barcode_value = decoded_objs[0].data.decode("utf-8")
                st.session_state.numero_adherent = barcode_value
                
                # Message de succès
                st.success(f"✅ Code-barres détecté: {barcode_value}")
                
                # Vibration/son de succès
                play_success_sound()
                
                # Confirmation visuelle
                display_confirmation_animation()
                
                # Formulaire rapide pour confirmer l'enregistrement
                with st.form("quick_form"):
                    st.subheader(f"Enregistrer le poly '{selected_course}' pour l'étudiant #{barcode_value}?")
                    submit_button = st.form_submit_button("Confirmer")
                    
                    if submit_button:
                        cellule = find_student_by_id(barcode_value)
                        if cellule:
                            update_course_for_student(cellule.row, selected_course, liste_cours)
                        else:
                            st.error(f"❌ Étudiant avec ID {barcode_value} non trouvé dans la base")
            else:
                st.error("❌ Aucun code-barres détecté. Veuillez réessayer.")
                st.image(processed_img, caption="Image traitée", width=300)
    
    # Onglet import d'image
    with scan_tabs[2]:
        st.write("📁 Importez une image contenant un code-barres")
        uploaded_file = st.file_uploader("Choisir une image", type=['jpg', 'jpeg', 'png', 'bmp'])
        
        if uploaded_file:
            # Même traitement que pour la photo
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            night_mode = st.checkbox("Mode faible luminosité", key="upload_night_mode", value=False)
            decoded_objs, processed_img = scan_barcode(image, night_mode)
            
            if decoded_objs:
                barcode_value = decoded_objs[0].data.decode("utf-8")
                st.session_state.numero_adherent = barcode_value
                
                # Message de succès
                st.success(f"✅ Code-barres détecté: {barcode_value}")
                
                # Vibration/son de succès
                play_success_sound()
                
                # Formulaire rapide pour confirmer l'enregistrement
                with st.form("upload_quick_form"):
                    st.subheader(f"Enregistrer le poly '{selected_course}' pour l'étudiant #{barcode_value}?")
                    submit_button = st.form_submit_button("Confirmer")
                    
                    if submit_button:
                        cellule = find_student_by_id(barcode_value)
                        if cellule:
                            update_course_for_student(cellule.row, selected_course, liste_cours)
                        else:
                            st.error(f"❌ Étudiant avec ID {barcode_value} non trouvé dans la base")
            else:
                st.error("❌ Aucun code-barres détecté. Veuillez réessayer.")
                st.image(processed_img, caption="Image traitée", width=300)

# ========== PAGE DISTRIBUTION STANDARD ==========
elif page == "📚 Distribution Standard":
    st.title("Distribution de Polys - Mode Standard")
    
    st.subheader("1. Scanner un code-barres")
    night_mode = st.checkbox("Mode faible luminosité", 
                           help="Activez cette option si vous êtes dans un environnement peu éclairé")
    
    scan_tab, upload_tab = st.tabs(["Utiliser la caméra", "Importer une image"])
    
    with scan_tab:
        st.write("Préparez-vous, j'ai pas trouvé comment mettre la caméra arrière par défaut")
        img_file_buffer = st.camera_input("Prendre la photo")
        
        # Ajouter un guide visuel par-dessus l'aperçu de la caméra
        if img_file_buffer:
            file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            
            # Scan du code-barres
            decoded_objs, processed_img = scan_barcode(image, night_mode)
            
            if decoded_objs:
                st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
                st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
                log_activity(st.session_state.username, "Scan de code-barres",
                         f"ID: {st.session_state.numero_adherent}", "Succès")
                
                # Vibration/son de succès
                play_success_sound()
                
                # Confirmation visuelle
                display_confirmation_animation()
            
                if st.checkbox("Afficher l'image traitée"):
                    st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
            else:
                st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                st.info("Conseil: Assurez-vous que le code-barres est bien éclairé et centré dans l'image.")
                log_activity(st.session_state.username, "Scan de code-barres", "Échec de détection", "Échec")
            
                # Afficher l'image traitée avec les guides
                guide_img = add_barcode_guide_overlay(image)
                st.image(guide_img, caption="Positionnez le code-barres dans le cadre vert", channels="RGB", width=400)
            
                if not night_mode:
                    st.warning("💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")
    
    with upload_tab:
        uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                     type=['jpg', 'jpeg', 'png', 'bmp'])
        
        if uploaded_file:
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
            image = cv2.imdecode(file_bytes, 1)
            
            # Scan du code-barres
            decoded_objs, processed_img = scan_barcode(image, night_mode)
            
            if decoded_objs:
                st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
                st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
                log_activity(st.session_state.username, "Scan de code-barres",
                         f"ID: {st.session_state.numero_adherent}", "Succès")
                
                # Vibration/son de succès
                play_success_sound()
            
                if st.checkbox("Afficher l'image traitée", key="show_processed_upload"):
                    st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
            else:
                st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                st.info("Conseil: Assurez-vous que le code-barres est bien visible dans l'image.")
                log_activity(st.session_state.username, "Scan de code-barres", "Échec de détection", "Échec")
                st.image(processed_img, caption="Image traitée", channels="GRAY", width=300)
    
    st.write("-" * 100)
    
    # Section de sélection du cours
    st.subheader("2. Sélectionner un cours")
    
    try:
        # Préselection du cours le plus fréquemment distribué
        default_course_index = liste_cours.index(most_frequent_course) if most_frequent_course in liste_cours else 0
        cours_selectionne = st.selectbox(
            "Choisissez un cours :",
            liste_cours,
            index=default_course_index,
            help="Le cours le plus fréquemment distribué est présélectionné"
        )
        
        # Indicateur visuel pour identifier le cours présélectionné
        if most_frequent_course == cours_selectionne:
            st.info(f"ℹ️ '{cours_selectionne}' est le cours le plus fréquemment distribué")
    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des cours : {e}")
        log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
        cours_selectionne = ""
    
    if st.button("Enregistrer la récupération du cours"):
        if st.session_state.numero_adherent is None:
            st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
            log_activity(st.session_state.username, "Enregistrement poly",
                       f"Cours: {cours_selectionne} - Aucun numéro d'adhérent", "Échec")
        else:
            cellule = find_student_by_id(st.session_state.numero_adherent)
            if cellule:
                ligne = cellule.row
                success = update_course_for_student(ligne, cours_selectionne, liste_cours)
                if success:
                    # Afficher une confirmation visuelle et sonore
                    display_confirmation_animation()
                    play_success_sound()
            else:
                st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
                log_activity(st.session_state.username, "Enregistrement poly",
                           f"ID: {st.session_state.numero_adherent} non trouvé", "Échec")

# ========== PAGE RECHERCHE ETUDIANT ==========
elif page == "🔍 Recherche Étudiant":
    st.title("Recherche d'Étudiants")
    
    search_tabs = st.tabs(["Recherche par Numéro", "Recherche par Nom/Prénom"])
    
    with search_tabs[0]:
        st.subheader("Recherche par numéro d'adhérent")
        id_search = st.text_input("Entrez le numéro d'adhérent")
        
        if id_search:
            cellule = find_student_by_id(id_search)
            if cellule:
                st.success(f"✅ Étudiant trouvé à la ligne {cellule.row}")
                
                # Récupérer les données de l'étudiant
                student_row = cellule.row
                student_data = sheet.row_values(student_row)
                headers = sheet.row_values(1)
                
                # Créer un dictionnaire des données de l'étudiant
                student_dict = {headers[i]: student_data[i] for i in range(len(headers)) if i < len(student_data)}
                
                # Afficher les informations de l'étudiant
                st.write("### Informations de l'étudiant")
                st.write(f"**Numéro d'adhérent:** {student_dict.get(headers[0], 'Non disponible')}")
                
                # Afficher les polys récupérés
                st.write("### Polys récupérés")
                cours_col1, cours_col2, cours_col3 = st.columns(3)
                cours_columns = [cours_col1, cours_col2, cours_col3]
                
                i = 0
                for header, value in student_dict.items():
                    if header != headers[0]:  # Ignorer la colonne d'ID
                        col = cours_columns[i % 3]
                        with col:
                            if value == '1':
                                st.write(f"✅ {header}")
                            else:
                                st.write(f"❌ {header}")
                        i += 1
                
                # Option pour modifier les polys
                with st.expander("Modifier les polys récupérés"):
                    st.write("Cochez les polys que l'étudiant a récupérés")
                    
                    edit_col1, edit_col2, edit_col3 = st.columns(3)
                    edit_columns = [edit_col1, edit_col2, edit_col3]
                    
                    updated_values = {}
                    i = 0
                    for header, value in student_dict.items():
                        if header != headers[0]:  # Ignorer la colonne d'ID
                            col = edit_columns[i % 3]
                            with col:
                                has_poly = st.checkbox(
                                    header,
                                    value=True if value == '1' else False,
                                    key=f"edit_{header}_{id_search}"
                                )
                                column_index = headers.index(header)
                                updated_values[column_index + 1] = '1' if has_poly else ''
                            i += 1
                    
                    if st.button("Enregistrer les modifications"):
                        # Mise à jour par lots
                        cell_list = []
                        for col, val in updated_values.items():
                            cell = sheet.cell(student_row, col)
                            cell.value = val
                            cell_list.append(cell)
                        
                        try:
                            sheet.update_cells(cell_list)
                            st.success("✅ Informations mises à jour avec succès!")
                            log_activity(st.session_state.username, "Modification polys",
                                       f"ID: {id_search}", "Succès")
                            # Vider le cache pour refléter les changements
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"❌ Erreur lors de la mise à jour : {e}")
                            log_activity(st.session_state.username, "Modification polys",
                                       f"ID: {id_search}, Erreur: {str(e)}", "Échec")
            else:
                st.error("❌ Aucun étudiant trouvé avec ce numéro.")
    
    with search_tabs[1]:
        st.subheader("Recherche par nom ou prénom")
        name_search = st.text_input("Entrez le nom ou prénom de l'étudiant")
        
        if name_search:
            # Récupérer tous les étudiants
            students = get_sheet_data()
            
            # Rechercher par nom/prénom
            # Note: cette fonction est un exemple - à adapter selon la structure réelle des données
            results = find_student_by_name(name_search)
            
            if results:
                st.success(f"✅ {len(results)} étudiant(s) trouvé(s)")
                
                # Afficher les résultats sous forme de tableau
                df = pd.DataFrame(results)
                st.dataframe(df)
                
                # Sélectionner un étudiant pour plus de détails
                id_field = sheet.cell(1, 1).value
                if id_field in df.columns:
                    selected_student = st.selectbox(
                        "Sélectionnez un étudiant pour voir les détails:",
                        df[id_field].tolist()
                    )
                    
                    if selected_student:
                        st.session_state.numero_adherent = str(selected_student)
                        st.write(f"Vous avez sélectionné l'étudiant #{selected_student}")
                        
                        # Option pour rediriger vers le scan rapide
                        if st.button("Distribuer un poly à cet étudiant"):
                            # Changer la page et mettre à jour l'ID
                            st.session_state.numero_adherent = str(selected_student)
                            st.experimental_set_query_params(page="scanner-rapide")
                            st.rerun()
            else:
                st.warning("❌ Aucun étudiant trouvé avec ce nom ou prénom.")
                
                # Suggestion d'ajout d'un nouvel étudiant
                if st.button("Ajouter un nouvel étudiant"):
                    with st.form("add_student_form"):
                        st.write("### Ajout d'un nouvel étudiant")
                        new_id = st.text_input("Numéro d'adhérent")
                        new_name = st.text_input("Nom complet")
                        
                        submit = st.form_submit_button("Ajouter")
                        
                        if submit and new_id:
                            try:
                                # Vérifier si l'étudiant existe déjà
                                existing = None
                                try:
                                    existing = sheet.find(new_id)
                                except:
                                    pass
                                
                                if existing:
                                    st.error(f"Un étudiant avec l'ID '{new_id}' existe déjà!")
                                else:
                                    # Ajouter l'étudiant avec des cellules vides pour tous les cours
                                    sheet.append_row([new_id] + [''] * (len(get_courses()) - 1))
                                    st.cache_data.clear()
                                    log_activity(st.session_state.username, "Ajout étudiant",
                                               f"ID: {new_id}", "Succès")
                                    st.success(f"✅ Étudiant '{new_id}' ajouté avec succès!")
                            except Exception as e:
                                st.error(f"❌ Erreur: {e}")
                                log_activity(st.session_state.username, "Ajout étudiant",
                                           f"ID: {new_id}, Erreur: {str(e)}", "Échec")

# ========== PAGE PARAMETRES ==========
elif page == "⚙️ Paramètres":
    st.title("Paramètres")
    
    # Options générales
    st.subheader("Options générales")
    st.session_state.debug_mode = st.checkbox("Mode débogage (afficher les temps d'exécution)", 
                                            value=st.session_state.get('debug_mode', False))
    
    # Personnalisation de l'interface
    st.subheader("Personnalisation de l'interface")
    theme_options = ["Clair", "Sombre", "Auto (selon l'appareil)"]
    selected_theme = st.selectbox("Thème", theme_options, index=0)
    
    # Paramètres de scanner
    st.subheader("Paramètres du scanner")
    default_night_mode = st.checkbox("Activer le mode faible luminosité par défaut")
    scan_quality = st.slider("Qualité de scan", min_value=1, max_value=5, value=3, 
                           help="Plus la qualité est élevée, plus le scan sera précis mais lent")
    
    # Préférences utilisateur
    st.subheader("Préférences utilisateur")
    default_course = st.selectbox("Cours présélectionné par défaut", 
                                 ["Cours le plus fréquent"] + liste_cours)
    
    # Paramètres administrateur (si applicable)
    if st.session_state.is_admin:
        st.subheader("Paramètres administrateur")
        
        # Options d'exportation
        export_options = st.multiselect(
            "Options d'exportation automatique",
            ["CSV quotidien", "Backup hebdomadaire", "Rapports mensuels"],
            default=[]
        )
        
        # Gestion des journaux
        log_retention = st.slider("Conservation des journaux (jours)", 
                                min_value=7, max_value=365, value=90)
    
    # Sauvegarde des paramètres
    if st.button("Enregistrer les paramètres"):
        # Dans une version réelle, ces paramètres seraient sauvegardés
        st.success("✅ Paramètres enregistrés avec succès!")
        log_activity(st.session_state.username, "Modification paramètres", 
                   f"Thème: {selected_theme}, Mode nuit: {default_night_mode}", "Succès")

# Pied de page et déconnexion
st.sidebar.write("---")
if st.sidebar.button("Se déconnecter"):
    log_activity(st.session_state.username, "Déconnexion", "", "Succès")
    # Réinitialisation des variables de session et vidage du cache
    st.session_state.authentifie = False
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.numero_adherent = None
    st.cache_data.clear()
    st.rerun()

# Info version
st.sidebar.write("---")
with st.sidebar.expander("À propos"):
    st.write("### CREM - Gestion des polys Tutorat")
    st.write("Version: 2.0.0")
    st.write("Contact: web@crem.fr")

# Nettoyage des ressources non utilisées
import gc
gc.collect()
