"""Accès en LECTURE SEULE aux projets STEP 7 V5.x via l'interface COM officielle
"Simatic.Simatic" (S7ABATCX.DLL).

Points importants :
- S7ABATCX.DLL est une DLL COM 32 bits chargée dans le processus appelant :
  ce module doit donc tourner dans un Python 32 bits.
- La navigation n'appelle que des propriétés en lecture (DISPATCH_PROPERTYGET)
  et une courte liste blanche de méthodes de parcours (SAFE_METHODS).
  Aucune méthode de modification (Remove, Compile, Download, Save, Import...)
  n'est jamais appelée. Seule exception volontaire : la méthode "Export",
  qui écrit un fichier texte hors du projet, utilisée par l'outil d'export.
"""

import datetime
import os
import struct
import tempfile

try:
    import pythoncom
    import pywintypes
    import win32com.client.dynamic as _dyn

    _IMPORT_ERROR = None
except ImportError as exc:  # hors Windows ou pywin32 absent
    pythoncom = None
    pywintypes = None
    _dyn = None
    _IMPORT_ERROR = exc

BITS = struct.calcsize("P") * 8
PROGID = "Simatic.Simatic"

# Méthodes sans effet de bord autorisées pendant la navigation.
SAFE_METHODS = {"next"}

# Méthodes IUnknown / IDispatch à masquer dans les descriptions.
_HIDDEN = {
    "queryinterface", "addref", "release", "gettypeinfocount",
    "gettypeinfo", "getidsofnames", "invoke",
}
_INVKIND = {1: "methode", 2: "get", 4: "put", 8: "putref"}
_PARAMFLAG_FOPT = 0x10
_PARAMFLAG_FHASDEFAULT = 0x20

# Dossiers d'exemples / bibliothèques Siemens masqués par défaut.
_EXCLUDED_MARKERS = ("\\examples\\", "\\s7libs\\")


class SimaticError(Exception):
    """Erreur présentée telle quelle à l'utilisateur."""


_app = None
_member_cache = {}


# --------------------------------------------------------------------------
# Environnement / connexion
# --------------------------------------------------------------------------

def _check_env():
    if _IMPORT_ERROR is not None:
        raise SimaticError(
            f"pywin32 n'est pas disponible ({_IMPORT_ERROR}). "
            "Installe-le dans le Python 32 bits : py -3.12-32 -m pip install pywin32"
        )
    if BITS != 32:
        raise SimaticError(
            "Ce Python est en 64 bits : l'interface COM de STEP 7 V5 (S7ABATCX.DLL) "
            "est 32 bits. Lance le serveur avec un Python 32 bits."
        )


def app():
    """Objet racine Simatic.Simatic (créé à la première utilisation)."""
    global _app
    _check_env()
    if _app is None:
        pythoncom.CoInitialize()
        try:
            _app = _dyn.Dispatch(PROGID)
        except Exception as exc:
            raise SimaticError(f"Impossible de créer {PROGID} : {com_message(exc)}")
    return _app


def reset():
    """Oublie l'objet racine (il sera recréé au prochain appel)."""
    global _app
    _app = None


def com_message(exc):
    if pywintypes is not None and isinstance(exc, pywintypes.com_error):
        hr, msg, excepinfo, _arg = exc.args
        detail = None
        if excepinfo and len(excepinfo) > 2 and excepinfo[2]:
            detail = excepinfo[2]
        return f"erreur COM 0x{hr & 0xFFFFFFFF:08X} : {detail or msg}"
    return str(exc)


def status():
    import sys

    res = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "bits": BITS,
        "pywin32": _IMPORT_ERROR is None,
    }
    try:
        projects = get_member(app(), "Projects")
        res["com"] = "OK"
        res["nb_projets"] = _simple(get_member(projects, "Count"))
    except Exception as exc:
        res["com"] = str(exc) if isinstance(exc, SimaticError) else com_message(exc)
    return res


# --------------------------------------------------------------------------
# Introspection COM générique
# --------------------------------------------------------------------------

def _is_obj(value):
    return hasattr(value, "_oleobj_")


def _wrap(value):
    if type(value).__name__ == "PyIDispatch":
        return _dyn.Dispatch(value)
    return value


def _simple(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (tuple, list)):
        return [_simple(v) for v in value[:50]]
    if type(value).__name__ in ("PyIDispatch", "CDispatch", "PyIUnknown"):
        return "<objet COM>"
    return repr(value)


def _typeinfo(obj):
    try:
        return obj._oleobj_.GetTypeInfo()
    except Exception:
        return None


def interface_name(obj):
    ti = _typeinfo(obj)
    if ti is None:
        return None
    try:
        return ti.GetDocumentation(-1)[0]
    except Exception:
        return None


def members(obj):
    """Dictionnaire nom_minuscule -> description du membre (via la typeinfo)."""
    ti = _typeinfo(obj)
    if ti is None:
        return {}
    key = interface_name(obj)
    if key and key in _member_cache:
        return _member_cache[key]
    res = {}
    attr = ti.GetTypeAttr()
    for i in range(attr.cFuncs):
        fd = ti.GetFuncDesc(i)
        names = ti.GetNames(fd.memid)
        if not names or names[0].lower() in _HIDDEN:
            continue
        name = names[0]
        args = fd.args or ()
        required = sum(
            1 for a in args if not (a[1] & (_PARAMFLAG_FOPT | _PARAMFLAG_FHASDEFAULT))
        )
        entry = res.setdefault(name.lower(), {"name": name, "memid": fd.memid, "kinds": {}})
        entry["kinds"][_INVKIND.get(fd.invkind, str(fd.invkind))] = {
            "params": list(names[1:]),
            "required": required,
        }
    for i in range(attr.cVars):
        vd = ti.GetVarDesc(i)
        names = ti.GetNames(vd.memid)
        if names:
            res.setdefault(names[0].lower(), {
                "name": names[0], "memid": vd.memid,
                "kinds": {"get": {"params": [], "required": 0}},
            })
    if key:
        _member_cache[key] = res
    return res


def signatures(obj):
    out = []
    for m in members(obj).values():
        for kind, info in m["kinds"].items():
            sig = f"{kind} {m['name']}({', '.join(info['params'])})"
            if info["required"]:
                sig += f"  [{info['required']} param. obligatoire(s)]"
            out.append(sig)
    return sorted(out, key=str.lower)


def get_member(obj, name):
    """Lit une propriété (ou appelle une méthode de la liste blanche) sans paramètre."""
    ms = members(obj)
    m = ms.get(name.lower())
    if m is None:
        # Repli : membre connu seulement en liaison tardive -> lecture pure.
        try:
            dispid = obj._oleobj_.GetIDsOfNames(name)
        except Exception:
            raise SimaticError(f"Membre '{name}' introuvable sur {interface_name(obj) or 'cet objet'}.")
        return _wrap(obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True))
    kinds = m["kinds"]
    if "get" in kinds and kinds["get"]["required"] == 0:
        flags = pythoncom.DISPATCH_PROPERTYGET
    elif "methode" in kinds and kinds["methode"]["required"] == 0 and m["name"].lower() in SAFE_METHODS:
        flags = pythoncom.DISPATCH_METHOD
    else:
        raise SimaticError(
            f"'{m['name']}' n'est pas une propriété lisible sans paramètre : "
            "appel refusé (serveur en lecture seule)."
        )
    return _wrap(obj._oleobj_.Invoke(m["memid"], 0, flags, True))


def _try_get(obj, name):
    try:
        return _simple(get_member(obj, name))
    except Exception:
        return None


def enum_items(coll):
    """Énumère une collection COM (_NewEnum)."""
    enum = coll._oleobj_.InvokeTypes(
        pythoncom.DISPID_NEWENUM, 0,
        pythoncom.DISPATCH_METHOD | pythoncom.DISPATCH_PROPERTYGET,
        (13, 10), (),
    )
    ev = enum.QueryInterface(pythoncom.IID_IEnumVARIANT)
    while True:
        batch = ev.Next(1)
        if not batch:
            break
        yield _wrap(batch[0])


def label(obj):
    info = {}
    for prop in ("Name", "Type", "LogPath"):
        value = _try_get(obj, prop)
        if value not in (None, ""):
            info[prop] = value
    iface = interface_name(obj)
    if iface:
        info["objet"] = iface
    return info


def read_properties(obj):
    props = {}
    for m in members(obj).values():
        get = m["kinds"].get("get")
        if not get or get["required"] != 0 or m["name"].startswith("_"):
            continue
        try:
            value = obj._oleobj_.Invoke(m["memid"], 0, pythoncom.DISPATCH_PROPERTYGET, True)
        except Exception as exc:
            props[m["name"]] = f"<{com_message(exc)}>"
            continue
        if type(value).__name__ == "PyIDispatch":
            props[m["name"]] = f"<objet {interface_name(_wrap(value)) or 'COM'}>"
        else:
            props[m["name"]] = _simple(value)
    return dict(sorted(props.items(), key=lambda kv: kv[0].lower()))


# --------------------------------------------------------------------------
# Projets et navigation
# --------------------------------------------------------------------------

def _norm(path):
    return (path or "").strip().replace("/", "\\").rstrip("\\").lower()


def list_projects(filtre=None, inclure_exemples=False):
    res = []
    for proj in enum_items(get_member(app(), "Projects")):
        info = label(proj)
        info.pop("objet", None)
        path = _norm(info.get("LogPath")) + "\\"
        if not inclure_exemples and any(mark in path for mark in _EXCLUDED_MARKERS):
            continue
        if filtre and filtre.lower() not in f"{info.get('Name', '')} {path}".lower():
            continue
        res.append(info)
    return res


def find_project(projet):
    target = _norm(projet)
    same_name = []
    for proj in enum_items(get_member(app(), "Projects")):
        path = _try_get(proj, "LogPath") or ""
        if _norm(path) == target:
            return proj
        if (_try_get(proj, "Name") or "").lower() == projet.strip().lower():
            same_name.append((proj, path))
    if len(same_name) == 1:
        return same_name[0][0]
    if same_name:
        paths = "\n".join(f"- {p}" for _, p in same_name)
        raise SimaticError(f"Nom de projet ambigu '{projet}', précise le chemin parmi :\n{paths}")
    raise SimaticError(f"Projet introuvable : '{projet}'. Utilise lister_projets pour voir les chemins.")


def find_item(coll, key):
    try:
        items = enum_items(coll)
        if key.isdigit():
            for idx, item in enumerate(items, start=1):
                if idx == int(key):
                    return item
        else:
            for item in items:
                if (_try_get(item, "Name") or "").lower() == key.lower():
                    return item
    except SimaticError:
        raise
    except Exception:
        raise SimaticError(
            f"'{key}' n'est ni un membre ni un élément de {interface_name(coll) or 'cet objet'}."
        )
    raise SimaticError(f"Élément '{key}' introuvable dans {interface_name(coll) or 'la collection'}.")


def navigate(obj, chemin):
    for step in chemin or []:
        step = str(step)
        if step.lower() in members(obj):
            obj = get_member(obj, step)
        else:
            obj = find_item(obj, step)
        if not _is_obj(obj):
            raise SimaticError(f"'{step}' n'est pas un objet navigable (valeur : {_simple(obj)!r}).")
    return obj


def _root(projet):
    return find_project(projet) if projet else app()


def explore(projet=None, chemin=None, max_elements=200, avec_signatures=True):
    obj = navigate(_root(projet), chemin)
    res = {
        "objet": interface_name(obj),
        "chemin": list(chemin or []),
        "proprietes": read_properties(obj),
    }
    if avec_signatures:
        res["membres"] = signatures(obj)
    try:
        items, total = [], 0
        for item in enum_items(obj):
            total += 1
            if len(items) < max_elements:
                items.append(label(item))
        res["nb_elements"] = total
        res["elements"] = items
        if total > len(items):
            res["remarque"] = f"{total - len(items)} élément(s) non affiché(s) (max_elements={max_elements})."
    except Exception:
        pass  # ce n'est pas une collection
    return res


# --------------------------------------------------------------------------
# Export (source, table des mnémoniques...)
# --------------------------------------------------------------------------

def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def export(projet, chemin, dossier_sortie=None, nom_fichier=None, max_caracteres=150000):
    obj = navigate(_root(projet), chemin)
    m = members(obj).get("export")
    if m is None or "methode" not in m["kinds"]:
        raise SimaticError(
            f"L'objet {interface_name(obj)} n'a pas de méthode Export. "
            "Membres disponibles :\n" + "\n".join(signatures(obj))
        )
    name = _try_get(obj, "Name") or "export"
    if not nom_fichier:
        iface = (interface_name(obj) or "").lower()
        ext = ".sdf" if "symbol" in iface else ".txt"
        nom_fichier = "".join(c if c.isalnum() or c in "-_." else "_" for c in name) + ext
    folder = dossier_sortie or tempfile.mkdtemp(prefix="mcp_simatic_")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, nom_fichier)
    try:
        obj._oleobj_.Invoke(m["memid"], 0, pythoncom.DISPATCH_METHOD, True, path)
    except Exception as exc:
        raise SimaticError(
            f"Échec de Export('{path}') : {com_message(exc)}\nSignature : "
            + ", ".join(s for s in signatures(obj) if " Export(" in s)
        )
    if not os.path.exists(path):
        candidates = [f for f in os.listdir(folder) if f.lower().startswith(os.path.splitext(nom_fichier)[0].lower())]
        if not candidates:
            raise SimaticError(f"Export terminé mais aucun fichier trouvé dans {folder}.")
        path = os.path.join(folder, candidates[0])
    text = _read_text(path)
    return {
        "fichier": path,
        "taille_caracteres": len(text),
        "tronque": len(text) > max_caracteres,
        "contenu": text[:max_caracteres],
    }
