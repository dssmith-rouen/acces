"""Tests du serveur MCP (protocole, prompts, gestion d'erreurs) avec un faux SIMATIC."""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

_stdout = sys.stdout
import server  # noqa: E402  (le module redirige stdout vers stderr à l'import)
sys.stdout = _stdout


def call(method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


class TestProtocole(unittest.TestCase):
    def test_initialize(self):
        res = call("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(res["protocolVersion"], "2025-06-18")
        self.assertIn("tools", res["capabilities"])
        self.assertIn("prompts", res["capabilities"])
        res = call("initialize", {"protocolVersion": "1999-01-01"})["result"]
        self.assertEqual(res["protocolVersion"], server.SUPPORTED_VERSIONS[0])

    def test_liste_des_outils(self):
        tools = call("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        for expected in ("simatic_etat", "lister_projets", "explorer", "exporter", "config_materielle",
                         "adresses_reseau", "rechercher", "tracer_boucle", "lister_elements",
                         "mnemoniques", "structure_programme", "generer_source"):
            self.assertIn(expected, names)
        for t in tools:
            props = t["inputSchema"].get("properties", {})
            for req in t["inputSchema"].get("required", []):
                self.assertIn(req, props, f"{t['name']} : '{req}' obligatoire mais non décrit")
            self.assertNotIn("handler", t)

    def test_notification_sans_reponse(self):
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_methode_et_outil_inconnus(self):
        self.assertEqual(call("foo")["error"]["code"], -32601)
        self.assertEqual(call("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertEqual(server.handle([1])["error"]["code"], -32600)


class TestAppelsOutils(unittest.TestCase):
    def setUp(self):
        self.saved = {name: tool["handler"] for name, tool in server._TOOLS_BY_NAME.items()}
        self.saved_reset = server.s7.reset

    def tearDown(self):
        for name, handler in self.saved.items():
            server._TOOLS_BY_NAME[name]["handler"] = handler
        server.s7.reset = self.saved_reset

    def tool(self, name, **arguments):
        return call("tools/call", {"name": name, "arguments": arguments})["result"]

    def test_parametre_manquant(self):
        res = self.tool("tracer_boucle", projet="X")
        self.assertTrue(res["isError"])
        self.assertIn("repere", res["content"][0]["text"])

    def test_arguments_inconnus_ignores_et_resultat_json(self):
        seen = {}

        def fake(projet, repere, prefixe=None):
            seen.update(projet=projet, repere=repere, prefixe=prefixe)
            return {"ok": True, "texte": "é"}

        server._TOOLS_BY_NAME["tracer_boucle"]["handler"] = fake
        res = self.tool("tracer_boucle", projet="P", repere="R", inconnu=1)
        self.assertFalse(res["isError"])
        self.assertEqual(json.loads(res["content"][0]["text"]), {"ok": True, "texte": "é"})
        self.assertEqual(seen, {"projet": "P", "repere": "R", "prefixe": None})

    def test_erreur_metier(self):
        def fake(**_):
            raise server.s7.SimaticError("Projet introuvable")

        server._TOOLS_BY_NAME["lister_projets"]["handler"] = fake
        res = self.tool("lister_projets")
        self.assertTrue(res["isError"])
        self.assertEqual(res["content"][0]["text"], "Projet introuvable")

    def test_reconnexion_apres_deconnexion_com(self):
        calls, resets = [], []

        class ComError(Exception):
            pass

        def fake(**_):
            calls.append(1)
            if len(calls) == 1:
                raise ComError(-2147023174, "Le serveur RPC n'est pas disponible.", None, None)  # 0x800706BA
            return ["ok"]

        server._TOOLS_BY_NAME["lister_projets"]["handler"] = fake
        server.s7.reset = lambda: resets.append(1)
        res = self.tool("lister_projets")
        self.assertFalse(res["isError"])
        self.assertEqual((len(calls), len(resets)), (2, 1))

    def test_pas_de_nouvelle_tentative_sur_autre_erreur(self):
        calls = []

        def fake(**_):
            calls.append(1)
            raise ValueError("autre")

        server._TOOLS_BY_NAME["lister_projets"]["handler"] = fake
        res = self.tool("lister_projets")
        self.assertTrue(res["isError"])
        self.assertEqual(len(calls), 1)


class TestPrompts(unittest.TestCase):
    def test_liste_et_contenu(self):
        prompts = call("prompts/list")["result"]["prompts"]
        self.assertEqual({p["name"] for p in prompts}, {"analyser_boucle", "inventaire_reseau", "fiche_station"})
        res = call("prompts/get", {"name": "analyser_boucle", "arguments": {"repere": "FIC101", "projet": "AS1"}})
        text = res["result"]["messages"][0]["content"]["text"]
        self.assertIn("FIC101", text)
        self.assertIn("du projet AS1", text)
        self.assertIn("tracer_boucle", text)
        self.assertEqual(call("prompts/get", {"name": "x"})["error"]["code"], -32602)


class TestBoucleStdio(unittest.TestCase):
    def test_lignes_json(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "pas du json",
            "",
            json.dumps([{"jsonrpc": "2.0", "id": 2, "method": "ping"},
                        {"jsonrpc": "2.0", "method": "notifications/initialized"}]),
        ]
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "server.py")],
                              input=("\n".join(lines) + "\n").encode(), capture_output=True, timeout=30)
        out = [json.loads(l) for l in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual(out[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertEqual(out[1]["error"]["code"], -32700)
        self.assertEqual(out[2], [{"jsonrpc": "2.0", "id": 2, "result": {}}])
        self.assertEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
