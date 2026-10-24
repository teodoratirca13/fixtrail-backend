"""Gruparea tichetelor care descriu aceeași problemă.

Două strategii cu aceeași ieșire ({id_tichet: id_cluster}):
- legat:      după coloana „Tichet legat” (răspunsul „corect”, scris de oameni)
- embeddings: după similaritatea semantică a textului (Gemini embeddings)

Când rulăm cu embeddings, calculăm și cât de bine se potrivesc grupurile găsite
de AI cu legăturile scrise de oameni: o cifră bună pentru pitch.
"""
import logging
import math

from . import llm
from .config import CLUSTER_MODE, SIMILARITY_THRESHOLD

log = logging.getLogger("fixtrail.clustering")


class UnionFind:
    """Structura clasică pentru „cine e în același grup cu cine”.
    find() întoarce reprezentantul grupului; union() unește două grupuri."""

    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # reprezentantul = ID-ul cel mai mic (tichetul original, cel mai vechi)
            lo, hi = sorted([ra, rb])
            self.parent[hi] = lo


def _groups(uf: UnionFind, ids) -> dict[str, str]:
    return {i: f"C-{uf.find(i)}" for i in ids}


def by_link(tickets: list[dict]) -> dict[str, str]:
    ids = [t["id"] for t in tickets]
    uf = UnionFind(ids)
    for t in tickets:
        if t.get("tichet_legat") and t["tichet_legat"] in uf.parent:
            uf.union(t["id"], t["tichet_legat"])
    return _groups(uf, ids)


def _cos(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def by_embeddings(tickets: list[dict]) -> dict[str, str] | None:
    texts = [f"{t['titlu']}. {t['descriere']}" for t in tickets]
    vectors = llm.embed(texts)
    if not vectors:
        return None
    ids = [t["id"] for t in tickets]
    uf = UnionFind(ids)
    # O(n²) pe 43 de tichete = ~900 de comparații: neglijabil
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if _cos(vectors[i], vectors[j]) >= SIMILARITY_THRESHOLD:
                uf.union(ids[i], ids[j])
    return _groups(uf, ids)


def agreement(found: dict[str, str], tickets: list[dict]) -> float | None:
    """Ce procent din legăturile scrise de oameni a regăsit AI-ul (recall)."""
    links = [(t["id"], t["tichet_legat"]) for t in tickets if t.get("tichet_legat") and t["tichet_legat"] in found]
    if not links:
        return None
    hit = sum(1 for a, b in links if found[a] == found[b])
    return round(hit / len(links), 3)


def cluster(tickets: list[dict]) -> tuple[dict[str, str], str, float | None]:
    """Întoarce (mapare tichet→cluster, modul folosit efectiv, acord cu „Tichet legat”)."""
    if CLUSTER_MODE == "embeddings":
        found = by_embeddings(tickets)
        if found:
            return found, "embeddings", agreement(found, tickets)
        log.warning("Embeddings indisponibile; cad pe „Tichet legat”")
    return by_link(tickets), "legat", None
