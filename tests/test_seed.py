import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import seed
from app.database import Base
from app.models import Book, BookCopy, Loan, Reader, User
from app.security import verify_password


@pytest.fixture
def seed_database(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (User.__table__, Reader.__table__, Book.__table__, BookCopy.__table__, Loan.__table__)
    previous_options = {
        table: table.dialect_kwargs.get("sqlite_autoincrement") for table in tables
    }
    for table in tables:
        table.dialect_kwargs["sqlite_autoincrement"] = True

    Base.metadata.create_all(engine)
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    yield sessionmaker(bind=engine, expire_on_commit=False)

    for table, option in previous_options.items():
        if option is None:
            table.dialect_kwargs.pop("sqlite_autoincrement", None)
        else:
            table.dialect_kwargs["sqlite_autoincrement"] = option
    engine.dispose()


def test_seed_can_run_repeatedly_and_keeps_generated_ids_linked(seed_database):
    seed.seed_data("small")
    seed.seed_data("small")

    with seed_database() as db:
        book_ids = set(db.scalars(select(Book.id)))
        reader_ids = set(db.scalars(select(Reader.id)))
        copy_ids = set(db.scalars(select(BookCopy.id)))
        copies = db.scalars(select(BookCopy)).all()
        loans = db.scalars(select(Loan)).all()
        admin = db.scalar(select(User).where(User.username == "admin"))

        assert all(copy.book_id in book_ids for copy in copies)
        assert all(loan.reader_id in reader_ids for loan in loans)
        assert all(loan.copy_id in copy_ids for loan in loans)
        assert admin is not None
        assert verify_password("admin123", admin.password_hash)
