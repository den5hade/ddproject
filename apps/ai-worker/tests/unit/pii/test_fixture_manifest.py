"""Phase 7 contract: the ``tests/fixtures/pii/`` manifest shape (plan §4.10).

Mirrors ``tests/unit/classification/test_fixture_manifest.py``, which asserts the
on-disk ``.md`` set equals the manifest set — so a fixture added without a
manifest entry (or the reverse) fails here. That parity is the reason the
classification dataset and this one are loaded through two different modules
rather than a shared one: the shapes differ (``expected_categories`` +
``expected_risk_level`` + ``contains_secret`` here, ``expected_type`` +
``expected_subtype`` there), and forcing them into a union would put three
always-null fields on every PII entry.

What these tests deliberately do not do: verify the ``expected_*`` fields. That
is not an oversight and it is not a Phase 13 regression — this module owns the
*shape* of the manifest, and checking that a file it never scans finds what the
manifest says it finds would put a second opinion about detection inside the
structural contract, where a reviewer would not look for it. The semantic check
lives in ``tests/unit/pii/test_manifest_verification.py``, which runs the real
gate; this one asserts the file is well-formed, resolvable and honest about
being synthetic, which is the part a reader of the dataset itself relies on.
"""

from __future__ import annotations

import json

import pytest
from app.pii.fixtures import (
    CONTOUR_CANONICAL,
    CONTOUR_DOCUMENT,
    PII_FIXTURE_DIRECTORIES,
    SYNTHETIC_FIXTURES_DIR,
    SYNTHETIC_MANIFEST_PATH,
    PIIFixture,
    iter_canonical_fixtures,
    iter_pii_fixtures,
)
from app.pii.models import PIICategory, PIIDecision, PIIRiskLevel, PIISource

MANIFEST = json.loads(SYNTHETIC_MANIFEST_PATH.read_text(encoding="utf-8"))
FIXTURES = iter_pii_fixtures()

# §4.10 fixes the entry keys: file, source, expected_categories,
# expected_decision, expected_risk_level, with contains_secret optional.
# M6 (Phase 1) adds id, contour and expected_detector_source. `contour` is
# required rather than derived from the extension because the two corpora use
# different extensions, so a payload in the document section has to be a
# manifest bug the loader rejects rather than a silently different evaluation.
REQUIRED_ENTRY_KEYS = {
    "file",
    "source",
    "expected_categories",
    "expected_decision",
    "expected_risk_level",
    "id",
    "contour",
    "expected_detector_source",
}
OPTIONAL_ENTRY_KEYS = {"contains_secret", "derived_from", "provenance"}
# Tolerated but not required by §4.10 — a future entry may carry them, and
# failing an unknown key is how a manifest silently grows a second contract.
ALLOWED_EXTRA_KEYS: set[str] = set()


# --- the manifest itself --------------------------------------------------


def test_manifest_exists_at_the_planned_path():
    assert SYNTHETIC_MANIFEST_PATH.name == "manifest.json"
    assert SYNTHETIC_MANIFEST_PATH.parent.name == "pii"
    assert SYNTHETIC_MANIFEST_PATH.parent == SYNTHETIC_FIXTURES_DIR


def test_manifest_top_level_keys_are_version_notes_fixtures_canonical():
    assert set(MANIFEST) == {"version", "notes", "fixtures", "canonical_fixtures"}


def test_manifest_version_is_semver():
    parts = MANIFEST["version"].split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)


def test_manifest_notes_record_the_appointment_entry_provenance():
    # Decision 9: a "real marker" entry reproduces the shape and invents every
    # value. That rule is only auditable if the file says which real document the
    # shape came from — and it must, without the contents, or a reader cannot
    # tell a deliberate synthetic from an accidental copy.
    notes = MANIFEST["notes"]
    assert "2b8fdd0d" in notes
    assert "appointment/synthetic-registration-01.md" in notes


def test_manifest_notes_say_the_expectations_are_measured():
    # The phase's whole point: expected_* stopped being a declaration and became
    # an observation. A manifest that said nothing about which would be
    # indistinguishable from the M4 file it replaced.
    assert "test_manifest_verification.py" in MANIFEST["notes"]


def test_manifest_notes_explain_the_assumed_policy_context():
    # expected_decision is context-dependent (Phase 5: a patient category is
    # ALLOW_WITH_WARNING internally and REVIEW at the external boundary) and
    # §4.10's entry keys have no destination field, so the notes have to say which
    # context the expectations assume or the manifest is unreadable.
    notes = MANIFEST["notes"]
    assert "expected_decision" in notes
    assert "external" in notes.lower()


def test_manifest_has_the_four_seeded_fixtures():
    assert len(FIXTURES) == 4


def test_manifest_covers_the_four_seeded_directories():
    dirs = {fixture.file.split("/", 1)[0] for fixture in FIXTURES}
    assert dirs == {"clean", "patient", "appointment", "malicious"}


def test_seeded_directories_are_a_subset_of_the_planned_seven():
    # The remaining three (laboratory, prescription, mixed) are the rest of M5's
    # sweep; fixing the target set up front means that sweep has a vocabulary and
    # a mis-pathed file fails instead of extending the dataset. `appointment` is
    # the one Phase 13 added, for the 2b8fdd0d shape and the G1 declined name.
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


# --- M6: ids, contours and detector sources -------------------------------


def test_every_entry_has_a_unique_id():
    # Report rows are keyed by id, so a duplicate would silently merge two
    # fixtures into one row and halve a denominator.
    ids = [f.id for f in FIXTURES] + [f.id for f in iter_canonical_fixtures()]
    assert len(set(ids)) == len(ids)


def test_document_entries_declare_the_document_contour():
    # The two sections describe different boundaries, so a payload filed under
    # `fixtures` would be scored at the source contour and compared against
    # expectations measured at persistence — wrong without ever raising.
    assert all(f.contour == CONTOUR_DOCUMENT for f in FIXTURES)
    assert all(f.contour == CONTOUR_CANONICAL for f in iter_canonical_fixtures())


def test_contour_agrees_with_the_file_extension():
    for fixture in iter_pii_fixtures():
        assert fixture.path.suffix == (".md" if fixture.contour == CONTOUR_DOCUMENT else ".json")


def test_every_entry_declares_its_detector_source():
    # The machine-checkable form of "the structured detector went silent on a
    # real layout": the expected set is per category, not per fixture, because
    # a single category can legitimately be reachable from two layers. The
    # clean fixture maps nothing, which is the honest answer for a document
    # with no categories — the keys have to line up with the categories exactly,
    # so an extra key would be a category no detector is expected to find.
    for fixture in iter_pii_fixtures():
        assert set(fixture.expected_detector_source) == set(fixture.expected_categories), fixture.id
        assert bool(fixture.expected_detector_source) == bool(fixture.expected_categories), (
            fixture.id
        )


def test_detector_source_layers_are_known():
    known = {s.value for s in PIISource}
    for fixture in iter_pii_fixtures():
        for category, sources in fixture.expected_detector_source.items():
            assert set(sources) <= known, (fixture.id, category)


def test_expected_detector_source_is_immutable():
    # The manifest is the ground truth; a test that could edit it would be
    # asserting an expectation it had just rewritten.
    fixture = FIXTURES[0]
    with pytest.raises(TypeError):
        fixture.expected_detector_source["phone"] = ()  # type: ignore[index]


def test_derived_entries_record_where_their_shape_came_from():
    # Decision 9 lets a fixture reproduce a real document's shape; that is only
    # auditable if it names the shape's origin without reproducing its contents.
    derived = [f for f in iter_pii_fixtures() if f.derived_from]
    assert derived, "expected at least one layout-derived entry"
    for fixture in derived:
        assert "layout only" in fixture.derived_from.lower(), fixture.id


def test_clean_entry_is_not_derived():
    assert next(f for f in iter_pii_fixtures() if f.file.startswith("clean/")).derived_from is None


def test_canonical_section_is_not_empty_and_uses_its_own_extension():
    canonical = iter_canonical_fixtures()
    assert canonical
    assert all(f.path.suffix == ".json" for f in canonical)


def test_canonical_entries_measure_the_persistence_boundary():
    # Contour 2's decision differs from the source contour's for the same bytes
    # (REVIEW -> ALLOW_WITH_WARNING), so its expected_decision is not a restated
    # document expectation and is stored against the canonical section.
    for fixture in iter_canonical_fixtures():
        assert fixture.expected_decision == PIIDecision.ALLOW_WITH_WARNING.value, fixture.id


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
        str(path.relative_to(SYNTHETIC_MANIFEST_PATH.parent)).replace("\\", "/")
        for path in SYNTHETIC_MANIFEST_PATH.parent.rglob("*.md")
    }
    assert on_disk == {fixture.file for fixture in FIXTURES}


def test_every_fixture_file_exists():
    for fixture in FIXTURES:
        assert fixture.path.exists(), fixture.file


def test_every_fixture_file_is_non_empty_and_readable():
    for fixture in FIXTURES:
        text = fixture.path.read_text(encoding="utf-8")
        assert text.strip(), fixture.file


def test_fixture_paths_resolve_under_the_synthetic_fixtures_dir():
    for fixture in FIXTURES:
        assert fixture.path.resolve().is_relative_to(SYNTHETIC_FIXTURES_DIR.resolve())


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
    # `dataset` is the one field that is in no manifest — it is derived from
    # which of the two manifests the entry was read out of, which is exactly
    # why it cannot be an entry key.
    assert set(PIIFixture.__dataclass_fields__) == (
        REQUIRED_ENTRY_KEYS | OPTIONAL_ENTRY_KEYS | {"path", "dataset"}
    )


def test_expected_detector_source_is_a_frozen_mapping_not_a_plain_dict():
    # Provenance and the detector-source map are the two fields a test would
    # most plausibly edit to make an assertion pass.
    fixture = FIXTURES[0]
    assert type(fixture.expected_detector_source).__name__ == "mappingproxy"
