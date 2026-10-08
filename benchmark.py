import argparse
import math
import statistics
import time
import httpx


def measure_endpoint(client, method, url, data=None, params=None, warmup=5, requests=30):
    # Warmup
    for _ in range(warmup):
        client.request(method, url, data=data, params=params).raise_for_status()
    
    durations = []
    for _ in range(requests):
        started = time.perf_counter()
        resp = client.request(method, url, data=data, params=params)
        resp.raise_for_status()
        durations.append((time.perf_counter() - started) * 1000)
    
    ordered = sorted(durations)
    p50 = statistics.median(durations)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return p50, p95, max(durations)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure authenticated API request latency")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=30) as client:
        # 1. Замер Авторизации (login)
        login_data = {"username": "admin", "password": "admin123"}
        l_p50, l_p95, _ = measure_endpoint(client, "POST", "/api/v1/auth/login", data=login_data, warmup=args.warmup, requests=args.requests)
        
        # Авторизуемся для следующего запроса
        token_resp = client.post("/api/v1/auth/login", data=login_data)
        client.headers["Authorization"] = f"Bearer {token_resp.json()['access_token']}"
        
        # 2. Замер получения списка выдач (loans)
        loans_params = {"page": 1, "size": 20}
        b_p50, b_p95, _ = measure_endpoint(client, "GET", "/api/v1/loans", params=loans_params, warmup=args.warmup, requests=args.requests)

        print(f"LOGIN: median={l_p50:.2f} ms p95={l_p95:.2f} ms")
        print(f"LOANS: median={b_p50:.2f} ms p95={b_p95:.2f} ms")


if __name__ == "__main__":
    main()