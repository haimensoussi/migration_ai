"""Agentic Mesh phase 2 : publication des agents par domaine, validée par le responsable du domaine.

Règles (décisions du 19/11/2026) :
- le propriétaire soumet ; seul le domaine de la fiche contrat est obligatoire (fiche incomplète = avertissement) ;
- valident : les responsables du domaine (table domain_owners), à défaut les administrateurs DISCOVERY ;
- une validation porte sur une version précise : si l'agent a changé depuis la soumission, la demande est obsolète ;
- un refus exige un motif ; l'auto-validation (valideur = demandeur) est permise mais tracée ;
- toute publication laisse une ligne dans publication_requests (y compris reprise initiale et chef d'équipe).
"""
from __future__ import annotations

import uuid

from backend import agent_contracts as ac

PENDING, VALIDATED, REFUSED, CANCELLED, OBSOLETE = "en_attente", "validee", "refusee", "annulee", "obsolete"
LABELS = {PENDING: "En attente", VALIDATED: "Validée", REFUSED: "Refusée", CANCELLED: "Annulée", OBSOLETE: "Obsolète"}
ORIGINS = ("soumission", "reprise", "equipe")
AGENT_IN_REVIEW = "en_validation"


class PublicationError(ValueError):
    pass


def admins_of(settings) -> set[str]:
    team = set(getattr(settings, "team_admins", ()) or ())
    return {e.lower() for e in (team or set(getattr(settings, "tool_admins", ()) or ()))}


def validators_for(domaine: str, owners: dict, admins: set[str]) -> tuple[set[str], str]:
    """Valideurs d'un domaine et leur origine : 'domaine' si désignés, sinon 'repli' (administrateurs)."""
    named = {e.lower() for e in owners.get(domaine, [])}
    return (named, "domaine") if named else (set(admins), "repli")


def submission_issues(agent: dict | None, contract: dict | None, user: str) -> tuple[list[str], list[str]]:
    """(bloquants, avertissements) d'une soumission."""
    if not agent:
        return ["Agent introuvable."], []
    errs = []
    if (agent.get("owner") or "").lower() != user.lower():
        errs.append("Seul le propriétaire de l'agent peut le soumettre.")
    if agent.get("status") == "archive":
        errs.append("Un agent archivé ne peut pas être soumis.")
    dom = (contract or {}).get("domaine")
    if dom not in ac.DOMAINES:
        errs.append("Renseignez le domaine dans la fiche contrat (Agent Builder, étape « Fiche contrat »).")
    warns = [] if not contract else ["Fiche contrat incomplète : " + ", ".join(ac.missing(contract))] if ac.missing(contract) else []
    return errs, warns


class PublicationService:
    def __init__(self, sql, settings):
        self.sql, self.s = sql, settings
        self.contracts = ac.ContractRepository(sql, settings)

    def t(self, name: str) -> str:
        return self.s.table(name)

    # -- Lecture -------------------------------------------------------------
    def domain_owners(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.sql.query(f"SELECT domaine, email FROM {self.t('domain_owners')} ORDER BY domaine, email")["rows"]:
            out.setdefault(r["domaine"], []).append(r["email"])
        return out

    def validators(self, domaine: str) -> tuple[set[str], str]:
        return validators_for(domaine, self.domain_owners(), admins_of(self.s))

    def can_validate(self, user: str, domaine: str) -> bool:
        return user.lower() in self.validators(domaine)[0]

    def validable_domains(self, user: str) -> list[str]:
        owners, admins = self.domain_owners(), admins_of(self.s)
        return [d for d in ac.DOMAINES if user.lower() in validators_for(d, owners, admins)[0]]

    def _agent(self, agent_id: str) -> dict | None:
        r = self.sql.query(f"SELECT agent_id, name, owner, status, current_version FROM {self.t('agents')} "
                           "WHERE agent_id = :a", {"a": agent_id})["rows"]
        return r[0] if r else None

    def requests(self, status: str | None = None, agent_id: str | None = None, limit: int = 200) -> list[dict]:
        where, p = [], {}
        if status:
            where.append("r.status = :s")
            p["s"] = status
        if agent_id:
            where.append("r.agent_id = :a")
            p["a"] = agent_id
        w = ("WHERE " + " AND ".join(where)) if where else ""
        return self.sql.query(f"""
            SELECT r.*, a.name AS agent_name, a.current_version AS agent_current_version, a.status AS agent_status
            FROM {self.t('publication_requests')} r LEFT JOIN {self.t('agents')} a ON a.agent_id = r.agent_id
            {w} ORDER BY r.requested_at DESC LIMIT {int(limit)}""", p or None)["rows"]

    def pending_for(self, user: str) -> list[dict]:
        doms = set(self.validable_domains(user))
        return [r for r in self.requests(PENDING) if r.get("domaine") in doms]

    # -- Écriture -------------------------------------------------------------
    def _set_agent_status(self, agent_id: str, status: str) -> None:
        self.sql.execute(f"UPDATE {self.t('agents')} SET status = :s, updated_at = current_timestamp() "
                         "WHERE agent_id = :a", {"a": agent_id, "s": status})

    def _close_pending(self, agent_id: str, status: str, user: str, note: str) -> None:
        self.sql.execute(f"""
            UPDATE {self.t('publication_requests')} SET status = :s, decided_by = :u, decided_at = current_timestamp(),
                   decision_note = :n WHERE agent_id = :a AND status = '{PENDING}'""",
            {"a": agent_id, "s": status, "u": user, "n": note})

    def _insert(self, agent: dict, contract: dict | None, user: str, status: str, origin: str,
                note: str | None = None, decided_by: str | None = None) -> str:
        rid = uuid.uuid4().hex
        self.sql.execute(f"""
            INSERT INTO {self.t('publication_requests')} (request_id, agent_id, agent_version, domaine,
              contract_version, contract_completeness, status, origin, requested_by, requested_at,
              decided_by, decided_at, decision_note, self_validation)
            VALUES (:id, :a, CAST(:v AS INT), CAST(:d AS STRING), CAST(:cv AS INT), CAST(:cc AS DOUBLE), :s, :o, :u,
                    current_timestamp(), CAST(:db AS STRING),
                    CASE WHEN :db IS NULL THEN NULL ELSE current_timestamp() END, CAST(:n AS STRING),
                    CAST(:sv AS BOOLEAN))""",
            {"id": rid, "a": agent["agent_id"], "v": int(agent["current_version"]),
             "d": (contract or {}).get("domaine") or None,
             "cv": int(contract["version"]) if contract and contract.get("version") else None,
             "cc": ac.completeness(contract), "s": status, "o": origin, "u": user, "db": decided_by, "n": note,
             "sv": (decided_by or "").lower() == user.lower() if decided_by else None})
        return rid

    def submit(self, agent_id: str, user: str) -> tuple[str, list[str]]:
        """Soumet la version courante ; une demande en attente pour le même agent est remplacée."""
        agent = self._agent(agent_id)
        contract = self.contracts.latest(agent_id) if agent else None
        errs, warns = submission_issues(agent, contract, user)
        if errs:
            raise PublicationError(" ".join(errs))
        self._close_pending(agent_id, CANCELLED, user, "Remplacée par une nouvelle soumission")
        rid = self._insert(agent, contract, user, PENDING, "soumission")
        # Un agent publié resoumis quitte la Marketplace : sa version courante n'est pas encore validée
        self._set_agent_status(agent_id, AGENT_IN_REVIEW)
        return rid, warns

    def cancel(self, agent_id: str, user: str) -> None:
        agent = self._agent(agent_id)
        if not agent or (agent.get("owner") or "").lower() != user.lower():
            raise PublicationError("Seul le propriétaire peut annuler la demande.")
        self._close_pending(agent_id, CANCELLED, user, "Annulée par le propriétaire")
        if agent["status"] == AGENT_IN_REVIEW:
            self._set_agent_status(agent_id, "brouillon")

    def decide(self, request_id: str, user: str, approve: bool, note: str = "") -> str:
        """Valide ou refuse ; renvoie le nouveau statut de la demande.

        Ordre des écritures : la demande d'abord, puis l'agent. Si la 2e écriture échoue, la demande reste la
        trace de la décision et resync_agent() réaligne le statut de l'agent (pas de publication sans trace).
        """
        rows = self.sql.query(f"SELECT * FROM {self.t('publication_requests')} WHERE request_id = :r",
                              {"r": request_id})["rows"]
        if not rows:
            raise PublicationError("Demande introuvable.")
        req = rows[0]
        if req["status"] != PENDING:
            raise PublicationError(f"Demande déjà traitée ({LABELS.get(req['status'], req['status'])}).")
        if not self.can_validate(user, req.get("domaine") or ""):
            raise PublicationError(f"Vous n'êtes pas valideur du domaine {req.get('domaine') or '—'}.")
        note = (note or "").strip()
        if not approve and not note:
            raise PublicationError("Un refus doit être motivé.")
        agent = self._agent(req["agent_id"])
        if not agent or int(agent["current_version"]) != int(req["agent_version"]):
            self._close_pending(req["agent_id"], OBSOLETE, user, "L'agent a changé depuis la soumission")
            if agent and agent.get("status") == AGENT_IN_REVIEW:   # plus de demande en attente : retour brouillon
                self._set_agent_status(req["agent_id"], "brouillon")
            raise PublicationError("L'agent a été modifié depuis la soumission : demande obsolète, à resoumettre.")
        status = VALIDATED if approve else REFUSED
        self.sql.execute(f"""
            UPDATE {self.t('publication_requests')} SET status = :s, decided_by = :u, decided_at = current_timestamp(),
                   decision_note = CAST(:n AS STRING), self_validation = CAST(:sv AS BOOLEAN)
            WHERE request_id = :r AND status = '{PENDING}'""",
            {"r": request_id, "s": status, "u": user, "n": note or None,
             "sv": user.lower() == (req.get("requested_by") or "").lower()})
        self._set_agent_status(req["agent_id"], "publie" if approve else "brouillon")
        return status

    def record(self, agent_id: str, user: str, origin: str, note: str) -> str:
        """Publication tracée hors soumission (reprise initiale, chef d'équipe publié par un administrateur)."""
        if origin not in ORIGINS or origin == "soumission":
            raise PublicationError(origin)
        agent = self._agent(agent_id)
        if not agent:
            raise PublicationError("Agent introuvable.")
        if origin == "equipe" and user.lower() not in admins_of(self.s):
            raise PublicationError("Seul un administrateur publie un chef d'équipe.")
        rid = self._insert(agent, self.contracts.latest(agent_id), agent["owner"], VALIDATED, origin, note,
                           decided_by=user)
        self._set_agent_status(agent_id, "publie")
        return rid

    def resync_agent(self, agent_id: str) -> None:
        """Réaligne le statut de l'agent sur sa dernière décision (après une écriture interrompue)."""
        last = self.requests(agent_id=agent_id, limit=1)
        if last and last[0]["status"] in (VALIDATED, REFUSED):
            self._set_agent_status(agent_id, "publie" if last[0]["status"] == VALIDATED else "brouillon")

    def set_domain_owners(self, domaine: str, emails: list[str], user: str) -> None:
        if user.lower() not in admins_of(self.s):
            raise PublicationError("Seul un administrateur désigne les responsables de domaine.")
        if domaine not in ac.DOMAINES:
            raise PublicationError(f"Domaine inconnu : {domaine}")
        clean = sorted({e.strip().lower() for e in emails if e.strip()})
        bad = [e for e in clean if not ac.EMAIL.match(e)]
        if bad:
            raise PublicationError("E-mails invalides : " + ", ".join(bad))
        rows = ", ".join(f"(:d, :e{i}, :u, current_timestamp())" for i in range(len(clean)))
        params = {"d": domaine, "u": user, **{f"e{i}": e for i, e in enumerate(clean)}}
        # Remplacement atomique de la liste du domaine (une seule instruction)
        if clean:
            self.sql.execute(f"INSERT INTO {self.t('domain_owners')} REPLACE WHERE domaine = :d "
                             f"VALUES {rows}", params)
        else:
            self.sql.execute(f"DELETE FROM {self.t('domain_owners')} WHERE domaine = :d", {"d": domaine})
