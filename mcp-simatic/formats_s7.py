"""Analyse de formats texte STEP 7 (indépendant de Windows, testable partout)."""

import csv
import io
import re


def parse_sdf(text):
    """Table des mnémoniques au format .sdf : "symbole","adresse","type","commentaire"."""
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        fields = [f.strip() for f in rec]
        if len(fields) < 2 or not fields[0]:
            continue
        rows.append({
            "symbole": fields[0],
            "adresse": " ".join(fields[1].split()),
            "type": fields[2] if len(fields) > 2 else "",
            "commentaire": fields[3] if len(fields) > 3 else "",
        })
    return rows


# --------------------------------------------------------------------------
# Adresses absolues STEP 7 (mnémonique allemand ou anglais)
# --------------------------------------------------------------------------

# zone -> (sens E/S/M, périphérie) ; taille par lettre B/W/D, sinon bit
_ZONES = {
    "E": ("E", False), "I": ("E", False),
    "A": ("S", False), "Q": ("S", False),
    "PE": ("E", True), "PI": ("E", True),
    "PA": ("S", True), "PQ": ("S", True),
    "M": ("M", False),
}
_SIZES = {"B": 1, "W": 2, "D": 4}
_ADDRESS = re.compile(r"^\s*(P[EIAQ]|[EIAQM])\s*([BWD])?\s*(\d+)(?:\.(\d))?\s*$", re.I)


def parse_address(text):
    """'PEW 1024' -> {'sens': 'E', 'octet': 1024, 'taille': 2, 'bit': None, 'peripherie': True}.

    Renvoie None pour ce qui n'est pas une adresse d'E/S ou de mémento (DB, FB, T, Z...).
    """
    m = _ADDRESS.match(text or "")
    if not m:
        return None
    zone, size, byte, bit = m.group(1).upper(), (m.group(2) or "").upper(), int(m.group(3)), m.group(4)
    if size and bit is not None:
        return None  # ex. 'EW 10.3' invalide
    if not size and bit is None:
        return None  # 'E 10' ou 'PE 10' : invalide
    if zone.startswith("P") and not size:
        return None  # la périphérie s'adresse par octet/mot/double mot
    sens, periph = _ZONES[zone]
    return {
        "sens": sens,
        "octet": byte,
        "taille": _SIZES.get(size, 0),
        "bit": int(bit) if bit is not None else None,
        "peripherie": periph,
    }
