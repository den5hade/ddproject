from app.domain.organization import (
    inn_checksum_valid,
    normalize_inn,
    normalize_ogrn,
    ogrn_checksum_valid,
)


def test_normalize_inn_strips_whitespace() -> None:
    assert normalize_inn(" 7707083893 ") == "7707083893"
    assert normalize_inn(None) is None


def test_inn_10_digits_valid() -> None:
    assert inn_checksum_valid("7707083893") is True


def test_inn_12_digits_valid() -> None:
    assert inn_checksum_valid("500100732259") is True


def test_inn_checksum_rejects_altered_digits() -> None:
    assert inn_checksum_valid("7707083894") is False
    assert inn_checksum_valid("500100732250") is False


def test_inn_rejects_bad_shape() -> None:
    assert inn_checksum_valid("770708389") is False
    assert inn_checksum_valid("77070838931") is False
    assert inn_checksum_valid("77A7083893") is False


def test_ogrn_13_digits_valid() -> None:
    assert ogrn_checksum_valid("1027700132195") is True


def test_ogrn_checksum_rejects_altered_digit() -> None:
    assert ogrn_checksum_valid("1027700132194") is False


def test_ogrn_rejects_bad_shape() -> None:
    assert ogrn_checksum_valid("102770013219") is False
    assert ogrn_checksum_valid("10277001321951") is False


def test_normalize_ogrn_strips_whitespace() -> None:
    assert normalize_ogrn(" 1027700132195 ") == "1027700132195"
    assert normalize_ogrn(None) is None