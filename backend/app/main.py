from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import get_settings
from .db import SessionLocal, create_schema
from .events import broadcaster
from .models import Machine, Operator


def seed() -> None:
    with SessionLocal() as db:
        if not db.query(Operator).count():
            db.add_all([
                Operator(name="Asha", skills=["kitting", "assembly"]),
                Operator(name="Ravi", skills=["machining", "automation"]),
                Operator(name="Meera", skills=["assembly", "kitting"]),
                Operator(name="Kabir", skills=["machining", "automation", "assembly"]),
            ])
        if not db.query(Machine).count():
            db.add_all([
                Machine(code="CNC-01", name="CNC Mill 1", capabilities=["cnc"]),
                Machine(code="CNC-02", name="CNC Mill 2", capabilities=["cnc"]),
                Machine(code="LINE-01", name="Automated Line 1", capabilities=["automated_line"]),
                Machine(code="LINE-02", name="Automated Line 2", capabilities=["automated_line"]),
            ])
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    settings = get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.reference_image_dir.mkdir(parents=True, exist_ok=True)
    seed()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
origins = ["*"] if settings.cors_origins == "*" else [item.strip() for item in settings.cors_origins.split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=origins != ["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
@app.websocket("/ws/events")
async def event_socket(websocket: WebSocket):
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)
