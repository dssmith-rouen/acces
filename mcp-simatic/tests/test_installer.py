"""Tests du script d'installation dans Claude Desktop (sur un fichier temporaire)."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import installer_claude_desktop as inst  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = inst.main(list(argv) + ["--forcer"])
    return code, out.getvalue()


class TestInstaller(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "claude_desktop_config.json")

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_creation_sans_fichier_existant(self):
        run("--config", self.path)
        entry = self.read()["mcpServers"]["simatic"]
        self.assertEqual(entry["command"], sys.executable)
        self.assertTrue(entry["args"][0].endswith("server.py"))
        self.assertNotIn("env", entry)

    def test_fusion_et_sauvegarde(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"preferences": {"x": 1}, "mcpServers": {"autre": {"command": "a"}}}, f)
        run("--config", self.path, "--journal", "--projets-ecriture", r"C:\copie\AS1")
        cfg = self.read()
        self.assertEqual(cfg["preferences"], {"x": 1})
        self.assertIn("autre", cfg["mcpServers"])
        env = cfg["mcpServers"]["simatic"]["env"]
        self.assertTrue(env["SIMATIC_MCP_LOG"].endswith("journal_mcp.log"))
        self.assertEqual(env["SIMATIC_PROJETS_ECRITURE"], r"C:\copie\AS1")
        self.assertEqual(len([f for f in os.listdir(self.dir) if ".bak-" in f]), 1)

    def test_afficher_n_ecrit_rien(self):
        code, out = run("--config", self.path, "--afficher")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.path))
        self.assertIn('"simatic"', out)

    def test_desinstaller(self):
        run("--config", self.path)
        run("--config", self.path, "--desinstaller")
        self.assertNotIn("simatic", self.read()["mcpServers"])
        _, out = run("--config", self.path, "--desinstaller")
        self.assertIn("rien à faire", out)

    def test_fichier_vide_ou_avec_bom(self):
        with open(self.path, "w", encoding="utf-8-sig") as f:
            f.write('{"a": 1}')
        run("--config", self.path)
        self.assertEqual(self.read()["a"], 1)


if __name__ == "__main__":
    unittest.main()
