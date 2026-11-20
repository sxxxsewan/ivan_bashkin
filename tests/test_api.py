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


def create_library_records(db_session, copy_status="available"):
    reader = Reader(full_name="Test Reader", ticket_number="T-1")
    book = Book(title="Test Book", author="Author", isbn="9780000000001", category="Fiction")
    copy = BookCopy(book=book, inventory_number="INV-1", status=copy_status)
    db_session.add_all([reader, book, copy])
    db_session.commit()
    return reader, copy


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


def test_loan_list_filters_reader_and_status_across_pages(client, db_session):
    token = make_token(client, db_session)
    reader, first_copy = create_library_records(db_session)
    second_copy = BookCopy(
        book_id=first_copy.book_id, inventory_number="INV-2", status="available"
    )
    active_copy = BookCopy(
        book_id=first_copy.book_id, inventory_number="INV-3", status="issued"
    )
    db_session.add_all([second_copy, active_copy])
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Loan(
                reader_id=reader.id,
                copy_id=first_copy.id,
                issue_date=now - timedelta(days=20),
                due_date=now - timedelta(days=10),
                return_date=now - timedelta(days=8),
            ),
            Loan(
                reader_id=reader.id,
                copy_id=second_copy.id,
                issue_date=now - timedelta(days=15),
                due_date=now - timedelta(days=5),
                return_date=now - timedelta(days=3),
            ),
            Loan(
                reader_id=reader.id,
                copy_id=active_copy.id,
                issue_date=now,
                due_date=now + timedelta(days=14),
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/loans?page=2&size=1&status=returned&reader_id={reader.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert response.json()["size"] == 1
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["return_date"] is not None


def test_invalid_pagination_returns_422(client, db_session):
    token = make_token(client, db_session)

    response = client.get(
        "/api/v1/loans?page=0", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 422


def test_invalid_loan_status_returns_422(client, db_session):
    token = make_token(client, db_session)

    response = client.get(
        "/api/v1/loans?status=unknown",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_loan_detail_contains_related_entities(client, db_session):
    token = make_token(client, db_session)
    reader, copy = create_library_records(db_session, copy_status="issued")
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
    assert response.json()["copy"]["inventory_number"] == "INV-1"
    assert response.json()["due_date"]


def test_login_returns_bearer_token(client, db_session):
    make_token(client, db_session)
    response = client.post(
        "/api/v1/auth/login", data={"username": "admin", "password": "secret"}
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_rejects_incorrect_credentials(client, db_session):
    make_token(client, db_session)
    response = client.post(
        "/api/v1/auth/login", data={"username": "admin", "password": "wrong"}
    )

    assert response.status_code == 401


def test_issue_returns_created_loan_and_rejects_repeated_copy(client, db_session):
    token = make_token(client, db_session)
    reader, copy = create_library_records(db_session)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"reader_id": reader.id, "copy_id": copy.id}

    first_response = client.post("/api/v1/loans", json=payload, headers=headers)
    repeated_response = client.post("/api/v1/loans", json=payload, headers=headers)

    assert first_response.status_code == 201
    assert first_response.json()["reader_id"] == reader.id
    assert first_response.json()["copy_id"] == copy.id
    assert first_response.json()["return_date"] is None
    assert repeated_response.status_code == 409


def test_issue_returns_404_for_missing_reader_or_copy(client, db_session):
    token = make_token(client, db_session)
    reader, copy = create_library_records(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    missing_reader = client.post(
        "/api/v1/loans",
        json={"reader_id": reader.id + 100, "copy_id": copy.id},
        headers=headers,
    )
    missing_copy = client.post(
        "/api/v1/loans",
        json={"reader_id": reader.id, "copy_id": copy.id + 100},
        headers=headers,
    )

    assert missing_reader.status_code == 404
    assert missing_copy.status_code == 404


def test_return_updates_loan_and_repeated_return_conflicts(client, db_session):
    token = make_token(client, db_session)
    reader, copy = create_library_records(db_session, copy_status="issued")
    loan = Loan(
        reader_id=reader.id,
        copy_id=copy.id,
        issue_date=datetime.now(timezone.utc) - timedelta(days=20),
        due_date=datetime.now(timezone.utc) - timedelta(days=3, hours=1),
    )
    db_session.add(loan)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(f"/api/v1/loans/{loan.id}/return", headers=headers)
    repeated_response = client.post(f"/api/v1/loans/{loan.id}/return", headers=headers)

    assert response.status_code == 200
    assert response.json()["loan_id"] == loan.id
    assert response.json()["overdue_days"] == 3
    assert response.json()["penalty_amount"] == "300.00"
    assert response.json()["return_date"]
    assert repeated_response.status_code == 409


def test_missing_loan_returns_404_for_detail_and_return(client, db_session):
    token = make_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    detail_response = client.get("/api/v1/loans/999", headers=headers)
    return_response = client.post("/api/v1/loans/999/return", headers=headers)

    assert detail_response.status_code == 404
    assert return_response.status_code == 404


def test_create_loan_rejects_invalid_parameters_with_422(client, db_session):
    token = make_token(client, db_session)

    response = client.post(
        "/api/v1/loans",
        json={"reader_id": 0, "copy_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_summary_response_contains_all_required_fields(client, db_session):
    token = make_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/summary", headers=headers)

    assert response.status_code == 200
    assert set(response.json()) == {"issued_copies", "overdue_loans", "popular_books"}
    assert isinstance(response.json()["popular_books"], list)
    assert len(response.json()["popular_books"]) <= 10


def test_root_serves_library_client(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Сводка" in response.text