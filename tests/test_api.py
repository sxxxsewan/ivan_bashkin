from datetime import datetime, timedelta, timezone

from app.models import Book, BookCopy, Loan, Reader, User
from app.security import hash_password


def make_token(client, db_session):
    db_session.add(User(username="admin", password_hash=hash_password("secret"), role="admin"))
    db_session.commit()
    response = client.post(
        "/api/v1/auth/login", data={"username": "admin", "password": "secret"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_protected_routes_require_authentication(client):
    paths = [
        ("get", "/api/v1/loans"),
        ("get", "/api/v1/loans/1"),
        ("post", "/api/v1/loans"),
        ("post", "/api/v1/loans/1/return"),
        ("get", "/api/v1/summary"),
    ]
    for method, path in paths:
        if method == "post" and path == "/api/v1/loans":
            response = client.post(path, json={"reader_id": 1, "copy_id": 1})
        else:
            response = getattr(client, method)(path)
        assert response.status_code == 401


def test_loan_list_has_pagination_structure(client, db_session):
    token = make_token(client, db_session)
    reader = Reader(full_name="Test Reader", ticket_number="T-1")
    book = Book(title="Test Book", author="Author", isbn="9780000000001", category="Fiction")
    copy = BookCopy(book=book, inventory_number="INV-1", status="issued")
    db_session.add_all([reader, book, copy])
    db_session.flush()
    db_session.add(
        Loan(
            reader_id=reader.id,
            copy_id=copy.id,
            issue_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc) + timedelta(days=14),
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/loans?page=1&size=10", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["page"] == 1
    assert response.json()["size"] == 10
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1


def test_invalid_pagination_returns_422(client, db_session):
    token = make_token(client, db_session)

    response = client.get(
        "/api/v1/loans?page=0", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 422


def test_loan_detail_contains_related_entities(client, db_session):
    token = make_token(client, db_session)
    reader = Reader(full_name="Test Reader", ticket_number="T-1")
    book = Book(title="Test Book", author="Author", isbn="9780000000001", category="Fiction")
    copy = BookCopy(book=book, inventory_number="INV-1", status="issued")
    db_session.add_all([reader, book, copy])
    db_session.flush()
    loan = Loan(
        reader_id=reader.id,
        copy_id=copy.id,
        issue_date=datetime.now(timezone.utc),
        due_date=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db_session.add(loan)
    db_session.commit()

    response = client.get(
        f"/api/v1/loans/{loan.id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["reader"]["full_name"] == "Test Reader"
    assert response.json()["copy"]["book"]["title"] == "Test Book"