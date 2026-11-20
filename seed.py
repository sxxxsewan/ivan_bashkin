import argparse
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, insert, select, text

from app.database import Base, SessionLocal, engine
from app.models import Book, BookCopy, Loan, Reader, User
from app.security import hash_password, verify_password


DATASETS = {
    "small": {"readers": 50, "books": 100, "copies": 200, "loans": 300},
    "large": {"readers": 3000, "books": 10000, "copies": 30000, "loans": 75000},
}
CATEGORIES = ["Fiction", "Science", "History", "Technology", "Art", "Biography"]
READER_CREATED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


def seed_data(dataset: str) -> None:
    counts = DATASETS[dataset]
    randomizer = random.Random(1729)
    Base.metadata.create_all(engine)
    # One anchor keeps every generated date consistent within this run.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with SessionLocal.begin() as db:
        admin_hash = db.scalar(
            select(User.password_hash).where(User.username == "admin")
        )
        if admin_hash is None or not verify_password("admin123", admin_hash):
            admin_hash = hash_password("admin123")
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    "TRUNCATE TABLE loans, book_copies, readers, books, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
        else:
            for model in (Loan, BookCopy, Reader, Book, User):
                db.execute(delete(model))
            if db.bind.dialect.name == "sqlite":
                has_sequence = db.scalar(
                    text(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'sqlite_sequence'"
                    )
                )
                if has_sequence:
                    db.execute(text("DELETE FROM sqlite_sequence"))
        db.execute(
            insert(User),
            [{"username": "admin", "password_hash": admin_hash, "role": "admin"}],
        )
        db.execute(
            insert(Reader),
            [
                {
                    "full_name": f"Reader {index:05d}",
                    "ticket_number": f"T-{index:06d}",
                    "created_at": READER_CREATED_AT,
                }
                for index in range(1, counts["readers"] + 1)
            ],
        )
        reader_ids = {
            ticket_number: reader_id
            for reader_id, ticket_number in db.execute(
                select(Reader.id, Reader.ticket_number)
            )
        }
        db.execute(
            insert(Book),
            [
                {
                    "title": f"Library Book {index:05d}",
                    "author": f"Author {((index - 1) % 500) + 1:04d}",
                    "isbn": f"978{index:010d}",
                    "category": randomizer.choice(CATEGORIES),
                }
                for index in range(1, counts["books"] + 1)
            ],
        )
        book_ids = {
            isbn: book_id
            for book_id, isbn in db.execute(select(Book.id, Book.isbn))
        }
        copy_rows = []
        for index in range(1, counts["copies"] + 1):
            first_loan_is_active = index <= counts["loans"] and index % 4 == 0
            book_index = ((index - 1) % counts["books"]) + 1
            copy_rows.append(
                {
                    "book_id": book_ids[f"978{book_index:010d}"],
                    "inventory_number": f"INV-{index:07d}",
                    "status": "issued" if first_loan_is_active else "available",
                }
            )
        db.execute(insert(BookCopy), copy_rows)
        copy_ids = {
            inventory_number: copy_id
            for copy_id, inventory_number in db.execute(
                select(BookCopy.id, BookCopy.inventory_number)
            )
        }

        loan_rows = []
        active_limit = min(counts["copies"], counts["loans"])
        for index in range(1, counts["loans"] + 1):
            copy_index = ((index - 1) % counts["copies"]) + 1
            reader_index = ((index - 1) % counts["readers"]) + 1
            is_active = index <= active_limit and index % 4 == 0
            issue_age = (
                40
                if is_active and (index // 4) % 2 == 0
                else (7 if is_active else 45 + index % 90)
            )
            issue_date = now - timedelta(days=issue_age)
            due_date = issue_date + timedelta(days=14)
            return_date = None if is_active else due_date + timedelta(days=index % 8)
            overdue_days = max(0, (return_date - due_date).days) if return_date else 0
            loan_rows.append(
                {
                    "reader_id": reader_ids[f"T-{reader_index:06d}"],
                    "copy_id": copy_ids[f"INV-{copy_index:07d}"],
                    "issue_date": issue_date,
                    "due_date": due_date,
                    "return_date": return_date,
                    "penalty_amount": Decimal(overdue_days * 100),
                }
            )
        db.execute(insert(Loan), loan_rows)
    print(
        f"Seeded {counts['readers']} readers, {counts['books']} books, "
        f"{counts['copies']} copies, {counts['loans']} loans. Login: admin / admin123"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate deterministic library data")
    parser.add_argument("--type", choices=DATASETS, default="small")
    seed_data(parser.parse_args().type)