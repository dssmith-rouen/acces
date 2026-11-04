"""Serveur MCP (transport stdio) en lecture seule pour SIMATIC Manager / STEP 7 V5.x.

Aucune dépendance hors pywin32 : le protocole MCP (JSON-RPC 2.0, un message
JSON par ligne) est implémenté ici directement, pour fonctionner dans un
Python 32 bits sans paquet supplémentaire.

Lancement : <python 32 bits> server.py   (normalement lancé par Claude Desktop)
"""

import json
import os
import sys
import time
import traceback

# Le canal stdout est réservé aux messages MCP : tout print() part sur stderr.
_OUT = sys.stdout.buffer
sys.stdout = sys.stderr
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import simatic_com as s7  # noqa: E402

SERVER_INFO = {"name": "simatic-step7", "version": "0.5.0"}
SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

_PROJET = {
    "type": "string",
    "description": "Chemin du projet (LogPath, ex. C:\\...\\S7Proj\\MonMulti\\AS1) "
                   "ou nom s'il est unique.",
}
_CHEMIN = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Étapes de navigation depuis le projet : nom d'une propriété "
                   "(ex. 'Programs', 'Stations', 'Next') ou nom, numéro (à partir de 1) ou "
                   "chemin LogPath (contient '\\\\', utile si les noms sont en double) d'un "
                   "élément de collection, ou propriété à un paramètre écrite 'Collection(5)'. "
                   "Ex. ['Programs', '<programme>', 'Next', "
                   "'<conteneur>', 'Next', 'FB1'].",
}

TOOLS = [
    {
        "name": "simatic_etat",
        "description": "Vérifie l'environnement : version et architecture de Python, "
                       "pywin32, connexion COM à SIMATIC Manager, nombre de projets.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda: s7.status(),
    },
    {
        "name": "lister_projets",
        "description": "Liste les projets/bibliothèques STEP 7 connus de SIMATIC Manager "
                       "(nom, type, chemin). Les exemples et bibliothèques Siemens sont "
                       "masqués par défaut.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filtre": {"type": "string", "description": "Texte recherché dans le nom ou le chemin."},
                "inclure_exemples": {"type": "boolean", "description": "Inclure Examples et S7libs (défaut : non)."},
            },
        },
        "handler": s7.list_projects,
    },
    {
        "name": "explorer",
        "description": "Explore un objet du modèle COM STEP 7 en lecture seule : propriétés "
                       "et valeurs, membres disponibles (signatures) et, pour une "
                       "collection, la liste de ses éléments. Point de départ : le projet "
                       "(ou la racine Simatic si 'projet' est vide). Seules des propriétés "
                       "en lecture sont appelées.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "chemin": _CHEMIN,
                "max_elements": {"type": "integer", "description": "Nombre max d'éléments listés (défaut 200)."},
                "avec_signatures": {"type": "boolean", "description": "Lister les membres COM (défaut : oui)."},
            },
        },
        "handler": s7.explore,
    },
    {
        "name": "exporter",
        "description": "Exporte un objet qui possède une méthode Export (source AWL/SCL, "
                       "table des mnémoniques...) vers un fichier texte et renvoie son "
                       "contenu. N'écrit rien dans le projet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "chemin": _CHEMIN,
                "dossier_sortie": {"type": "string", "description": "Dossier où garder le fichier (défaut : dossier temporaire)."},
                "nom_fichier": {"type": "string", "description": "Nom du fichier (l'extension fixe le format des mnémoniques : .sdf, .asc, .dif, .seq)."},
                "max_caracteres": {"type": "integer", "description": "Taille max du contenu renvoyé (défaut 150000)."},
            },
            "required": ["projet", "chemin"],
        },
        "handler": s7.export,
    },
    {
        "name": "config_materielle",
        "description": "Configuration matérielle d'un projet : exporte chaque station en .cfg "
                       "(sans rien modifier) et renvoie les modules par emplacement (rack, "
                       "slot, esclave DP...) avec référence, firmware, adresses E/S et "
                       "paramètres réseau.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "station": {"type": "string", "description": "Nom de la station (défaut : toutes)."},
                "details": {"type": "boolean", "description": "Inclure tous les attributs des modules (défaut : non)."},
                "dossier_sortie": {"type": "string", "description": "Dossier où conserver les fichiers .cfg."},
            },
            "required": ["projet"],
        },
        "handler": s7.hardware,
    },
    {
        "name": "adresses_reseau",
        "description": "Tableau des adresses réseau : IP/masque/passerelle/MAC/nom d'appareil "
                       "des interfaces Ethernet, adresses PROFIBUS (maîtres et esclaves), "
                       "MPI, périphériques PROFINET. Sur un projet, ou sur tous les projets "
                       "(hors exemples et bibliothèques) filtrés par 'filtre'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "filtre": {"type": "string", "description": "Texte dans le nom/chemin des projets à inclure (ex. '\\\\MonMulti\\\\')."},
            },
        },
        "handler": s7.network,
    },
    {
        "name": "rechercher",
        "description": "Recherche un texte (repère de boucle, nom de bloc, diagramme CFC, "
                       "mnémonique...) dans les noms, noms symboliques et commentaires des "
                       "éléments de tous les programmes S7 (blocs, sources, diagrammes...).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "texte": {"type": "string", "description": "Texte recherché (insensible à la casse)."},
                "projet": _PROJET,
                "filtre_projets": {"type": "string", "description": "Si pas de projet : texte dans le nom/chemin des projets à parcourir."},
                "mot_entier": {"type": "boolean", "description": "Recherche par mot entier : 'PID' ne trouve pas 'RAPIDE' (défaut : non)."},
                "max_resultats": {"type": "integer", "description": "Défaut 200."},
            },
            "required": ["texte"],
        },
        "handler": s7.search,
    },
    {
        "name": "tracer_boucle",
        "description": "Fiche d'une boucle ou d'un équipement à partir de son repère (ex. "
                       "'12_0345_FRC' ou '12_0345') : diagrammes CFC/SFC correspondants, "
                       "mnémoniques du repère et, pour chaque entrée/sortie, le câblage "
                       "(station décentralisée, adresse PROFIBUS, emplacement, carte, voie).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "repere": {"type": "string", "description": "Repère de la boucle ou du diagramme."},
                "prefixe": {"type": "string", "description": "Préfixe commun aux mnémoniques (défaut : déduit du repère, ex. '12_0345')."},
            },
            "required": ["projet", "repere"],
        },
        "handler": s7.trace_loop,
    },
    {
        "name": "lister_elements",
        "description": "Liste les éléments d'un conteneur des programmes S7 de la CPU : "
                       "'Charts' (diagrammes CFC/SFC = boucles, avec commentaire), 'Blocks' "
                       "(FB/FC/DB/OB avec nom symbolique, famille, langage) ou 'Sources'. "
                       "Filtre texte optionnel sur le nom, le nom symbolique, le commentaire...",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "conteneur": {"type": "string", "description": "'Charts', 'Blocks' ou 'Sources' (défaut 'Charts')."},
                "programme": {"type": "string", "description": "LogPath du programme (défaut : programmes S7 de la CPU)."},
                "filtre": {"type": "string", "description": "Texte recherché (insensible à la casse)."},
                "mot_entier": {"type": "boolean", "description": "Recherche par mot entier : 'PID' ne trouve pas 'RAPIDE' (défaut : non)."},
                "genre": {"type": "string", "description": "Ne garder qu'un genre : FB, FC, DB, OB, 'Diagramme CFC', 'Diagramme SFC'..."},
                "max_resultats": {"type": "integer", "description": "Défaut 500."},
            },
            "required": ["projet"],
        },
        "handler": s7.list_items,
    },
    {
        "name": "mnemoniques",
        "description": "Table des mnémoniques du programme CPU (symbole, adresse, type, "
                       "commentaire), avec filtre texte. Permet de relier une adresse E/S "
                       "(ex. 'PEW 1024') à son repère et inversement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "programme": {"type": "string", "description": "LogPath du programme (défaut : programmes S7 de la CPU)."},
                "filtre": {"type": "string", "description": "Texte recherché dans le symbole, l'adresse ou le commentaire."},
                "mot_entier": {"type": "boolean", "description": "Recherche par mot entier : 'PID' ne trouve pas 'RAPIDE' (défaut : non)."},
                "max_resultats": {"type": "integer", "description": "Défaut 500."},
            },
            "required": ["projet"],
        },
        "handler": s7.symbols,
    },
    {
        "name": "structure_dossier_projet",
        "description": "Structure du dossier d'un projet sur le disque (sous-dossiers, nombre "
                       "et taille des fichiers par extension). Lecture du système de fichiers "
                       "uniquement : sert à comprendre comment les données (CFC...) sont stockées.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "profondeur": {"type": "integer", "description": "Profondeur des dossiers listés (défaut 2)."},
                "min_ko": {"type": "integer", "description": "Ne lister que les dossiers d'au moins cette taille (Ko)."},
            },
            "required": ["projet"],
        },
        "handler": s7.project_files,
    },
    {
        "name": "structure_programme",
        "description": "Exporte la structure d'appel du programme CPU (quel OB appelle quels "
                       "FC/FB avec quels DB d'instance) dans un fichier texte et renvoie son "
                       "contenu. Lecture seule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "programme": {"type": "string", "description": "LogPath du programme (défaut : programme CPU)."},
                "colonnes": {"type": "integer", "description": "Masque des colonnes (défaut : toutes)."},
                "appels_multiples": {"type": "boolean", "description": "Répéter les appels multiples (défaut : non)."},
                "max_caracteres": {"type": "integer", "description": "Défaut 150000."},
            },
            "required": ["projet"],
        },
        "handler": s7.program_structure,
    },
    {
        "name": "generer_source",
        "description": "EXPÉRIMENTAL. Génère la source AWL d'un bloc (ou d'un conteneur) pour en "
                       "lire le code. Peut créer un objet source dans le projet (supprimé ensuite "
                       "si nettoyer=true) : autorisé uniquement sur les projets listés dans la "
                       "variable d'environnement SIMATIC_PROJETS_ECRITURE.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projet": _PROJET,
                "chemin": _CHEMIN,
                "flags": {"type": "integer", "description": "Options GenerateSource (défaut 0)."},
                "nettoyer": {"type": "boolean", "description": "Supprimer les sources créées dans le projet (défaut : oui)."},
                "max_caracteres": {"type": "integer", "description": "Défaut 150000."},
            },
            "required": ["projet", "chemin"],
        },
        "handler": s7.generate_source,
    },
    {
        "name": "decrire_interface_com",
        "description": "Décrit la bibliothèque de types d'un composant COM à partir de son "
                       "ProgID (interfaces, méthodes, énumérations), sans créer d'objet. "
                       "Sert à découvrir les API (CFC, SFC, HW Config, NetPro...).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "progid": {"type": "string", "description": "Ex. 'Simatic.Simatic', 'CfcEditor', 'Sfc.Document'."},
                "filtre": {"type": "string", "description": "Ne garder que les types dont le nom contient ce texte."},
            },
            "required": ["progid"],
        },
        "handler": s7.describe_typelib,
    },
]
_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def _log(*args):
    print("[simatic-mcp]", *args, file=sys.stderr, flush=True)


def _send(message):
    _OUT.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    _OUT.flush()


def _result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


# Codes COM indiquant que SIMATIC (ou son serveur RPC) a été fermé : on recrée l'objet racine.
_RECONNECT_HRESULTS = {0x800706BA, 0x800706BE, 0x80010108, 0x80010012}
_LOG_PATH = os.environ.get("SIMATIC_MCP_LOG")


def _journal(line):
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def _hresult(exc):
    try:
        return exc.args[0] & 0xFFFFFFFF
    except Exception:
        return None


def _call_tool(params):
    name = params.get("name")
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return None
    allowed = tool["inputSchema"].get("properties", {})
    args = {k: v for k, v in (params.get("arguments") or {}).items() if k in allowed}
    missing = [k for k in tool["inputSchema"].get("required", []) if k not in args]
    started = time.time()
    if missing:
        text, is_error = f"Paramètre(s) obligatoire(s) manquant(s) : {', '.join(missing)}", True
    else:
        for attempt in (1, 2):
            try:
                data = tool["handler"](**args)
                text, is_error = json.dumps(data, ensure_ascii=False, indent=2, default=str), False
                break
            except s7.SimaticError as exc:
                text, is_error = str(exc), True
                break
            except Exception as exc:  # erreur COM ou inattendue
                if attempt == 1 and _hresult(exc) in _RECONNECT_HRESULTS:
                    _log("connexion COM perdue, nouvelle tentative")
                    s7.reset()
                    continue
                _log(traceback.format_exc())
                text, is_error = f"{type(exc).__name__} : {s7.com_message(exc)}", True
                break
    _journal(f"{name} {json.dumps(args, ensure_ascii=False)} -> "
             f"{'ERREUR' if is_error else 'ok'} ({time.time() - started:.1f} s)"
             + (f" {text[:300]}" if is_error else ""))
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# --------------------------------------------------------------------------
# Modèles de demande (prompts MCP) proposés dans Claude Desktop
# --------------------------------------------------------------------------

PROMPTS = [
    {
        "name": "analyser_boucle",
        "description": "Fiche complète d'une boucle : rôle, instrumentation, câblage, points d'attention.",
        "arguments": [
            {"name": "repere", "description": "Repère de la boucle (ex. 12_0345_FRC)", "required": True},
            {"name": "projet", "description": "Chemin ou nom du projet (facultatif)", "required": False},
        ],
        "template": (
            "Analyse la boucle {repere}{projet_txt} avec les outils SIMATIC. "
            "1) Si le projet n'est pas précisé, trouve-le avec lister_projets puis rechercher. "
            "2) Utilise tracer_boucle pour obtenir le diagramme, les mnémoniques et le câblage. "
            "3) Explique en français le rôle probable de la boucle (mesure, régulation, actionneur), "
            "en distinguant ce qui est lu dans le projet de ce que tu déduis des noms. "
            "4) Présente un tableau du câblage (signal, adresse, station décentralisée, carte, voie). "
            "5) Termine par les points à vérifier sur site ou dans le diagramme CFC."
        ),
    },
    {
        "name": "inventaire_reseau",
        "description": "Plan d'adressage IP / PROFIBUS / MPI d'un projet ou d'un multiprojet.",
        "arguments": [
            {"name": "filtre", "description": "Partie du chemin des projets (facultatif)", "required": False},
        ],
        "template": (
            "Dresse le plan d'adressage réseau avec l'outil adresses_reseau{filtre_txt}. "
            "Présente un tableau des interfaces Ethernet (projet, station, module, IP, masque, "
            "passerelle, nom d'appareil), puis un résumé PROFIBUS par station (maîtres, nombre "
            "d'esclaves, plages d'adresses). Signale les doublons d'IP, les sous-réseaux différents "
            "et les passerelles incohérentes."
        ),
    },
    {
        "name": "fiche_station",
        "description": "Description matérielle d'une station : châssis, CPU, cartes, périphérie décentralisée.",
        "arguments": [
            {"name": "projet", "description": "Chemin ou nom du projet", "required": True},
        ],
        "template": (
            "Avec l'outil config_materielle sur le projet {projet}, décris la station : châssis et "
            "alimentation, CPU (référence, firmware), cartes de communication et leurs adresses, "
            "puis la périphérie décentralisée regroupée par station esclave (adresse PROFIBUS, "
            "cartes, plages d'E/S). Termine par un décompte des cartes par référence."
        ),
    },
]
_PROMPTS_BY_NAME = {p["name"]: p for p in PROMPTS}


def _get_prompt(params):
    prompt = _PROMPTS_BY_NAME.get(params.get("name"))
    if prompt is None:
        return None
    args = params.get("arguments") or {}
    values = {
        "repere": args.get("repere", ""),
        "projet": args.get("projet", ""),
        "projet_txt": f" du projet {args['projet']}" if args.get("projet") else "",
        "filtre_txt": f" (filtre '{args['filtre']}')" if args.get("filtre") else "",
    }
    return {
        "description": prompt["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": prompt["template"].format(**values)}}],
    }


def handle(msg):
    if not isinstance(msg, dict):
        return _error(None, -32600, "Requête invalide")
    method, id_ = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return _result(id_, {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": SERVER_INFO,
            "instructions": "Accès en lecture seule, hors ligne, aux projets STEP 7 V5 / PCS 7 "
                            "(SIMATIC Manager). Désigner les projets par leur chemin (lister_projets). "
                            "Pour une boucle : tracer_boucle ; pour le réseau : adresses_reseau ; "
                            "pour le matériel : config_materielle ; sinon rechercher / explorer.",
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": [
            {k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS
        ]})
    if method == "tools/call":
        res = _call_tool(params)
        if res is None:
            return _error(id_, -32602, f"Outil inconnu : {params.get('name')}")
        return _result(id_, res)
    if method == "prompts/list":
        return _result(id_, {"prompts": [
            {"name": p["name"], "description": p["description"], "arguments": p["arguments"]} for p in PROMPTS
        ]})
    if method == "prompts/get":
        res = _get_prompt(params)
        if res is None:
            return _error(id_, -32602, f"Modèle inconnu : {params.get('name')}")
        return _result(id_, res)
    if id_ is None:
        return None  # notification (ex. notifications/initialized) : pas de réponse
    return _error(id_, -32601, f"Méthode non prise en charge : {method}")


def main():
    _log(f"démarrage ({s7.BITS} bits, Python {sys.version.split()[0]})")
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            break
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception as exc:
            _send(_error(None, -32700, f"JSON invalide : {exc}"))
            continue
        if isinstance(msg, list):
            responses = [r for r in (handle(m) for m in msg) if r is not None]
            if responses:
                _send(responses)
        else:
            response = handle(msg)
            if response is not None:
                _send(response)
    _log("arrêt")


if __name__ == "__main__":
    main()
