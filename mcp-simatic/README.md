# MCP SIMATIC Manager (STEP 7 V5.x / PCS 7)

Serveur MCP qui permet à Claude (Claude Desktop) de lire les projets STEP 7 V5 et
PCS 7 via l'interface COM officielle de SIMATIC Manager (`Simatic.Simatic`) :
projets, diagrammes CFC/SFC, blocs, mnémoniques, configuration matérielle,
adressage réseau et câblage des boucles.

## Sécurité : lecture seule, hors ligne

- Le serveur lit les **fichiers projet** uniquement. Il ne communique jamais avec un
  automate : les propriétés COM qui interrogent la CPU en ligne (`ModuleState`,
  `HSystemState`, `OnlineBlocks`…) sont bloquées.
- Aucune méthode de modification n'est appelée (pas de compilation, chargement,
  import, suppression). Les exports (`Export`, `ExportProgramStructure`) écrivent des
  fichiers texte **en dehors** du projet, dans le dossier temporaire.
- Seule exception : l'outil expérimental `generer_source`, refusé par défaut (voir
  plus bas).

## Prérequis

- Windows avec SIMATIC Manager (développé sur STEP 7 V5.6 SP2 / PCS 7 V9.1 SP1).
- **Python 32 bits** : le COM de STEP 7 (`S7ABATCX.DLL`) est une DLL 32 bits. Un
  Python 64 bits renvoie `0x80040154 Classe non enregistrée`.
- `pywin32` dans ce Python 32 bits. Aucune autre dépendance n'est nécessaire.

## Installation

1. Python 3.12 **32 bits**, à côté du Python existant, pour l'utilisateur courant,
   **sans** l'ajouter au PATH :
   ```powershell
   [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/3.12.10/python-3.12.10.exe" -OutFile "$env:TEMP\python-3.12.10-32.exe"
   Start-Process "$env:TEMP\python-3.12.10-32.exe" -ArgumentList "/passive InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0" -Wait
   py -0p          # une ligne -V:3.12-32 doit apparaître
   ```
2. pywin32 :
   ```powershell
   py -3.12-32 -m pip install pywin32
   ```
3. Le code :
   ```powershell
   git clone -b claude/modest-edison-mao9an https://github.com/dssmith-rouen/acces.git "C:\Claude cloud test\acces"
   ```

## Vérification sans Claude

```powershell
cd "C:\Claude cloud test\acces\mcp-simatic"
py -3.12-32 test_local.py --projet "<chemin d'un projet>" --repere "<repère d'une boucle>"
```

Le chemin d'un projet est sa colonne « LogPath », par exemple
`C:\Program Files (x86)\SIEMENS\STEP7\S7Proj\MonMulti\AS1`. Le script écrit
`rapport_test.txt` dans ce dossier. Avec `--complet`, il ajoute la configuration
matérielle complète, les adresses réseau du multiprojet et
`rapport_interfaces_com.txt`.

## Ajout dans Claude Desktop

```powershell
py -3.12-32 installer_claude_desktop.py --afficher   # aperçu, n'écrit rien
py -3.12-32 installer_claude_desktop.py              # installe (avec sauvegarde)
```

Le script sauvegarde `claude_desktop_config.json` (fichier `.bak-date`), ajoute
l'entrée `simatic` sans toucher au reste, puis demande de redémarrer Claude Desktop
complètement (icône près de l'horloge, puis Quitter). Options :
- `--journal` : journal des appels dans `journal_mcp.log`, utile au dépannage ;
- `--desinstaller` : retire l'entrée.

Installation manuelle : voir `claude_desktop_config.exemple.json`.

## Utilisation dans Claude Desktop

Exemples de demandes :
- « Liste les projets STEP 7 du multiprojet MonMulti. »
- « Trace la boucle 12_0345_FRC du projet AS1 : diagramme, mesures, vannes, câblage. »
- « Fais le plan d'adressage IP de tous les automates et signale les incohérences. »
- « Quelles cartes d'entrées analogiques y a-t-il sur la station AS1, et sur quels esclaves PROFIBUS ? »
- « Quels diagrammes CFC parlent de la cuve T1 ? »
- « À quoi correspond l'adresse PEW 514 ? »

Le bouton « + » de Claude Desktop propose aussi trois **modèles de demande** :
`analyser_boucle`, `inventaire_reseau` et `fiche_station`.

## Outils

| Outil | Rôle |
|---|---|
| `simatic_etat` | Python (32/64 bits), pywin32, connexion COM, nombre de projets |
| `lister_projets` | Projets avec nom, type et chemin. Exemples et `S7libs` masqués par défaut |
| `tracer_boucle` | Repère → diagrammes, mnémoniques et câblage de chaque E/S (station décentralisée, PROFIBUS, carte, voie) |
| `localiser_adresse` | Adresse (`PEW 512`, `E 12.3`, `PIW 512`…) → mnémoniques, carte, voie, station décentralisée |
| `lister_elements` | Diagrammes CFC/SFC, blocs ou sources d'un programme, filtre texte ou par genre (FB, DB…) |
| `mnemoniques` | Table des mnémoniques (symbole, adresse, type, commentaire) avec filtre |
| `rechercher` | Recherche dans les noms, symboles et commentaires de tous les programmes |
| `config_materielle` | Modules par emplacement : référence, firmware, plages E/S, paramètres réseau (export `.cfg`) |
| `adresses_reseau` | IP / masque / passerelle / MAC / nom d'appareil, PROFIBUS, MPI, PROFINET, avec alertes (IP en double, passerelle hors sous-réseau, PROFIBUS en double) |
| `structure_programme` | Structure d'appel du programme (OB → FC/FB → DB d'instance). Peut être long |
| `explorer` | Navigation générique dans le modèle COM : propriétés, membres, éléments |
| `exporter` | Appelle `Export` sur un objet (source, mnémoniques, station…) et renvoie le texte |
| `structure_dossier_projet` | Dossiers et types de fichiers du projet sur le disque |
| `decrire_interface_com` | Décrit l'API d'un composant COM (ProgID) sans créer d'objet |
| `generer_source` | EXPÉRIMENTAL : source AWL d'un bloc, sur les projets autorisés uniquement |

Les recherches acceptent `mot_entier` : « PID » trouve « SORTIE PID » mais pas
« RAPIDE ».

### Désignation des projets et navigation

Un projet se désigne par son **chemin** (LogPath), car un même nom peut exister dans
plusieurs copies d'un multiprojet. `explorer` prend une liste d'étapes : nom d'une
propriété (`Programs`, `Stations`, `Next`), nom, numéro ou chemin d'un élément, ou
propriété à un paramètre (`Collection(5)`). Exemple :
`["Programs", "<LogPath du programme>", "Next", "Charts", "Next", "<diagramme>"]`.

## Variables d'environnement

| Variable | Effet |
|---|---|
| `SIMATIC_MCP_LOG` | Fichier où journaliser chaque appel (outil, durée, erreur) |
| `SIMATIC_PROJETS_ECRITURE` | Projets (chemins séparés par `;`) où `generer_source` est autorisé |

### Outil expérimental `generer_source`

`GenerateSource` peut créer un objet source dans le projet. Le serveur le refuse
sauf sur les projets listés dans `SIMATIC_PROJETS_ECRITURE`, idéalement une **copie**.
Les sources créées sont détectées et supprimées ensuite (`nettoyer=true`).
Constaté : la génération fonctionne pour les DB (valeurs des paramètres d'instance)
mais échoue pour les blocs compilés en SCL, dont les FC générés par le CFC.

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `0x80040154 Classe non enregistrée` | Serveur lancé avec un Python 64 bits |
| `pywin32 n'est pas disponible` | `py -3.12-32 -m pip install pywin32` |
| Un appel ne répond plus | Boîte de dialogue SIMATIC en attente (regarder la barre des tâches), ou export très long (`structure_programme`) |
| Claude ne voit pas les outils | Redémarrer complètement Claude Desktop ; vérifier `claude_desktop_config.json` ; tester `test_local.py` |
| Erreur après fermeture de SIMATIC Manager | Le serveur se reconnecte automatiquement une fois ; sinon relancer Claude Desktop |

## Développement

```powershell
python -m unittest discover -s tests      # 53 tests, sans Windows ni STEP 7
```

| Fichier | Contenu |
|---|---|
| `server.py` | Protocole MCP (JSON-RPC sur stdio), outils, prompts |
| `simatic_com.py` | Accès COM en lecture seule, caches, exports |
| `hw_config.py` | Analyse des exports matériels `.cfg` |
| `formats_s7.py` | Mnémoniques `.sdf`, adresses STEP 7 |
| `analyse.py` | Recherche par mot, localisation d'E/S, synthèse de boucle |
| `installer_claude_desktop.py` | Ajout / retrait dans Claude Desktop |
| `test_local.py` | Scénarios de test sur le PC (rapport texte) |
| `tests/` | Tests sur données fictives, dont un faux SIMATIC (`fake_com.py`) |

## Limites connues et feuille de route

- [x] Projets, stations, programmes, diagrammes, blocs, mnémoniques.
- [x] Configuration matérielle, plages E/S, adresses réseau.
- [x] Traçage d'une boucle (repère → câblage).
- [ ] Adresses IP des périphériques PROFINET IO (ET 200S…).
- [ ] Contenu des diagrammes CFC (blocs, paramètres, connexions) : le COM STEP 7 ne
      l'expose pas et les blocs SCL générés ne sont pas régénérables. Pistes en cours :
      sous-collections `Collection(ID)` des diagrammes, DB d'instance.
