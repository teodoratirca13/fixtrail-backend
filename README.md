# FixTrail API

Backend-ul FixTrail: importă tichetele din Excel, le prioritizează, le grupează pe probleme și rulează periodic un agent care verifică în Wizz Bees dacă fix-urile livrate chiar funcționează. Contractul API e cel din promptul de Lovable (`src/types.ts`).

## Pornire

```bash
pip install -r requirements.txt
playwright install chromium          # o singură dată
cp .env.example .env                 # puneți GEMINI_API_KEY (sau folosiți .env-ul inclus)
python -m app.check_gemini           # testează cheia și spune ce GEMINI_BACKEND să puneți
python -m app.check_gemini           # verifică dacă cheia Gemini merge

# în alt terminal: Wizz Bees pe http://localhost:5173
cd ../wizz-bees && npm install && npm run dev

uvicorn app.main:app --reload --port 8000
```

Swagger: http://localhost:8000/docs

Import:

```bash
curl -F file=@data/wizz-bees-tichete.xlsx localhost:8000/api/import
```

Dashboard-ul Lovable: `VITE_USE_MOCK=false`, `VITE_API_URL=http://localhost:8000`.

## Endpoint-uri

| Metodă | Rută | Ce face |
|---|---|---|
| GET | `/api/tickets` | Toate tichetele, sortate după prioritate |
| GET | `/api/tickets/{id}` | Un tichet |
| GET | `/api/clusters` | Problemele (grupuri de tichete), sortate după prioritate |
| GET | `/api/stats` | KPI-urile pentru PM |
| GET | `/api/reports?ticketId=` | Rapoartele agentului, cele mai noi primele |
| GET | `/api/reports/{id}` | Un raport, cu pașii și screenshot-urile |
| POST | `/api/import` | Încarcă Excel-ul (multipart, câmpul `file`) |
| POST | `/api/import/reload` | Reîncarcă ultimul Excel = resetează demo-ul (în plus față de contract) |
| POST | `/api/verify/run` | Pornește verificarea în fundal; body opțional `{"ticketIds": [...]}` |
| GET | `/api/verify/status` | Rulează acum? Ultima și următoarea rulare |
| GET/PUT | `/api/settings` | Versiunea live, intervalul, URL-ul Wizz Bees |

Screenshot-urile se servesc din `/screenshots/<raport>/pas-N.png`.

## Structura

```
app/
  main.py          rutele FastAPI + pornirea scheduler-ului
  config.py        setări din .env
  models.py        contractul API (Pydantic) — doar ADĂUGAȚI câmpuri
  db.py            SQLite (tichete, rapoarte, clustere, setări)
  importer.py      Excel → severitate LLM (unde e goală) → clustere → DB
  clustering.py    clustere din „Tichet legat” sau din embeddings Gemini
  priority.py      regula: severitate întâi, apoi raportările din cluster
  repository.py    citiri/scrieri + calcule derivate (prioritate, statistici)
  verification.py  ce testăm, ce plan folosim, regulile de status
  scheduler.py     rularea periodică (APScheduler)
  llm.py           tot ce vorbește cu Gemini, fiecare funcție cu fallback
  agent/
    plans.py       vocabularul de acțiuni + planurile pentru cele 4 bug-uri
    runner.py      execuția cu Playwright, screenshot-uri, verdict
```

## Reguli de status

- Se testează doar tichetele `Rezolvat – fix livrat` care au `Pași de verificare`.
- **Trecut:** statusul rămâne; se salvează ultima verificare.
- **Picat:** status `În lucru`, data deschiderii = azi, `redeschisDeAgent = true`.
- **Eroare** (Wizz Bees oprit): statusul nu se schimbă, apare doar în raport.

## Rezultate verificate pe Wizz Bees

| Versiune live | WB-1008 bagaj | WB-1016/1029 hartă locuri | WB-1022/1036 QR | WB-1027 check-in grup |
|---|---|---|---|---|
| 3.14.0 (curentă) | ✓ trecut | ✓ trecut | ✗ contrast 1.6:1 | ✗ CHK-500 |
| 3.5.0 (regresie) | ✗ 265 lei în loc de 189 | ✗ hartă blocată | ✗ | ✗ |

## Scenariul de demo

1. `POST /api/import` → dashboard-ul PM arată prioritățile.
2. „Verifică acum” → 3 confirmate, 3 redeschise (versiunea 3.14.0).
3. **Regresie:** în Setări, versiunea live = 3.9.0, apoi `POST /api/import/reload` și „Verifică acum” → harta locurilor pică.
4. **Fix adevărat:** în `wizz-bees/src/data/bugs.js`, la `groupCheckIn`, `fixedIn: '3.14.0'` → la rularea următoare check-in-ul trece.
5. Reset între repetiții: `POST /api/import/reload` + versiunea live 3.14.0.

## Unde intră AI-ul (cu `GEMINI_API_KEY`)

| Pas | Cu Gemini | Fără Gemini (fallback) |
|---|---|---|
| Severitate goală în Excel | Clasificare few-shot | Rămâne goală |
| Clustere | Embeddings + similaritate cosinus ≥ 0.85; se raportează acordul cu „Tichet legat” | Coloana „Tichet legat” |
| Plan de test | Generat din „Pași de verificare” (`PLANNER_MODE=gemini`), salvat în cache | Planuri scrise de mână |
| Explicația pentru developer | Gemini Vision pe ultimul screenshot | Text construit din pași |

Un plan generat de Gemini e validat (doar acțiunile permise) și salvat în cache după prima generare. Rulați-l o dată și verificați raportul înainte de demo: un selector greșit produce un fals „picat”.

## Adăugarea unui test nou

1. În Excel, completați `Pași de verificare` pentru tichet.
2. Fie scrieți planul în `agent/plans.py` (cheia = tichetul original din lanțul „Tichet legat”), fie lăsați Gemini să-l genereze (`PLANNER_MODE=gemini`). Dacă e nevoie, completați `CATALOG` cu selectoarele noii pagini.
