from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Book, BookCopy, Loan


PENALTY_PER_DAY = Decimal("100.00")


def issue_book(db: Session, reader_id: int, copy_id: int, due_date: datetime | None) -> Loan:
    copy = db.get(BookCopy, copy_id)
    if copy is None:
        raise HTTPException(status_code=404, detail="Book copy not found")
    if copy.status != "available":
        raise HTTPException(status_code=409, detail="Book copy is already issued")

    now = datetime.now(timezone.utc)
    overdue = db.scalar(
        select(Loan.id).where(
            Loan.reader_id == reader_id,
            Loan.return_date.is_(None),
            Loan.due_date < now,
        ).limit(1)
    )
    if overdue is not None:
        raise HTTPException(status_code=409, detail="Reader has overdue loans")

    loan = Loan(
        reader_id=reader_id,
        copy_id=copy_id,
        issue_date=now,
        due_date=due_date or now + timedelta(days=14),
        penalty_amount=Decimal("0.00"),
    )
    copy.status = "issued"
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


def return_book(db: Session, loan: Loan) -> tuple[int, Decimal]:
    if loan.return_date is not None:
        raise HTTPException(status_code=409, detail="Loan has already been returned")
    returned_at = datetime.now(timezone.utc)
    due_date = loan.due_date
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)
    overdue_days = max(0, (returned_at - due_date).days)
    penalty = PENALTY_PER_DAY * overdue_days
    loan.return_date = returned_at
    loan.penalty_amount = penalty
    loan.copy.status = "available"
    db.commit()
    db.refresh(loan)
    return overdue_days, penalty


def get_summary(db: Session) -> dict:
    issued_copies = db.scalar(
        select(func.count(BookCopy.id)).where(BookCopy.status == "issued")
    ) or 0
    overdue_loans = db.scalar(
        select(func.count(Loan.id)).where(
            Loan.return_date.is_(None), Loan.due_date < datetime.now(timezone.utc)
        )
    ) or 0
    popular_books = db.execute(
        select(Book.id, Book.title, Book.author, func.count(Loan.id).label("loan_count"))
        .join(BookCopy, BookCopy.book_id == Book.id)
        .join(Loan, Loan.copy_id == BookCopy.id)
        .group_by(Book.id, Book.title, Book.author)
        .order_by(func.count(Loan.id).desc(), Book.id)
        .limit(10)
    ).all()
    return {
        "issued_copies": issued_copies,
        "overdue_loans": overdue_loans,
        "popular_books": [
            {
                "book_id": row.id,
                "title": row.title,
                "author": row.author,
                "loan_count": row.loan_count,
            }
            for row in popular_books
        ],
    }