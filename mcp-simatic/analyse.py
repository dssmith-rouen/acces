"""Analyses sans dépendance Windows : recherche par mot, localisation d'une adresse
d'E/S dans la configuration matérielle, synthèse d'une boucle.

Les données d'entrée sont celles produites par simatic_com (listes de diagrammes,
mnémoniques, modules issus de hw_config.summarize).
"""

import re

import formats_s7


def make_matcher(texte, mot_entier=False):
    """Fonction de test 'contient' insensible à la casse, éventuellement par mot entier.

    Avec mot_entier, une lettre ou un chiffre ne peut pas coller au texte cherché :
    'PID' trouve 'SORTIE PID 1' mais pas 'RAPIDE' ; '12_0345' trouve '12_0345_FT'.
    """
    if not texte:
        return lambda value: True
    if mot_entier:
        regex = re.compile(r"(?<![A-Za-z0-9])" + re.escape(texte) + r"(?![A-Za-z0-9])", re.I)
        return lambda value: isinstance(value, str) and regex.search(value) is not None
    needle = texte.lower()
    return lambda value: isinstance(value, str) and needle in value.lower()


def loop_prefix(repere):
    """'12_0345_FRC' -> '12_0345' ; 'FIC101' -> 'FIC101'."""
    tokens = (repere or "").strip().split("_")
    if len(tokens) >= 2 and tokens[1][:1].isdigit():
        return "_".join(tokens[:2])
    return (repere or "").strip()


def _prefix_regex(prefix):
    return re.compile("^" + re.escape(prefix) + r"(?![0-9])", re.I)


def _heads(modules):
    """Têtes de station décentralisée (esclave DP / périphérique PN) par adresse."""
    heads = {}
    for m in modules:
        if "slot" in m:
            continue
        if "dp_adresse" in m:
            heads[("dp", m.get("dp_reseau"), m["dp_adresse"])] = m
        if "pn_numero" in m:
            heads[("pn", m.get("pn_reseau"), m["pn_numero"])] = m
    return heads


def locate_io(stations, address):
    """Trouve le module dont la plage d'E/S contient l'adresse (dict de formats_s7.parse_address).

    stations : [{"station": nom, "modules": [modules résumés]}].
    """
    if not address or address["sens"] not in ("E", "S"):
        return None
    byte = address["octet"]
    for st in stations:
        heads = _heads(st["modules"])
        for mod in st["modules"]:
            for rng in mod.get("adresses_es", []):
                length = rng.get("longueur") or 0
                if rng["sens"] != address["sens"] or not (rng["debut"] <= byte < rng["debut"] + length):
                    continue
                found = {
                    "station": st["station"],
                    "emplacement": mod.get("emplacement"),
                    "module": mod.get("nom"),
                    "reference": mod.get("reference"),
                    "plage": rng.get("plage"),
                }
                offset = byte - rng["debut"]
                if address["bit"] is not None:
                    found["voie"] = offset * 8 + address["bit"]
                elif address["taille"] == 2:
                    found["voie"] = offset // 2
                    found["hypothese_voie"] = "2 octets par voie (cartes analogiques)"
                head = None
                if "dp_adresse" in mod:
                    head = heads.get(("dp", mod.get("dp_reseau"), mod["dp_adresse"]))
                    found["profibus"] = {"reseau": mod.get("dp_reseau"), "adresse": mod["dp_adresse"]}
                elif "pn_numero" in mod:
                    head = heads.get(("pn", mod.get("pn_reseau"), mod["pn_numero"]))
                    found["profinet"] = {"reseau": mod.get("pn_reseau"), "numero": mod["pn_numero"]}
                if head is not None and head is not mod:
                    found["station_decentralisee"] = head.get("nom")
                    if head.get("reference"):
                        found["reference_tete"] = head["reference"]
                return found
    return None


def trace_loop(repere, charts, symbols, stations, prefixe=None):
    """Synthèse d'une boucle : diagrammes, mnémoniques et câblage des E/S."""
    prefix = prefixe or loop_prefix(repere)
    regex = _prefix_regex(prefix)
    loop_charts = [c for c in charts if regex.search(c.get("Name", ""))]
    rows, unresolved = [], []
    for sym in symbols:
        if not regex.search(sym.get("symbole", "")):
            continue
        row = {k: sym.get(k) for k in ("symbole", "adresse", "type", "commentaire") if sym.get(k)}
        address = formats_s7.parse_address(sym.get("adresse", ""))
        if address:
            row["zone"] = {"E": "entrée", "S": "sortie", "M": "mémento"}[address["sens"]]
            if address["sens"] in ("E", "S"):
                where = locate_io(stations, address)
                if where:
                    row["cablage"] = where
                else:
                    unresolved.append(sym.get("adresse"))
        rows.append(row)
    res = {
        "repere": repere,
        "prefixe": prefix,
        "diagrammes": loop_charts,
        "mnemoniques": rows,
        "nb_entrees": sum(1 for r in rows if r.get("zone") == "entrée"),
        "nb_sorties": sum(1 for r in rows if r.get("zone") == "sortie"),
    }
    if unresolved:
        res["adresses_non_trouvees_dans_le_materiel"] = unresolved
    if not loop_charts and not rows:
        res["remarque"] = (f"Aucun diagramme ni mnémonique ne commence par '{prefix}'. "
                           "Essaie un autre préfixe (paramètre 'prefixe').")
    return res
