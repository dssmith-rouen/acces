"""Analyse des fichiers de configuration matérielle STEP 7 exportés (.cfg).

Le format .cfg (FILEVERSION 2.x) est un texte structuré :
    RACK 0, SLOT 5, "6GK7 443-1EX20-0XE0" "V2.0", "CPU1 - CP 443-1"
    BEGIN
      IPADDRESS "C0A8650B"
      ...
    PARAMETER
      NOM, "valeur"
    LOCAL_IN_ADDRESSES
      ADDRESS  512, 0, 16, 0, 0, 0
    END
Ce module ne dépend pas de Windows : il est testable partout.
"""

import re

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_ATTR = re.compile(r'^([A-Za-z_][\w]*)\s+"(.*)"\s*$')
_NUMBERS = re.compile(r"-?\d+")

# Attributs gardés dans le résumé (les autres seulement avec details=True).
_SUMMARY_KEYS = (
    "IPADDRESS", "SUBNETMASK", "ROUTERADDRESS", "ROUTERACTIVE", "IPACTIVE",
    "MACADDRESS", "DEVICE_NAME", "PROFIBUSADDRESS", "MPI_ADDRESS",
    "LINKED_SUBNETNAME", "COMMENT", "PLANT_DESIGNATION", "LOCAL_DESIGNATION",
)
# Attributs sans intérêt (mise en page, identifiants internes).
_NOISE = re.compile(r"^(POS_[XY]|SIZE_[XY]|ASSET_ID|CAX_APP_ID|OBJECT_\w+|__\d+|_ATTR\w*|GUI_HIDE)$")
_ADDRESS_SECTIONS = re.compile(r"^(LOCAL_)?(IN|OUT)_ADDRESSES$|^\w*ADDRESSES$")


def hex_to_ip(value):
    if value and re.fullmatch(r"[0-9A-Fa-f]{8}", value):
        return ".".join(str(int(value[i:i + 2], 16)) for i in range(0, 8, 2))
    return value or None


def hex_to_mac(value):
    if value and re.fullmatch(r"[0-9A-Fa-f]{12}", value):
        return ":".join(value[i:i + 2].upper() for i in range(0, 12, 2))
    return value or None


def _parse_header(line):
    quoted = _QUOTED.findall(line)
    first_quote = line.find('"')
    location = line[:first_quote].strip().rstrip(",").strip() if first_quote >= 0 else line.strip()
    comp = {"emplacement": location}
    if len(quoted) >= 3:
        comp["reference"], comp["version"], comp["nom"] = quoted[0], quoted[1], quoted[-1]
    elif len(quoted) == 2:
        comp["reference"], comp["nom"] = quoted
    elif len(quoted) == 1:
        comp["nom"] = quoted[0]
    for key, regex in (("dp_reseau", r"DPSUBSYSTEM\s+(\d+)"), ("dp_adresse", r"DPADDRESS\s+(\d+)"),
                       ("pn_reseau", r"IOSUBSYSTEM\s+(\d+)"), ("pn_numero", r"IOADDRESS\s+(\d+)"),
                       ("rack", r"RACK\s+(\d+)"), ("slot", r"\bSLOT\s+(\d+)"), ("subslot", r"SUBSLOT\s+(\d+)")):
        m = re.search(regex, location)
        if m:
            comp[key] = int(m.group(1))
    return comp


def parse_cfg(text):
    """Renvoie {"entete": {...}, "composants": [...]}."""
    header, components = {}, []
    current, depth, mode = None, 0, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "BEGIN":
            depth += 1
            mode = "attributs" if depth == 1 else mode
            continue
        if line == "END":
            depth = max(0, depth - 1)
            mode = "attributs" if depth == 1 else None
            continue
        if depth == 0:
            if line.startswith("#"):
                key, _, value = line[1:].partition(" ")
                header[key] = value.strip().strip('"')
            elif line.startswith("FILEVERSION"):
                header["FILEVERSION"] = (_QUOTED.findall(line) or [""])[0]
            elif line == "AUTOCREATED":
                if current is not None:
                    current["auto"] = True
            elif line.startswith("MASTER ") and current is not None:
                current["maitre"] = {
                    "systeme": line[len("MASTER "):].strip(),
                    "sous_reseau": (_QUOTED.findall(line) or [None])[0],
                }
            elif '"' in line:
                current = _parse_header(line)
                current["attributs"], current["adresses"], current["nb_parametres"] = {}, [], 0
                components.append(current)
            continue
        if current is None or depth > 1:
            continue  # sous-blocs (REDUNDANCY...) ignorés
        if line == "PARAMETER":
            mode = "parametres"
            continue
        if _ADDRESS_SECTIONS.match(line):
            mode = line
            continue
        if mode == "parametres":
            current["nb_parametres"] += 1
        elif mode and mode.endswith("ADDRESSES") and line.startswith("ADDRESS"):
            nums = [int(n) for n in _NUMBERS.findall(line)]
            sens = "E" if "IN_" in mode else ("S" if "OUT_" in mode else mode)
            entry = {"sens": sens, "debut": nums[0] if nums else None}
            if len(nums) > 2 and nums[2] > 0:
                # Format constaté : début, 0, longueur en octets, 0, 1, 0
                entry["longueur"] = nums[2]
                entry["plage"] = f"{nums[0]}..{nums[0] + nums[2] - 1}"
            entry["brut"] = nums
            current["adresses"].append(entry)
        else:
            m = _ATTR.match(line)
            if m:
                current["attributs"][m.group(1)] = m.group(2)
    return {"entete": header, "composants": components}


def summarize(parsed, details=False):
    """Vue compacte : un dictionnaire par module."""
    out = []
    for comp in parsed["composants"]:
        attrs = comp["attributs"]
        item = {k: v for k, v in comp.items() if k not in ("attributs", "adresses", "nb_parametres") and v not in (None, "")}
        for key in _SUMMARY_KEYS:
            if attrs.get(key) not in (None, ""):
                item[key] = attrs[key]
        for key in ("IPADDRESS", "SUBNETMASK", "ROUTERADDRESS"):
            if key in item:
                item[key] = hex_to_ip(item[key])
        if "MACADDRESS" in item:
            item["MACADDRESS"] = hex_to_mac(item["MACADDRESS"])
        user_addresses = [a for a in comp["adresses"] if a["debut"] is not None and a["debut"] < 16000]
        if user_addresses:
            item["adresses_es"] = user_addresses
        diag = [a["debut"] for a in comp["adresses"] if a["debut"] is not None and a["debut"] >= 16000]
        if diag:
            item["adresses_diagnostic"] = diag
        if details:
            item["tous_attributs"] = {k: v for k, v in attrs.items() if not _NOISE.match(k)}
            item["nb_parametres"] = comp["nb_parametres"]
        out.append(item)
    return out


def network_view(parsed):
    """Liste les interfaces et participants réseau (Ethernet, PROFIBUS, MPI, PROFINET IO)."""
    rows, seen = [], set()
    comps = summarize(parsed)
    parents = {
        (c.get("rack"), c.get("slot"), c.get("dp_reseau"), c.get("dp_adresse")): c.get("nom")
        for c in comps if "subslot" not in c
    }
    for comp in comps:
        row = {}
        if comp.get("IPADDRESS") and comp.get("IPACTIVE", "1") != "0":
            row.update(type="Ethernet", ip=comp["IPADDRESS"], masque=comp.get("SUBNETMASK"),
                       passerelle=comp.get("ROUTERADDRESS") if comp.get("ROUTERACTIVE") == "1" else None,
                       mac=comp.get("MACADDRESS"), nom_appareil=comp.get("DEVICE_NAME"))
        elif comp.get("PROFIBUSADDRESS") or comp.get("maitre"):
            row.update(type="PROFIBUS (maître)", adresse=comp.get("PROFIBUSADDRESS"),
                       sous_reseau=(comp.get("maitre") or {}).get("sous_reseau") or comp.get("LINKED_SUBNETNAME"))
        elif "dp_adresse" in comp and "slot" not in comp:
            row.update(type="PROFIBUS (esclave)", adresse=comp["dp_adresse"], reseau_dp=comp.get("dp_reseau"))
        elif "pn_numero" in comp and "slot" not in comp:
            row.update(type="PROFINET IO (périphérique)", numero=comp["pn_numero"],
                       reseau_pn=comp.get("pn_reseau"), nom_appareil=comp.get("DEVICE_NAME"),
                       ip=comp.get("IPADDRESS"))
        elif comp.get("MPI_ADDRESS"):
            row.update(type="MPI", adresse=comp["MPI_ADDRESS"])
        if row:
            key = (row["type"], row.get("ip") or row.get("adresse") or row.get("numero"),
                   comp.get("dp_reseau"), comp.get("dp_adresse"), comp.get("rack"), comp.get("slot"))
            if key in seen:
                continue  # même interface vue sur le module et son sous-module
            seen.add(key)
            row = {k: v for k, v in row.items() if v not in (None, "")}
            row["module"] = comp.get("nom")
            if "subslot" in comp:
                parent = parents.get((comp.get("rack"), comp.get("slot"), comp.get("dp_reseau"), comp.get("dp_adresse")))
                if parent:
                    row["module"] = f"{parent} / {comp.get('nom')}"
            row["emplacement"] = comp.get("emplacement")
            if comp.get("reference"):
                row["reference"] = comp["reference"]
            rows.append(row)
    return rows
