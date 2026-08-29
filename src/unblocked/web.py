"""Entry point for hosted deployment.

Separate from the CLI on purpose. `unblocked ui` shells out through Typer, which
is right for a laptop and wrong for a container: a platform sends SIGTERM to
PID 1 and expects the server to handle it, and an extra process layer swallows
that. This starts uvicorn directly.
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "unblocked.ui.app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        workers=1,
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
