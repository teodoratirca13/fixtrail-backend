"""Tot ce vorbește cu Gemini stă aici, într-un singur loc.

Fiecare funcție are un fallback determinist: dacă nu există cheie sau Gemini
dă eroare, aplicația merge mai departe. Pentru un demo live asta e esențial:
o eroare de rețea nu are voie să oprească pipeline-ul.
"""
import json
import logging
import time
from typing import Literal, Optional

from pydantic import BaseModel

from .config import GEMINI_API_KEY, GEMINI_BACKEND, GEMINI_EMBED_MODEL, GEMINI_MODEL

log = logging.getLogger("fixtrail.llm")
_client = None


def enabled() -> bool:
    return bool(GEMINI_API_KEY)


# Planul gratuit Gemini are o cotă mică de cereri de generare pe zi (ex. 20).
# După un 429 / RESOURCE_EXHAUSTED nu mai încercăm o vreme: altfel fiecare
# rulare a agentului ar pierde timp și ar umple log-ul cu aceeași eroare.
# Embeddings au cotă separată și nu sunt afectate.
_gen_blocked_until = 0.0
QUOTA_PAUSE_SECONDS = 15 * 60


def gen_available() -> bool:
    return enabled() and time.time() >= _gen_blocked_until


def _note_error(e: Exception) -> None:
    global _gen_blocked_until
    if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
        _gen_blocked_until = time.time() + QUOTA_PAUSE_SECONDS
        log.warning("Cota Gemini epuizată: pauză %d min pentru generare (folosesc variantele de rezervă)",
                    QUOTA_PAUSE_SECONDS // 60)


def use_vertex() -> bool:
    """Implicit Gemini API (merge și cu cheile noi „AQ.”); GEMINI_BACKEND=vertex
    doar pentru proiecte Google Cloud cu Vertex AI activat."""
    return GEMINI_BACKEND == "vertex"


def make_client(vertex: bool):
    from google import genai  # import aici: aplicația pornește și fără pachet configurat
    return genai.Client(api_key=GEMINI_API_KEY, vertexai=True) if vertex else genai.Client(api_key=GEMINI_API_KEY)


def client():
    """Clientul Gemini, creat o singură dată (lazy), doar dacă avem cheie."""
    global _client
    if _client is None:
        _client = make_client(use_vertex())
    return _client


# ---------------------------------------------------------------------------
# 1. Severitate pentru tichetele noi (coloana goală în Excel)
# ---------------------------------------------------------------------------
class SeverityItem(BaseModel):
    id: str
    severitate: Literal["Critică", "Mare", "Medie", "Mică"]


def classify_severity(to_classify: list[dict], examples: list[dict]) -> dict[str, str]:
    """Întoarce {id_tichet: severitate}. Exemplele = tichete cu severitate deja decisă,
    ca LLM-ul să judece la fel ca în restul datelor (few-shot)."""
    if not gen_available() or not to_classify:
        return {}
    from google.genai import types

    ex_lines = "\n".join(
        f"- [{e['severitate']}] {e['titlu']} — {e['descriere']} ({e['nr_raportari']} raportări)" for e in examples[:15]
    )
    items = "\n".join(
        f"- id={t['id']}: {t['titlu']} — {t['descriere']} ({t['nr_raportari']} raportări, categoria {t['categorie']})"
        for t in to_classify
    )
    prompt = f"""Ești analist de suport pentru site-ul unei companii aeriene.
Clasifică severitatea fiecărui tichet nou: Critică, Mare, Medie sau Mică.
Criterii: Critică = clientul pierde bani, zborul sau nu poate finaliza un flux esențial (plată, check-in);
Mare = un flux important e blocat sau produce costuri; Medie = neplăcut, dar există ocolire;
Mică = cosmetic sau informativ.

Exemple deja clasificate de echipă:
{ex_lines}

Tichete de clasificat:
{items}"""
    wanted = {t["id"] for t in to_classify}
    # Încercarea 1: JSON cu schemă (cel mai strict). Încercarea 2: JSON simplu,
    # pentru modelele care resping schema; răspunsul e normalizat oricum.
    attempts = [
        dict(response_mime_type="application/json", response_schema=list[SeverityItem]),
        dict(response_mime_type="application/json"),
    ]
    plain_hint = '\n\nRăspunde DOAR cu o listă JSON: [{"id": "WB-....", "severitate": "Critică|Mare|Medie|Mică"}]'
    for i, cfg in enumerate(attempts, start=1):
        try:
            resp = client().models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt if i == 1 else prompt + plain_hint,
                config=types.GenerateContentConfig(**cfg),
            )
            result = _parse_severities(resp.text, wanted)
            if result:
                log.info("Severitate LLM (încercarea %d): %s", i, result)
                return result
            log.warning("Severitate LLM (încercarea %d): răspuns fără valori valide: %s", i, (resp.text or "")[:300])
        except Exception as e:  # noqa: BLE001 — orice eroare => următoarea încercare / fallback
            log.warning("Gemini severity failed (încercarea %d): %s", i, str(e)[:200])
            _note_error(e)
            if not gen_available():
                break  # cotă epuizată: a doua încercare ar pica la fel
    return {}


_SEV_NORMAL = {"critica": "Critică", "critică": "Critică", "mare": "Mare", "medie": "Medie", "mica": "Mică", "mică": "Mică"}


def _parse_severities(text: str | None, wanted: set[str]) -> dict[str, str]:
    """Acceptă ```json ...``` sau listă simplă; normalizează diacriticele și ID-urile („id=WB-1044”)."""
    if not text:
        return {}
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(raw[raw.find("[") : raw.rfind("]") + 1] if "[" in raw else raw)
    if isinstance(data, dict):  # ex. {"tichete": [...]}
        data = next((v for v in data.values() if isinstance(v, list)), [])
    out = {}
    for d in data:
        tid = str(d.get("id", "")).replace("id=", "").strip()
        sev = _SEV_NORMAL.get(str(d.get("severitate", "")).strip().lower())
        if tid in wanted and sev:
            out[tid] = sev
    return out


# ---------------------------------------------------------------------------
# 2. Embeddings pentru gruparea reclamațiilor despre aceeași problemă
# ---------------------------------------------------------------------------
def embed(texts: list[str]) -> Optional[list[list[float]]]:
    if not enabled():
        return None
    try:
        out: list[list[float]] = []
        for i in range(0, len(texts), 50):  # loturi mici, ca să nu lovim limita per request
            res = client().models.embed_content(model=GEMINI_EMBED_MODEL, contents=texts[i : i + 50])
            out.extend(e.values for e in res.embeddings)
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini embeddings failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# 3. Explicația pentru developer (cu screenshot-ul final, prin Gemini Vision)
# ---------------------------------------------------------------------------
def explain(ticket: dict, verdict: str, steps: list[dict], expected: str, screenshot: Optional[bytes]) -> Optional[str]:
    if not gen_available():
        return None
    from google.genai import types

    steps_txt = "\n".join(f"{s['nr']}. {s['actiune']} → {s['rezultat']}" + (f" ({s['detalii']})" if s.get("detalii") else "") for s in steps)
    prompt = f"""Ești un QA engineer. Un agent automat a verificat dacă fix-ul pentru un tichet chiar funcționează.
Tichet {ticket['id']}: {ticket['titlu']}
Descriere: {ticket['descriere']}
Fix livrat în versiunea: {ticket.get('versiune_fix') or 'necunoscută'}
Rezultat așteptat: {expected}
Pașii executați:
{steps_txt}
Verdict: {verdict}

Scrie în română, 2-3 propoziții, pentru developer: ce s-a întâmplat, unde exact a picat (dacă a picat)
și ce se vede în screenshot-ul atașat. Fără introduceri, fără markdown."""
    contents: list = [prompt]
    if screenshot:
        contents.append(types.Part.from_bytes(data=screenshot, mime_type="image/png"))
    try:
        resp = client().models.generate_content(model=GEMINI_MODEL, contents=contents)
        return (resp.text or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini explain failed: %s", str(e)[:200])
        _note_error(e)
        return None


# ---------------------------------------------------------------------------
# 4. Planul agentului, generat din „Pași de verificare” (PLANNER_MODE=gemini)
# ---------------------------------------------------------------------------
def generate_plan(steps_text: str, catalog: str, allowed_actions: list[str]) -> Optional[dict]:
    if not gen_available():
        return None
    from google.genai import types

    prompt = f"""Transformă pașii de verificare scriși de un developer într-un plan JSON pentru Playwright.
Folosește DOAR aceste acțiuni: {', '.join(allowed_actions)}.
Format: {{"pasi": [{{"actiune": "...", "descriere": "text scurt în română", ...câmpuri}}]}}
Câmpuri: goto{{path}}, fill{{selector, valoare}}, select{{selector, valoare}}, click{{text}} (textul vizibil al butonului
sau etichetei), expect_visible{{text sau selector}}, expect_hidden{{text sau selector}},
expect_text{{selector, text}}, expect_js{{script}} (o funcție JS fără argumente care întoarce true/false).
Ultimii pași trebuie să fie aserțiuni care verifică „Rezultat așteptat”.

Ce știi despre aplicație (folosește exact aceste selectoare și texte):
{catalog}

Pașii developerului:
{steps_text}"""
    try:
        resp = client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        plan = json.loads(resp.text)
        return plan if isinstance(plan, dict) and isinstance(plan.get("pasi"), list) else None
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini plan failed: %s", str(e)[:200])
        _note_error(e)
        return None
