"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from ..config import get_app_config
from ..db.session import init_engine
from ..policy.loader import get_return_policy
from .routers import tickets

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate configuration and open the database before serving any request.

    Both config files are parsed here so a malformed policy fails at startup rather
    than on the first customer ticket.
    """
    config = get_app_config()
    policy = get_return_policy()
    init_engine(config.database_url)

    logger.info(
        "Started for %r | classifier=%s | fake_llm=%s | return window=%s days",
        policy.shop_name,
        config.models.classification,
        config.use_fake_llm,
        policy.return_window_days,
    )
    yield


app = FastAPI(
    title="AI Analizator Zgłoszeń",
    description=(
        "Wstępna obsługa zgłoszeń klientów sklepu e-commerce. "
        "Model klasyfikuje treść; o zgodności z regulaminem decyduje deterministyczny kod."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(tickets.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness probe that also reports which shop policy is loaded."""
    config = get_app_config()
    policy = get_return_policy()
    return {
        "status": "ok",
        "shop": policy.shop_name,
        "classification_model": config.models.classification,
        "fake_llm": config.use_fake_llm,
    }
