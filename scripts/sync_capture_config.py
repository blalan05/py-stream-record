#!/usr/bin/env python3
"""Merge capture settings from repo config into /etc/theater-app/config.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROD = Path("/etc/theater-app/config.yaml")
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/theater-app/config.yaml")


def main() -> int:
    if not PROD.exists():
        print(f"Missing {PROD}; run install.sh first")
        return 1
    if not SRC.exists():
        print(f"Missing source config {SRC}")
        return 1

    prod = yaml.safe_load(PROD.read_text(encoding="utf-8")) or {}
    src = yaml.safe_load(SRC.read_text(encoding="utf-8")) or {}
    prod.setdefault("capture", {})
    # Keep production audio settings — they are tuned per-site via the Settings UI.
    preserve = {"audio_enabled", "audio_device", "audio_rate", "audio_channels"}
    for key, value in src.get("capture", {}).items():
        if key not in preserve:
            prod["capture"][key] = value
    PROD.write_text(yaml.dump(prod, default_flow_style=False, sort_keys=False), encoding="utf-8")
    print(f"Updated capture section in {PROD}")
    print(yaml.dump({"capture": prod["capture"]}, default_flow_style=False, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
