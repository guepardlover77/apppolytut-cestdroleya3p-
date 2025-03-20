import pandas as pd
import streamlit as st
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import gspread
from google.oauth2.service_account import Credentials
import datetime
import base64
import time
from streamlit.components.v1 import html

#pompompidou

st.set_page_config(
    page_title="CREM - Gestion des polys Tutorat",
    page_icon="logo.png" #logo du crem ou du tut ?
)

#pompompidou

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
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if night_mode:
        gray = enhance_for_low_light(gray, alpha=1.8, beta=30)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

    results = None

    #ethod 1: Basic blur and direct decode
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    results = decode(blurred)
    if results:
        return results, blurred

    #method 2: adaptive threshold
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 13 if night_mode else 11, 5 if night_mode else 2)
    results = decode(thresh)
    if results:
        return results, thresh

    #method 3: edge enhancement with adjusted parameters for night mode
    edges = cv2.Canny(blurred, 30 if night_mode else 50, 150 if night_mode else 200, apertureSize=3)
    results = decode(edges)
    if results:
        return results, edges

    #method 4: morphological operations
    kernel = np.ones((5, 5) if night_mode else (3, 3), np.uint8)
    dilated = cv2.dilate(blurred, kernel, iterations=2 if night_mode else 1)
    eroded = cv2.erode(dilated, kernel, iterations=1)
    results = decode(eroded)

    return results, eroded if night_mode else blurred


# Composant personnalisé pour le scanner de code-barres en continu
def continuous_barcode_scanner(callback_url, night_mode=False, key=None):
    # Code JavaScript pour scanner en continu
    scanner_html = """
    <div>
        <div id="barcode-scanner-wrapper">
            <video id="barcode-scanner" width="100%" autoplay></video>
            <canvas id="barcode-canvas" style="display:none;"></canvas>
            <div id="scanner-status">Initialisation de la caméra...</div>
            <div id="scan-result"></div>
            <button id="toggle-camera" style="margin-top: 10px; padding: 8px;">Changer de caméra</button>
            <button id="stop-scanning" style="margin-top: 10px; margin-left: 10px; padding: 8px;">Arrêter le scan</button>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/@zxing/library@0.19.1"></script>
        <script>
            const videoElement = document.getElementById('barcode-scanner');
            const canvasElement = document.getElementById('barcode-canvas');
            const statusElement = document.getElementById('scanner-status');
            const resultElement = document.getElementById('scan-result');
            const toggleButton = document.getElementById('toggle-camera');
            const stopButton = document.getElementById('stop-scanning');
            
            let selectedDeviceId = '';
            let codeReader = new ZXing.BrowserMultiFormatReader();
            let scanning = true;
            let nightMode = """ + str(night_mode).lower() + """;
            let lastScanned = '';
            let lastScannedTime = 0;
            
            async function startScanner() {
                try {
                    statusElement.textContent = 'Accès à la caméra...';
                    const videoConstraints = {};
                    
                    // Si un appareil est sélectionné, l'utiliser
                    if (selectedDeviceId !== '') {
                        videoConstraints.deviceId = {exact: selectedDeviceId};
                    } else {
                        // Sinon, préférer la caméra arrière
                        videoConstraints.facingMode = 'environment';
                    }
                    
                    // Ajouter des paramètres pour une meilleure performance dans des conditions de faible luminosité
                    if (nightMode) {
                        videoConstraints.advanced = [
                            {exposureMode: 'manual', exposureCompensation: 2},
                            {focusMode: 'continuous'}
                        ];
                    }
                    
                    const constraints = {
                        video: videoConstraints,
                        audio: false
                    };
                    
                    const stream = await navigator.mediaDevices.getUserMedia(constraints);
                    videoElement.srcObject = stream;
                    statusElement.textContent = 'Caméra prête. Scannez un code-barres...';
                    
                    decodeFromStream();
                } catch (err) {
                    statusElement.textContent = 'Erreur d\'accès à la caméra: ' + err;
                    console.error(err);
                }
            }

            function decodeFromStream() {
                if (!scanning) return;
                
                // Dessiner l'image vidéo sur le canvas
                const context = canvasElement.getContext('2d');
                canvasElement.width = videoElement.videoWidth;
                canvasElement.height = videoElement.videoHeight;
                context.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height);
                
                // Améliorer l'image en mode nuit
                if (nightMode) {
                    const imageData = context.getImageData(0, 0, canvasElement.width, canvasElement.height);
                    const data = imageData.data;
                    
                    // Simple amélioration du contraste
                    for (let i = 0; i < data.length; i += 4) {
                        data[i] = data[i] < 100 ? 0 : 255;        // Rouge
                        data[i + 1] = data[i + 1] < 100 ? 0 : 255; // Vert
                        data[i + 2] = data[i + 2] < 100 ? 0 : 255; // Bleu
                    }
                    
                    context.putImageData(imageData, 0, 0);
                }
                
                try {
                    // Utiliser ZXing pour détecter les codes-barres
                    codeReader.decodeFromCanvas(canvasElement)
                        .then(result => {
                            const now = Date.now();
                            // Ne traiter que si c'est un nouveau code ou si 3 secondes se sont écoulées
                            if (result && (result.text !== lastScanned || now - lastScannedTime > 3000)) {
                                lastScanned = result.text;
                                lastScannedTime = now;
                                resultElement.textContent = 'Code trouvé: ' + result.text;
                                
                                // Envoyer le résultat à Streamlit
                                const data = {
                                    barcode: result.text,
                                    format: result.format,
                                    timestamp: now
                                };
                                
                                fetch('""" + callback_url + """', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(data)
                                }).then(response => {
                                    if (response.ok) {
                                        resultElement.textContent += ' - Envoyé!';
                                    }
                                }).catch(error => {
                                    console.error('Error sending data:', error);
                                });
                            }
                        })
                        .catch(() => { /* Ignorer les erreurs de décodage */ });
                } catch (e) {
                    console.error('Erreur de décodage:', e);
                }
                
                // Scanner en continu
                if (scanning) {
                    requestAnimationFrame(decodeFromStream);
                }
            }
            
            async function toggleCamera() {
                // Arrêter la caméra actuelle
                if (videoElement.srcObject) {
                    videoElement.srcObject.getTracks().forEach(track => track.stop());
                }
                
                // Obtenir la liste des appareils disponibles
                const devices = await navigator.mediaDevices.enumerateDevices();
                const videoDevices = devices.filter(device => device.kind === 'videoinput');
                
                if (videoDevices.length <= 1) {
                    statusElement.textContent = 'Une seule caméra détectée';
                    selectedDeviceId = '';
                } else {
                    // Si aucun appareil n'est sélectionné ou si l'appareil courant est le dernier de la liste,
                    // sélectionner le premier appareil, sinon sélectionner l'appareil suivant
                    if (selectedDeviceId === '' || 
                        selectedDeviceId === videoDevices[videoDevices.length - 1].deviceId) {
                        selectedDeviceId = videoDevices[0].deviceId;
                    } else {
                        const currentIndex = videoDevices.findIndex(device => device.deviceId === selectedDeviceId);
                        selectedDeviceId = videoDevices[currentIndex + 1].deviceId;
                    }
                    
                    statusElement.textContent = 'Changement de caméra...';
                }
                
                // Redémarrer le scanner avec le nouvel appareil
                startScanner();
            }
            
            function stopScanning() {
                scanning = false;
                if (videoElement.srcObject) {
                    videoElement.srcObject.getTracks().forEach(track => track.stop());
                }
                statusElement.textContent = 'Scan arrêté';
            }
            
            // Démarrer le scanner
            startScanner();
            toggleButton.addEventListener('click', toggleCamera);
            stopButton.addEventListener('click', stopScanning);
            
            // Nettoyer les ressources quand le composant est détruit
            window.addEventListener('beforeunload', () => {
                if (videoElement.srcObject) {
                    videoElement.srcObject.getTracks().forEach(track => track.stop());
                }
            });
        </script>
    </div>
    """
    
    # Générer un ID unique pour ce composant
    component_id = f"barcode_scanner_{key}"
    
    # Créer une URL de callback pour ce composant
    if not callback_url:
        callback_url = "/_stcore/stream"
    
    # Injecter le composant HTML
    html(scanner_html, height=400, key=component_id)


# Pour gérer les résultats du scanner
def handle_scan_result():
    # Vérifier si une nouvelle analyse a été reçue
    if 'scan_results' in st.session_state and st.session_state.scan_results:
        result = st.session_state.scan_results.pop(0)  # Prendre le premier résultat
        barcode_data = result.get('barcode')
        
        if barcode_data:
            st.session_state.numero_adherent = barcode_data
            return True
    
    return False


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

# Initialiser les structures de données nécessaires
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "last_processed_barcode" not in st.session_state:
    st.session_state.last_processed_barcode = None
if "processing_status" not in st.session_state:
    st.session_state.processing_status = None
if "continuous_scan_active" not in st.session_state:
    st.session_state.continuous_scan_active = False
if "cours_selectionne" not in st.session_state:
    st.session_state.cours_selectionne = None
if "numero_adherent" not in st.session_state:
    st.session_state.numero_adherent = None


if st.session_state.username not in st.session_state.is_admin:
    st.header(f"Coucou {st.session_state.username} !")

    # Section pour le scanner continu
    st.subheader("1. Scanner un code-barres")
    
    night_mode = st.checkbox("Mode faible luminosité",
                            help="Activez cette option si vous êtes dans un environnement peu éclairé")
    
    scan_tab, upload_tab = st.tabs(["Scanner en continu", "Importer une image"])
    
    with scan_tab:
        # Montrer le statut actuel
        status_placeholder = st.empty()
        
        # Option pour activer/désactiver le scan continu
        if not st.session_state.continuous_scan_active:
            if st.button("Activer le scan continu"):
                st.session_state.continuous_scan_active = True
                st.rerun()
        else:
            if st.button("Désactiver le scan continu"):
                st.session_state.continuous_scan_active = False
                st.rerun()
        
        # Afficher le scanner continu s'il est activé
        if st.session_state.continuous_scan_active:
            st.markdown("### Scanner en continu")
            st.markdown("Tenez simplement le code-barres devant la caméra. Le scan se fait automatiquement.")
            
            # Créer une URL de callback pour la communication avec le composant
            callback_url = "/_stcore/component/barcode_callback"
            
            # Injecter le composant de scan continu
            continuous_barcode_scanner(callback_url, night_mode, key="main_scanner")
            
            # Afficher l'état actuel du scanner
            if st.session_state.numero_adherent:
                status_placeholder.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
            else:
                status_placeholder.info("En attente de la détection d'un code-barres...")
    
    with upload_tab:
        uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                         type=['jpg', 'jpeg', 'png', 'bmp'])
        
        if uploaded_file is not None:
            file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
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
    
    st.write("-------------------------------------------------------------------------------------------------------------------------")
    
    st.subheader("2. Sélectionner un cours")
    #pompompidou
    
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
    st.session_state.cours_selectionne = cours_selectionne
    
    # Fonction pour enregistrer automatiquement
    def enregistrer_cours(numero_adherent, cours):
        if not numero_adherent:
            st.error("❌ Aucun numéro d'adhérent détecté. Veuillez scanner un code-barres.")
            log_activity(st.session_state.username, "Enregistrement poly",
                        f"Cours: {cours} - Aucun numéro d'adhérent", "Échec")
            return False
        
        try:
            cellule = sheet.find(numero_adherent)
        except Exception as e:
            st.error(f"❌ Erreur lors de la recherche de l'adhérent : {e}")
            log_activity(st.session_state.username, "Recherche adhérent",
                        f"ID: {numero_adherent}, Erreur: {str(e)}", "Échec")
            return False

        if cellule:
            ligne = cellule.row
            if cours in liste_cours:
                colonne = liste_cours.index(cours) + 1
                try:
                    current_value = sheet.cell(ligne, colonne).value

                    if current_value and str(current_value).strip() and int(float(current_value)) >= 1:
                        st.error("❌ Cet étudiant a déjà récupéré ce poly.")
                        log_activity(st.session_state.username, "Enregistrement poly",
                                    f"ID: {numero_adherent}, Cours: {cours}, Déjà récupéré",
                                    "Échec")
                        return False
                    else:
                        sheet.update_cell(ligne, colonne, 1)
                        st.success("✅ Mise à jour réussie dans Google Sheets !")
                        log_activity(st.session_state.username, "Enregistrement poly",
                                    f"ID: {numero_adherent}, Cours: {cours}",
                                    "Succès")
                        return True
                except Exception as e:
                    st.error(f"❌ Erreur lors de la mise à jour : {e}")
                    log_activity(st.session_state.username, "Enregistrement poly",
                                f"ID: {numero_adherent}, Cours: {cours}, Erreur: {str(e)}",
                                "Échec")
                    return False
            else:
                st.error("⚠️ Le cours sélectionné n'existe pas dans la feuille.")
                log_activity(st.session_state.username, "Enregistrement poly",
                            f"ID: {numero_adherent}, Cours: {cours} inexistant",
                            "Échec")
                return False
        else:
            st.error("❌ Numéro d'adhérent non trouvé dans la base de données.")
            log_activity(st.session_state.username, "Enregistrement poly",
                        f"ID: {numero_adherent} non trouvé", "Échec")
            return False
    
    # Option pour activer l'enregistrement automatique
    auto_register = st.checkbox("Enregistrement automatique", 
                              help="Enregistre automatiquement le cours dès qu'un code-barres est détecté")
    
    if auto_register:
        st.info("Mode automatique activé. Le cours sera enregistré dès qu'un code-barres est détecté.")
        
        # Vérifier si un nouveau code-barres a été scanné
        if handle_scan_result():
            if st.session_state.numero_adherent != st.session_state.last_processed_barcode:
                st.session_state.last_processed_barcode = st.session_state.numero_adherent
                
                # Enregistrer automatiquement le cours
                if enregistrer_cours(st.session_state.numero_adherent, cours_selectionne):
                    # Réinitialiser pour le prochain scan
                    time.sleep(2)  # Donner le temps à l'utilisateur de voir le message de succès
                    st.session_state.numero_adherent = None
                    st.rerun()
    else:
        # Bouton d'enregistrement manuel
        if st.button("Enregistrer la récupération du cours"):
            enregistrer_cours(st.session_state.numero_adherent, cours_selectionne)



if st.session_state.username in st.session_state.is_admin:
    tab1, tab2 = st.tabs(["🤓 Interface des tuteurs", "👑 Admin"])
    with tab1:
        # Section pour le scanner continu
        st.subheader("1. Scanner un code-barres")
        
        night_mode = st.checkbox("Mode faible luminosité",
                                help="Activez cette option si vous êtes dans un environnement peu éclairé")
        
        scan_tab, upload_tab = st.tabs(["Scanner en continu", "Importer une image"])
        
        with scan_tab:
            # Montrer le statut actuel
            status_placeholder = st.empty()
            
            # Option pour activer/désactiver le scan continu
            if not st.session_state.continuous_scan_active:
                if st.button("Activer le scan continu"):
                    st.session_state.continuous_scan_active = True
                    st.rerun()
            else:
                if st.button("Désactiver le scan continu"):
                    st.session_state.continuous_scan_active = False
                    st.rerun()
            
            # Afficher le scanner continu s'il est activé
            if st.session_state.continuous_scan_active:
                st.markdown("### Scanner en continu")
                st.markdown("Tenez simplement le code-barres devant la caméra. Le scan se fait automatiquement.")
                
                # Créer une URL de callback pour la communication avec le composant
                callback_url = "/_stcore/component/barcode_callback"
                
                # Injecter le composant de scan continu
                continuous_barcode_scanner(callback_url, night_mode, key="admin_scanner")
                
                # Afficher l'état actuel du scanner
                if st.session_state.numero_adherent:
                    status_placeholder.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
                else:
                    status_placeholder.info("En attente de la détection d'un code-barres...")
        
        with upload_tab:
            uploaded_file = st.file_uploader("Importer une photo contenant un code-barres",
                                            type=['jpg', 'jpeg', 'png', 'bmp'],
                                            key="admin_uploader")
            
            if uploaded_file is not None:
                file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
                image = cv2.imdecode(file_bytes, 1)
                decoded_objs, processed_img = scan_barcode(image, night_mode)
            
                if decoded_objs:
                    st.session_state.numero_adherent = decoded_objs[0].data.decode("utf-8")
                    st.success(f"✅ Numéro d'adhérent détecté : {st.session_state.numero_adherent}")
                    log_activity(st.session_state.username, "Scan de code-barres",
                                f"ID: {st.session_state.numero_adherent}", "Succès")
            
                    if st.checkbox("Afficher l'image traitée", key="admin_show_processed"):
                        st.image(processed_img, caption="Image traitée pour la détection", channels="GRAY")
                else:
                    st.error("❌ Code-barres non reconnu. Veuillez réessayer.")
                    st.info("Conseil: Assurez-vous que le code-barres est bien éclairé et centré dans l'image.")
                    log_activity(st.session_state.username, "Scan de code-barres", "Échec de détection", "Échec")
            
                    st.image(processed_img, caption="Dernière image traitée", channels="GRAY", width=300)
            
                    if not night_mode:
                        st.warning("💡 Essayez d'activer le mode faible luminosité si vous êtes dans un environnement sombre.")
        
        st.write("-------------------------------------------------------------------------------------------------------------------------")
        
        st.subheader("2. Sélectionner un cours")
        
        try:
            liste_cours = sheet.row_values(1)
            if not liste_cours:
                st.error("⚠️ Aucun cours trouvé dans la première ligne du Google Sheets.")
                log_activity(st.session_state.username, "Chargement des cours", "Aucun cours trouvé", "Échec")
        except Exception as e:
            st.error(f"❌ Erreur lors de la récupération des cours : {e}")
            log_activity(st.session_state.username, "Chargement des cours", f"Erreur: {str(e)}", "Échec")
            liste_cours = []
        
        cours_selectionne = st.selectbox("Choisissez un cours :", liste_cours, key="admin_course")
        st.session_state.cours_selectionne = cours_selectionne
        
        # Option pour activer l'enregistrement automatique
        auto_register_admin = st.checkbox("Enregistrement automatique", 
                                        help="Enregistre automatiquement le cours dès qu'un code-barres est détecté",
                                        key="admin_auto_register")
        
        if auto_register_admin:
            st.info("Mode automatique activé. Le cours sera enregistré dès qu'un code-barres est détecté.")
            
            # Vérifier si un nouveau code-barres a été scanné
            if handle_scan_result():
                if st.session_state.numero_adherent != st.session_state.last_processed_barcode:
                    st.session_state.last_processed_barcode = st.session_state.numero_adherent
                    
                    # Enregistrer automatiquement le cours
                    if enregistrer_cours(st.session_state.numero_adherent, cours_selectionne):
                        # Réinitialiser pour le prochain scan
                        time.sleep(2)  # Donner le temps à l'utilisateur de voir le message de succès
                        st.session_state.numero_adherent = None
                        st.rerun()
        else:
            # Bouton d'enregistrement manuel
            if st.button("Enregistrer la récupération du cours", key="admin_register_button"):
                enregistrer_cours(st.session_state.numero_adherent, cours_selectionne)
        
    # Le reste du code administrateur reste inchangé
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
        #pompompidou
        
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
                            selected_user = st.selectbox("Filtrer par utilisateur:", ["Tous les utilisateurs"] + usernames)
        
                        with col2:
                            actions = list(set(log['Action'] for log in all_logs))
                            selected_action = st.selectbox("Filtrer par type d'action:", ["Toutes les actions"] + actions)
        
                        start_date, end_date = st.columns(2)
                        with start_date:
                            min_date = datetime.datetime.strptime(min(log['Date'] for log in all_logs), "%d/%m/%Y").date()
                            date_debut = st.date_input("Date de début:", min_date)
        
                        with end_date:
                            max_date = datetime.datetime.strptime(max(log['Date'] for log in all_logs), "%d/%m/%Y").date()
                            date_fin = st.date_input("Date de fin:", max_date)
        #pompompidou
        
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
        #pompompidou
        
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
        #pompompidou
        
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
#pompompidou

# Endpoint Streamlit pour recevoir les résultats de scan
# Cette fonction est appelée par le composant JavaScript via fetch
def barcode_callback():
    import json
    from streamlit.web.server.server import Server
    
    # Obtenir les données POST
    request = json.loads(Server.get_current()._session_mgr.get_session_info().websocket_message)
    if not request:
        return {"error": "No data received"}
    
    # Enregistrer le résultat dans la session state
    if "scan_results" not in st.session_state:
        st.session_state.scan_results = []
    
    st.session_state.scan_results.append(request)
    st.session_state.numero_adherent = request.get("barcode")
    
    return {"success": True}

# Enregistrer l'endpoint
Server.get_current()._add_websocket_handler("barcode_callback", barcode_callback)

st.write("-------------------------------------------------------------------------------------------------------------------------")
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
        st.write("Version: 1.1.0")
        st.write("Contact: web@crem.fr")
        st.write("<3")


#Mathéo Milley-Arjaliès, Webmaster au CREM, référent SHS au Tutorat
