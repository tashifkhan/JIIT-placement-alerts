"""
One-time backfill of likely_on_campus / on_campus_confidence on placement offers.

New offers get the tag during extraction. Offers saved before that have neither
field, so this replays the same decision: the shared ranker narrows the year's
Jobs collection to at most eight candidate drives, then an LLM judges whether
the offer came through one of them. Student rows are never sent.

Requests go to an OpenAI-compatible endpoint rather than the configured Gemini
client, so the run can be pointed at a self-hosted gateway.

Usage:
    python -m scripts.backfill_offer_on_campus --all-years --dry-run --limit 10
    python -m scripts.backfill_offer_on_campus --all-years
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients.db_client import DBClient
from core.config import get_settings, safe_print
from core.year_context import (
    DEFAULT_PLACEMENT_YEAR,
    database_name_for_year,
    get_configured_placement_years,
    normalize_year,
)
from services.campus_match import find_job_candidates, parse_campus_verdict
from services.placement.extraction.prompts import OFFER_ON_CAMPUS_PROMPT

DEFAULT_BASE_URL = "http://100.111.180.97:8317"
DEFAULT_MODEL = "go/muse-spark-1.3-contributor"
DEFAULT_REASONING_EFFORT = "medium"
REASONING_LIMIT = 4000
DEFAULT_STATE_DIR = Path(__file__).resolve().parents[2] / "logs"

logger = logging.getLogger("backfill_offer_on_campus")


class GatewayError(RuntimeError):
    """Raised when the gateway cannot answer a classification request."""


class GatewayClient:
    """Minimal OpenAI-compatible chat client with retry and usage totals."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: int = 180,
        max_retries: int = 3,
        max_tokens: int = 1500,
        reasoning_effort: str | None = None,
    ):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.session_id = f"placement-backfill-{uuid.uuid4()}"
        self._lock = threading.Lock()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    def _post(self, request: urllib.request.Request) -> dict[str, Any]:
        """Send one request and parse the JSON reply within self.timeout seconds.

        urlopen's timeout bounds each socket read, not the whole call, so an
        upstream that trickles bytes can hold a worker forever. Reading in
        chunks against a deadline caps the full request.
        """
        deadline = time.monotonic() + self.timeout
        chunks: list[bytes] = []
        with urllib.request.urlopen(request, timeout=min(60, self.timeout)) as response:
            while chunk := response.read(65536):
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise TimeoutError(f"no complete reply within {self.timeout}s")
        return json.loads(b"".join(chunks))

    def classify(self, prompt: str) -> tuple[str, str | None]:
        """Return the model's answer and its reasoning text, if the model sent any.

        Widens the budget if the answer truncates.

        Reasoning models spend the completion budget on reasoning_content first
        and emit an empty content when it runs out, so a truncated answer is
        retried with double the room rather than counted as a failure.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "placement-backfill/1.0",
            # OpenCode Go refuses contributor models without a session id.
            "x-opencode-session": self.session_id,
        }
        budget = self.max_tokens
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            body_fields: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": budget,
            }
            if self.reasoning_effort:
                body_fields["reasoning_effort"] = self.reasoning_effort
            payload = json.dumps(body_fields).encode()
            request = urllib.request.Request(
                self.url, data=payload, method="POST", headers=headers
            )
            try:
                body = self._post(request)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:200]
                last_error = GatewayError(f"HTTP {error.code}: {detail}")
                if error.code < 500 and error.code != 429:
                    raise last_error from error
            except Exception as error:  # network, timeout, malformed JSON
                last_error = error
            else:
                usage = body.get("usage") or {}
                with self._lock:
                    self.calls += 1
                    self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    self.completion_tokens += int(usage.get("completion_tokens") or 0)

                choices = body.get("choices") or []
                if not choices:
                    raise GatewayError("gateway returned no choices")
                message = choices[0].get("message") or {}
                content = message.get("content") or ""
                reasoning = message.get("reasoning_content") or message.get("reasoning")
                if content.strip():
                    return content, reasoning if isinstance(reasoning, str) else None

                last_error = GatewayError(
                    f"empty content (finish_reason={choices[0].get('finish_reason')}, "
                    f"max_tokens={budget})"
                )
                budget *= 2
                continue
            time.sleep(2**attempt)

        raise GatewayError(f"gateway failed after {self.max_retries} attempts: {last_error}")


def build_prompt(doc: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    """Render the production offer judge prompt. Student rows are left out."""
    offer = {
        "company": doc.get("company"),
        "roles": doc.get("roles") or [],
        "job_location": doc.get("job_location"),
        "number_of_offers": doc.get("number_of_offers"),
    }
    messages = OFFER_ON_CAMPUS_PROMPT.format_messages(
        subject=doc.get("email_subject") or "",
        offer=json.dumps(offer, default=str),
        candidates=json.dumps(candidates, default=str),
    )
    return messages[0].content


def offer_role(doc: dict[str, Any]) -> str:
    roles = doc.get("roles") or []
    return " / ".join(str(r.get("role")) for r in roles if isinstance(r, dict) and r.get("role"))


class StateFile:
    """Append-only record of processed ids so a rerun can resume.

    A failed record is logged but deliberately left out of the done set, so
    rerunning the script picks the failures back up instead of stranding them
    without the fields this backfill exists to write.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.done: set[str] = set()
        self.failed: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                    record_id = entry["_id"]
                except (json.JSONDecodeError, KeyError):
                    continue
                if entry.get("outcome") == "failed":
                    self.failed.add(record_id)
                    self.done.discard(record_id)
                else:
                    self.done.add(record_id)
                    self.failed.discard(record_id)

    def record(self, record_id: str, result: dict[str, Any]) -> None:
        entry = {"_id": record_id, "at": datetime.now(UTC).isoformat(), **result}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
            if result.get("outcome") == "failed":
                self.failed.add(record_id)
            else:
                self.done.add(record_id)
                self.failed.discard(record_id)


def backfill_year(
    year: str,
    client: GatewayClient,
    state: StateFile,
    *,
    dry_run: bool,
    limit: int,
    min_confidence: float,
    force: bool,
    concurrency: int,
) -> dict[str, int]:
    """Classify and update every eligible placement offer for one year."""
    db_client = DBClient(database_name=database_name_for_year(year))
    db_client.connect()
    counts = {"seen": 0, "skipped": 0, "no_candidates": 0, "likely": 0, "unlikely": 0, "failed": 0}
    lock = threading.Lock()

    try:
        db = db_client.db
        jobs = list(db["Jobs"].find({}))
        offers = db["PlacementOffers"]

        query: dict[str, Any] = {} if force else {"likely_on_campus": {"$exists": False}}
        docs = list(offers.find(query))
        if limit:
            docs = docs[:limit]

        def handle(doc: dict[str, Any]) -> None:
            offer_id = str(doc["_id"])
            # --force only widens the query; the resume log is per run, so an
            # offer it already holds was finished by this run and is skipped.
            if offer_id in state.done:
                with lock:
                    counts["skipped"] += 1
                return

            candidates = find_job_candidates(jobs, doc.get("company"), offer_role(doc))
            if not candidates:
                if not dry_run:
                    offers.update_one(
                        {"_id": doc["_id"]},
                        {
                            "$set": {
                                "likely_on_campus": False,
                                "on_campus_confidence": None,
                                "on_campus_reason": "No posted drive resembles this company.",
                                "on_campus_signals": [],
                                "on_campus_job_id": None,
                                "on_campus_model": None,
                            }
                        },
                    )
                state.record(offer_id, {"outcome": "no_candidates", "company": doc.get("company")})
                with lock:
                    counts["no_candidates"] += 1
                return

            try:
                raw, reasoning = client.classify(build_prompt(doc, candidates))
                verdict = parse_campus_verdict(raw, candidates, min_confidence)
                likely, confidence, job = verdict["likely"], verdict["confidence"], verdict["job"]
            except (GatewayError, ValueError, TypeError, json.JSONDecodeError) as error:
                logger.warning("Offer %s could not be classified: %s", offer_id, error)
                state.record(offer_id, {"outcome": "failed", "error": str(error)[:200]})
                with lock:
                    counts["failed"] += 1
                return

            if not dry_run:
                offers.update_one(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "likely_on_campus": likely,
                            "on_campus_confidence": confidence,
                            "on_campus_reason": verdict["reason"],
                            "on_campus_signals": verdict["signals"],
                            "on_campus_job_id": verdict["job_id"],
                            "on_campus_ppo": verdict["pre_placement_offer"],
                            "on_campus_model": client.model,
                            "on_campus_reasoning": (reasoning or "")[:REASONING_LIMIT] or None,
                        }
                    },
                )
            state.record(
                offer_id,
                {
                    "outcome": "likely" if likely else "unlikely",
                    "company": doc.get("company"),
                    "confidence": confidence,
                    "job_id": (job or {}).get("id"),
                    "picked_job_id": verdict["job_id"],
                    "ppo": verdict["pre_placement_offer"],
                    "reason": verdict["reason"],
                    "previous": {
                        "likely_on_campus": doc.get("likely_on_campus"),
                        "on_campus_confidence": doc.get("on_campus_confidence"),
                    },
                    "candidates": len(candidates),
                },
            )
            with lock:
                counts["likely" if likely else "unlikely"] += 1

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(handle, docs))

        counts["seen"] = len(docs)
        return counts
    finally:
        db_client.close_connection()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", help="Placement year, e.g. 202526")
    parser.add_argument("--all-years", action="store_true", help="Run every configured year")
    parser.add_argument("--dry-run", action="store_true", help="Classify without writing")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N offers per year")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gateway model id")
    parser.add_argument("--base-url", default=os.getenv("BACKFILL_GATEWAY_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=os.getenv("BACKFILL_GATEWAY_KEY", ""))
    parser.add_argument("--min-confidence", type=float, default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--reasoning-effort",
        default=DEFAULT_REASONING_EFFORT,
        help="low | medium | high, or empty to omit",
    )
    parser.add_argument("--force", action="store_true", help="Reclassify offers already carrying the flag")
    parser.add_argument("--state-file", help="Resume log path (defaults to logs/)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.api_key:
        parser.error("gateway key required: pass --api-key or set BACKFILL_GATEWAY_KEY")

    settings = get_settings()
    min_confidence = (
        args.min_confidence
        if args.min_confidence is not None
        else settings.likely_on_campus_min_confidence
    )

    if args.all_years:
        years = get_configured_placement_years(settings)
    else:
        years = [
            normalize_year(
                args.year
                or getattr(settings, "active_placement_year", None)
                or DEFAULT_PLACEMENT_YEAR
            )
        ]

    client = GatewayClient(
        args.base_url,
        args.api_key,
        args.model,
        reasoning_effort=args.reasoning_effort or None,
    )
    totals: dict[str, dict[str, int]] = {}

    for year in years:
        state_path = (
            Path(args.state_file)
            if args.state_file
            else DEFAULT_STATE_DIR / f"backfill_offer_on_campus_{year}.jsonl"
        )
        state = StateFile(state_path)
        mode = "dry run" if args.dry_run else "write"
        safe_print(
            f"Backfilling {year} ({mode}, model={args.model}, "
            f"min_confidence={min_confidence}, resumed={len(state.done)}, "
            f"retrying_failed={len(state.failed)})"
        )
        totals[year] = backfill_year(
            year,
            client,
            state,
            dry_run=args.dry_run,
            limit=args.limit,
            min_confidence=min_confidence,
            force=args.force,
            concurrency=args.concurrency,
        )
        safe_print(f"  {year}: {totals[year]}")

    safe_print(
        f"Backfill complete: {totals} | calls={client.calls} "
        f"prompt_tokens={client.prompt_tokens} completion_tokens={client.completion_tokens}"
    )


if __name__ == "__main__":
    main()
