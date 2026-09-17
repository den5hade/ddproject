import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.consumers.document_events import run_consumer
from app.consumers.notification_result import run_consumer as run_notification_consumer
from app.core.bus import close_publisher
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.redis import close_redis
from app.middleware.request_logging import LoggingMiddleware
from app.services.rbac import RbacService
from app.tasks.api_request_purge import run_api_request_purge

logger = logging.getLogger("account_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    consumer_task = asyncio.create_task(run_consumer())
    notification_consumer_task = asyncio.create_task(run_notification_consumer())
    purge_task = asyncio.create_task(run_api_request_purge())
    try:
        async with async_session_factory() as session:
            await RbacService(session).seed()
    except Exception:
        logger.warning("rbac_seed_failed at startup", exc_info=True)
    yield
    consumer_task.cancel()
    notification_consumer_task.cancel()
    purge_task.cancel()
    await asyncio.gather(
        consumer_task,
        notification_consumer_task,
        purge_task,
        return_exceptions=True,
    )
    await close_redis()
    await close_publisher()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)