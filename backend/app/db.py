from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_schema() -> None:
    from . import platform_models  # noqa: F401

    Base.metadata.create_all(engine)
    # Preserve deployments whose configuration audit table predates timestamps.
    columns = {column['name'] for column in inspect(engine).get_columns('platform_configuration_changes')}
    if 'created_at' not in columns:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE platform_configuration_changes ADD COLUMN created_at TIMESTAMP'))
            connection.execute(text('UPDATE platform_configuration_changes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL'))
