"""Ajoute (ou retire) le serveur MCP SIMATIC dans la configuration de Claude Desktop.

À lancer avec le Python 32 bits qui exécutera le serveur :
    py -3.12-32 installer_claude_desktop.py              # installe
    py -3.12-32 installer_claude_desktop.py --afficher   # montre le résultat sans rien écrire
    py -3.12-32 installer_claude_desktop.py --desinstaller

La configuration existante est sauvegardée (fichier .bak-date) avant toute modification,
et seules les clés de l'entrée "simatic" sont touchées.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def default_config_path():
    appdata = os.environ.get("APPDATA", "")
    candidates = [os.path.join(appdata, "Claude", "claude_desktop_config.json")] if appdata else []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:  # version Microsoft Store (MSIX)
        candidates += glob.glob(os.path.join(local, "Packages", "Claude*", "LocalCache", "Roaming",
                                             "Claude", "claude_desktop_config.json"))
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0] if candidates else None


def load_config(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        text = f.read().strip()
    return json.loads(text) if text else {}


def build_entry(python, log=False, write_projects=None):
    entry = {"command": python, "args": [os.path.join(HERE, "server.py")]}
    env = {}
    if log:
        env["SIMATIC_MCP_LOG"] = os.path.join(HERE, "journal_mcp.log")
    if write_projects:
        env["SIMATIC_PROJETS_ECRITURE"] = write_projects
    if env:
        entry["env"] = env
    return entry


def check_environment(force=False):
    problems = []
    if os.name != "nt":
        problems.append("ce script est prévu pour Windows")
    if struct.calcsize("P") * 8 != 32:
        problems.append("ce Python est en 64 bits : lance le script avec le Python 32 bits (py -3.12-32)")
    try:
        import pythoncom  # noqa: F401
    except ImportError:
        problems.append("pywin32 manque : py -3.12-32 -m pip install pywin32")
    if problems and not force:
        raise SystemExit("Installation arrêtée :\n- " + "\n- ".join(problems)
                         + "\n(--forcer pour passer outre)")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="Chemin de claude_desktop_config.json (défaut : détecté).")
    parser.add_argument("--nom", default="simatic", help="Nom du serveur dans Claude Desktop.")
    parser.add_argument("--journal", action="store_true", help="Active le journal des appels (journal_mcp.log).")
    parser.add_argument("--projets-ecriture", help="Projets autorisés pour generer_source (chemins séparés par ';').")
    parser.add_argument("--afficher", action="store_true", help="Affiche la configuration obtenue sans l'écrire.")
    parser.add_argument("--desinstaller", action="store_true", help="Retire le serveur de la configuration.")
    parser.add_argument("--forcer", action="store_true", help="Ignore les vérifications (Windows, 32 bits, pywin32).")
    args = parser.parse_args(argv)

    if not args.desinstaller:
        for problem in check_environment(force=args.forcer):
            print(f"Attention : {problem}")
    path = args.config or default_config_path()
    if not path:
        raise SystemExit("Configuration de Claude Desktop introuvable : précise --config.")
    config = load_config(path)
    servers = config.setdefault("mcpServers", {})
    if args.desinstaller:
        if servers.pop(args.nom, None) is None:
            print(f"Aucune entrée '{args.nom}' : rien à faire.")
            return 0
    else:
        servers[args.nom] = build_entry(sys.executable, args.journal, args.projets_ecriture)

    text = json.dumps(config, ensure_ascii=False, indent=2)
    if args.afficher:
        print(f"Configuration qui serait écrite dans {path} :\n{text}")
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        backup = f"{path}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
        print(f"Sauvegarde : {backup}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    action = "retiré de" if args.desinstaller else "ajouté à"
    print(f"Serveur '{args.nom}' {action} {path}")
    print("Ferme complètement Claude Desktop (icône près de l'horloge > Quitter) puis rouvre-le.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
