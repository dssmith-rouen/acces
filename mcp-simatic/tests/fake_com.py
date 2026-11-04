"""Faux modules pythoncom / pywintypes / win32com simulant l'interface COM de STEP 7.

Reproduit juste ce qu'utilise simatic_com : typeinfo (GetTypeAttr, GetFuncDesc,
GetNames, GetDocumentation), Invoke, GetIDsOfNames, énumération _NewEnum.
Chaque appel est journalisé pour vérifier qu'aucune méthode interdite n'est appelée.
"""

import sys
import types

DISPATCH_METHOD = 1
DISPATCH_PROPERTYGET = 2
DISPID_NEWENUM = -4
IID_IEnumVARIANT = "IEnumVARIANT"

CALLS = []  # (interface, membre, type d'appel, arguments)


class com_error(Exception):
    pass


# Identifiants de membres par interface, comme dans un vrai COM (stables pour une interface).
REGISTRY = {}  # interface -> {nom: {"memid": int, "get": nb_params | None, "method": nb_params | None}}


class FakeObject:
    """Objet COM simulé.

    props   : nom -> valeur, FakeObject ou fonction(*args) (propriété en lecture)
    params  : nom -> nombre de paramètres obligatoires d'une propriété (défaut 0)
    methods : nom -> (nb de paramètres obligatoires, fonction(*args))
    items   : éléments si l'objet est une collection
    Un membre déclaré par un autre objet de la même interface mais absent de celui-ci
    lève une erreur COM, comme STEP 7 (« ID d'attribut inexistante »).
    """

    def __init__(self, iface, props=None, methods=None, items=None, params=None):
        self.iface, self.items = iface, items
        self.props, self.methods, self.params = {}, {}, {}
        for name, value in (props or {}).items():
            self.add_prop(name, value, (params or {}).get(name, 0))
        for name, (n, fn) in (methods or {}).items():
            self.add_method(name, n, fn)
        if items is not None:
            self.add_prop("Count", lambda: len(self.items))

    def _entry(self, name):
        reg = REGISTRY.setdefault(self.iface, {})
        if name not in reg:
            reg[name] = {"memid": len(reg) + 1, "get": None, "method": None}
        return reg[name]

    def add_prop(self, name, value, nparams=0):
        self.props[name], self.params[name] = value, nparams
        self._entry(name)["get"] = nparams

    def add_method(self, name, nparams, fn):
        self.methods[name] = (nparams, fn)
        self._entry(name)["method"] = nparams

    def name_of(self, memid):
        for name, entry in REGISTRY[self.iface].items():
            if entry["memid"] == memid:
                return name
        raise com_error(-2147352573, "Membre introuvable", None, None)


class _FuncDesc:
    def __init__(self, memid, invkind, nparams):
        self.memid, self.invkind = memid, invkind
        self.args = tuple((12, 1, None) for _ in range(nparams))


class _TypeAttr:
    def __init__(self, cfuncs):
        self.cFuncs, self.cVars = cfuncs, 0


class _TypeInfo:
    def __init__(self, obj):
        self.obj = obj
        self.entries = REGISTRY.get(obj.iface, {})
        self.funcs = []
        for entry in self.entries.values():
            if entry["get"] is not None:
                self.funcs.append(_FuncDesc(entry["memid"], DISPATCH_PROPERTYGET, entry["get"]))
            if entry["method"] is not None:
                self.funcs.append(_FuncDesc(entry["memid"], DISPATCH_METHOD, entry["method"]))
        # IDispatch hérité (doit être masqué par simatic_com)
        self.funcs.append(_FuncDesc(9999, DISPATCH_METHOD, 0))

    def GetTypeAttr(self):
        return _TypeAttr(len(self.funcs))

    def GetFuncDesc(self, i):
        return self.funcs[i]

    def GetNames(self, memid):
        if memid == 9999:
            return ("QueryInterface",)
        name = self.obj.name_of(memid)
        entry = self.entries[name]
        n = entry["method"] if entry["method"] is not None else entry["get"]
        return (name,) + tuple(f"p{i}" for i in range(n or 0))

    def GetDocumentation(self, index):
        return (self.obj.iface, None, 0, None)


class _Enum:
    def __init__(self, items):
        self.items, self.pos = list(items), 0

    def Next(self, n):
        chunk = self.items[self.pos:self.pos + n]
        self.pos += n
        return tuple(_ole(x) for x in chunk)


class _Unknown:
    def __init__(self, items):
        self.items = items

    def QueryInterface(self, iid):
        return _Enum(self.items)


class PyIDispatch:  # le nom compte : simatic_com teste type(x).__name__
    def __init__(self, obj):
        self.obj = obj

    def GetTypeInfo(self):
        return _TypeInfo(self.obj)

    def GetIDsOfNames(self, name):
        entry = REGISTRY.get(self.obj.iface, {}).get(name)
        if entry is None:
            raise com_error(-2147352570, "Nom inconnu", None, None)
        return entry["memid"]

    def Invoke(self, memid, lcid, flags, want, *args):
        name = self.obj.name_of(memid)
        CALLS.append((self.obj.iface, name, "get" if flags == DISPATCH_PROPERTYGET else "methode", args))
        if flags == DISPATCH_PROPERTYGET and name in self.obj.props:
            value = self.obj.props[name]
            if callable(value) and not isinstance(value, FakeObject):
                value = value(*args)
            return _ole(value)
        if flags == DISPATCH_METHOD and name in self.obj.methods:
            return _ole(self.obj.methods[name][1](*args))
        raise com_error(-2147352567, "Une exception s'est produite.",
                        (0, None, f"ID d'attribut {memid} inexistante.", None, 0, 0), None)

    def InvokeTypes(self, dispid, lcid, flags, ret, argtypes, *args):
        if dispid != DISPID_NEWENUM or self.obj.items is None:
            raise com_error(-2147352573, "Pas une collection", None, None)
        return _Unknown(self.obj.items)


def _ole(value):
    return PyIDispatch(value) if isinstance(value, FakeObject) else value


class CDispatch:
    def __init__(self, ole):
        self._oleobj_ = ole


ROOT = {"obj": None}


def Dispatch(value):
    if isinstance(value, PyIDispatch):
        return CDispatch(value)
    if value == "Simatic.Simatic" and ROOT["obj"] is not None:
        return CDispatch(PyIDispatch(ROOT["obj"]))
    raise com_error(-2147221005, "Chaîne de classe non valide", None, None)


def install():
    """Installe les faux modules dans sys.modules (avant d'importer simatic_com)."""
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.DISPATCH_METHOD = DISPATCH_METHOD
    pythoncom.DISPATCH_PROPERTYGET = DISPATCH_PROPERTYGET
    pythoncom.DISPID_NEWENUM = DISPID_NEWENUM
    pythoncom.IID_IEnumVARIANT = IID_IEnumVARIANT
    pythoncom.CoInitialize = lambda: None
    pywintypes = types.ModuleType("pywintypes")
    pywintypes.com_error = com_error
    win32com = types.ModuleType("win32com")
    client = types.ModuleType("win32com.client")
    dynamic = types.ModuleType("win32com.client.dynamic")
    dynamic.Dispatch = Dispatch
    client.dynamic = dynamic
    win32com.client = client
    sys.modules.update({
        "pythoncom": pythoncom, "pywintypes": pywintypes, "win32com": win32com,
        "win32com.client": client, "win32com.client.dynamic": dynamic,
    })
