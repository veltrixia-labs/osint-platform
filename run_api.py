"""
Production ASGI entrypoint.

Render / local:
  uvicorn run_api:app --host 0.0.0.0 --port $PORT

Equivalent to:
  uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment before importing the FastAPI app graph.
load_dotenv(Path(__file__).resolve().parent / ".env")

from api.main import app  # noqa: E402

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("run_api:app", host="0.0.0.0", port=port, factory=False)
