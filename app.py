import streamlit as st
import cv2
import numpy as np
from pylibdmtx.pylibdmtx import decode  # Remplace pyzbar
import gspread
from google.oauth2.service_account import Credentials

# --- Configuration de Google Sheets ---
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Authentification avec les secrets Streamlit
creds = Credentials.from_service_account_info(st.secrets["google_sheets"], scopes=scopes)
client = gspread.authorize(creds)
sheet = client.open("1").sheet1  # Remplacez par le nom réel de votre fichier

# --- Authentification ---
def verifier_identifiants(utilisateur, mot_de_passe):
    utilisateurs = st.secrets["credentials"]
    return utilisateurs.get(utilisateur) == mot_de_passe

# Vérifier si l'utilisateur est connecté
if "authentifie" not in st.session_state:
    st.session_state.authentifie = False

if not st.session_state.authentifie:
    st.title("🔑 Connexion")

    utilisateur = st.text_input("👤 Identifiant")
    mot_de_passe = st.text_input("🔒 Mot de passe", type="password")
    if st.button("Se connecter"):
        if verifier_identifiants(utilisateur, mot_de_passe):
            st.session_state.authentifie = True
            st.success("✅ Connexion réussie !")
            st.experimental_rerun()
        else:
            st.error("❌ Identifiants incorrects")

    st.stop()

# --- Interface principale ---
st.title("📚 Gestion des cours - Association Étudiante")

# Bouton de déconnexion
if st.button("🚪 Se déconnecter"):
    st.session_state.authentifie = False
    st.experimental_rerun()

# Scanner un QR Code
st.subheader("📷 Scanner un QR Code")
img_file_buffer = st.camera_input("Scannez le QR code")

if "numero_adherent" not in st.session_state:
    st.session_state.numero_adherent = None

if img_file_buffer is not None:
    file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)
    
    decoded_objs = decode(image)
    if decoded_objs:
        st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
        st.success(f"✅ Numéro d'adhérent : {st.session_state.numero_adherent}")
    else:
        st.error("❌ QR code non reconnu.")

# Récupérer les cours depuis Google Sheets
st.subheader("📌 Sélectionner un cours")
try:
    liste_cours = sheet.row_values(1)  # Récupère les intitulés de la première ligne
    if not liste_cours:
        st.error("⚠️ Aucun cours trouvé dans Google Sheets.")
except Exception as e:
    st.error(f"❌ Erreur : {e}")
    liste_cours = []

cours_selectionne = st.selectbox("📖 Choisissez un cours :", liste_cours)

# Enregistrer la récupération du cours
if st.button("📤 Enregistrer"):
    if st.session_state.numero_adherent is None:
        st.error("❌ Aucun numéro d'adhérent détecté.")
    else:
        try:
            cellule = sheet.find(st.session_state.numero_adherent)
        except Exception as e:
            st.error(f"❌ Erreur lors de la recherche : {e}")
            cellule = None
        
        if cellule:
            ligne = cellule.row
            if cours_selectionne in liste_cours:
                colonne = liste_cours.index(cours_selectionne) + 1
                try:
                    sheet.update_cell(ligne, colonne, 1)
                    st.success("✅ Mise à jour réussie !")
                except Exception as e:
                    st.error(f"❌ Erreur : {e}")
            else:
                st.error("⚠️ Le cours sélectionné n'existe pas.")
        else:
            st.error("❌ Numéro d'adhérent non trouvé.")
