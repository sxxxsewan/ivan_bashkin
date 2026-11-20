from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models import Book, BookCopy, Loan, Reader
from app.services import get_summary, issue_book, return_book


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


def test_returned_copy_can_be_issued_again(db_session):
    reader, copy = setup_library(db_session)

    loan = issue_book(db_session, reader.id, copy.id, None)
    return_book(db_session, loan)
    next_loan = issue_book(db_session, reader.id, copy.id, None)

    assert next_loan.id != loan.id
    assert copy.status == "issued"


def test_on_time_return_has_no_penalty(db_session):
    reader, copy = setup_library(db_session)
    loan = Loan(
        reader_id=reader.id,
        copy_id=copy.id,
        issue_date=datetime.now(timezone.utc) - timedelta(days=2),
        due_date=datetime.now(timezone.utc) + timedelta(days=1),
    )
    copy.status = "issued"
    db_session.add(loan)
    db_session.commit()

    overdue_days, penalty = return_book(db_session, loan)

    assert overdue_days == 0
    assert penalty == 0


def test_summary_counts_issued_overdue_and_popular_books(db_session):
    reader, copy = setup_library(db_session)
    returned_copy = BookCopy(
        book_id=copy.book_id, inventory_number="INV-2", status="available"
    )
    db_session.add(returned_copy)
    db_session.flush()
    now = datetime.now(timezone.utc)
    overdue_loan = Loan(
        reader_id=reader.id,
        copy_id=copy.id,
        issue_date=now - timedelta(days=30),
        due_date=now - timedelta(days=5),
        penalty_amount=0,
    )
    returned_loan = Loan(
        reader_id=reader.id,
        copy_id=returned_copy.id,
        issue_date=now - timedelta(days=20),
        due_date=now - timedelta(days=6),
        return_date=now - timedelta(days=5),
        penalty_amount=100,
    )
    copy.status = "issued"
    db_session.add_all([overdue_loan, returned_loan])
    db_session.commit()

    summary = get_summary(db_session)

    assert summary["issued_copies"] == 1
    assert summary["overdue_loans"] == 1
    assert len(summary["popular_books"]) == 1
    assert summary["popular_books"][0]["loan_count"] == 2