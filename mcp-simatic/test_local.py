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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--projet", help="Chemin du projet à explorer (LogPath).")
    parser.add_argument("--sortie", default=os.path.join(HERE, "rapport_test.txt"))
    parser.add_argument("--sans-export-hw", action="store_true",
                        help="Ne pas tenter l'export de la configuration matérielle.")
    args = parser.parse_args()

    out = open(args.sortie, "w", encoding="utf-8")

    def section(title, payload):
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        out.write(f"\n===== {title} =====\n{text}\n")
        out.flush()
        print(f"- {title}")

    client = Client()
    try:
        init = client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test_local", "version": "0"},
        })
        client.notify("notifications/initialized")
        section("initialize", init)
        tools = client.request("tools/list")
        section("outils", [t["name"] for t in tools["result"]["tools"]])
        section("simatic_etat", client.tool("simatic_etat")[1])
        section("lister_projets", client.tool("lister_projets")[1])
        section("ProgID COM CFC/SFC/XML/PH (32 bits)", "\n".join(scan_com_registry()))

        if args.projet:
            p = args.projet
            section("explorer racine Simatic", client.tool("explorer", chemin=[], max_elements=0)[1])
            section("explorer projet", client.tool("explorer", projet=p, chemin=[])[1])

            # --- Matériel ---
            err, stations = client.tool("explorer", projet=p, chemin=["Stations"])
            section("explorer Stations", stations)
            if not err and stations.get("elements"):
                st = stations["elements"][0].get("Name", "1")
                section(f"explorer station {st}", client.tool("explorer", projet=p, chemin=["Stations", st])[1])
                if not args.sans_export_hw:
                    err_hw, hw = client.tool("exporter", projet=p, chemin=["Stations", st],
                                             nom_fichier="station.cfg", max_caracteres=20000)
                    section(f"export HW station {st} (20000 premiers caractères)", hw)

            # --- Programmes S7 ---
            err, progs = client.tool("explorer", projet=p, chemin=["Programs"])
            section("explorer Programs", progs)
            if not err and progs.get("elements"):
                prog = progs["elements"][0].get("Name", "1")
                base = ["Programs", prog]
                section(f"explorer programme {prog}", client.tool("explorer", projet=p, chemin=base)[1])
                err, conts = client.tool("explorer", projet=p, chemin=base + ["Next"])
                section("explorer conteneurs du programme (Next)", conts)
                if not err:
                    for c in conts.get("elements", [])[:8]:
                        cname = c.get("Name")
                        if not cname:
                            continue
                        err, items = client.tool("explorer", projet=p, chemin=base + ["Next", cname, "Next"],
                                                 max_elements=15)
                        section(f"conteneur '{cname}' -> Next (15 premiers)", items)
                        if not err and items.get("elements"):
                            first = items["elements"][0].get("Name", "1")
                            section(f"premier élément de '{cname}' : {first}",
                                    client.tool("explorer", projet=p,
                                                chemin=base + ["Next", cname, "Next", first])[1])
    except Exception as exc:
        section("ERREUR DU TEST", f"{type(exc).__name__} : {exc}")
    finally:
        client.close()
        section("stderr du serveur (fin)", "\n".join(client.stderr[-40:]))
        out.close()
    print(f"\nRapport écrit dans : {args.sortie}")


if __name__ == "__main__":
    main()
