"""
SAQ supports async whereas huvey, celery doesn't support
"""

from saq import Queue
from .config import settings

background_tasks = Queue.from_url(settings.SAQ_URL)


