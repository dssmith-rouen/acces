"""Serveur MCP (transport stdio) en lecture seule pour SIMATIC Manager / STEP 7 V5.x.

Aucune dépendance hors pywin32 : le protocole MCP (JSON-RPC 2.0, un message
JSON par ligne) est implémenté ici directement, pour fonctionner dans un
Python 32 bits sans paquet supplémentaire.

Lancement : <python 32 bits> server.py   (normalement lancé par Claude Desktop)
"""

import json
import sys
import traceback

# Le canal stdout est réservé aux messages MCP : tout print() part sur stderr.
_OUT = sys.stdout.buffer
sys.stdout = sys.stderr
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import simatic_com as s7  # noqa: E402

SERVER_INFO = {"name": "simatic-step7", "version": "0.3.0"}
SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

_PROJET = {
    "type": "string",
    "description": "Chemin du projet (LogPath, ex. C:\\...\\S7Proj\\Pr948v09\\Uc1) "
                   "ou nom s'il est unique.",
}
_CHEMIN = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Étapes de navigation depuis le projet : nom d'une propriété "
                   "(ex. 'Programs', 'Stations', 'Next') ou nom, numéro (à partir de 1) ou "
                   "chemin LogPath (contient '\\\\', utile si les noms sont en double) d'un "
                   "élément de collection. Ex. ['Programs', '<programme>', 'Next', "
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
                "filtre": {"type": "string", "description": "Texte dans le nom/chemin des projets à inclure (ex. 'Pr948v09\\\\')."},
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
                "max_resultats": {"type": "integer", "description": "Défaut 200."},
            },
            "required": ["texte"],
        },
        "handler": s7.search,
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
            },
            "required": ["projet"],
        },
        "handler": s7.project_files,
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


def _call_tool(params):
    name = params.get("name")
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return None
    allowed = tool["inputSchema"].get("properties", {})
    args = {k: v for k, v in (params.get("arguments") or {}).items() if k in allowed}
    try:
        data = tool["handler"](**args)
        text, is_error = json.dumps(data, ensure_ascii=False, indent=2, default=str), False
    except s7.SimaticError as exc:
        text, is_error = str(exc), True
    except Exception as exc:  # erreur COM ou inattendue
        _log(traceback.format_exc())
        text, is_error = f"{type(exc).__name__} : {s7.com_message(exc)}", True
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


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
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": "Accès en lecture seule aux projets STEP 7 V5 (SIMATIC Manager). "
                            "Commencer par lister_projets, puis explorer avec un chemin.",
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
