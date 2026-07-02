#!/usr/bin/env python3
"""Run the theater control app locally."""

import uvicorn

from app.config import get_config

if __name__ == "__main__":
    cfg = get_config()
    uvicorn.run(
        "app.main:app",
        host=cfg["app"]["host"],
        port=int(cfg["app"]["port"]),
        reload=False,
    )
