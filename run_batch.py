"""Manual full-batch triage run.

Run explicitly:

    python run_batch.py

Processes all 20 dataset tickets sequentially against the live Gemini API
and prints a runtime summary. Not discovered by pytest, so running the test
suite never triggers an API call.
"""

import asyncio
import json
import time

from backend.app.schemas import TriageStatus
from backend.app.services.triage import triage_batch


async def main() -> None:
    started = time.perf_counter()

    results = await triage_batch()

    total_ms = int((time.perf_counter() - started) * 1000)

    succeeded = [r for r in results if r.status is TriageStatus.OK]
    failed = [r for r in results if r.status is TriageStatus.FAILED]

    average_latency = sum(r.latency_ms for r in results) / len(results)

    print("\n=== Batch summary ===")
    print(f"Total tickets:    {len(results)}")
    print(f"Successful:       {len(succeeded)}")
    print(f"Failed:           {len(failed)}")
    print(f"Total batch time: {total_ms} ms ({total_ms / 1000:.1f} s)")
    print(f"Average latency:  {average_latency:.0f} ms")

    print("\n=== Per-ticket results ===")
    for result in results:
        if result.status is TriageStatus.OK:
            label = f"{result.urgency.value}/{result.category.value}"
        else:
            label = "-"

        print(
            f"ticket {result.ticket_id:>2} | "
            f"{result.status.value:<8} | "
            f"{result.latency_ms:>6} ms | "
            f"{label}"
        )

    if failed:
        print("\n=== Failures ===")
        for result in failed:
            print(f"ticket {result.ticket_id}: {result.error}")

    print("\n=== Full results (JSON) ===")
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))


if __name__ == "__main__":
    asyncio.run(main())