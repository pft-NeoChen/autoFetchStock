"""R3-sample — build a sampled universe for V1 §6.1 evaluation.

Fetches the full TWSE + TPEx listed directory via OpenAPI, excludes the
stocks already on disk (so backfill effort is incremental), then writes
a deterministic random sample to ``data/cache/sampled_universe.json``
and prints the new stock_ids comma-joined for piping into
``backfill_historical_daily.py --stocks ...``.

Used to test whether R3 (survivorship-bias-free universe) would materially
change V1 §6.1 verdict before committing to the ~35h full-universe
backfill.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path

from src.universe.api_loader import (
    fetch_tpex_listed,
    fetch_twse_delisted,
    fetch_twse_listed,
)

logger = logging.getLogger("autofetchstock.scripts.build_sampled_universe")


def existing_stock_ids(data_dir: Path) -> set[str]:
    stocks_dir = data_dir / "stocks"
    if not stocks_dir.exists():
        return set()
    return {p.stem for p in stocks_dir.glob("*.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/cache/sampled_universe.json"),
    )
    parser.add_argument(
        "--include-delisted",
        action="store_true",
        help="Append all TWSE delisted records to the sample (no random pick).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    logger.info("fetching listed directory…")
    twse = fetch_twse_listed()
    tpex = fetch_tpex_listed()
    logger.info("TWSE listed=%d  TPEx listed=%d", len(twse), len(tpex))

    full = {s.stock_id: s for s in twse + tpex}
    have = existing_stock_ids(args.data_dir)
    candidates = sorted(sid for sid in full if sid not in have)
    logger.info("candidates new=%d (excluded %d already on disk)", len(candidates), len(have))

    rng = random.Random(args.seed)
    sample_ids = rng.sample(candidates, min(args.sample_size, len(candidates)))

    delisted_ids: list[str] = []
    if args.include_delisted:
        delisted = fetch_twse_delisted()
        delisted_ids = sorted({d.stock_id for d in delisted} - have)
        logger.info("delisted records=%d new=%d", len(delisted), len(delisted_ids))

    payload = {
        "sample_size": len(sample_ids),
        "seed": args.seed,
        "existing_on_disk": sorted(have),
        "sampled_listed": sorted(sample_ids),
        "delisted": delisted_ids,
        "twse_listed_total": len(twse),
        "tpex_listed_total": len(tpex),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("wrote %s", args.out)

    backfill_targets = sorted(set(sample_ids) | set(delisted_ids))
    print(",".join(backfill_targets))


if __name__ == "__main__":
    main()
