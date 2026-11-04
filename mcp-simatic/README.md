# MCP SIMATIC Manager (STEP 7 V5.x / PCS 7)

Serveur MCP qui permet à Claude de lire les projets STEP 7 V5 via l'interface COM
officielle de SIMATIC Manager (`Simatic.Simatic`).

**Version 0.2 : lecture seule, hors ligne.** Le serveur lit uniquement les fichiers
projet. Il ne communique pas avec les automates et ne modifie rien : pas de
compilation, pas de chargement, pas d'import. Seule la méthode `Export` est
autorisée, et elle écrit un fichier texte en dehors du projet. Les propriétés COM
qui interrogent l'automate en ligne (`ModuleState`, `HSystemState`, `OnlineBlocks`…)
sont bloquées.

## Prérequis

- Windows + SIMATIC Manager (testé avec STEP 7 V5.6 SP2 HF8 / PCS 7 V9.1 SP1).
- **Python 32 bits** obligatoire : `S7ABATCX.DLL` (le COM de STEP 7) est une DLL 32 bits.
  Un Python 64 bits renvoie l'erreur `0x80040154 Classe non enregistrée`.
- `pywin32` installé dans ce Python 32 bits. Aucune autre dépendance n'est nécessaire.

## Installation

1. Télécharge **« Windows installer (32-bit) »** de Python 3.12.10 sur
   <https://www.python.org/downloads/release/python-31210/>.
   - Choisis « Install Now », pour l'utilisateur courant (pas besoin de droits administrateur).
   - **Ne coche pas** « Add python.exe to PATH », pour ne pas masquer ton Python 64 bits.
2. Vérifie l'installation :
   ```powershell
   py -0p
   ```
   Une ligne `-V:3.12-32` doit apparaître.
3. Installe pywin32 :
   ```powershell
   py -3.12-32 -m pip install pywin32
   ```
4. Récupère le code :
   ```powershell
   git clone -b claude/modest-edison-mao9an https://github.com/dssmith-rouen/acces.git "C:\Claude cloud test\acces"
   ```

## Test sans Claude

```powershell
cd "C:\Claude cloud test\acces\mcp-simatic"
py -3.12-32 test_local.py --projet "C:\Program Files (x86)\SIEMENS\STEP7\S7Proj\Pr948v09\Uc1"
```

Le script écrit deux fichiers dans ce dossier :
- `rapport_test.txt` : état, structure du programme CPU (conteneurs, premiers
  éléments), configuration matérielle, recherche, adresses réseau ;
- `rapport_interfaces_com.txt` : description des API COM disponibles (STEP 7, CFC,
  SFC, HW Config, NetPro, assistant d'import/export…).

## Ajout dans Claude Desktop

Ajoute le bloc `mcpServers` de `claude_desktop_config.exemple.json` dans
`%APPDATA%\Claude\claude_desktop_config.json`. **Fusionne-le** avec le contenu
existant au lieu d'écraser le fichier, puis redémarre complètement Claude Desktop.
Le chemin de `python.exe` est celui affiché par `py -0p` pour la version `3.12-32`.

## Outils exposés

| Outil | Rôle |
|---|---|
| `simatic_etat` | Python (32/64 bits), pywin32, connexion COM, nombre de projets |
| `lister_projets` | Projets avec nom, type et chemin. Exemples et `S7libs` masqués par défaut |
| `explorer` | Navigation générique dans le modèle COM : propriétés, membres, éléments d'une collection |
| `exporter` | Appelle `Export` sur un objet (source, mnémoniques, station...) et renvoie le texte |
| `config_materielle` | Modules par emplacement : référence, firmware, adresses E/S, paramètres réseau (via export `.cfg`) |
| `adresses_reseau` | Tableau IP / masque / passerelle / MAC / nom d'appareil, PROFIBUS, MPI, PROFINET |
| `rechercher` | Recherche un texte dans les noms, noms symboliques et commentaires des blocs, sources et diagrammes |
| `decrire_interface_com` | Décrit l'API d'un composant COM (ProgID) sans créer d'objet |

Un projet se désigne par son **chemin** (LogPath), car des noms comme `UC1` existent
en double. La navigation est une liste d'étapes, par exemple :
`["Programs", "<programme>", "Next", "<conteneur>", "Next", "FB1"]`.

## Feuille de route

- [x] Modèle COM validé : projets, stations, programmes (désignés par LogPath).
- [x] Configuration matérielle : export `.cfg` des stations et analyse des modules.
- [x] Adressage réseau : IP, masque, passerelle, MAC, PROFIBUS, MPI.
- [ ] Recherche transverse : à valider sur les vrais conteneurs (blocs, diagrammes CFC).
- [ ] Interprétation fine des lignes `ADDRESS` (début/longueur des E/S).
- [ ] Boucles CFC/SFC : lire le contenu des diagrammes (blocs, paramètres, connexions).
      Le COM `Simatic.Simatic` ne le permet pas. Une autre voie est à trouver
      (interface CFC, export XML, objets de process...).
