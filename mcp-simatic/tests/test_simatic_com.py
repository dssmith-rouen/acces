"""Tests de bout en bout de simatic_com sur un faux SIMATIC (données fictives).

Vérifie notamment qu'aucune propriété en ligne ni méthode de modification n'est appelée.
"""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fake_com  # noqa: E402
from fake_com import CALLS, FakeObject, com_error  # noqa: E402

fake_com.install()
sys.modules.pop("simatic_com", None)
import simatic_com as s7  # noqa: E402

s7.BITS = 32  # le faux COM tourne sous un Python 64 bits

FIXTURES = os.path.join(HERE, "fixtures")
PROJ_PATH = r"C:\Fake\S7Proj\MULTI\AS1"
WHEN = datetime.datetime(2024, 1, 1, 8, 0, 0)
ALLOWED_METHODS = {"Export", "GenerateSource", "ExportProgramStructure", "Remove"}
ONLINE = {"ModuleState", "OnlineBlocks", "HSystemState"}


def coll(iface, items):
    return FakeObject(iface, items=items, props={"Item": lambda i: items[i - 1]}, params={"Item": 1})



def copy_fixture(name):
    return lambda path: shutil.copy(os.path.join(FIXTURES, name), path)


def write_text(text):
    def writer(path, *_):
        with open(path, "w", encoding="cp1252") as f:
            f.write(text)
    return writer


def build():
    """Construit un multiprojet fictif et renvoie (racine, conteneur des sources)."""
    fake_com.REGISTRY.clear()
    sources = []

    def raise_online(*_):
        raise AssertionError("accès en ligne interdit")

    def item(iface, name, extra, methods=None):
        props = {"Name": name, "LogPath": f"AS1\\AS1\\CPU\\S7Prog\\{name}", "Modified": WHEN}
        props.update(extra)
        return FakeObject(iface, props, methods or {})

    prog = FakeObject("IS7Program4", {
        "Name": "S7Prog", "LogPath": "AS1\\AS1\\CPU\\S7Prog", "Type": 1327361,
        "ModuleState": raise_online, "HSystemState": raise_online,
        "OnlineBlocks": FakeObject("IS7OnlineBlocks"), "Modified": WHEN,
    }, {"Stop": (0, raise_online), "Remove": (0, raise_online)})

    def new_source(path, flags):
        src = item("IS7Source3", "FB860_gen", {"ConcreteType": 1122309},
                   {"Export": (1, write_text("FUNCTION_BLOCK FB 860\nBEGIN\nEND_FUNCTION_BLOCK\n")),
                    "Remove": (0, lambda: sources.remove(src))})
        sources.append(src)

    def scl_error(*_):
        raise com_error(-2147352567, "Une exception s'est produite.", (0, None, "Bloc SCL", None, 0, 0), None)

    blocks = [
        item("IS7Block3", "FB860", {"SymbolicName": "REGUL_PID", "Comment": "PID controller", "Family": "CTRL",
                                    "Language": "SCL", "ConcreteType": 1138945, "Program": prog},
             {"GenerateSource": (2, new_source), "Download": (1, raise_online)}),
        item("IS7Block3", "FB10", {"SymbolicName": "MOT_RAPIDE", "Comment": "Moteur rapide",
                                   "ConcreteType": 1138945, "Program": prog}),
        item("IS7Block3", "DB201", {"Family": "CTRL", "Language": "DB", "ConcreteType": 1138947, "Program": prog},
             {"GenerateSource": (2, write_text("DATA_BLOCK DB 201\n\"REGUL_PID\"\nBEGIN\n   GAIN := 2.0;\nEND_DATA_BLOCK\n"))}),
        item("IS7Block3", "FC5", {"Language": "SCL", "ConcreteType": 1138946, "Program": prog},
             {"GenerateSource": (2, scl_error)}),
    ]
    plan = item("IS7Plan3", "12_0345_FRC", {"Comment": "Régulation débit eau", "ConcreteType": 17829890},
                {"Edit": (0, raise_online)})
    plan.add_prop("Child", lambda i: FakeObject("IS7StdItem", {"Name": f"enfant{i}"}), 1)
    plans = [plan, item("IS7Plan3", "12_0999_LRC", {"Comment": "Niveau cuve", "ConcreteType": 17829890})]

    def container(name, ctype, items):
        return FakeObject("IS7Container3", {
            "Name": name, "LogPath": f"AS1\\AS1\\CPU\\S7Prog\\{name}", "Modified": WHEN,
            "ConcreteType": ctype, "Type": 63, "Next": coll("IS7SWItems", items), "Program": prog,
        }, {"Compile": (0, raise_online)})

    prog.add_prop("Next", coll("IS7SWItems", [container("Charts", 17829889, plans),
                                              container("Blocks", 1138689, blocks),
                                              container("Sources", 1122308, sources)]))
    prog.add_prop("SymbolTable", FakeObject("IS7SymbolTable3", {"Name": "Symbols", "Modified": WHEN},
                                            {"Export": (1, copy_fixture("mnemoniques_exemple.sdf"))}))
    prog.add_method("ExportProgramStructure", 3, write_text("OB35\n  FC1250\n    FB860, DB201\n"))

    slave_prog = FakeObject("IS7Program4", {"Name": "S7Prog", "LogPath": "AS1\\AS1\\DP\\S7Prog", "Type": 1327367,
                                            "Next": coll("IS7SWItems", [])})
    station = FakeObject("IS7Station", {"Name": "AS1", "LogPath": "AS1\\AS1", "Type": 40},
                         {"Export": (1, copy_fixture("station_exemple.cfg")), "Compile": (1, raise_online)})
    proj = FakeObject("IS7Project3", {
        "Name": "AS1", "LogPath": PROJ_PATH, "Type": 1122305, "Modified": WHEN,
        "Programs": coll("IS7Programs", [slave_prog, prog]), "Stations": coll("IS7Stations", [station]),
    }, {"Remove": (0, raise_online)})
    example = FakeObject("IS7Project3", {"Name": "AS1", "LogPath": r"C:\Siemens\Examples\ZEx01", "Type": 1122305})
    lib = FakeObject("IS7Project3", {"Name": "BIB", "LogPath": r"C:\Fake\S7Proj\MULTI\BIB", "Type": 1122306})
    root = FakeObject("ISimatic4", {"Projects": coll("IS7Projects", [proj, example, lib]),
                                    "MemCard": raise_online})
    return root, sources


class SimaticTestCase(unittest.TestCase):
    def setUp(self):
        self.root, self.sources = build()
        fake_com.ROOT["obj"] = self.root
        s7.reset()
        for cache in (s7._member_cache, s7._cfg_cache, s7._sym_cache, s7._rows_cache):
            cache.clear()
        CALLS.clear()
        os.environ.pop(s7.WRITE_ENV, None)

    def tearDown(self):
        names = {c[1] for c in CALLS}
        self.assertFalse(names & ONLINE, f"propriété en ligne lue : {names & ONLINE}")
        forbidden = {c[1] for c in CALLS if c[2] == "methode"} - ALLOWED_METHODS
        self.assertFalse(forbidden, f"méthode interdite appelée : {forbidden}")
        removed = [c for c in CALLS if c[1] == "Remove"]
        self.assertTrue(all(c[0] == "IS7Source3" for c in removed), "Remove hors source générée")


class TestProjets(SimaticTestCase):
    def test_etat(self):
        st = s7.status()
        self.assertEqual((st["com"], st["nb_projets"]), ("OK", 3))

    def test_lister_projets(self):
        self.assertEqual([p["LogPath"] for p in s7.list_projects()], [PROJ_PATH, r"C:\Fake\S7Proj\MULTI\BIB"])
        self.assertEqual(len(s7.list_projects(inclure_exemples=True)), 3)
        self.assertEqual(len(s7.list_projects(filtre="bib")), 1)

    def test_trouver_projet(self):
        self.assertIsNotNone(s7.find_project(PROJ_PATH.lower() + "\\"))
        with self.assertRaises(s7.SimaticError) as ctx:
            s7.find_project("AS1")  # deux projets portent ce nom
        self.assertIn("ambigu", str(ctx.exception))
        with self.assertRaises(s7.SimaticError):
            s7.find_project("INCONNU")


class TestNavigation(SimaticTestCase):
    def test_proprietes_en_ligne_non_lues(self):
        res = s7.explore(PROJ_PATH, ["Programs", "AS1\\AS1\\CPU\\S7Prog"])
        self.assertEqual(res["proprietes"]["ModuleState"], "<non lu : accès en ligne>")
        self.assertEqual(res["proprietes"]["OnlineBlocks"], "<non lu : accès en ligne>")
        self.assertEqual(res["proprietes"]["Name"], "S7Prog")
        self.assertFalse(any("QueryInterface" in m for m in res["membres"]))
        root = s7.explore(None, [])
        self.assertEqual(root["proprietes"]["MemCard"], "<non lu : accès en ligne>")

    def test_navigation_refusee(self):
        for chemin in (["Programs", "AS1\\AS1\\CPU\\S7Prog", "OnlineBlocks"],
                       ["Programs", "AS1\\AS1\\CPU\\S7Prog", "Stop"],
                       ["Remove"]):
            with self.subTest(chemin=chemin), self.assertRaises(s7.SimaticError):
                s7.explore(PROJ_PATH, chemin)

    def test_noms_en_double_par_logpath_ou_numero(self):
        res = s7.explore(PROJ_PATH, ["Programs", "AS1\\AS1\\DP\\S7Prog"], avec_signatures=False)
        self.assertEqual(res["proprietes"]["Type"], 1327367)
        res = s7.explore(PROJ_PATH, ["Programs", "2"], avec_signatures=False)
        self.assertEqual(res["proprietes"]["Type"], 1327361)

    def test_collection_et_propriete_a_parametre(self):
        res = s7.explore(PROJ_PATH, ["Programs", "2", "Next", "Charts", "Next"], avec_signatures=False)
        self.assertEqual(res["nb_elements"], 2)
        res = s7.explore(PROJ_PATH, ["Programs", "2", "Next", "Charts", "Next", "12_0345_FRC", "Child(3)"])
        self.assertEqual(res["proprietes"]["Name"], "enfant3")
        with self.assertRaises(s7.SimaticError):
            s7.explore(PROJ_PATH, ["Programs", "2", "Next", "Charts", "Next", "12_0345_FRC", "Name(1)"])


class TestListesEtRecherche(SimaticTestCase):
    def test_lister_diagrammes_et_blocs(self):
        charts = s7.list_items(PROJ_PATH, "Charts")
        self.assertEqual(charts["nb"], 2)
        self.assertEqual(charts["elements"][0]["genre"], "Diagramme CFC")
        dbs = s7.list_items(PROJ_PATH, "Blocks", genre="DB")
        self.assertEqual([e["Name"] for e in dbs["elements"]], ["DB201"])

    def test_mot_entier(self):
        self.assertEqual(s7.list_items(PROJ_PATH, "Blocks", filtre="PID")["nb"], 2)  # PID + RAPIDE
        self.assertEqual(s7.list_items(PROJ_PATH, "Blocks", filtre="PID", mot_entier=True)["nb"], 1)
        hits = s7.search("PID", projet=PROJ_PATH, mot_entier=True)["resultats"]
        self.assertEqual([h["Name"] for h in hits], ["FB860"])

    def test_cache_des_conteneurs(self):
        s7.list_items(PROJ_PATH, "Blocks")
        first = len(CALLS)
        CALLS.clear()
        s7.list_items(PROJ_PATH, "Blocks")
        self.assertLess(len(CALLS), first / 2)

    def test_mnemoniques(self):
        self.assertEqual(s7.symbols(PROJ_PATH)["nb"], 9)
        res = s7.symbols(PROJ_PATH, filtre="RAPIDE")
        self.assertEqual([r["symbole"] for r in res["mnemoniques"]], ["MOTEUR_P1_MARCHE"])
        exports = [c for c in CALLS if c[1] == "Export"]
        self.assertEqual(len(exports), 1, "table exportée une seule fois (cache)")


class TestMaterielEtBoucle(SimaticTestCase):
    def test_config_materielle_et_reseau(self):
        hw = s7.hardware(PROJ_PATH)
        self.assertEqual(hw[0]["station"], "AS1")
        self.assertTrue(any(m.get("IPADDRESS") == "10.0.0.10" for m in hw[0]["modules"]))
        net = s7.network(filtre="\\MULTI\\")
        self.assertEqual(net["nb"], 6)
        self.assertTrue(all(r["projet"] == "AS1" for r in net["interfaces"]))

    def test_reseau_filtre_et_controles(self):
        net = s7.network(projet=PROJ_PATH, type_interface="ethernet")
        self.assertEqual([r["ip"] for r in net["interfaces"]], ["10.0.0.10"])
        self.assertEqual(net["alertes"], [])
        self.assertNotIn("alertes", s7.network(projet=PROJ_PATH, controles=False))

    def test_localiser_adresse(self):
        res = s7.locate_address(PROJ_PATH, "PAW 646")
        self.assertEqual([m["symbole"] for m in res["mnemoniques"]], ["12_0345_FV"])
        self.assertEqual(res["cablage"]["station_decentralisee"], "ET200M-ZONE-B")

    def test_tracer_boucle(self):
        res = s7.trace_loop(PROJ_PATH, "12_0345_FRC")
        self.assertEqual([d["Name"] for d in res["diagrammes"]], ["12_0345_FRC"])
        self.assertEqual((res["nb_entrees"], res["nb_sorties"]), (2, 2))
        ft = res["mnemoniques"][0]
        self.assertEqual((ft["symbole"], ft["cablage"]["station_decentralisee"], ft["cablage"]["voie"]),
                         ("12_0345_FT", "ET200M-ZONE-A", 1))


class TestExports(SimaticTestCase):
    def test_exporter_mnemoniques(self):
        res = s7.export(PROJ_PATH, ["Programs", "2", "SymbolTable"])
        self.assertTrue(res["fichier"].endswith(".sdf"))
        self.assertIn("12_0345_FT", res["contenu"])
        with self.assertRaises(s7.SimaticError):
            s7.export(PROJ_PATH, ["Programs", "2"])  # pas de méthode Export

    def test_exporter_nom_et_dossier_securises(self):
        out = tempfile.mkdtemp()
        res = s7.export(PROJ_PATH, ["Programs", "2", "SymbolTable"], dossier_sortie=out,
                        nom_fichier="..\\..\\evasion.sdf")
        self.assertEqual(os.path.dirname(res["fichier"]), out)
        res2 = s7.export(PROJ_PATH, ["Programs", "2", "SymbolTable"], dossier_sortie=out,
                         nom_fichier="evasion.sdf")
        self.assertNotEqual(res["fichier"], res2["fichier"], "pas d'écrasement")
        with self.assertRaises(s7.SimaticError):
            s7.export(PROJ_PATH, ["Programs", "2", "SymbolTable"], dossier_sortie=PROJ_PATH + "\\sous")

    def test_structure_programme(self):
        res = s7.program_structure(PROJ_PATH, colonnes=7)
        self.assertIn("FB860, DB201", res["contenu"])


class TestGenererSource(SimaticTestCase):
    BLOCK = ["Programs", "2", "Next", "Blocks", "Next"]

    def test_refuse_sans_autorisation(self):
        with self.assertRaises(s7.SimaticError) as ctx:
            s7.generate_source(PROJ_PATH, self.BLOCK + ["DB201"])
        self.assertIn(s7.WRITE_ENV, str(ctx.exception))
        self.assertFalse(any(c[1] == "GenerateSource" for c in CALLS))

    def test_autorise_sur_projet_liste(self):
        os.environ[s7.WRITE_ENV] = r"C:\autre;" + PROJ_PATH.lower()
        db = s7.generate_source(PROJ_PATH, self.BLOCK + ["DB201"])
        self.assertEqual(db["origine_contenu"], "fichier")
        self.assertIn("GAIN := 2.0", db["contenu"])
        fb = s7.generate_source(PROJ_PATH, self.BLOCK + ["FB860"])
        self.assertEqual(fb["sources_creees_dans_projet"], ["FB860_gen"])
        self.assertEqual(fb["sources_supprimees"], ["FB860_gen"])
        self.assertEqual(self.sources, [], "la source créée a été retirée du projet")
        self.assertIn("FUNCTION_BLOCK", fb["contenu"])
        with self.assertRaises(s7.SimaticError) as ctx:
            s7.generate_source(PROJ_PATH, self.BLOCK + ["FC5"])
        self.assertIn("Bloc SCL", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
