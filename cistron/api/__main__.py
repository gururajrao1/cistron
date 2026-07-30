"""``python -m cistron.api`` / ``cistron-api`` entrypoint."""

from __future__ import annotations


def main() -> None:
    import os

    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "cistron.api.app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
