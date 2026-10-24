"""Verificarea periodică (APScheduler, într-un thread de fundal).

Intervalul vine din setări (implicit 2 minute în demo) și se schimbă din
dashboard prin PUT /api/settings, fără restart.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import verification

log = logging.getLogger("fixtrail.scheduler")
_sched = BackgroundScheduler(timezone="Europe/Bucharest")
JOB_ID = "verify-periodic"


def _job():
    verification.run_verification()
    _publish_next()


def _publish_next():
    job = _sched.get_job(JOB_ID)
    verification.set_next_run(job.next_run_time.isoformat(timespec="seconds") if job and job.next_run_time else None)


def start(interval_min: int) -> None:
    _sched.add_job(_job, "interval", minutes=max(1, interval_min), id=JOB_ID,
                   max_instances=1, coalesce=True, replace_existing=True)
    if not _sched.running:
        _sched.start()
    _publish_next()
    log.info("Scheduler pornit: la fiecare %d min", interval_min)


def reschedule(interval_min: int) -> None:
    _sched.reschedule_job(JOB_ID, trigger="interval", minutes=max(1, interval_min))
    _publish_next()


def stop() -> None:
    if _sched.running:
        _sched.shutdown(wait=False)
