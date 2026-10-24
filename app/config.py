"""Configurația aplicației, citită din variabile de mediu (sau din fișierul .env).

De ce variabile de mediu: aceeași bază de cod rulează la voi pe laptop și pe
laptopul de demo, iar cheia Gemini nu ajunge niciodată în cod sau în git.
"""
import os
from pathlib import Path

# Încărcăm .env manual (fără dependență în plus): linii KEY=VALUE
BASE_DIR = Path(__file__).resolve().parent.parent
_env = BASE_DIR / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DATA_DIR = Path(os.getenv("FIXTRAIL_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "fixtrail.db"
SCREENSHOT_DIR = DATA_DIR / "screenshots"

# URL-ul public al acestui API: screenshot-urile din rapoarte se servesc de aici
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")

# Originile din care are voie dashboard-ul (Lovable local, Vite etc.) să ne apeleze
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# --- Gemini ---------------------------------------------------------------
# Fără cheie, tot ce ține de AI cade pe o variantă deterministă (vezi llm.py)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
# gemini (implicit, merge și cu cheile „AQ.”) | vertex = doar pentru Vertex AI
GEMINI_BACKEND = os.getenv("GEMINI_BACKEND", "gemini").lower()

# legat = clustere din coloana „Tichet legat”; embeddings = similaritate semantică
CLUSTER_MODE = os.getenv("CLUSTER_MODE", "embeddings" if GEMINI_API_KEY else "legat")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.85"))

# --- Agent ----------------------------------------------------------------
# hand   = planuri scrise de mână (sigur pentru demo)
# gemini = planul e generat de Gemini din „Pași de verificare” (cu fallback pe hand)
PLANNER_MODE = os.getenv("PLANNER_MODE", "hand")
# false = vedeți browserul cum lucrează agentul (efect bun în demo)
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"
STEP_TIMEOUT_MS = int(os.getenv("STEP_TIMEOUT_MS", "6000"))

# Setări implicite (se pot schimba din dashboard prin PUT /api/settings)
DEFAULT_SETTINGS = {
    "versiuneLive": os.getenv("DEFAULT_VERSION", "3.14.0"),
    "intervalMinute": int(os.getenv("DEFAULT_INTERVAL_MIN", "2")),
    "wizzBeesUrl": os.getenv("WIZZ_BEES_URL", "http://localhost:5173"),
}

DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
