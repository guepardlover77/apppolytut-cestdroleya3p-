import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="CREM - Gestion des polys Tutorat",
    page_icon="logo.png",
    layout="wide"
)

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


def verifier_identifiants(utilisateur, mot_de_passe):
    utilisateurs = st.secrets["credentials"]
    return utilisateurs.get(utilisateur) == mot_de_passe


def enhance_for_low_light(image, alpha=1.5, beta=10):
    """Enhance image for low light conditions"""
    # Adjust brightness and contrast
    enhanced = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    return enhanced


def scan_barcode(image, night_mode=False):
    """Improved barcode detection with support for low light conditions"""
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply low-light enhancement if night mode is enabled
    if night_mode:
        # Enhance brightness and contrast
        gray = enhance_for_low_light(gray, alpha=1.8, beta=30)
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

    # Try different preprocessing techniques
    results = None

    # Method 1: Basic blur and direct decode
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    results = decode(blurred)
    if results:
        return results, blurred

    # Method 2: Adaptive threshold
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 13 if night_mode else 11, 5 if night_mode else 2)
    results = decode(thresh)
    if results:
        return results, thresh

    # Method 3: Edge enhancement with adjusted parameters for night mode
    edges = cv2.Canny(blurred, 30 if night_mode else 50, 150 if night_mode else 200, apertureSize=3)
    results = decode(edges)
    if results:
        return results, edges

    # Method 4: Morphological operations
    kernel = np.ones((5, 5) if night_mode else (3, 3), np.uint8)
    dilated = cv2.dilate(blurred, kernel, iterations=2 if night_mode else 1)
    eroded = cv2.erode(dilated, kernel, iterations=1)
    results = decode(eroded)
    
    return results, eroded if night_mode else blurred


if "authentifie" not in st.session_state:
    st.session_state.authentifie = False

if not st.session_state.authentifie:
    st.title("🔑 Connexion requise")

    utilisateur = st.text_input("👤 Identifiant")
    mot_de_passe = st.text_input("🔒 Mot de passe", type="password")
    connexion_bouton = st.button("Se connecter")

    if connexion_bouton:
        if verifier_identifiants(utilisateur, mot_de_passe):
            st.session_state.authentifie = True
            st.success("✅ Connexion réussie !")
            st.rerun()
        else:
            st.error("❌ Identifiants incorrects. Veuillez réessayer.")

    st.stop()

st.title("📚 Gestion des polys - CREM")

if st.button("🚪 Se déconnecter"):
    st.session_state.authentifie = False
    st.rerun()

st.subheader("📷 Scanner un code-barres")

# Night mode toggle
night_mode = st.checkbox("🌙 Mode faible luminosité", 
                         help="Activez cette option si vous êtes dans un environnement peu éclairé")

img_file_buffer = st.camera_input("Scannez le code-barres pour récupérer un numéro d'adhérent")

if "numero_adherent" not in st.session_state:
    st.session_state.numero_adherent = None

if img_file_buffer is not None:
    file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)

    # Use enhanced barcode scanning with night mode if enabled
    decoded_objs, processed_img = scan_barcode(image, night_mode)

    if decoded_objs:
        st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
        st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
        
        # Option to show processed image
        if st.checkbox("Afficher l'image traitée"):
            st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
    else:
        st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
        st.info("Conseil: Assurez-vous que le code-barres est bien éclairé et centré dans l'image.")
        
        # Show processed image in error case to help troubleshoot
        st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)
        
        if not night_mode:
            st.warning("💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")

st.subheader("📌 Sélectionner un cours")

try:
    liste_cours = sheet.row_values(1)
    if not liste_cours:
        st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
except Exception as e:
    st.error(f"❌ Erreur lors de la récupération des cours : {e}")
    liste_cours = []

cours_selectionne = st.selectbox("📖 Choisissez un cours :", liste_cours)

if st.button("📤 Enregistrer la récupération du cours"):
    if st.session_state.numero_adherent is None:
        st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
    else:
        try:
            cellule = sheet.find(st.session_state.numero_adherent)
        except Exception as e:
            st.error(f"❌ Erreur lors de la recherche de l'adhérent : {e}")
            cellule = None

        if cellule:
            ligne = cellule.row
            if cours_selectionne in liste_cours:
                colonne = liste_cours.index(cours_selectionne) + 1
                try:
                    current_value = sheet.cell(ligne, colonne).value

                    if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                        st.error("❌ Cet étudiant a déjà récupéré ce poly.")
                    else:
                        sheet.update_cell(ligne, colonne, 1)
                        st.success("✅ Mise à jour réussie dans Google Sheets !")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la mise à jour : {e}")
            else:
                st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
        else:
            st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
