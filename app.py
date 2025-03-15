import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials
import time

# --- Page configuration ---
st.set_page_config(page_title="Gestion des polys - CREM", page_icon="📚", layout="wide")

# --- Configuration de Google Sheets ---
@st.cache_resource
def get_google_sheet_connection():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    
    # Charger les identifiants depuis st.secrets
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
    # Utiliser spreadsheet_id s'il existe, sinon utiliser sheet_name
    return client.open_by_key(st.secrets.get("spreadsheet_id", st.secrets["sheet_name"])).sheet1

# --- Fonction d'authentification ---
def verifier_identifiants(utilisateur, mot_de_passe):
    """Vérifie si les identifiants sont corrects."""
    utilisateurs = st.secrets["credentials"]
    return utilisateurs.get(utilisateur) == mot_de_passe

# --- Interface de connexion ---
if "authentifie" not in st.session_state:
    st.session_state.authentifie = False

if not st.session_state.authentifie:
    st.title("🔑 Connexion requise")

    with st.form("login_form"):
        utilisateur = st.text_input("👤 Identifiant")
        mot_de_passe = st.text_input("🔒 Mot de passe", type="password")
        connexion_bouton = st.form_submit_button("Se connecter")

        if connexion_bouton:
            if verifier_identifiants(utilisateur, mot_de_passe):
                st.session_state.authentifie = True
                st.success("✅ Connexion réussie !")
                st.rerun()  
            else:
                st.error("❌ Identifiants incorrects. Veuillez réessayer.")

    st.stop()  # Arrête l'exécution ici si non authentifié

# --- Initialisation des variables de session ---
if "numero_adherent" not in st.session_state:
    st.session_state.numero_adherent = None
if "scanning" not in st.session_state:
    st.session_state.scanning = False
if "last_detection_time" not in st.session_state:
    st.session_state.last_detection_time = 0

# --- Interface principale après connexion ---
st.title("📚 Gestion des polys - CREM")

# Bouton de déconnexion dans la sidebar
with st.sidebar:
    if st.button("🚪 Se déconnecter"):
        st.session_state.authentifie = False
        st.rerun()

# Récupération des cours depuis Google Sheets
try:
    sheet = get_google_sheet_connection()
    liste_cours = sheet.row_values(1)  # Récupère les intitulés de la première ligne
    if not liste_cours:
        st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
except Exception as e:
    st.error(f"❌ Erreur lors de la récupération des cours : {e}")
    liste_cours = []

# Interface avec deux colonnes
col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("📷 Scanner un QR Code")
    
    # Contrôles pour le scan de QR code
    start_stop_button = st.button(
        "⏹️ Arrêter le scan" if st.session_state.scanning else "▶️ Démarrer le scan"
    )
    
    if start_stop_button:
        st.session_state.scanning = not st.session_state.scanning
        if st.session_state.scanning:
            st.session_state.numero_adherent = None
            st.rerun()
    
    # Emplacements pour l'affichage de la caméra et des statuts
    video_placeholder = st.empty()
    status_placeholder = st.empty()

with col2:
    st.subheader("📌 Informations")
    
    # Affichage du numéro d'adhérent si détecté
    adherent_placeholder = st.empty()
    if st.session_state.numero_adherent:
        adherent_placeholder.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
    else:
        adherent_placeholder.info("En attente de scan...")
    
    # Sélection du cours
    st.subheader("📌 Sélectionner un cours")
    cours_selectionne = st.selectbox("📖 Choisissez un cours :", liste_cours)
    
    # Bouton d'enregistrement
    record_button = st.button("📤 Enregistrer la récupération du cours")
    result_placeholder = st.empty()

# Fonction de mise à jour de Google Sheet
def update_sheet(numero_adherent, cours):
    try:
        # Recherche du numéro d'adhérent dans la feuille
        cellule = sheet.find(numero_adherent)
        
        if cellule:
            ligne = cellule.row
            if cours in liste_cours:
                colonne = liste_cours.index(cours) + 1  # Index basé sur 1
                try:
                    sheet.update_cell(ligne, colonne, 1)
                    return True, "✅ Mise à jour réussie dans Google Sheets !"
                except Exception as e:
                    return False, f"❌ Erreur lors de la mise à jour : {e}"
            else:
                return False, "⚠️ Le cours sélectionné n'existe pas dans la feuille."
        else:
            return False, "❌ Numéro d'adhérent non trouvé dans la base de données."
    except Exception as e:
        return False, f"❌ Erreur lors de la recherche de l'adhérent : {e}"

# Logique du bouton d'enregistrement
if record_button:
    if st.session_state.numero_adherent is None:
        result_placeholder.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un QR code.")
    else:
        success, message = update_sheet(st.session_state.numero_adherent, cours_selectionne)
        if success:
            result_placeholder.success(message)
        else:
            result_placeholder.error(message)

# Logique de scan de QR code
if st.session_state.scanning:
    try:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        status_placeholder.info("Recherche de QR code...")
        
        while st.session_state.scanning:
            ret, frame = cap.read()
            if not ret:
                status_placeholder.error("Impossible d'accéder à la caméra")
                break
                
            # Affichage du flux vidéo
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            video_placeholder.image(frame_rgb, channels="RGB")
            
            # Recherche de QR codes
            decoded_objects = decode(frame)
            
            # Traitement du premier QR code détecté
            if decoded_objects:
                for obj in decoded_objects:
                    qr_data = obj.data.decode('utf-8')
                    
                    # Dessiner un rectangle autour du QR code
                    points = obj.polygon
                    if len(points) > 4:
                        hull = cv2.convexHull(np.array([point for point in points]))
                        cv2.polylines(frame, [hull], True, (0, 255, 0), 3)
                    else:
                        for j in range(4):
                            cv2.line(frame, points[j], points[(j+1) % 4], (0, 255, 0), 3)
                    
                    # Mettre à jour l'affichage avec le QR code surligné
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    video_placeholder.image(frame_rgb, channels="RGB")
                    
                    # Traiter le QR code détecté
                    status_placeholder.success("QR Code détecté!")
                    st.session_state.numero_adherent = qr_data
                    adherent_placeholder.success(f"✅ Numéro d'adhérent détecté : {qr_data}")
                    
                    # Arrêter le scan après détection
                    st.session_state.scanning = False
                    break
            
            # Petit délai pour réduire l'utilisation CPU
            time.sleep(0.1)
            
    except Exception as e:
        st.error(f"Une erreur s'est produite: {e}")
    finally:
        try:
            cap.release()
        except:
            pass
