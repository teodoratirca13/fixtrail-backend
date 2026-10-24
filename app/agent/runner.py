"""Execuția unui plan cu Playwright (API sincron).

Rulează într-un thread separat de serverul FastAPI (vezi verification.py), de
aceea folosim API-ul sincron: e mai simplu de citit și nu se bate cu event
loop-ul lui uvicorn.

Reguli importante:
- fiecare test pornește într-un browser context NOU (localStorage gol), altfel
  un check-in reușit rămâne salvat și testul următor n-ar mai avea ce verifica;
- versiunea „live” se injectează în localStorage înainte de încărcarea paginii,
  exact cum o salvează Wizz Bees (cheia „wb.version”, valoare JSON);
- o acțiune care nu găsește elementul (ex. harta de locuri nu apare) = test PICAT;
  aplicația inaccesibilă (connection refused) = EROARE, nu schimbă statusul.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, Page, TimeoutError as PWTimeout, expect, sync_playwright

from ..config import HEADLESS, STEP_TIMEOUT_MS


@dataclass
class StepResult:
    nr: int
    actiune: str
    rezultat: str  # ok | picat | neexecutat
    detalii: str | None = None
    screenshot: str | None = None  # cale locală; URL-ul public îl face verification.py
    selector: str | None = None
    durata_ms: int | None = None


@dataclass
class RunResult:
    verdict: str  # trecut | picat | eroare
    steps: list[StepResult] = field(default_factory=list)
    durata: float = 0.0
    last_screenshot: bytes | None = None
    console_errors: list[str] = field(default_factory=list)
    stack: str | None = None


class AppUnreachable(Exception):
    pass


def _button(page: Page, text: str):
    """Găsește un element clickabil după textul vizibil: întâi buton cu nume exact,
    apoi buton care conține textul, apoi orice element cu textul (ex. o etichetă)."""
    exact = page.get_by_role("button", name=text, exact=True)
    if exact.count():
        return exact.first
    partial = page.get_by_role("button", name=text)
    if partial.count():
        return partial.first
    return page.get_by_text(text).first


def _do(page: Page, step: dict, base_url: str) -> str | None:
    """Execută un pas. Întoarce un detaliu opțional; aruncă AssertionError/timeout la eșec."""
    a = step["actiune"]
    t = STEP_TIMEOUT_MS
    if a == "goto":
        try:
            page.goto(base_url.rstrip("/") + step.get("path", "/"), wait_until="domcontentloaded", timeout=15000)
        except Exception as e:  # noqa: BLE001
            if "ERR_CONNECTION_REFUSED" in str(e) or "ECONNREFUSED" in str(e):
                raise AppUnreachable(f"Aplicația nu răspunde la {base_url}") from e
            raise
    elif a == "fill":
        page.locator(step["selector"]).first.fill(str(step["valoare"]), timeout=t)
    elif a == "select":
        page.locator(step["selector"]).first.select_option(str(step["valoare"]), timeout=t)
    elif a == "click":
        # mic răgaz: unele butoane apar după o tranziție de pagină
        target = _button(page, step["text"])
        target.wait_for(state="visible", timeout=t)
        target.click(timeout=t)
    elif a == "expect_visible":
        what = step.get("text") or step.get("selector")
        loc = page.locator(step["selector"]).first if step.get("selector") else page.get_by_text(step["text"]).first
        try:
            expect(loc).to_be_visible(timeout=t)
        except AssertionError:
            # mesaj pentru oameni, nu pentru Playwright; includem ce se vede în locul lui
            hint = _visible_status_text(page)
            raise AssertionError(f"„{what}” nu a apărut în {t // 1000} secunde" + (f"; pagina arată: „{hint}”" if hint else "")) from None
    elif a == "expect_hidden":
        what = step.get("text") or step.get("selector")
        loc = page.locator(step["selector"]) if step.get("selector") else page.get_by_text(step["text"])
        try:
            expect(loc).to_have_count(0, timeout=1500)
        except AssertionError:
            raise AssertionError(f"„{what}” este încă afișat în pagină") from None
    elif a == "expect_text":
        loc = page.locator(step["selector"]).first
        try:
            expect(loc).to_contain_text(step["text"], timeout=t)
        except AssertionError:
            actual = loc.inner_text(timeout=1000).strip().replace("\t", " ") if loc.count() else "elementul lipsește"
            raise AssertionError(f"Așteptat „{step['text']}”, găsit „{actual}”") from None
        return f"găsit: „{loc.inner_text().strip().replace(chr(9), ' ')}”"
    elif a == "expect_js":
        ok = page.evaluate(step["script"])
        detail = page.evaluate("() => window.__fixtrailDetail || null")
        if not ok:
            raise AssertionError(detail or "condiția verificată în pagină este falsă")
        return detail
    else:
        raise ValueError(f"Acțiune necunoscută: {a}")
    return None


def _visible_status_text(page: Page) -> str | None:
    """Caută în pagină un mesaj de stare (alertă sau „se încarcă…”), util în raport."""
    for sel in ("[role=alert]", "[aria-busy=true]"):
        try:
            texts = [x.strip() for x in page.locator(sel).all_inner_texts() if x.strip()]
            if texts:
                return texts[0]
        except Exception:  # noqa: BLE001
            pass
    return None


def _failure_detail(page: Page, err: Exception) -> str:
    """Un mesaj util pentru developer: alertele din pagină bat mesajul tehnic Playwright."""
    if isinstance(err, AssertionError) and str(err):
        return str(err)  # mesajele noastre din _do sunt deja clare
    hint = _visible_status_text(page)
    if hint:
        return "Pagina afișează: „" + hint + "”"
    msg = str(err).splitlines()[0] if str(err) else err.__class__.__name__
    if isinstance(err, PWTimeout) or "Timeout" in msg:
        return "Elementul așteptat nu a apărut în timpul alocat"
    return msg[:300]


def run_plan(browser: Browser, plan: dict, *, base_url: str, version: str, shot_dir: Path) -> RunResult:
    shot_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    ctx = browser.new_context(viewport={"width": 1280, "height": 860}, locale="ro-RO")
    # rulează înainte de orice script al paginii, la fiecare navigare
    ctx.add_init_script(f"try {{ localStorage.setItem('wb.version', {json.dumps(json.dumps(version))}) }} catch (e) {{}}")
    page = ctx.new_page()
    result = RunResult(verdict="trecut")
    # erorile JavaScript din pagină ajung în raport (utile developerului)
    page.on("console", lambda m: result.console_errors.append(m.text[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda e: result.console_errors.append(f"Uncaught: {str(e)[:300]}"))
    failed = False
    try:
        for i, step in enumerate(plan["pasi"], start=1):
            label = step.get("descriere") or step["actiune"]
            if failed:
                result.steps.append(StepResult(i, label, "neexecutat", selector=step.get("selector")))
                continue
            shot = shot_dir / f"pas-{i}.png"
            sel = step.get("selector") or (f'text="{step["text"]}"' if step.get("text") else step.get("path"))
            t0 = time.time()
            try:
                detail = _do(page, step, base_url)
                ms = int((time.time() - t0) * 1000)
                page.wait_for_timeout(250)  # lăsăm UI-ul să se așeze înainte de poză
                page.screenshot(path=str(shot))
                result.steps.append(StepResult(i, label, "ok", detail, str(shot), sel, ms))
            except AppUnreachable as e:
                result.verdict = "eroare"
                result.stack = str(e)
                result.steps.append(StepResult(i, label, "picat", str(e), None, sel, int((time.time() - t0) * 1000)))
                failed = True
            except Exception as e:  # noqa: BLE001 — orice eșec al unui pas = test picat
                ms = int((time.time() - t0) * 1000)
                page.screenshot(path=str(shot))
                result.verdict = "picat"
                result.stack = f"{e.__class__.__name__}: {e}"[:2000]
                result.steps.append(StepResult(i, label, "picat", _failure_detail(page, e), str(shot), sel, ms))
                failed = True
        last = next((s.screenshot for s in reversed(result.steps) if s.screenshot), None)
        result.last_screenshot = Path(last).read_bytes() if last else None
    finally:
        ctx.close()
        result.durata = round(time.time() - started, 1)
    return result


class AgentSession:
    """Un browser deschis pentru toată rularea (mai rapid decât unul per test)."""

    def __enter__(self):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=HEADLESS, slow_mo=0 if HEADLESS else 250)
        return self

    def __exit__(self, *exc):
        self.browser.close()
        self._pw.stop()
