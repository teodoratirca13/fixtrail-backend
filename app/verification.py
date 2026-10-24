"""Orchestrarea verificărilor: ce tichete testăm, cu ce plan, și ce facem cu rezultatul.

Regulile de business (stabilite de echipă):
- testăm DOAR tichetele cu status „Rezolvat – fix livrat” care au pași de verificare;
- test trecut  → statusul rămâne, salvăm doar ultima verificare (OK + data);
- test picat   → status „În lucru”, data deschiderii = azi, redeschisDeAgent = true;
- eroare       → (ex. Wizz Bees oprit) nu schimbăm statusul, doar raportăm;
- „Nou”, „În lucru”, „Închis – nu se reproduce” → nu se întâmplă nimic.
"""
import datetime as dt
import json
import logging
import re
import threading
import uuid

from . import llm, repository
from .agent import plans
from .agent.runner import AgentSession, run_plan
from .config import PLANNER_MODE, PUBLIC_URL, SCREENSHOT_DIR
from .db import kv_get
from .models import STATUS_FIXED, STATUS_IN_PROGRESS, PasRaport, Raport, SchedulerStatus, Settings

log = logging.getLogger("fixtrail.verify")

# Starea rulării, citită de GET /api/verify/status
_state = {"running": False, "last_run": None, "next_run": None}
_run_lock = threading.Lock()  # o singură rulare odată (scheduler + buton „Verifică acum”)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def get_settings() -> Settings:
    from .config import DEFAULT_SETTINGS
    return Settings(**{k: kv_get(f"settings.{k}", v) for k, v in DEFAULT_SETTINGS.items()})


def status() -> SchedulerStatus:
    return SchedulerStatus(ruleazaAcum=_state["running"], ultimaRulare=_state["last_run"], urmatoareaRulare=_state["next_run"])


def set_next_run(when: str | None) -> None:
    _state["next_run"] = when


def _expected(pasi: str | None) -> str:
    m = re.search(r"Rezultat așteptat:\s*(.+)", pasi or "", re.S)
    return m.group(1).strip() if m else "comportamentul descris în pașii de verificare"


def _plan_for(t: dict, links: dict) -> dict | None:
    """Ordinea: plan din cache → Gemini (dacă e activat) → plan scris de mână."""
    if t.get("plan_json"):
        cached = json.loads(t["plan_json"])
        if plans.is_valid(cached):
            return cached
    if PLANNER_MODE == "gemini" and t.get("pasi_verificare"):
        generated = llm.generate_plan(t["pasi_verificare"], plans.CATALOG, plans.ALLOWED_ACTIONS)
        if plans.is_valid(generated):
            repository.save_plan(t["id"], generated)  # generat o singură dată, refolosit la fiecare rulare
            return generated
        log.warning("Plan Gemini invalid pentru %s; folosesc planul scris de mână", t["id"])
    return plans.hand_plan_for(t["id"], links)


def _explanation(t: dict, verdict: str, steps: list[dict], expected: str, shot: bytes | None, versiune: str) -> str:
    # Gemini doar pentru testele PICATE: acolo explicația ajută developerul.
    # Pentru „trecut” și „eroare” textul generat din pași e suficient și nu
    # consumă din cota zilnică (planul gratuit are ~20 de cereri/zi).
    ai = llm.explain(t, verdict, steps, expected, shot) if verdict == "picat" else None
    if ai:
        return ai
    # fallback fără Gemini: text construit din rezultatul pașilor
    if verdict == "trecut":
        return f"Toți cei {len(steps)} pași au trecut pe versiunea {versiune}. Rezultatul așteptat a fost confirmat: {expected}"
    if verdict == "eroare":
        bad = next((s for s in steps if s["rezultat"] == "picat"), None)
        return f"Verificarea nu a putut rula: {bad['detalii'] if bad else 'eroare necunoscută'}. Statusul tichetului nu a fost modificat."
    bad = next(s for s in steps if s["rezultat"] == "picat")
    fix = t.get("versiune_fix") or "versiunea anunțată"
    return (f"Fix-ul livrat în {fix} nu a rezolvat problema pe versiunea {versiune}. "
            f"Testul a picat la pasul {bad['nr']} („{bad['actiune']}”): {bad['detalii']}. "
            f"Rezultat așteptat: {expected}")


def verify_one(session: AgentSession, t: dict, links: dict, settings: Settings) -> Raport | None:
    plan = _plan_for(t, links)
    if not plan:
        log.info("%s: nu am plan, sar peste", t["id"])
        return None
    rid = f"R-{t['id']}-{uuid.uuid4().hex[:6]}"
    res = run_plan(session.browser, plan, base_url=settings.wizzBeesUrl, version=settings.versiuneLive,
                   shot_dir=SCREENSHOT_DIR / rid)

    steps = [
        PasRaport(
            nr=s.nr, actiune=s.actiune, rezultat=s.rezultat, detalii=s.detalii,
            selector=s.selector, durataMs=s.durata_ms,
            screenshotUrl=f"{PUBLIC_URL}/screenshots/{rid}/{s.screenshot.rsplit('/', 1)[-1]}" if s.screenshot else None,
        )
        for s in res.steps
    ]
    expected = _expected(t.get("pasi_verificare"))
    when = now_iso()
    status_before = t["status"]
    status_after = STATUS_IN_PROGRESS if res.verdict == "picat" else status_before

    raport = Raport(
        id=rid, ticketId=t["id"], data=when, versiuneTestata=settings.versiuneLive, verdict=res.verdict,
        pasi=steps,
        explicatieAI=_explanation(t, res.verdict, [s.model_dump() for s in steps], expected, res.last_screenshot, settings.versiuneLive),
        statusInainte=status_before, statusDupa=status_after, durataSecunde=res.durata,
        eroriDom=res.console_errors[:20], stackTrace=res.stack,
    )
    repository.save_report(raport)
    repository.apply_verification(
        t["id"], verdict=res.verdict, data=when, versiune=settings.versiuneLive, raport_id=rid,
        new_status=STATUS_IN_PROGRESS if res.verdict == "picat" else None,
        reopen_date=dt.date.today().isoformat() if res.verdict == "picat" else None,
    )
    log.info("%s: %s (%.1fs)", t["id"], res.verdict, res.durata)
    return raport


def eligible(ticket_ids: list[str] | None = None) -> list[dict]:
    rows = repository.raw_tickets()
    out = [r for r in rows if r["status"] == STATUS_FIXED and r["pasi_verificare"]]
    if ticket_ids:
        out = [r for r in out if r["id"] in set(ticket_ids)]
    return out


def run_verification(ticket_ids: list[str] | None = None) -> list[Raport]:
    """Rulează sincron (în thread-ul apelantului). Întoarce rapoartele generate."""
    if not _run_lock.acquire(blocking=False):
        log.info("O verificare rulează deja; ignor cererea")
        return []
    _state["running"] = True
    reports: list[Raport] = []
    try:
        todo = eligible(ticket_ids)
        if not todo:
            return []
        settings = get_settings()
        links = {r["id"]: r["tichet_legat"] for r in repository.raw_tickets()}
        with AgentSession() as session:
            for t in todo:
                try:
                    r = verify_one(session, t, links, settings)
                    if r:
                        reports.append(r)
                except Exception:  # noqa: BLE001 — un tichet stricat nu oprește restul
                    log.exception("Verificarea %s a eșuat", t["id"])
        return reports
    finally:
        _state["running"] = False
        _state["last_run"] = now_iso()
        _run_lock.release()


def run_in_background(ticket_ids: list[str] | None = None) -> None:
    """Pentru butonul „Verifică acum”: răspundem imediat, testele rulează în fundal."""
    if _state["running"]:
        return
    _state["running"] = True  # setat imediat, ca răspunsul HTTP să arate deja „rulează”
    def _target():
        _state["running"] = False  # run_verification îl setează din nou sub lock
        run_verification(ticket_ids)
    threading.Thread(target=_target, daemon=True, name="fixtrail-run").start()
