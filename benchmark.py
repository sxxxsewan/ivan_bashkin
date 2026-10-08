import argparse
import math
import statistics
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure authenticated API request latency")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    if args.requests < 20 or args.warmup < 0:
        parser.error("--requests must be at least 20 and --warmup cannot be negative")

    with httpx.Client(base_url=args.url, timeout=30) as client:
        token_response = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        )
        token_response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {token_response.json()['access_token']}"
        for _ in range(args.warmup):
            client.get("/api/v1/loans", params={"page": 1, "size": 20}).raise_for_status()
        durations = []
        for _ in range(args.requests):
            started = time.perf_counter()
            response = client.get("/api/v1/loans", params={"page": 1, "size": 20})
            response.raise_for_status()
            durations.append((time.perf_counter() - started) * 1000)
    ordered = sorted(durations)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    print(
        f"n={len(durations)} median={statistics.median(durations):.2f} ms "
        f"p95={p95:.2f} ms max={max(durations):.2f} ms"
    )


if __name__ == "__main__":
    main()