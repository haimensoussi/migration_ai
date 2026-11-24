"""Personnel fictif de démonstration pour l'équipe Sales (Horizon Équipements).

Aucune personne réelle : les commerciaux reprennent les fiches fictives de data_sales_representatives,
complétées de 8 fonctions support fictives. Les niveaux de compétence sont tirés de façon
déterministe (graine fixe) dans des plages dépendant de la fonction ; ils devront être remplacés
par une évaluation réelle des responsables avant tout usage hors démonstration.
"""
from __future__ import annotations

import random
import unicodedata

ASSESSOR = "seed:demonstration"

# Plages (min, max) de niveau par profil ; les compétences absentes ne sont pas détenues.
PROFILES = {
    "PME": {"prospection": (3, 5), "relance_clients": (3, 5), "negociation": (2, 4), "gestion_pipeline": (2, 4),
            "offre_materiel": (1, 4), "offre_cloud": (1, 4), "analyse_donnees": (1, 2)},
    "ETI": {"prospection": (2, 4), "relance_clients": (2, 4), "negociation": (3, 4), "grands_comptes": (2, 3),
            "gestion_pipeline": (3, 4), "offre_materiel": (1, 4), "offre_cloud": (2, 4), "analyse_donnees": (1, 3)},
    "Grands comptes": {"prospection": (2, 3), "negociation": (4, 5), "grands_comptes": (4, 5),
                       "gestion_pipeline": (3, 4), "offre_cloud": (2, 5), "offre_materiel": (2, 4), "analyse_donnees": (2, 3)},
    "Direction régionale": {"pilotage_regional": (4, 5), "negociation": (3, 4), "grands_comptes": (2, 4),
                            "gestion_pipeline": (3, 4), "analyse_donnees": (2, 4), "relance_clients": (2, 3)},
    "ADV": {"administration_ventes": (4, 5), "relance_clients": (2, 3), "analyse_donnees": (2, 3)},
    "Marketing": {"marketing_digital": (4, 5), "analyse_donnees": (2, 3), "offre_cloud": (2, 3), "prospection": (1, 2)},
    "Data": {"analyse_donnees": (5, 5), "marketing_digital": (1, 2), "controle_gestion": (2, 3), "gestion_pipeline": (2, 3)},
    "Contrôle de gestion": {"controle_gestion": (5, 5), "analyse_donnees": (4, 4), "administration_ventes": (2, 3)},
    "Direction commerciale": {"pilotage_regional": (5, 5), "negociation": (5, 5), "grands_comptes": (4, 4),
                              "analyse_donnees": (3, 3), "gestion_pipeline": (4, 4)},
}
# Part du temps disponible pour les missions (%) par profil.
AVAILABILITY = {"PME": (10, 20), "ETI": (10, 20), "Grands comptes": (10, 15), "Direction régionale": (15, 25),
                "ADV": (30, 40), "Marketing": (30, 50), "Data": (40, 60), "Contrôle de gestion": (20, 30),
                "Direction commerciale": (10, 10)}

SUPPORT = [
    ("S001", "Lucie Garnier", "Gestionnaire ADV", "ADV"),
    ("S002", "Karim Benali", "Gestionnaire ADV", "ADV"),
    ("S003", "Sophie Marchand", "Chargée de marketing digital", "Marketing"),
    ("S004", "Thomas Leroux", "Responsable campagnes", "Marketing"),
    ("S005", "Inès Moreau", "Analyste de données commerciales", "Data"),
    ("S006", "Julien Faure", "Analyste de données commerciales", "Data"),
    ("S007", "Claire Dupuis", "Contrôleuse de gestion", "Contrôle de gestion"),
    ("S008", "Marc Lefebvre", "Directeur commercial", "Direction commerciale"),
]
JOB_TITLES = {"PME": "Commercial PME", "ETI": "Commercial ETI", "Grands comptes": "Ingénieur commercial grands comptes",
              "Direction régionale": "Responsable régional"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _draw(rng: random.Random, profile: str) -> tuple[dict[str, int], int]:
    skills = {s: rng.randint(lo, hi) for s, (lo, hi) in sorted(PROFILES[profile].items())}
    lo, hi = AVAILABILITY[profile]
    return skills, rng.randint(lo, hi)


def build_sales_staff(reps: list[dict], team_id: str = "sales", seed: int = 42) -> list[tuple[dict, dict[str, int]]]:
    """Renvoie [(fiche personne, compétences)] à partir des commerciaux fictifs et des fonctions support."""
    rng = random.Random(seed)
    out = []
    for r in sorted(reps, key=lambda x: x["rep_id"]):
        profile = r["team"] if r["team"] in PROFILES else "PME"
        skills, avail = _draw(rng, profile)
        out.append(({"person_id": r["rep_id"], "team_id": team_id, "full_name": f"{r['first_name']} {r['last_name']}",
                     "email": r.get("email"), "job_title": JOB_TITLES.get(profile, "Commercial"), "department": profile,
                     "region": r.get("region"), "capacity_hours_week": 35, "availability_pct": avail,
                     "status": "actif" if r.get("status") == "actif" else "inactif",
                     "source": "data_sales_representatives (fictif)"}, skills))
    for pid, name, title, profile in SUPPORT:
        skills, avail = _draw(rng, profile)
        first, last = name.split(" ", 1)
        out.append(({"person_id": pid, "team_id": team_id, "full_name": name,
                     "email": _ascii(f"{first}.{last}").lower() + "@horizon-equipements.example",
                     "job_title": title, "department": profile, "region": "Siège", "capacity_hours_week": 35,
                     "availability_pct": avail, "status": "actif", "source": "fonction support (fictif)"}, skills))
    return out
