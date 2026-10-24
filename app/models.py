"""Modelele Pydantic = contractul API cu dashboard-ul.

Numele câmpurilor sunt exact cele din src/types.ts din Lovable (camelCase).
Regula de aur: puteți ADĂUGA câmpuri, dar nu redenumiți și nu ștergeți,
altfel dashboard-ul se strică.

Pentru cine vine din Java: un BaseModel e echivalentul unui DTO cu validare
(ca un record + Bean Validation); FastAPI îl serializează automat în JSON.
"""
from typing import Literal, Optional
from pydantic import BaseModel

Severitate = Literal["Critică", "Mare", "Medie", "Mică"]
Status = Literal["Nou", "În lucru", "Rezolvat – fix livrat", "Închis – nu se reproduce"]
Verdict = Literal["trecut", "picat", "eroare"]

STATUS_FIXED = "Rezolvat – fix livrat"
STATUS_IN_PROGRESS = "În lucru"
ALL_STATUSES = ["Nou", "În lucru", "Rezolvat – fix livrat", "Închis – nu se reproduce"]


class UltimaVerificare(BaseModel):
    verdict: Verdict
    data: str
    versiuneTestata: str
    raportId: str


class Ticket(BaseModel):
    id: str
    dataDeschiderii: str
    canal: str
    categorie: str
    functionalitate: str
    titlu: str
    descriere: str
    pasiVerificare: Optional[str]
    severitate: Optional[Severitate]
    severitateSursa: Literal["excel", "llm"]
    nrRaportari: int
    versiuneRaportata: str
    status: Status
    versiuneFix: Optional[str]
    dataLivrareFix: Optional[str]
    echipa: str
    tichetLegat: Optional[str]
    clusterId: str
    totalRaportariCluster: int
    prioritate: int
    testabil: bool
    redeschisDeAgent: bool
    ultimaVerificare: Optional[UltimaVerificare]


class Cluster(BaseModel):
    id: str
    titlu: str
    ticketIds: list[str]
    totalRaportari: int
    severitateMax: Optional[Severitate]


class PasRaport(BaseModel):
    nr: int
    actiune: str
    rezultat: Literal["ok", "picat", "neexecutat"]
    detalii: Optional[str] = None
    screenshotUrl: Optional[str] = None
    selector: Optional[str] = None      # adăugat pentru view-ul Developer
    durataMs: Optional[int] = None


class Raport(BaseModel):
    id: str
    ticketId: str
    data: str
    versiuneTestata: str
    verdict: Verdict
    pasi: list[PasRaport]
    explicatieAI: str
    statusInainte: Status
    statusDupa: Status
    durataSecunde: float
    eroriDom: list[str] = []            # erori din consola browserului în timpul testului
    stackTrace: Optional[str] = None    # mesajul tehnic complet al pasului picat


class CategorieStat(BaseModel):
    categorie: str
    raportari: int
    tichete: int


class Stats(BaseModel):
    totalTichete: int
    ticheteDisponibile: int = 0         # tichete „Nou”, pe care le poate prelua un developer
    perStatus: dict[str, int]
    fixuriConfirmate: int
    fixuriInvalidate: int
    necesitaVerificareManuala: int
    rataRedeschidere: float
    raportariPeCategorie: list[CategorieStat]


class Settings(BaseModel):
    versiuneLive: str
    intervalMinute: int
    wizzBeesUrl: str


class SchedulerStatus(BaseModel):
    ruleazaAcum: bool
    ultimaRulare: Optional[str]
    urmatoareaRulare: Optional[str]


class ImportResult(BaseModel):
    importate: int
    severitatiCompletateDeAI: int
    clustere: int
    # câmpuri adăugate (permise de contract): utile în pitch
    modClustere: str = "legat"
    acordCuTichetLegat: Optional[float] = None


class VerifyRequest(BaseModel):
    ticketIds: Optional[list[str]] = None
