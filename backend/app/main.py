from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .platform_api import router
from .platform_mcp import router as mcp_router
from .config import get_settings
from .db import SessionLocal, create_schema
from .platform_models import Configuration


def initialize_configuration() -> None:
    with SessionLocal() as db:
        if not db.get(Configuration, 1):
            db.add(Configuration(id=1, revision=0, specification=None))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    settings = get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.reference_image_dir.mkdir(parents=True, exist_ok=True)
    initialize_configuration()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip() != "*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(mcp_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(_, error: RequestValidationError):
    detail = "; ".join(f"{'.'.join(str(item) for item in failure['loc'][1:])}: {failure['msg']}" for failure in error.errors())
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
