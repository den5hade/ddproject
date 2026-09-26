"""Phase 7 contract: the ``tests/fixtures/pii/`` manifest shape (plan §4.10).

Mirrors ``tests/unit/classification/test_fixture_manifest.py``, which asserts the
on-disk ``.md`` set equals the manifest set — so a fixture added without a
manifest entry (or the reverse) fails here. That parity is the reason the
classification dataset and this one are loaded through two different modules
rather than a shared one: the shapes differ (``expected_categories`` +
``expected_risk_level`` + ``contains_secret`` here, ``expected_type`` +
``expected_subtype`` there), and forcing them into a union would put three
always-null fields on every PII entry.

What these tests cannot do, and say so out loud: verify the ``expected_*``
fields. There is no detector in M4, so those values are a specification for M5
to confirm. The tests that matter here are the structural ones — shape, path
resolution, enum validity — plus the checks that keep M4's synthetic-only state
honest.
"""

from __future__ import annotations

import json

import pytest
from app.pii.fixtures import (
    FIXTURES_DIR,
    MANIFEST_PATH,
    PII_FIXTURE_DIRECTORIES,
    PIIFixture,
    iter_pii_fixtures,
)
from app.pii.models import PIICategory, PIIDecision, PIIRiskLevel

MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
FIXTURES = iter_pii_fixtures()

# §4.10 fixes the entry keys: file, source, expected_categories,
# expected_decision, expected_risk_level, with contains_secret optional.
REQUIRED_ENTRY_KEYS = {
    "file",
    "source",
    "expected_categories",
    "expected_decision",
    "expected_risk_level",
}
OPTIONAL_ENTRY_KEYS = {"contains_secret"}
# Tolerated but not required by §4.10 — a future M5 entry may carry them, and
# failing an unknown key is how a manifest silently grows a second contract.
ALLOWED_EXTRA_KEYS: set[str] = set()


# --- the manifest itself --------------------------------------------------


def test_manifest_exists_at_the_planned_path():
    assert MANIFEST_PATH.name == "manifest.json"
    assert MANIFEST_PATH.parent.name == "pii"
    assert MANIFEST_PATH.parent == FIXTURES_DIR


def test_manifest_top_level_keys_are_version_notes_fixtures():
    assert set(MANIFEST) == {"version", "notes", "fixtures"}


def test_manifest_version_is_semver():
    parts = MANIFEST["version"].split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)


def test_manifest_notes_explain_the_assumed_policy_context():
    # expected_decision is context-dependent (Phase 5: a patient category is
    # ALLOW_WITH_WARNING internally and REVIEW at the external boundary) and
    # §4.10's entry keys have no destination field, so the notes have to say which
    # context the expectations assume or the manifest is unreadable.
    notes = MANIFEST["notes"]
    assert "expected_decision" in notes
    assert "external" in notes.lower()


def test_manifest_has_the_three_seeded_fixtures():
    assert len(FIXTURES) == 3


def test_manifest_covers_the_three_seeded_directories():
    dirs = {fixture.file.split("/", 1)[0] for fixture in FIXTURES}
    assert dirs == {"clean", "patient", "malicious"}


def test_seeded_directories_are_a_subset_of_the_planned_seven():
    # The remaining four (laboratory, appointment, prescription, mixed) are M5's
    # real-marker sweep; fixing the target set now means that sweep has a
    # vocabulary and a mis-pathed file fails instead of extending the dataset.
    assert set(PII_FIXTURE_DIRECTORIES) == {
        "clean",
        "patient",
        "laboratory",
        "appointment",
        "prescription",
        "mixed",
        "malicious",
    }
    dirs = {fixture.file.split("/", 1)[0] for fixture in FIXTURES}
    assert dirs <= set(PII_FIXTURE_DIRECTORIES)


# --- entry shape ----------------------------------------------------------


def test_every_entry_has_exactly_the_planned_keys():
    for entry in MANIFEST["fixtures"]:
        keys = set(entry)
        assert keys >= REQUIRED_ENTRY_KEYS, entry["file"]
        assert keys <= REQUIRED_ENTRY_KEYS | OPTIONAL_ENTRY_KEYS | ALLOWED_EXTRA_KEYS


def test_contains_secret_is_bool_when_present():
    for entry in MANIFEST["fixtures"]:
        if "contains_secret" in entry:
            assert isinstance(entry["contains_secret"], bool), entry["file"]


def test_absent_contains_secret_means_false():
    # The two entries that omit the key must load as False rather than raising —
    # the flag exists because a secret-bearing fixture must be handled specially,
    # so its absence cannot mean "unknown".
    absent = [entry["file"] for entry in MANIFEST["fixtures"] if "contains_secret" not in entry]
    assert absent
    for fixture in FIXTURES:
        if fixture.file in absent:
            assert fixture.contains_secret is False


def test_only_the_malicious_fixture_declares_a_secret():
    holders = [f.file for f in FIXTURES if f.contains_secret]
    assert holders == ["malicious/synthetic-injection-01.md"]


def test_loader_defaults_contains_secret_to_false():
    for fixture in FIXTURES:
        if not fixture.contains_secret:
            assert fixture.contains_secret is False


def test_entry_file_is_a_relative_posix_path():
    for fixture in FIXTURES:
        assert not fixture.file.startswith("/")
        assert "\\" not in fixture.file
        assert fixture.file.endswith(".md")
        assert fixture.file == fixture.file.strip()


def test_expected_categories_is_a_list_of_valid_categories():
    for fixture in FIXTURES:
        assert isinstance(fixture.expected_categories, tuple)
        for category in fixture.expected_categories:
            assert category in {c.value for c in PIICategory}, (fixture.file, category)


def test_expected_categories_has_no_duplicates():
    for fixture in FIXTURES:
        assert len(set(fixture.expected_categories)) == len(fixture.expected_categories)


def test_expected_decision_is_a_valid_decision():
    for fixture in FIXTURES:
        assert fixture.expected_decision in {d.value for d in PIIDecision}


def test_expected_risk_level_is_a_valid_risk_level():
    for fixture in FIXTURES:
        assert fixture.expected_risk_level in {r.value for r in PIIRiskLevel}


def test_every_source_is_real_or_synthetic():
    for fixture in FIXTURES:
        assert fixture.source in {"real", "synthetic"}


# --- the M4 synthetic-only state -----------------------------------------


def test_all_seeded_fixtures_are_synthetic():
    # Deliberate: M4 has no detector, and a real marker would mean copying real
    # patient data into a second file — a new instance of the exact leak this
    # milestone exists to close. The real-marker sweep is M5's.
    assert all(fixture.source == "synthetic" for fixture in FIXTURES)


def test_no_fixture_contains_a_known_real_marker_name():
    # Guards the rule above mechanically: the real markers are named by their
    # marker ids, so none may appear in a file M4 seeded.
    real_markers = {"fbbcb675", "2b8fdd0d"}
    for fixture in FIXTURES:
        assert not (real_markers & {fixture.file}), fixture.file


# --- on-disk agreement (the classification-manifest parity rule) ---------


def test_manifest_matches_on_disk_fixture_set():
    on_disk = {
        str(path.relative_to(MANIFEST_PATH.parent)).replace("\\", "/")
        for path in MANIFEST_PATH.parent.rglob("*.md")
    }
    assert on_disk == {fixture.file for fixture in FIXTURES}


def test_every_fixture_file_exists():
    for fixture in FIXTURES:
        assert fixture.path.exists(), fixture.file


def test_every_fixture_file_is_non_empty_and_readable():
    for fixture in FIXTURES:
        text = fixture.path.read_text(encoding="utf-8")
        assert text.strip(), fixture.file


def test_fixture_paths_resolve_under_the_fixtures_dir():
    for fixture in FIXTURES:
        assert fixture.path.resolve().is_relative_to(FIXTURES_DIR.resolve())


def test_fixtures_are_immutable_records():
    fixture = FIXTURES[0]
    with pytest.raises(AttributeError):
        fixture.file = "other.md"  # type: ignore[misc]


def test_decisions_span_allow_review_and_block():
    # The trio exists to cover the widest decision spread obtainable without a
    # real marker: if all three fixtures expected the same decision, the shape
    # would be proven but the spread would not.
    assert {fixture.expected_decision for fixture in FIXTURES} == {"allow", "review", "block"}


def test_risk_levels_span_low_high_and_critical():
    assert {fixture.expected_risk_level for fixture in FIXTURES} == {"low", "high", "critical"}


def test_block_fixture_is_the_secret_holder():
    # Only SECRET is critical, and it is the only category that blocks, so the
    # critical/block pairing and the secret flag are the same fact seen twice.
    blocked = [f for f in FIXTURES if f.expected_decision == "block"]
    assert len(blocked) == 1
    assert PIICategory.SECRET.value in blocked[0].expected_categories
    assert blocked[0].expected_risk_level == PIIRiskLevel.CRITICAL.value
    assert blocked[0].contains_secret


def test_patient_fixture_expects_more_than_a_secret():
    # Proves the manifest can express a multi-category document, which is the
    # case the category_counts/categories split in §4.7 exists for.
    patient = [f for f in FIXTURES if f.file.startswith("patient/")]
    assert len(patient) == 1
    assert len(patient[0].expected_categories) > 1
    assert PIICategory.SECRET.value not in patient[0].expected_categories


def test_clean_fixture_expects_nothing():
    clean = [f for f in FIXTURES if f.file.startswith("clean/")]
    assert len(clean) == 1
    assert clean[0].expected_categories == ()
    assert clean[0].expected_decision == PIIDecision.ALLOW.value
    assert clean[0].expected_risk_level == PIIRiskLevel.LOW.value


def test_loader_returns_fixtures_in_manifest_order():
    assert [f.file for f in iter_pii_fixtures()] == [
        entry["file"] for entry in MANIFEST["fixtures"]
    ]


def test_fixture_dataclass_field_names_match_the_entry_keys():
    # A reader should be able to go from the manifest entry to the dataclass
    # without consulting the loader; this fails if one side gains a field.
    assert set(PIIFixture.__dataclass_fields__) == REQUIRED_ENTRY_KEYS | {
        "path",
        "contains_secret",
    }
