"""Tests des analyses de fichiers (sans Windows ni STEP 7). Données 100 % fictives."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import analyse  # noqa: E402
import formats_s7  # noqa: E402
import hw_config  # noqa: E402


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
        return f.read()


class TestParseAddress(unittest.TestCase):
    def test_mnemoniques_allemands_et_anglais(self):
        cases = {
            "PEW 1024": ("E", 1024, 2, None, True),
            "PIW 512": ("E", 512, 2, None, True),
            "PAW  1568": ("S", 1568, 2, None, True),
            "PQD 8": ("S", 8, 4, None, True),
            "EW 1068": ("E", 1068, 2, None, False),
            "E 342.2": ("E", 342, 0, 2, False),
            "I 0.0": ("E", 0, 0, 0, False),
            "A 369.4": ("S", 369, 0, 4, False),
            "QB 3": ("S", 3, 1, None, False),
            "MW 10": ("M", 10, 2, None, False),
        }
        for text, (sens, octet, taille, bit, periph) in cases.items():
            with self.subTest(text=text):
                a = formats_s7.parse_address(text)
                self.assertEqual((a["sens"], a["octet"], a["taille"], a["bit"], a["peripherie"]),
                                 (sens, octet, taille, bit, periph))

    def test_non_adresses(self):
        for text in ("DB 10", "FB 849", "T 5", "Z 3", "E 10", "PE 10", "EW 10.3", "", None):
            with self.subTest(text=text):
                self.assertIsNone(formats_s7.parse_address(text))


class TestParseSdf(unittest.TestCase):
    def test_champs_nettoyes(self):
        rows = formats_s7.parse_sdf(fixture("mnemoniques_exemple.sdf"))
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0], {"symbole": "12_0345_FT", "adresse": "PEW 514", "type": "WORD",
                                   "commentaire": "Débit eau vers cuve T1"})
        self.assertEqual(rows[2]["adresse"], "E 12.3")

    def test_guillemets_doubles_et_crlf(self):
        text = '"A","MW 2","INT","valeur ""entre guillemets"""\r\n"","E 0.0","BOOL",""\r\n'
        rows = formats_s7.parse_sdf(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["commentaire"], 'valeur "entre guillemets"')


class TestHwConfig(unittest.TestCase):
    def setUp(self):
        self.parsed = hw_config.parse_cfg(fixture("station_exemple.cfg"))
        self.modules = hw_config.summarize(self.parsed)
        self.by_name = {m.get("nom"): m for m in self.modules}

    def test_entete(self):
        self.assertEqual(self.parsed["entete"]["FILEVERSION"], "2.4")
        self.assertEqual(self.parsed["entete"]["STEP7_VERSION"], "V5.6 + SP2 + HF8")

    def test_modules_et_emplacements(self):
        cpu = self.by_name["AS1 - CPU 417-4"]
        self.assertEqual((cpu["rack"], cpu["slot"], cpu["reference"], cpu["version"]),
                         (0, 3, "6ES7 417-4XT05-0AB0", "V5.2"))
        self.assertEqual(cpu["COMMENT"], "CPU de test")
        ai = self.by_name["A.03.04"]
        self.assertEqual((ai["dp_reseau"], ai["dp_adresse"], ai["slot"]), (1, 3, 4))
        self.assertTrue(self.by_name["DP"]["auto"])

    def test_sous_bloc_et_parametres_ignores(self):
        detailed = {m.get("nom"): m for m in hw_config.summarize(self.parsed, details=True)}
        cpu = detailed["AS1 - CPU 417-4"]
        self.assertEqual(cpu["nb_parametres"], 2)
        self.assertNotIn("SCAN_CYCLE_MONITORING_TIME", cpu["tous_attributs"])
        self.assertNotIn("POS_X", detailed["AS1 - UR"]["tous_attributs"])

    def test_plages_es(self):
        self.assertEqual(self.by_name["A.03.04"]["adresses_es"][0]["plage"], "512..527")
        out = self.by_name["B.04.04"]["adresses_es"][0]
        self.assertEqual((out["sens"], out["longueur"]), ("S", 16))
        self.assertEqual(self.by_name["DP"]["adresses_diagnostic"], [16383])

    def test_ip_et_mac(self):
        iface = self.by_name["AS1"]
        self.assertEqual(iface["IPADDRESS"], "10.0.0.10")
        self.assertEqual(iface["SUBNETMASK"], "255.255.255.0")
        self.assertEqual(iface["ROUTERADDRESS"], "10.0.0.254")
        self.assertEqual(iface["MACADDRESS"], "08:00:06:01:02:03")

    def test_vue_reseau(self):
        rows = hw_config.network_view(self.parsed)
        types = [r["type"] for r in rows]
        self.assertEqual(types.count("MPI"), 1, "MPI de la CPU et de son sous-module dédoublonnés")
        eth = next(r for r in rows if r["type"] == "Ethernet")
        self.assertEqual((eth["ip"], eth["passerelle"], eth["module"]), ("10.0.0.10", "10.0.0.254", "AS1 - CP 443-1 / AS1"))
        slaves = sorted(r["adresse"] for r in rows if r["type"] == "PROFIBUS (esclave)")
        self.assertEqual(slaves, [3, 4])
        pn = next(r for r in rows if r["type"].startswith("PROFINET"))
        self.assertEqual((pn["numero"], pn["nom_appareil"]), (1, "et200s-pn-1"))

    def test_conversions(self):
        self.assertEqual(hw_config.hex_to_ip("C0A80001"), "192.168.0.1")
        self.assertEqual(hw_config.hex_to_ip(""), None)
        self.assertEqual(hw_config.hex_to_ip("pas_hexa"), "pas_hexa")


class TestAnalyse(unittest.TestCase):
    def setUp(self):
        parsed = hw_config.parse_cfg(fixture("station_exemple.cfg"))
        self.stations = [{"station": "AS_EXEMPLE", "modules": hw_config.summarize(parsed)}]
        self.symbols = formats_s7.parse_sdf(fixture("mnemoniques_exemple.sdf"))
        self.charts = [{"Name": "12_0345_FRC", "Comment": "Régulation débit eau"},
                       {"Name": "12_03450_LRC", "Comment": "Autre boucle"}]

    def test_matcher(self):
        mot = analyse.make_matcher("PID", mot_entier=True)
        self.assertTrue(mot("SORTIE PID 1"))
        self.assertTrue(mot("VP_PID"))
        self.assertFalse(mot("ORDRE RAPIDE"))
        self.assertTrue(analyse.make_matcher("pid")("ORDRE RAPIDE"))
        self.assertFalse(analyse.make_matcher("x")(None))

    def test_prefixe(self):
        self.assertEqual(analyse.loop_prefix("12_0345_FRC"), "12_0345")
        self.assertEqual(analyse.loop_prefix("FIC101"), "FIC101")

    def test_localisation_analogique_et_tor(self):
        loc = analyse.locate_io(self.stations, formats_s7.parse_address("PEW 514"))
        self.assertEqual((loc["module"], loc["voie"], loc["station_decentralisee"], loc["profibus"]["adresse"]),
                         ("A.03.04", 1, "ET200M-ZONE-A", 3))
        loc = analyse.locate_io(self.stations, formats_s7.parse_address("E 12.3"))
        self.assertEqual((loc["module"], loc["voie"]), ("A.03.05", 19))
        self.assertIsNone(analyse.locate_io(self.stations, formats_s7.parse_address("PEW 900")))
        self.assertIsNone(analyse.locate_io(self.stations, formats_s7.parse_address("MW 10")))

    def test_tracer_boucle(self):
        res = analyse.trace_loop("12_0345_FRC", self.charts, self.symbols, self.stations)
        self.assertEqual(res["prefixe"], "12_0345")
        self.assertEqual([c["Name"] for c in res["diagrammes"]], ["12_0345_FRC"])
        names = [r["symbole"] for r in res["mnemoniques"]]
        self.assertEqual(names, ["12_0345_FT", "12_0345_FV", "12_0345_FCO", "12_0345_OEV", "12_0345_CALC"])
        self.assertEqual((res["nb_entrees"], res["nb_sorties"]), (2, 2))
        fv = res["mnemoniques"][1]["cablage"]
        self.assertEqual((fv["module"], fv["voie"], fv["station_decentralisee"]), ("B.04.04", 3, "ET200M-ZONE-B"))
        oev = res["mnemoniques"][3]["cablage"]
        self.assertEqual((oev["module"], oev["voie"]), ("B.04.05", 8))
        self.assertNotIn("cablage", res["mnemoniques"][4])

    def test_tracer_boucle_inconnue(self):
        res = analyse.trace_loop("99_9999_XX", self.charts, self.symbols, self.stations)
        self.assertIn("remarque", res)


if __name__ == "__main__":
    unittest.main()
