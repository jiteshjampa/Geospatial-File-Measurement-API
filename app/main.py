from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine

from app.api import router
from app.core.config import get_database_url
from app.db import Base, make_engine, make_session_factory
from app import models  # noqa: F401 - registers ORM models with SQLAlchemy metadata

STATIC_DIR = Path(__file__).parent / "static"


def create_app(engine: Engine | None = None) -> FastAPI:
    app_engine = engine or make_engine(get_database_url())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(bind=app_engine)
        yield
        app_engine.dispose()

    application = FastAPI(
        title="Aereo Geospatial File Measurement API",
        description=(
            "Upload KML or zipped Shapefiles, inspect their features, and calculate "
            "projected polygon areas and line lengths."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.session_factory = make_session_factory(app_engine)
    application.include_router(router)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
