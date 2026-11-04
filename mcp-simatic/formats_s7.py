"""Analyse de formats texte STEP 7 (indépendant de Windows, testable partout)."""

import csv
import io


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
