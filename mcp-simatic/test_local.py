"""Test local du serveur MCP SIMATIC, sans Claude Desktop.

Lance server.py avec le même Python, dialogue avec lui comme le ferait Claude,
explore un projet et écrit un rapport texte à renvoyer.

Usage (Python 32 bits) :
    py -3.12-32 test_local.py --projet "C:\\...\\S7Proj\\Pr948v09\\Uc1"
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 300  # secondes par requête


class Client:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self.next_id = 0
        self.stderr = []

    def _pump(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def _drain_stderr(self):
        for raw in self.proc.stderr:
            self.stderr.append(raw.decode("utf-8", "replace").rstrip())

    def request(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg).encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        raw = self.lines.get(timeout=TIMEOUT)
        if raw is None:
            raise RuntimeError("Le serveur s'est arrêté.\n" + "\n".join(self.stderr[-20:]))
        return json.loads(raw.decode("utf-8"))

    def notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}).encode() + b"\n")
        self.proc.stdin.flush()

    def tool(self, name, **arguments):
        resp = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in resp:
            return True, resp["error"]["message"]
        res = resp["result"]
        text = res["content"][0]["text"]
        if res.get("isError"):
            return True, text
        try:
            return False, json.loads(text)
        except ValueError:
            return False, text

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def scan_com_registry():
    """ProgID COM utiles pour CFC/SFC, hiérarchie technologique, exports XML..."""
    try:
        import winreg
    except ImportError:
        return ["(winreg indisponible hors Windows)"]
    pattern = re.compile(r"cfc|sfc|iea|xml|pcs ?7|plant|chart|s7ph|esapi|hwcnf|netpro|s7wb", re.I)
    found = []
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as root:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            if not name.startswith(".") and pattern.search(name):
                try:
                    with winreg.OpenKey(root, name + "\\CLSID"):
                        found.append(name)
                except OSError:
                    pass
    return found


def _extrait_hw(result):
    err, data = result
    if err or not data:
        return data
    mods = [m for m in data[0]["modules"] if m.get("adresses_es")][:15]
    return {"station": data[0]["station"], "nb_modules": len(data[0]["modules"]), "exemples_modules_es": mods}


PROGIDS_A_DECRIRE = (
    "Simatic.Simatic", "CfcEditor", "CFC-Plan", "Sfc.Document", "SfcEditor", "CSfcServer",
    "S7jieaEx.Document", "S7JWZAPX.PCS7Wizard", "IS7hwcnfxAutomation", "S7hwcnfx.Document",
    "NetproAutomation",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--projet", help="Chemin du projet à explorer (LogPath).")
    parser.add_argument("--filtre-multiprojet", default="\\Pr948v09\\",
                        help="Filtre des projets pour adresses_reseau.")
    parser.add_argument("--recherche", default="PID", help="Texte pour l'outil rechercher.")
    parser.add_argument("--complet", action="store_true",
                        help="Ajoute la config matérielle complète, le réseau du multiprojet et les API COM.")
    parser.add_argument("--sortie", default=os.path.join(HERE, "rapport_test.txt"))
    parser.add_argument("--sortie-com", default=os.path.join(HERE, "rapport_interfaces_com.txt"))
    args = parser.parse_args()

    out = open(args.sortie, "w", encoding="utf-8")

    def section(title, payload, fichier=None):
        f = fichier or out
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        f.write(f"\n===== {title} =====\n{text}\n")
        f.flush()
        print(f"- {title}")

    client = Client()
    try:
        init = client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test_local", "version": "0"},
        })
        client.notify("notifications/initialized")
        section("initialize", init["result"]["serverInfo"])
        tools = client.request("tools/list")
        section("outils", [t["name"] for t in tools["result"]["tools"]])
        section("simatic_etat", client.tool("simatic_etat")[1])

        if args.projet:
            p = args.projet
            # --- Programme S7 de la CPU (pas ceux des esclaves DP) ---
            err, progs = client.tool("explorer", projet=p, chemin=["Programs"], avec_signatures=False)
            if err:
                section("explorer Programs", progs)
            else:
                cpu_progs = [e for e in progs.get("elements", []) if e.get("Type") == 1327361] \
                    or progs.get("elements", [])[-1:]
                section("programmes CPU retenus", cpu_progs)
                for prog in cpu_progs[:2]:
                    base = ["Programs", prog.get("LogPath") or prog.get("Name")]
                    section(f"programme {prog.get('Name')}", client.tool("explorer", projet=p, chemin=base)[1])
                    err, conts = client.tool("explorer", projet=p, chemin=base + ["Next"])
                    section(f"conteneurs de {prog.get('Name')}", conts)
                    if err:
                        continue
                    for c in conts.get("elements", [])[:8]:
                        cname = c.get("Name")
                        if not cname:
                            continue
                        section(f"conteneur '{cname}' (objet)",
                                client.tool("explorer", projet=p, chemin=base + ["Next", cname])[1])
                        err, items = client.tool("explorer", projet=p, chemin=base + ["Next", cname, "Next"],
                                                 max_elements=25, avec_signatures=False)
                        section(f"conteneur '{cname}' -> éléments (25 premiers)", items)
                        if not err and items.get("elements"):
                            first = items["elements"][0].get("Name", "1")
                            section(f"premier élément de '{cname}' : {first}",
                                    client.tool("explorer", projet=p,
                                                chemin=base + ["Next", cname, "Next", first])[1])

            if args.complet:
                err, hw = client.tool("config_materielle", projet=p)
                section("config_materielle", hw)

            # --- Boucles, blocs, mnémoniques ---
            section("lister_elements Charts (tous les diagrammes)",
                    client.tool("lister_elements", projet=p, conteneur="Charts", max_resultats=1000)[1])
            section(f"lister_elements Blocks filtre '{args.recherche}'",
                    client.tool("lister_elements", projet=p, conteneur="Blocks",
                                filtre=args.recherche, max_resultats=50)[1])
            err, sym = client.tool("mnemoniques", projet=p, max_resultats=60)
            section("mnemoniques (60 premiers)", sym)
            section(f"mnemoniques filtre '{args.recherche}'",
                    client.tool("mnemoniques", projet=p, filtre=args.recherche, max_resultats=60)[1])
            section("config_materielle station 1 (modules avec plages E/S, extrait)",
                    _extrait_hw(client.tool("config_materielle", projet=p)))
            section("structure_dossier_projet",
                    client.tool("structure_dossier_projet", projet=p, profondeur=2)[1])

        if args.complet:
            section(f"adresses_reseau (filtre {args.filtre_multiprojet})",
                    client.tool("adresses_reseau", filtre=args.filtre_multiprojet)[1])

        if not args.complet:
            return

        # --- API COM disponibles (fichier séparé, volumineux) ---
        with open(args.sortie_com, "w", encoding="utf-8") as fcom:
            section("ProgID COM CFC/SFC/XML/PH (32 bits)", "\n".join(scan_com_registry()), fcom)
            for progid in PROGIDS_A_DECRIRE:
                section(f"interface COM {progid}", client.tool("decrire_interface_com", progid=progid)[1], fcom)
    except Exception as exc:
        section("ERREUR DU TEST", f"{type(exc).__name__} : {exc}")
    finally:
        client.close()
        section("stderr du serveur (fin)", "\n".join(client.stderr[-40:]))
        out.close()
        print(f"\nRapport écrit dans : {args.sortie}")
        if args.complet:
            print(f"Interfaces COM : {args.sortie_com}")


if __name__ == "__main__":
    main()
