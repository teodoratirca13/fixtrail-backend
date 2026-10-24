"""Planurile agentului: o listă de acțiuni dintr-un vocabular fix.

De ce un vocabular fix și nu un agent „liber”: execuția trebuie să fie stabilă
în demo. AI-ul (Gemini) poate GENERA planul din „Pași de verificare”
(PLANNER_MODE=gemini), dar îl execută Playwright, determinist.

Planurile de mai jos sunt scrise de mână pentru cele 4 bug-uri din Wizz Bees
(src/data/bugs.js). Au exact formatul pe care trebuie să-l producă Gemini, deci
servesc și ca fallback, și ca exemplu.

Cheia fiecărui plan = tichetul „rădăcină” al problemei (primul din lanțul
„Tichet legat”). Așa WB-1016 și WB-1029 folosesc amândouă planul WB-1013.
"""

ALLOWED_ACTIONS = ["goto", "fill", "select", "click", "expect_visible", "expect_hidden", "expect_text", "expect_js"]

# Ce știe Gemini despre Wizz Bees când generează un plan (selectoare reale din cod)
CATALOG = """Rute: / (căutare zboruri), /zboruri (rezultate), /rezervare (pași: Pasageri → Bagaje și extra → Locuri → Plată),
/check-in, /cont, /cont/recenzie, /noutati.
Căutare (/): select #from (cod aeroport, ex. OTP), select #to (ex. BCN), input #date (AAAA-LL-ZZ), select #pax (1-9), buton „Caută zboruri”.
Rezultate: buton „Alege zborul” pe fiecare zbor (textul zborului conține numărul și aeronava, ex. „WB 541 · A321neo”).
Rezervare: inputuri #first-0, #last-0 (prenume / nume pasager 1); buton „Continuă” (exact) între pași;
pe pasul Locuri butonul e „Continuă fără locuri” dacă nu e ales un loc.
Bagaje: opțiuni-etichetă „Geantă mică”, „Troler de cabină”, „Bagaj de cală 20 kg”, „Bagaj de cală 32 kg”.
Locuri: harta are selectorul .seatmap; când nu se încarcă apare textul „Se încarcă harta locurilor…”.
Plată: tabel table.summary, câte un rând (tr) pe fiecare poziție, ex. „Bagaj de cală 20 kg, Ana … 189 lei”.
Check-in: input #pnr, input #last, buton „Caută rezervarea”, apoi buton „Fă check-in pentru …”;
succes = textul „Check-in făcut”; eroare = element [role=alert].
Boarding pass: svg[aria-label="Cod de îmbarcare"], pătrățelele sunt rect-uri cu atributul fill."""

# Verifică contrastul pătrățelelor QR față de fundalul alb (WCAG: raport ≥ 4.5).
# Bug-ul face pătrățelele #c9cdd6 (contrast ~1.5); fix-ul corect = #1D2B4F (~13).
QR_CONTRAST_JS = """() => {
  const svg = document.querySelector('svg[aria-label="Cod de îmbarcare"]');
  if (!svg) return false;
  const fills = [...svg.querySelectorAll('rect')].slice(1).map(r => r.getAttribute('fill'));
  if (!fills.length) return false;
  const lum = hex => {
    const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const contrast = (1.05) / (lum(fills[0]) + 0.05);   // fundal alb: L = 1
  window.__fixtrailDetail = 'culoare QR ' + fills[0] + ', contrast ' + contrast.toFixed(1) + ':1 (minim 4.5:1)';
  return contrast >= 4.5;
}"""

# Pașii comuni: căutăm zborul de test OTP → BCN din 13.11.2026 (WB 541, A321neo)
_SEARCH_WB541 = [
    {"actiune": "goto", "path": "/", "descriere": "Deschide pagina de căutare"},
    {"actiune": "select", "selector": "#from", "valoare": "OTP", "descriere": "Alege plecarea: București (OTP)"},
    {"actiune": "select", "selector": "#to", "valoare": "BCN", "descriere": "Alege destinația: Barcelona (BCN)"},
    {"actiune": "fill", "selector": "#date", "valoare": "2026-11-13", "descriere": "Alege data 13.11.2026"},
    {"actiune": "click", "text": "Caută zboruri", "descriere": "Apasă „Caută zboruri”"},
    {"actiune": "click", "text": "Alege zborul", "descriere": "Alege zborul WB 541 (A321neo)"},
    {"actiune": "fill", "selector": "#first-0", "valoare": "Ana", "descriere": "Completează prenumele pasagerului"},
    {"actiune": "fill", "selector": "#last-0", "valoare": "Test", "descriere": "Completează numele pasagerului"},
    {"actiune": "click", "text": "Continuă", "descriere": "Continuă la „Bagaje și extra”"},
]

HAND_PLANS: dict[str, dict] = {
    # Check-in-ul eșuează pentru grupuri de peste 4 pasageri
    "WB-1027": {"pasi": [
        {"actiune": "goto", "path": "/check-in", "descriere": "Deschide pagina „Check-in”"},
        {"actiune": "fill", "selector": "#pnr", "valoare": "BEE5X2", "descriere": "Introdu codul rezervării BEE5X2"},
        {"actiune": "fill", "selector": "#last", "valoare": "Popescu", "descriere": "Introdu numele Popescu"},
        {"actiune": "click", "text": "Caută rezervarea", "descriere": "Apasă „Caută rezervarea”"},
        {"actiune": "click", "text": "Fă check-in pentru toți cei 6 pasageri", "descriere": "Apasă „Fă check-in pentru toți cei 6 pasageri”"},
        {"actiune": "expect_visible", "text": "Check-in făcut", "descriere": "Verifică: apare confirmarea „Check-in făcut”"},
        {"actiune": "expect_hidden", "text": "Ceva nu a mers bine", "descriere": "Verifică: nu apare eroarea „Ceva nu a mers bine”"},
    ]},
    # Codul QR de pe boarding pass e prea șters
    "WB-1022": {"pasi": [
        {"actiune": "goto", "path": "/check-in", "descriere": "Deschide pagina „Check-in”"},
        {"actiune": "fill", "selector": "#pnr", "valoare": "HNY42K", "descriere": "Introdu codul rezervării HNY42K"},
        {"actiune": "fill", "selector": "#last", "valoare": "Ionescu", "descriere": "Introdu numele Ionescu"},
        {"actiune": "click", "text": "Caută rezervarea", "descriere": "Apasă „Caută rezervarea”"},
        {"actiune": "click", "text": "Fă check-in pentru pasager", "descriere": "Apasă „Fă check-in pentru pasager”"},
        {"actiune": "expect_visible", "selector": "svg[aria-label=\"Cod de îmbarcare\"]", "descriere": "Verifică: boarding pass-ul are cod QR"},
        {"actiune": "expect_js", "script": QR_CONTRAST_JS, "descriere": "Verifică: codul QR are contrast suficient pentru scanare"},
    ]},
    # Harta locurilor nu se încarcă pe A321neo
    "WB-1013": {"pasi": _SEARCH_WB541 + [
        {"actiune": "click", "text": "Continuă", "descriere": "Continuă la pasul „Locuri”"},
        {"actiune": "expect_visible", "selector": ".seatmap", "descriere": "Verifică: harta locurilor se afișează"},
        {"actiune": "expect_hidden", "text": "Se încarcă harta locurilor", "descriere": "Verifică: harta nu rămâne blocată la încărcare"},
    ]},
    # Prețul bagajului de cală crește la plată
    "WB-1008": {"pasi": _SEARCH_WB541 + [
        {"actiune": "click", "text": "Bagaj de cală 20 kg", "descriere": "Alege „Bagaj de cală 20 kg” (afișat: 189 lei)"},
        {"actiune": "click", "text": "Continuă", "descriere": "Continuă la pasul „Locuri”"},
        {"actiune": "click", "text": "Continuă fără locuri", "descriere": "Continuă la pasul „Plată”"},
        {"actiune": "expect_text", "selector": "table.summary tr:has-text(\"Bagaj de cală 20 kg\")", "text": "189 lei",
         "descriere": "Verifică: la plată bagajul costă tot 189 lei"},
    ]},
}


def root_of(tid: str, links: dict[str, str | None]) -> str:
    """Urcă pe lanțul „Tichet legat” până la tichetul original."""
    seen = set()
    while links.get(tid) and tid not in seen:
        seen.add(tid)
        tid = links[tid]
    return tid


def hand_plan_for(tid: str, links: dict[str, str | None]) -> dict | None:
    return HAND_PLANS.get(tid) or HAND_PLANS.get(root_of(tid, links))


def is_valid(plan: dict | None) -> bool:
    return bool(plan) and isinstance(plan.get("pasi"), list) and len(plan["pasi"]) > 0 and all(
        isinstance(p, dict) and p.get("actiune") in ALLOWED_ACTIONS for p in plan["pasi"]
    )
