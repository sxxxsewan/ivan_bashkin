from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Loan, Reader, User
from app.schemas import (
    LoanCreate,
    LoanDetail,
    LoanListItem,
    LoanPage,
    ReturnResult,
    SummaryResponse,
    TokenResponse,
)
from app.security import create_access_token, get_current_user, verify_password
from app.services import get_summary, issue_book, return_book


app = FastAPI(title="Ivan Bashkin Library API", version="1.0.0")
router = APIRouter(prefix="/api/v1")
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/auth/login", response_model=TokenResponse)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession
) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get(
    "/loans", response_model=LoanPage, dependencies=[Depends(get_current_user)]
)
def list_loans(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: Literal["active", "returned", "overdue"] | None = None,
    reader_id: int | None = Query(default=None, gt=0),
) -> LoanPage:
    statement = select(Loan)
    count_statement = select(func.count(Loan.id))
    if status == "active":
        statement = statement.where(Loan.return_date.is_(None))
        count_statement = count_statement.where(Loan.return_date.is_(None))
    elif status == "returned":
        statement = statement.where(Loan.return_date.is_not(None))
        count_statement = count_statement.where(Loan.return_date.is_not(None))
    elif status == "overdue":
        overdue_filter = Loan.return_date.is_(None) & (Loan.due_date < datetime.now(timezone.utc))
        statement = statement.where(overdue_filter)
        count_statement = count_statement.where(overdue_filter)
    if reader_id is not None:
        statement = statement.where(Loan.reader_id == reader_id)
        count_statement = count_statement.where(Loan.reader_id == reader_id)
    total = db.scalar(count_statement) or 0
    items = db.scalars(
        statement.order_by(Loan.id).offset((page - 1) * size).limit(size)
    ).all()
    return LoanPage(items=items, page=page, size=size, total=total)


@router.get(
    "/loans/{loan_id}",
    response_model=LoanDetail,
    dependencies=[Depends(get_current_user)],
)
def get_loan(loan_id: int, db: DbSession) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return loan


@router.post(
    "/loans",
    response_model=LoanListItem,
    status_code=201,
    dependencies=[Depends(get_current_user)],
)
def create_loan(payload: LoanCreate, db: DbSession) -> Loan:
    if db.get(Reader, payload.reader_id) is None:
        raise HTTPException(status_code=404, detail="Reader not found")
    return issue_book(db, payload.reader_id, payload.copy_id, payload.due_date)


@router.post(
    "/loans/{loan_id}/return",
    response_model=ReturnResult,
    dependencies=[Depends(get_current_user)],
)
def return_loan(loan_id: int, db: DbSession) -> ReturnResult:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    overdue_days, penalty = return_book(db, loan)
    return ReturnResult(
        loan_id=loan.id,
        return_date=loan.return_date,
        overdue_days=overdue_days,
        penalty_amount=penalty,
    )


@router.get(
    "/summary", response_model=SummaryResponse, dependencies=[Depends(get_current_user)]
)
def summary(db: DbSession) -> dict:
    return get_summary(db)


app.include_router(router)