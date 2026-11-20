import os
from collections.abc import Generator
from contextvars import ContextVar
from time import perf_counter

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


load_dotenv()


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://app:changeme@localhost:5432/ivan_bashkin",
    )
)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

request_sql_metrics: ContextVar[dict[str, float | int | list[float]] | None] = (
    ContextVar("request_sql_metrics", default=None)
)


@event.listens_for(engine, "before_cursor_execute")
def start_query_timer(_connection, _cursor, _statement, _parameters, _context, _many):
    metrics = request_sql_metrics.get()
    if metrics is not None:
        starts = metrics["query_starts"]
        assert isinstance(starts, list)
        starts.append(perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def finish_query_timer(_connection, _cursor, _statement, _parameters, _context, _many):
    metrics = request_sql_metrics.get()
    if metrics is not None:
        starts = metrics["query_starts"]
        assert isinstance(starts, list)
        if starts:
            metrics["db_seconds"] = float(metrics["db_seconds"]) + (
                perf_counter() - starts.pop()
            )
            metrics["db_queries"] = int(metrics["db_queries"]) + 1


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
