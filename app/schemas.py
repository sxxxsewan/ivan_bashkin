from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoanCreate(BaseModel):
    reader_id: int = Field(gt=0)
    copy_id: int = Field(gt=0)
    due_date: datetime | None = None


class LoanListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reader_id: int
    copy_id: int
    issue_date: datetime
    due_date: datetime
    return_date: datetime | None
    penalty_amount: Decimal


class LoanPage(BaseModel):
    items: list[LoanListItem]
    page: int
    size: int
    total: int


class ReaderInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    ticket_number: str


class BookInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    isbn: str
    category: str


class CopyInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inventory_number: str
    status: str
    book: BookInfo


class LoanDetail(LoanListItem):
    reader: ReaderInfo
    copy_info: CopyInfo = Field(validation_alias="copy", serialization_alias="copy")


class ReturnResult(BaseModel):
    loan_id: int
    return_date: datetime
    overdue_days: int
    penalty_amount: Decimal


class PopularBook(BaseModel):
    book_id: int
    title: str
    author: str
    loan_count: int


class SummaryResponse(BaseModel):
    issued_copies: int
    overdue_loans: int
    popular_books: list[PopularBook]