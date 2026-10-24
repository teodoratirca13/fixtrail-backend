"""Citirea și scrierea tichetelor/rapoartelor + calculele derivate
(prioritate, totaluri pe cluster, statistici).

Valorile derivate nu se stochează: se calculează la fiecare citire din datele
brute. Cu 43 de tichete costă microsecunde și nu pot rămâne desincronizate.
"""
import json
from collections import defaultdict

from .db import tx
from .models import (
    ALL_STATUSES, STATUS_FIXED, CategorieStat, Cluster, Raport, Stats, Ticket, UltimaVerificare,
)
from .priority import cluster_sort_key, max_severity, ticket_sort_key


def raw_tickets() -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tickets ORDER BY ordine")]


def raw_ticket(tid: str) -> dict | None:
    with tx() as c:
        r = c.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
    return dict(r) if r else None


def _cluster_info(rows: list[dict]):
    """Pentru fiecare cluster: membrii, severitatea maximă, totalul raportărilor."""
    members = defaultdict(list)
    for r in rows:
        members[r["cluster_id"]].append(r)
    info = {}
    for cid, ms in members.items():
        info[cid] = {
            "members": ms,
            "sev": max_severity([m["severitate"] for m in ms]),
            "total": sum(m["nr_raportari"] or 0 for m in ms),
        }
    return info


def _to_ticket(r: dict, ci: dict, prioritate: int) -> Ticket:
    uv = json.loads(r["ultima_verificare"]) if r["ultima_verificare"] else None
    return Ticket(
        id=r["id"],
        dataDeschiderii=r["data_deschiderii"] or "",
        canal=r["canal"] or "",
        categorie=r["categorie"] or "",
        functionalitate=r["functionalitate"] or "",
        titlu=r["titlu"] or "",
        descriere=r["descriere"] or "",
        pasiVerificare=r["pasi_verificare"],
        severitate=r["severitate"],
        severitateSursa=r["severitate_sursa"] or "excel",
        nrRaportari=r["nr_raportari"] or 0,
        versiuneRaportata=r["versiune_raportata"] or "",
        status=r["status"],
        versiuneFix=r["versiune_fix"],
        dataLivrareFix=r["data_livrare_fix"],
        echipa=r["echipa"] or "",
        tichetLegat=r["tichet_legat"],
        clusterId=r["cluster_id"],
        totalRaportariCluster=ci["total"],
        prioritate=prioritate,
        testabil=bool(r["pasi_verificare"]),
        redeschisDeAgent=bool(r["redeschis_de_agent"]),
        ultimaVerificare=UltimaVerificare(**uv) if uv else None,
    )


def list_tickets() -> list[Ticket]:
    rows = raw_tickets()
    info = _cluster_info(rows)
    ordered = sorted(
        rows,
        key=lambda r: ticket_sort_key(
            info[r["cluster_id"]]["sev"], info[r["cluster_id"]]["total"], r["severitate"], r["nr_raportari"] or 0, r["id"]
        ),
    )
    return [_to_ticket(r, info[r["cluster_id"]], i + 1) for i, r in enumerate(ordered)]


def get_ticket(tid: str) -> Ticket | None:
    return next((t for t in list_tickets() if t.id == tid), None)


def list_clusters() -> list[Cluster]:
    rows = raw_tickets()
    info = _cluster_info(rows)
    with tx() as c:
        titles = {r["id"]: r["titlu"] for r in c.execute("SELECT * FROM clusters")}
    clusters = [
        Cluster(
            id=cid,
            titlu=titles.get(cid) or v["members"][0]["titlu"],
            ticketIds=[m["id"] for m in sorted(v["members"], key=lambda m: m["id"])],
            totalRaportari=v["total"],
            severitateMax=v["sev"],
        )
        for cid, v in info.items()
    ]
    return sorted(clusters, key=lambda c: cluster_sort_key(c.severitateMax, c.totalRaportari))


def stats() -> Stats:
    tickets = list_tickets()
    per_status = {s: 0 for s in ALL_STATUSES}
    cat = defaultdict(lambda: {"raportari": 0, "tichete": 0})
    for t in tickets:
        per_status[t.status] = per_status.get(t.status, 0) + 1
        cat[t.categorie]["raportari"] += t.nrRaportari
        cat[t.categorie]["tichete"] += 1

    fixed = [t for t in tickets if t.status == STATUS_FIXED]
    confirmed = sum(1 for t in fixed if t.ultimaVerificare and t.ultimaVerificare.verdict == "trecut")
    invalidated = sum(1 for t in tickets if t.redeschisDeAgent)
    manual = sum(1 for t in fixed if not t.testabil)
    # Aceeași definiție ca în foaia „Sumar”: tichete legate de o problemă anterioară / fix-uri livrate
    linked = sum(1 for t in tickets if t.tichetLegat)
    rate = round(linked / len(fixed), 4) if fixed else 0.0

    return Stats(
        totalTichete=len(tickets),
        ticheteDisponibile=per_status.get("Nou", 0),
        perStatus=per_status,
        fixuriConfirmate=confirmed,
        fixuriInvalidate=invalidated,
        necesitaVerificareManuala=manual,
        rataRedeschidere=rate,
        raportariPeCategorie=sorted(
            [CategorieStat(categorie=k, **v) for k, v in cat.items()], key=lambda x: -x.raportari
        ),
    )


# --- rapoarte -------------------------------------------------------------
def save_report(r: Raport) -> None:
    with tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO reports(id, ticket_id, data, payload) VALUES (?, ?, ?, ?)",
            (r.id, r.ticketId, r.data, r.model_dump_json()),
        )


def list_reports(ticket_id: str | None = None, limit: int = 200) -> list[Raport]:
    q, args = "SELECT payload FROM reports", []
    if ticket_id:
        q += " WHERE ticket_id = ?"
        args.append(ticket_id)
    q += " ORDER BY data DESC LIMIT ?"
    args.append(limit)
    with tx() as c:
        return [Raport.model_validate_json(r["payload"]) for r in c.execute(q, args)]


def get_report(rid: str) -> Raport | None:
    with tx() as c:
        r = c.execute("SELECT payload FROM reports WHERE id = ?", (rid,)).fetchone()
    return Raport.model_validate_json(r["payload"]) if r else None


# --- actualizări făcute de agent -----------------------------------------
def apply_verification(tid: str, *, verdict: str, data: str, versiune: str, raport_id: str,
                       new_status: str | None, reopen_date: str | None) -> None:
    uv = json.dumps({"verdict": verdict, "data": data, "versiuneTestata": versiune, "raportId": raport_id})
    with tx() as c:
        if new_status:
            c.execute(
                "UPDATE tickets SET ultima_verificare = ?, status = ?, data_deschiderii = ?, redeschis_de_agent = 1 WHERE id = ?",
                (uv, new_status, reopen_date, tid),
            )
        else:
            c.execute("UPDATE tickets SET ultima_verificare = ? WHERE id = ?", (uv, tid))


def save_plan(tid: str, plan: dict) -> None:
    with tx() as c:
        c.execute("UPDATE tickets SET plan_json = ? WHERE id = ?", (json.dumps(plan, ensure_ascii=False), tid))
