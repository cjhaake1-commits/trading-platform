from __future__ import annotations

import argparse
import json

from .adapters.bloomberg import BloombergAdapter, BloombergConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe a licensed Bloomberg research-data connection without requesting trades"
    )
    parser.add_argument(
        "--require-connected",
        action="store_true",
        help="Return a non-zero exit code unless the Bloomberg session is connected",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Include the non-secret effective Bloomberg configuration",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = BloombergConfig.from_env()
    status = BloombergAdapter(config).probe()
    payload: dict[str, object] = {"bloomberg": status.as_dict()}
    if args.show_config:
        payload["config"] = config.public_summary()
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.require_connected and not status.connected:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
