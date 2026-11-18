"""Regles de nommage de la chaine DQ v3.

Tout nom de catalogue, de schema ou de prefixe est valide ici avant d'etre place dans une requete :
les valeurs saisies par l'utilisateur passent uniquement par des parametres SQL nommes.
"""
from __future__ import annotations

import re

PREFIX_ROOT = "sncf_dqv3"
LAYERS = ("config", "results", "silver", "gold", "ref")
FILIERES = ("Supply Chain", "PTE", "UDR", "a_qualifier")
# Tables techniques toujours exclues du controle (produits de la chaine, rapports)
DEFAULT_EXCLUSIONS = ("dq_%", "rapport_%", "slv_%", "qrt_%")

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_CODE = re.compile(r"^[a-z][a-z0-9]{1,19}$")
_PREFIX = re.compile(r"^sncf_dqv3(_[a-z][a-z0-9]{1,19})?$")
_PATTERN = re.compile(r"^[A-Za-z0-9_%\-]{1,80}$")


class NamingError(ValueError):
    pass


def check_identifier(name: str, what: str = "identifiant") -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise NamingError(f"{what} invalide : {name!r} (minuscules, chiffres et _ uniquement).")
    return name


def check_code_source(code: str) -> str:
    if not isinstance(code, str) or not _CODE.match(code):
        raise NamingError(f"Code source invalide : {code!r} (2 a 20 minuscules ou chiffres, commence par une lettre).")
    return code


def prefix_for(code_source: str) -> str:
    """Prefixe des schemas produits pour une source : sncf_dqv3_<code_source>."""
    return f"{PREFIX_ROOT}_{check_code_source(code_source)}"


def check_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not _PREFIX.match(prefix):
        raise NamingError(f"Prefixe invalide : {prefix!r} (attendu sncf_dqv3 ou sncf_dqv3_<code>).")
    return prefix


def schema_fqn(catalog: str, prefix: str, layer: str) -> str:
    if layer not in LAYERS:
        raise NamingError(f"Couche inconnue : {layer!r}.")
    return f"{check_identifier(catalog, 'catalogue')}.{check_prefix(prefix)}_{layer}"


def parse_patterns(text: str | None) -> list[str]:
    """'a%, b_%' -> ['a%', 'b_%'] ; refuse tout caractere hors motif LIKE simple."""
    items = [x.strip() for x in (text or "").split(",") if x.strip()]
    for x in items:
        if not _PATTERN.match(x):
            raise NamingError(f"Motif de table invalide : {x!r} (lettres, chiffres, _, -, % uniquement).")
    return items
