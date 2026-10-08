from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models import Book, BookCopy, Loan, Reader
from app.services import issue_book, return_book


def setup_library(db_session):
    reader = Reader(full_name="Test Reader", ticket_number="T-1")
    book = Book(title="Test Book", author="Author", isbn="9780000000001", category="Fiction")
    copy = BookCopy(book=book, inventory_number="INV-1", status="available")
    db_session.add_all([reader, book, copy])
    db_session.commit()
    return reader, copy


def test_return_calculates_penalty(db_session):
    reader, copy = setup_library(db_session)
    due_date = datetime.now(timezone.utc) - timedelta(days=3, hours=1)
    loan = Loan(
        reader_id=reader.id,
        copy_id=copy.id,
        issue_date=due_date - timedelta(days=14),
        due_date=due_date,
    )
    copy.status = "issued"
    db_session.add(loan)
    db_session.commit()

    overdue_days, penalty = return_book(db_session, loan)

    assert overdue_days == 3
    assert penalty == 300
    assert copy.status == "available"


def test_issue_is_blocked_for_reader_with_overdue_loan(db_session):
    reader, copy = setup_library(db_session)
    other_copy = BookCopy(book_id=copy.book_id, inventory_number="INV-2", status="issued")
    db_session.add(other_copy)
    db_session.flush()
    db_session.add(
        Loan(
            reader_id=reader.id,
            copy_id=other_copy.id,
            issue_date=datetime.now(timezone.utc) - timedelta(days=20),
            due_date=datetime.now(timezone.utc) - timedelta(days=5),
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        issue_book(db_session, reader.id, copy.id, None)

    assert error.value.status_code == 409
    assert copy.status == "available"


def test_issue_is_blocked_for_occupied_copy(db_session):
    reader, copy = setup_library(db_session)
    copy.status = "issued"
    db_session.commit()

    with pytest.raises(HTTPException) as error:
        issue_book(db_session, reader.id, copy.id, None)

    assert error.value.status_code == 409