# Yo
## Introduction
C'est un projet pour vérifier que les LAS sont bien adhérents au Tutorat et qu'ils ne prennent bien qu'un seul poly.
Ce projet permettra à la fois de vérifier que chacun prend son poly et aussi qu'il y ait assez de poly pour tout le monde ! Ben oui parce que les petits malins qui en prennent plusieurs pour leurs amis en fait ils en volent à d'honnêtes LAS qui sont adhérents et qui n'en avaient pas encore pris...
Donc les petits malins font perdre de l'argent au CREM parce qu'on imprime trop de polys et que les LAS adhèrent désormais à plusieurs.
Je précise que si le CREM perd de l'argent y aura plus de gala, plus de voyage au ski, plus de soirée, plus d'action de Santé Publique, etc. Plus grand chose en fin de compte.

# Ok on fait les choses propres au cas où quelqu'un inspecte ce repo
## Description
Application web permettant de vérifier l'adhésion des étudiants au Tutorat et de gérer la distribution des polycopiés. Le système assure qu'un étudiant ne prenne qu'un seul exemplaire par cours, optimisant ainsi l'utilisation des poly et garantissant une distribution équitable.

## Fonctionnalités
- Vérification d'adhésion au Tutorat par numéro CREM
- Suivi des polycopiés distribués par étudiant
- Interface d'administration pour la gestion des utilisateurs
- Journalisation des activités
- Gestion et ajout de nouveaux cours
- Recherche et modification des données étudiants

## Prérequis
- Python 3.12+
- Compte Google (pour l'accès au Google Sheet)
- Fichier de configuration avec identifiants

## Installation

```bash
git clone https://github.com/guepardlover77/apppolytut-cestdroleya3p-.git
cd apppolytut-cestdroleya3p-
pip install -r requirements.txt
```

## Configuration
1. Créez un fichier `.streamlit/secrets.toml` avec les informations d'authentification:
   - Identifiants Google Sheets
   - Identifiants utilisateurs

## Utilisation
Pour lancer l'application:
```bash
streamlit run app.py
```

## Auteur
Mathéo Milley-Arjaliès, CREMeux

## Contact
- [web@crem.fr](MAILTO:web@crem.fr)
- [shs@tutorat.crem.fr](MAILTO:shs@tutorat.crem.fr)
- www.crem.fr
