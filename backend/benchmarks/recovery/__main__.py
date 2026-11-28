"""Run opt-in recovery benchmarks: python -m recovery --tier 1|64|256."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from recovery.runner import run_benchmarks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("1", "64", "256"), required=True)
    parser.add_argument("--seed", type=int, default=72531)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_benchmarks(args.tier, size_mib=int(args.tier) if args.tier != "1" else 64,
                            seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "tier": args.tier,
        "resultKeys": list(result),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
