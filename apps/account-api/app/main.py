from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.bus import close_publisher
from app.core.config import settings
from app.core.redis import close_redis
from app.middleware.request_logging import LoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
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