
<img width="1919" height="1024" alt="{FA633D65-9969-4142-859B-14E47DE794E9}" src="https://github.com/user-attachments/assets/2c8c5fa5-2d5b-4b23-91a3-211582e9128e" />
<img width="806" height="835" alt="{F6394FCE-F007-4404-A7DD-CB791F2CD3AB}" src="https://github.com/user-attachments/assets/22a1f388-42ea-4096-b882-7ff0c9100959" />

<img width="1912" height="1015" alt="{454B2ED7-B0E1-43D4-BAF3-802293C7593E}" src="https://github.com/user-attachments/assets/092b0c9c-0f04-4c3d-a545-e372e2593807" />

<img width="456" height="886" alt="{44B55FBB-04E3-419B-BFD9-88C9F41BB308}" src="https://github.com/user-attachments/assets/709a83a6-605f-4749-96d8-d9844c2b9b08" />


<img width="1606" height="976" alt="{A1258C86-3815-4199-9748-5F186D2E681B}" src="https://github.com/user-attachments/assets/9a4f58cf-1364-45b1-98d4-5e7aabce8dc7" />

<img width="1501" height="970" alt="{6C0BF326-486D-49F7-9E1A-A7D6E6A084C1}" src="https://github.com/user-attachments/assets/6cca88a1-312b-4e66-97fd-6c3fece23823" />
<img width="1519" height="932" alt="{1976EE4C-DEDE-4FBE-A61D-2CE5800F8ECA}" src="https://github.com/user-attachments/assets/ba7882f6-6f31-4698-825d-d08c8a1fec0a" />



# 🎾 Tennis Prediction & Odds Analysis

> **⚠️ LICENCE ET CONDITIONS D'UTILISATION**  
> **This project is free for personal use ONLY.**  
> Any commercial use (including selling the software, using it for commercial betting syndicates, or integrating it into a paid product or tipster service) is **strictly prohibited** without a prior written commercial license.  
> *For any commercial use, please contact the author to purchase a commercial license.*

---

## 📌 À propos du projet

Ce projet est une suite complète d'outils d'analyse, de machine learning et de scraping dédiée aux pronostics de matchs de tennis (ATP et WTA). Il permet d'agréger les cotes des bookmakers, de récupérer l'historique détaillé des joueurs, et de calculer la probabilité de victoire de chaque joueur afin de repérer les **Value Bets** (cotes mal ajustées par les bookmakers).

Le projet comprend plusieurs interfaces graphiques (GUI) pour analyser l'ensemble des matchs d'une journée en quelques clics et générer des bulletins de pronostics complets.

## 🚀 Fonctionnalités principales

- **Scraping et Agrégation de données** : Récupère les données depuis The Odds API, RapidAPI et TennisExplorer.
- **Analyse des Value Bets** : Compare les probabilités générées par notre algorithme (surface, face-à-face, fatigue, dynamique récente) avec les cotes réelles du marché pour détecter les anomalies mathématiques.
- **Modèle Machine Learning dédié** : Modèles séparés et distincts pour les circuits ATP (Hommes) et WTA (Femmes) pour plus de précision.
- **Applications GUI (Tkinter / CustomTkinter)** :
  - `0_gui_app.py` : Application principale pour analyser un match spécifique.
  - `1_gui_app_bulletin.py` : Génère un bulletin global des meilleurs paris du jour et l'envoie par email.
  - `2_gui_app_daily_all.py` : Scanne automatiquement tous les matchs du jour ou du lendemain et affiche les Value Bets détectés de façon dynamique.
- **Système de Cache Intelligent** : Minimise les requêtes API coûteuses en stockant les données récentes en local.

## 🛠 Prérequis et Installation

1. **Cloner le dépôt** :
   ```bash
   git clone https://github.com/VOTRE_PSEUDO/tennis-prediction.git
   cd tennis-prediction
   ```

2. **Installer les dépendances** :
   Ce projet utilise plusieurs bibliothèques Python (Pandas, Scikit-Learn, BeautifulSoup, CustomTkinter, etc.).
   *(Il est recommandé d'utiliser un environnement virtuel)*
   ```bash
   pip install pandas scikit-learn requests beautifulsoup4 customtkinter
   ```

3. **Configurer les Clés API (Environnement)** :
   Le projet utilise des variables d'environnement pour sécuriser les clés API :
   - `RAPIDAPI_TENNIS_KEY` : Votre clé pour l'API Tennis de RapidAPI.
   - `ODDS_API_KEY_1`, `ODDS_API_KEY_2`, etc. : Vos clés pour The Odds API.
   
   *Sur Windows (PowerShell) :*
   ```powershell
   $env:RAPIDAPI_TENNIS_KEY="votre_cle_ici"
   $env:ODDS_API_KEY_1="votre_cle_ici"
   ```

## 🖥 Utilisation

Lancer l'application d'analyse globale de la journée (recommandé) :
```bash
python 2_gui_app_daily_all.py
```

Lancer l'interface détaillée de prédiction pour un seul match :
```bash
python 0_gui_app.py
```

## ⚖️ Licence

Consultez le fichier `LICENSE` pour plus de détails. Ce projet est soumis à une licence stricte limitant son usage à un cadre personnel et non-commercial.
