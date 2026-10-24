"""Verifică cheia Gemini pe ambele moduri și spune ce să puneți în .env.

Rulare (din folderul fixtrail-backend):  python -m app.check_gemini
"""
from . import llm
from .config import GEMINI_API_KEY, GEMINI_EMBED_MODEL, GEMINI_MODEL


def try_mode(vertex: bool) -> tuple[bool, bool]:
    name = "vertex" if vertex else "gemini"
    c = llm.make_client(vertex)
    gen = emb = False
    try:
        r = c.models.generate_content(model=GEMINI_MODEL, contents="Răspunde doar cu: ok")
        gen = bool(r.text)
        print(f"[{name}] generate_content ({GEMINI_MODEL}): OK → {r.text.strip()[:30]}")
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] generate_content ({GEMINI_MODEL}): EȘUAT → {str(e)[:160]}")
    try:
        r = c.models.embed_content(model=GEMINI_EMBED_MODEL, contents=["test"])
        emb = bool(r.embeddings and r.embeddings[0].values)
        print(f"[{name}] embed_content ({GEMINI_EMBED_MODEL}): OK → {len(r.embeddings[0].values)} dimensiuni")
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] embed_content ({GEMINI_EMBED_MODEL}): EȘUAT → {str(e)[:160]}")
    return gen, emb


if __name__ == "__main__":
    if not GEMINI_API_KEY:
        raise SystemExit("Nu există GEMINI_API_KEY în .env")
    print(f"Cheie: {GEMINI_API_KEY[:6]}… | detectat automat: {'vertex' if llm.use_vertex() else 'gemini'}\n")
    results = {mode: try_mode(mode == "vertex") for mode in ("gemini", "vertex")}
    best = next((m for m, (g, e) in results.items() if g and e), None) or next((m for m, (g, _) in results.items() if g), None)
    print()
    if best:
        print(f"→ Puneți în .env: GEMINI_BACKEND={best}")
        if not results[best][1]:
            print("  Embeddings nu merg pe acest mod: puneți CLUSTER_MODE=legat")
    else:
        print("→ Niciun mod nu funcționează. Verificați cheia, modelul (GEMINI_MODEL) și conexiunea.")
