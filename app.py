import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials
import json


# --- Configuration de Google Sheets ---
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Charger les identifiants depuis st.secrets au lieu d'un fichier
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

    utilisateur = st.text_input("👤 Identifiant")
    mot_de_passe = st.text_input("🔒 Mot de passe", type="password")
    connexion_bouton = st.button("Se connecter")

    if connexion_bouton:
        if verifier_identifiants(utilisateur, mot_de_passe):
            st.session_state.authentifie = True
            st.success("✅ Connexion réussie !")
            st.rerun()  # Recharge la page après connexion
        else:
            st.error("❌ Identifiants incorrects. Veuillez réessayer.")

    st.stop()  # Arrête l'exécution ici si non authentifié

# --- Interface principale après connexion ---
st.title("📚 Gestion des polys - CREM")

# Bouton de déconnexion
if st.button("🚪 Se déconnecter"):
    st.session_state.authentifie = False
    (st.rerun())

# Capture du code-barres
st.subheader("📷 Scanner un code-barres")
img_file_buffer = st.camera_input("Scannez le code-barres pour récupérer un numéro d'adhérent")

if "numero_adherent" not in st.session_state:
    st.session_state.numero_adherent = None

# Détection du code-barres
if img_file_buffer is not None:
    file_bytes = np.asarray(bytearray(img_file_buffer.read()), dtype=np.uint8)
    image = cv2.imdecode(file_bytes, 1)

    decoded_objs = decode(image)
    if decoded_objs:
        st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
        st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
    else:
        st.error("❌ Code-barres non reconnu. Veuillez réessayer.")

# Récupération des cours depuis Google Sheets
st.subheader("📌 Sélectionner un cours")

try:
    liste_cours = sheet.row_values(1)  # Récupère les intitulés de la première ligne
    if not liste_cours:
        st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
except Exception as e:
    st.error(f"❌ Erreur lors de la récupération des cours : {e}")
    liste_cours = []

cours_selectionne = st.selectbox("📖 Choisissez un cours :", liste_cours)

# Bouton de mise à jour
if st.button("📤 Enregistrer la récupération du cours"):
    if st.session_state.numero_adherent is None:
        st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
    else:
        try:
            # Recherche du numéro d'adhérent dans la feuille
            cellule = sheet.find(st.session_state.numero_adherent)
        except Exception as e:
            st.error(f"❌ Erreur lors de la recherche de l'adhérent : {e}")
            cellule = None

        if cellule:
            ligne = cellule.row
            if cours_selectionne in liste_cours:
                colonne = liste_cours.index(cours_selectionne) + 1  # Index basé sur 1
                try:
                    # Vérifier si l'étudiant a déjà récupéré le poly
                    current_value = sheet.cell(ligne, colonne).value

                    # Si la cellule contient déjà une valeur ≥ 1
                    if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                        st.error("❌ Cet étudiant a déjà récupéré ce poly.")
                    else:
                        # Sinon, mettre à jour la cellule
                        sheet.update_cell(ligne, colonne, 1)
                        st.success("✅ Mise à jour réussie dans Google Sheets !")
                except Exception as e:
                    st.error(f"❌ Erreur lors de la mise à jour : {e}")
            else:
                st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
        else:
            st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
