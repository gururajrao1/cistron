"""``python -m voidsignal.api`` / ``voidsignal-api`` entrypoint."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run(
        "voidsignal.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
