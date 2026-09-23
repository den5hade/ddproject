"""Phase 5: regression fixture manifest integrity (every fixture loads)."""

import json

from app.classification.models import ClassificationDecision, DocumentType
from tests.support.classification_fixtures import (
    MANIFEST_PATH,
    iter_classification_fixtures,
)


def test_manifest_parses():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0"
    assert len(manifest["fixtures"]) == 11


def test_manifest_entries_have_expected_keys():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    required = {"file", "expected_type", "expected_subtype", "expected_decision"}
    for entry in manifest["fixtures"]:
        assert required <= entry.keys()


def test_manifest_expected_values_are_contract_values():
    valid_types = {t.value for t in DocumentType}
    valid_decisions = {d.value for d in ClassificationDecision}
    fixtures = iter_classification_fixtures()
    assert fixtures
    for fixture in fixtures:
        assert fixture.expected_type in valid_types
        assert fixture.expected_decision in valid_decisions


def test_every_fixture_file_loads():
    fixtures = iter_classification_fixtures()
    for fixture in fixtures:
        assert fixture.path.is_file(), f"{fixture.file} missing"
        text = fixture.path.read_text(encoding="utf-8")
        assert text.strip(), f"{fixture.file} is empty"


def test_manifest_covers_all_fixture_files():
    covered = {fixture.file for fixture in iter_classification_fixtures()}
    expected = {
        "laboratory/fbbcb675.md",
        "laboratory/b8f07559.md",
        "laboratory/datalab-output-27022026.pdf.md",
        "laboratory/datalab-output-gemotest_1_photo.jpg.md",
        "laboratory/datalab-output-helix_3_photo.jpeg.md",
        "laboratory/datalab-output-invitro_3_prscreen.jpg.md",
        "appointment/2b8fdd0d.md",
        "appointment/appointment_002.md",
        "prescription/prescription_001.md",
        "other/lab_without_keywords_001.md",
        "other/generic_001.md",
    }
    assert covered == expected


def test_each_document_type_directory_has_fixtures():
    dirs = {fixture.file.split("/", 1)[0] for fixture in iter_classification_fixtures()}
    assert dirs == {"laboratory", "appointment", "prescription", "other"}


def test_manifest_matches_on_disk_fixture_set():
    on_disk = {
        str(p.relative_to(MANIFEST_PATH.parent)).replace("\\", "/")
        for p in (MANIFEST_PATH.parent).rglob("*.md")
    }
    covered = {fixture.file for fixture in iter_classification_fixtures()}
    assert on_disk == covered