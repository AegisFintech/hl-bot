"""Offline versioned simulation or evidence review; JSON input/output, no network."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.validation.simulator import simulate
from src.validation.evidence import evaluate
from src.validation.portfolio import review_portfolio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["simulate", "review", "portfolio"])
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    with args.input.open() as handle:
        payload = json.load(handle)
    if args.mode == "simulate":
        output = {
            name: simulate(payload["order"], payload["events"], assumptions)
            for name, assumptions in payload["scenarios"].items()
        }
    elif args.mode == "portfolio":
        output = review_portfolio(payload)
    else:
        output = evaluate(payload["episodes"], payload["protocol"], payload["as_of"])
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
