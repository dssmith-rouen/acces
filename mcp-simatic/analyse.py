"""Analyses sans dépendance Windows : recherche par mot, localisation d'une adresse
d'E/S dans la configuration matérielle, synthèse d'une boucle.

Les données d'entrée sont celles produites par simatic_com (listes de diagrammes,
mnémoniques, modules issus de hw_config.summarize).
"""

import ntpath
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


# --------------------------------------------------------------------------
# Adresse -> mnémoniques et câblage
# --------------------------------------------------------------------------

def _span(address):
    """Octets couverts par une adresse (un bit couvre son octet)."""
    return set(range(address["octet"], address["octet"] + max(address["taille"], 1)))


def overlaps(a, b):
    if a["sens"] != b["sens"] or not (_span(a) & _span(b)):
        return False
    if a["bit"] is not None and b["bit"] is not None:
        return a["octet"] == b["octet"] and a["bit"] == b["bit"]
    return True


def find_address(text, symbols, stations):
    address = formats_s7.parse_address(text)
    if address is None:
        return {"adresse": text, "erreur": "Adresse non reconnue (ex. 'PEW 512', 'E 12.3', 'AW 20', 'PIW 512')."}
    matches = []
    for sym in symbols:
        other = formats_s7.parse_address(sym.get("adresse", ""))
        if other and overlaps(address, other):
            matches.append({k: sym.get(k) for k in ("symbole", "adresse", "type", "commentaire") if sym.get(k)})
    res = {"adresse": text, "zone": {"E": "entrée", "S": "sortie", "M": "mémento"}[address["sens"]],
           "mnemoniques": matches}
    if address["sens"] in ("E", "S"):
        res["cablage"] = locate_io(stations, address) or "adresse absente de la configuration matérielle"
    return res


# --------------------------------------------------------------------------
# Contrôles de cohérence du plan d'adressage
# --------------------------------------------------------------------------

def _ip_int(ip):
    try:
        parts = [int(x) for x in ip.split(".")]
    except (AttributeError, ValueError):
        return None
    if len(parts) != 4 or any(not 0 <= p <= 255 for p in parts):
        return None
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


def _group(row):
    """Dossier du multiprojet : deux copies d'un même multiprojet ne sont pas comparées."""
    path = row.get("chemin_projet")
    return ntpath.dirname(ntpath.normpath(path)).lower() if path else None


def network_checks(rows):
    """Alertes sur une liste d'interfaces (sortie de simatic_com.network).

    Les IP ne sont comparées qu'entre projets d'un même dossier de multiprojet.
    """
    alerts = []
    by_ip = {}
    for r in rows:
        if r.get("ip"):
            by_ip.setdefault((_group(r), r["ip"]), []).append(r)
    for (_grp, ip), users in sorted(by_ip.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        if len(users) > 1:
            where = ", ".join(f"{u.get('projet')}/{u.get('station')} ({u.get('module')})" for u in users)
            alerts.append({"type": "IP en double", "ip": ip, "interfaces": where})
    for r in rows:
        ip, mask, gw = _ip_int(r.get("ip")), _ip_int(r.get("masque")), _ip_int(r.get("passerelle"))
        if ip is not None and mask is not None and gw is not None and (ip & mask) != (gw & mask):
            alerts.append({"type": "Passerelle hors du sous-réseau", "ip": r["ip"], "masque": r["masque"],
                           "passerelle": r["passerelle"], "interface": f"{r.get('projet')}/{r.get('station')}"})
    seen = {}
    for r in rows:
        if r.get("type") in ("PROFIBUS (esclave)", "PROFIBUS (maître)") and r.get("adresse") not in (None, ""):
            subnet = r.get("sous_reseau") or r.get("reseau_dp")
            key = (r.get("projet"), r.get("station"), str(subnet), str(r["adresse"]))
            seen.setdefault(key, []).append(r)
    for (proj, station, subnet, addr), users in sorted(seen.items()):
        if len(users) > 1 and subnet != "None":
            alerts.append({"type": "Adresse PROFIBUS en double", "station": f"{proj}/{station}",
                           "reseau": subnet, "adresse": addr, "nb": len(users)})
    return alerts
