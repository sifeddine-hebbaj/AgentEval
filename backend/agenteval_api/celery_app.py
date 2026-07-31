"""Celery application definition, shared by the API (to enqueue jobs)
and the worker process (to execute them).
"""
from __future__ import annotations

from celery import Celery

from agenteval_api.config import settings

celery_app = Celery("agenteval", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,  # a crashed worker requeues the job rather than losing it (NFR-AVAIL-3)
    worker_prefetch_multiplier=1,
    task_track_started=True,
)
