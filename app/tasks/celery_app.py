from celery import Celery

from app.config import settings

celery_app = Celery(
    "docapp",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.worker"],
)

celery_app.conf.task_routes = {
    "app.tasks.worker.process_document_task": {"queue": "documents"},
}
celery_app.conf.update(task_track_started=True)
