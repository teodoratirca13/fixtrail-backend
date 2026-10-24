"""FixTrail API — punctul de intrare FastAPI.

Pornire:  uvicorn app.main:app --reload --port 8000
Docs interactive (Swagger): http://localhost:8000/docs

Endpoint-urile respectă contractul din promptul de Lovable (src/types.ts).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import importer, repository, scheduler, verification
from .config import CORS_ORIGINS, SCREENSHOT_DIR
from .db import init_db, kv_set
from .models import (
    Cluster, ImportResult, Raport, SchedulerStatus, Settings, Stats, Ticket, VerifyRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # la pornire: schema DB + scheduler; la oprire: oprim scheduler-ul curat
    init_db()
    scheduler.start(verification.get_settings().intervalMinute)
    yield
    scheduler.stop()


app = FastAPI(title="FixTrail API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
# screenshot-urile agentului: /screenshots/<raport>/pas-N.png
app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR), name="screenshots")


@app.get("/api/health")
def health():
    return {"ok": True}


# --- tichete & clustere -------------------------------------------------
@app.get("/api/tickets", response_model=list[Ticket])
def tickets():
    return repository.list_tickets()


@app.get("/api/tickets/{ticket_id}", response_model=Ticket)
def ticket(ticket_id: str):
    t = repository.get_ticket(ticket_id)
    if not t:
        raise HTTPException(404, f"Tichetul {ticket_id} nu există")
    return t


@app.get("/api/clusters", response_model=list[Cluster])
def clusters():
    return repository.list_clusters()


@app.get("/api/stats", response_model=Stats)
def stats():
    return repository.stats()


# --- rapoarte -------------------------------------------------------------
@app.get("/api/reports", response_model=list[Raport])
def reports(ticketId: str | None = None):  # noqa: N803 — numele din contract
    return repository.list_reports(ticketId)


@app.get("/api/reports/{report_id}", response_model=Raport)
def report(report_id: str):
    r = repository.get_report(report_id)
    if not r:
        raise HTTPException(404, f"Raportul {report_id} nu există")
    return r


# --- import ---------------------------------------------------------------
@app.post("/api/import", response_model=ImportResult)
async def import_xlsx(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Încarcă un fișier .xlsx")
    try:
        return importer.import_excel(await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/import/reload", response_model=ImportResult)
def import_reload():
    """În plus față de contract: reîncarcă ultimul Excel = resetează scenariul de demo."""
    try:
        return importer.reload_last()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


# --- verificare -----------------------------------------------------------
@app.post("/api/verify/run", response_model=SchedulerStatus)
def verify_run(body: VerifyRequest | None = None):
    verification.run_in_background(body.ticketIds if body else None)
    return verification.status()


@app.get("/api/verify/status", response_model=SchedulerStatus)
def verify_status():
    return verification.status()


# --- setări ---------------------------------------------------------------
@app.get("/api/settings", response_model=Settings)
def get_settings():
    return verification.get_settings()


@app.put("/api/settings", response_model=Settings)
def put_settings(s: Settings):
    old = verification.get_settings()
    for k, v in s.model_dump().items():
        kv_set(f"settings.{k}", v)
    if s.intervalMinute != old.intervalMinute:
        scheduler.reschedule(s.intervalMinute)
    return s
