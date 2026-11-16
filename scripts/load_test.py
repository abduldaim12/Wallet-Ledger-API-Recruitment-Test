
import argparse
import asyncio
import json
import math
import os
import statistics
import time
import uuid
from collections import Counter, defaultdict

import httpx


TOKEN = os.getenv("API_TOKEN", "recruitment-test-token")
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080").rstrip("/")


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


async def worker(
    queue: asyncio.Queue,
    client: httpx.AsyncClient,
    latencies: dict,
    statuses: dict,
    errors: dict,
) -> None:
    while True:
        job = await queue.get()

        if job is None:
            queue.task_done()
            break

        method, path, payload = job
        started = time.perf_counter()

        try:
            response = await client.request(
                method,
                f"{BASE_URL}{path}",
                json=payload,
            )
            status = response.status_code
            statuses[path][str(status)] += 1

        except Exception as exc:
            status = 0
            statuses[path]["error"] += 1
            if len(errors[path]) < 5:
                errors[path].append(str(exc))

        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies[path].append(elapsed_ms)

        queue.task_done()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Wallet Ledger API load test")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--amount", type=int, default=1)
    args = parser.parse_args()

    if args.concurrency < 1 or args.requests < 1:
        parser.error("concurrency and requests must be positive")

    if args.amount < 1 or args.amount > 1_000_000_000:
        parser.error("amount must be between 1 and 1000000000")

    funding = args.requests * args.amount
    if funding > 1_000_000_000:
        parser.error("requests multiplied by amount must not exceed 1000000000")

    user_id = f"loadtest_{uuid.uuid4().hex}"

    latencies = defaultdict(list)
    statuses = defaultdict(Counter)
    errors = defaultdict(list)

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )

    timeout = httpx.Timeout(60.0)

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {TOKEN}"},
        limits=limits,
        timeout=timeout,
    ) as client:

        # Fund the test user so every debit can succeed.
        setup = await client.post(
            f"{BASE_URL}/credit",
            json={"user_id": user_id, "amount": funding},
        )

        if setup.status_code != 200:
            raise RuntimeError(
                f"Could not fund benchmark user: "
                f"HTTP {setup.status_code}: {setup.text}"
            )

        queue = asyncio.Queue()

        # Interleave all three endpoints against one hot user.
        for _ in range(args.requests):
            queue.put_nowait((
                "POST",
                "/credit",
                {"user_id": user_id, "amount": args.amount},
            ))
            queue.put_nowait((
                "POST",
                "/debit",
                {"user_id": user_id, "amount": args.amount},
            ))
            queue.put_nowait((
                "GET",
                f"/balance/{user_id}",
                None,
            ))

        tasks = [
            asyncio.create_task(
                worker(queue, client, latencies, statuses, errors)
            )
            for _ in range(args.concurrency)
        ]

        started = time.perf_counter()

        await queue.join()

        duration = time.perf_counter() - started

        for _ in tasks:
            queue.put_nowait(None)

        await asyncio.gather(*tasks)

        # Verify the final balance after all writes have completed.
        final_response = await client.get(
            f"{BASE_URL}/balance/{user_id}"
        )

    print("\n=== Wallet Ledger Load Test ===")
    print(f"User: {user_id}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Requests per endpoint: {args.requests}")
    print(f"Total benchmark requests: {args.requests * 3}")
    print(f"Duration: {duration:.3f} seconds")
    print(f"Overall throughput: {args.requests * 3 / duration:.2f} req/s")

    print("\n=== Endpoint Results ===")

    for path, samples in latencies.items():
        success = statuses[path].get("200", 0)
        total = len(samples)

        result = {
            "endpoint": path,
            "requests": total,
            "success": success,
            "failures": total - success,
            "p50_ms": round(statistics.median(samples), 3),
            "p99_ms": round(percentile(samples, 0.99), 3),
            "throughput_rps": round(total / duration, 2),
            "http_statuses": dict(statuses[path]),
        }

        print(json.dumps(result))

        for error in errors[path]:
            print(f"Request error ({path}): {error}")

    print("\n=== Final Balance Verification ===")

    if final_response.status_code == 200:
        actual = final_response.json()["balance"]
        expected = funding

        print(f"Expected balance: {expected}")
        print(f"Actual balance:   {actual}")
        print(f"Match:            {actual == expected}")
    else:
        print(f"Balance check failed: HTTP {final_response.status_code}")
        print(final_response.text)


if __name__ == "__main__":
    asyncio.run(main())
