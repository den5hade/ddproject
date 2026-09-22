"""ai-worker entry point: process documents through the AI pipeline."""

from app.worker.runner import main, run

__all__ = ["main", "run"]

if __name__ == "__main__":
    main()