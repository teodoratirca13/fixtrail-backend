"""Regulile de prioritizare (deterministe, fără AI).

Regula stabilită de echipă: severitatea e criteriul nr. 1; numărul de
raportări departajează doar între probleme cu aceeași severitate.
Raportările se adună pe tot clusterul (toate tichetele despre aceeași problemă),
altfel o problemă raportată în 3 tichete ar părea de 3 ori mai mică.
"""
SEVERITY_RANK = {"Critică": 1, "Mare": 2, "Medie": 3, "Mică": 4}
UNKNOWN_RANK = 5  # severitate goală (LLM-ul n-a putut decide) => la coadă


def sev_rank(sev: str | None) -> int:
    return SEVERITY_RANK.get(sev or "", UNKNOWN_RANK)


def max_severity(sevs: list[str | None]) -> str | None:
    """Cea mai gravă severitate dintr-o listă (Critică bate Mare etc.)."""
    known = [s for s in sevs if s in SEVERITY_RANK]
    return min(known, key=sev_rank) if known else None


def cluster_sort_key(severitate_max: str | None, total_raportari: int):
    # tuplu: Python compară element cu element, ca un Comparator.thenComparing din Java
    return (sev_rank(severitate_max), -total_raportari)


def ticket_sort_key(cluster_sev: str | None, cluster_total: int, ticket_sev: str | None, nr: int, tid: str):
    # întâi poziția clusterului, apoi, în interiorul lui, tichetele cele mai grave/raportate
    return (sev_rank(cluster_sev), -cluster_total, sev_rank(ticket_sev), -nr, tid)
