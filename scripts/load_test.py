import asyncio
import json
import os
import statistics
from collections import defaultdict

import httpx


TOKEN = os.getenv("API_TOKEN", "recruitment-test-token")
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")


async def make_request(method: str, path: str, payload: dict | None = None) -> tuple[float, int]:
    start = __import__("time").perf_counter()
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if method == "GET":
            response = await client.get(f"{BASE_URL}{path}", headers=headers)
        else:
            response = await client.post(f"{BASE_URL}{path}", json=payload, headers=headers)
    elapsed = __import__("time").perf_counter() - start
    return elapsed, response.status_code


async def smoke_test() -> dict[str, list[float]]:
    results: dict[str, list[float]] = defaultdict(list)
    for endpoint in [
        ("POST", "/credit", {"user_id": "u_seed", "amount": 100}),
        ("POST", "/debit", {"user_id": "u_seed", "amount": 25}),
        ("GET", "/balance/u_seed", None),
    ]:
        method, path, body = endpoint
        latencies: list[float] = []
        for _ in range(20):
            elapsed, status = await make_request(method, path, body)
            latencies.append(elapsed * 1000.0)
            results[path].extend(latencies)
    return results


async def main() -> None:
    results = await smoke_test()
    for path, samples in results.items():
        samples_sorted = sorted(samples)
        p50 = statistics.median(samples_sorted)
        p99 = samples_sorted[min(len(samples_sorted) - 1, max(0, int(len(samples_sorted) * 0.99)))]
        print(json.dumps({"path": path, "p50_ms": round(p50, 3), "p99_ms": round(p99, 3), "samples": len(samples_sorted)}))


if __name__ == "__main__":
    asyncio.run(main())
