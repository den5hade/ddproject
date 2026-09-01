from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent
PROMPTS_DIR = APP_ROOT / "app" / "prompts"

_SAMPLE_PDF_CANDIDATES = [
    REPO_ROOT / "apps" / "web" / "tests" / "e2e" / "fixtures" / "sample.pdf",
    APP_ROOT / "tests" / "fixtures" / "sample.pdf",
]


@pytest.fixture
def prompts_dir() -> Path:
    return PROMPTS_DIR


@pytest.fixture
def sample_pdf() -> bytes:
    for candidate in _SAMPLE_PDF_CANDIDATES:
        if candidate.exists():
            return candidate.read_bytes()
    raise FileNotFoundError(
        f"no sample.pdf fixture found (tried {[str(c) for c in _SAMPLE_PDF_CANDIDATES]})"
    )
