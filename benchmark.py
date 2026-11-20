import argparse
import csv
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from sqlalchemy import exists, select

from app.database import SessionLocal
from app.models import BookCopy, Loan, Reader


CSV_FIELDS = [
    "dataset",
    "operation",
    "parameter_bytes",
    "requests",
    "warmup",
    "p50_ms",
    "p95_ms",
    "max_ms",
    "db_p50_ms",
    "code_p50_ms",
    "db_queries_p50",
]


def percentile95(values: list[float]) -> float:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def request_bytes(*, data=None, json_body=None, params=None, path_parameter=None) -> int:
    total = len(urlencode(params or {}).encode())
    if path_parameter is not None:
        total += len(str(path_parameter).encode())
    if data is not None:
        total += len(urlencode(data).encode())
    if json_body is not None:
        total += len(json.dumps(json_body, separators=(",", ":")).encode())
    return total


def get_server_timing(response: httpx.Response) -> tuple[float, float, int]:
    timing = response.headers.get("Server-Timing")
    query_count = response.headers.get("X-DB-Query-Count")
    if timing is None or query_count is None:
        raise RuntimeError(
            "Server timing headers are missing; restart the API with the current code."
        )
    metrics = {}
    for metric in timing.split(","):
        name, _, value = metric.strip().partition(";dur=")
        metrics[name] = float(value)
    if "db" not in metrics or "app" not in metrics:
        raise RuntimeError(f"Unexpected Server-Timing header: {timing}")
    return metrics["db"], metrics["app"], int(query_count)


def send(client: httpx.Client, request: dict) -> httpx.Response:
    response = client.request(
        request["method"],
        request["url"],
        data=request.get("data"),
        json=request.get("json"),
        params=request.get("params"),
    )
    response.raise_for_status()
    return response


def measure(
    client: httpx.Client,
    operation: str,
    requests: list[dict],
    warmup: int,
) -> dict:
    if len(requests) == 0:
        raise ValueError(f"No requests prepared for {operation}")
    for request in requests[:warmup]:
        send(client, request)

    durations = []
    db_durations = []
    code_durations = []
    query_counts = []
    payload_sizes = []
    for request in requests[warmup:]:
        started = time.perf_counter()
        response = send(client, request)
        durations.append((time.perf_counter() - started) * 1000)
        db_ms, code_ms, query_count = get_server_timing(response)
        db_durations.append(db_ms)
        code_durations.append(code_ms)
        query_counts.append(float(query_count))
        payload_sizes.append(
            request_bytes(
                data=request.get("data"),
                json_body=request.get("json"),
                params=request.get("params"),
                path_parameter=request.get("path_parameter"),
            )
        )

    if not durations:
        raise ValueError("At least one measured request is required")
    return {
        "operation": operation,
        "parameter_bytes": int(statistics.median(payload_sizes)),
        "p50_ms": statistics.median(durations),
        "p95_ms": percentile95(durations),
        "max_ms": max(durations),
        "db_p50_ms": statistics.median(db_durations),
        "code_p50_ms": statistics.median(code_durations),
        "db_queries_p50": int(statistics.median(query_counts)),
    }


def prepare_database_inputs(required_copies: int) -> tuple[int, list[int]]:
    now_subquery = select(Loan.id).where(
        Loan.reader_id == Reader.id,
        Loan.return_date.is_(None),
        Loan.due_date < datetime.now(timezone.utc),
    )
    with SessionLocal() as db:
        reader_id = db.scalar(
            select(Reader.id).where(~exists(now_subquery)).order_by(Reader.id).limit(1)
        )
        if reader_id is None:
            raise RuntimeError("No reader without an overdue active loan was found.")
        copy_ids = list(
            db.scalars(
                select(BookCopy.id)
                .where(BookCopy.status == "available")
                .order_by(BookCopy.id)
                .limit(required_copies)
            )
        )
    if len(copy_ids) < required_copies:
        raise RuntimeError(
            f"Need {required_copies} available copies for this benchmark; found {len(copy_ids)}."
        )
    return reader_id, copy_ids


def check_success(response: httpx.Response, expected_status: int, operation: str) -> dict:
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{operation} returned HTTP {response.status_code}, expected {expected_status}."
        )
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure library API latency, SQL time, and query counts."
    )
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--dataset", choices=("small", "large"), required=True)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--csv", default="benchmark_results.csv")
    args = parser.parse_args()
    if args.requests < 20:
        parser.error("--requests must be at least 20")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")

    count_per_mutation = args.requests + args.warmup
    reader_id, available_copy_ids = prepare_database_inputs(2 * count_per_mutation)
    return_copy_ids = available_copy_ids[:count_per_mutation]
    issue_copy_ids = available_copy_ids[count_per_mutation:]

    with httpx.Client(base_url=args.url, timeout=30) as client:
        login_request = {
            "method": "POST",
            "url": "/api/v1/auth/login",
            "data": {"username": args.username, "password": args.password},
        }
        login_requests = [login_request] * (args.requests + args.warmup)
        login_result = measure(client, "POST /api/v1/auth/login", login_requests, args.warmup)

        token_response = send(client, login_request)
        token = check_success(token_response, 200, "POST /api/v1/auth/login")
        client.headers["Authorization"] = f"Bearer {token['access_token']}"

        list_request = {
            "method": "GET",
            "url": "/api/v1/loans",
            "params": {"page": 1, "size": 20},
        }
        list_response = send(client, list_request)
        listed_loans = check_success(list_response, 200, "GET /api/v1/loans")
        if not listed_loans["items"]:
            raise RuntimeError("GET /api/v1/loans returned no loan to use for detail timing.")
        loan_id = listed_loans["items"][0]["id"]

        results = [
            login_result,
            measure(
                client,
                "GET /api/v1/loans",
                [list_request] * (args.requests + args.warmup),
                args.warmup,
            ),
            measure(
                client,
                "GET /api/v1/loans/{id}",
                [
                    {
                        "method": "GET",
                        "url": f"/api/v1/loans/{loan_id}",
                        "path_parameter": loan_id,
                    }
                ] * (args.requests + args.warmup),
                args.warmup,
            ),
            measure(
                client,
                "GET /api/v1/summary",
                [{"method": "GET", "url": "/api/v1/summary"}]
                * (args.requests + args.warmup),
                args.warmup,
            ),
        ]

        return_loan_ids = []
        for copy_id in return_copy_ids:
            request = {
                "method": "POST",
                "url": "/api/v1/loans",
                "json": {"reader_id": reader_id, "copy_id": copy_id},
            }
            response = send(client, request)
            created = check_success(response, 201, "POST /api/v1/loans (preparation)")
            return_loan_ids.append(created["id"])
        return_requests = [
            {
                "method": "POST",
                "url": f"/api/v1/loans/{loan_id}/return",
                "path_parameter": loan_id,
            }
            for loan_id in return_loan_ids
        ]
        results.append(
            measure(
                client,
                "POST /api/v1/loans/{id}/return",
                return_requests,
                args.warmup,
            )
        )

        issue_requests = [
            {
                "method": "POST",
                "url": "/api/v1/loans",
                "json": {"reader_id": reader_id, "copy_id": copy_id},
            }
            for copy_id in issue_copy_ids
        ]
        results.append(
            measure(client, "POST /api/v1/loans", issue_requests, args.warmup)
        )

    print(
        f"{'Операция':38} {'Параметры, Б':>12} {'p50, ms':>10} {'p95, ms':>10} "
        f"{'max, ms':>10} {'БД p50, ms':>12} {'код p50, ms':>12} {'SQL p50':>9}"
    )
    for result in results:
        print(
            f"{result['operation']:38} {result['parameter_bytes']:12d} "
            f"{result['p50_ms']:10.2f} {result['p95_ms']:10.2f} "
            f"{result['max_ms']:10.2f} {result['db_p50_ms']:12.2f} "
            f"{result['code_p50_ms']:12.2f} {result['db_queries_p50']:9d}"
        )

    csv_path = Path(args.csv)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "dataset": args.dataset,
                    **result,
                    "requests": args.requests,
                    "warmup": args.warmup,
                }
            )


if __name__ == "__main__":
    main()
