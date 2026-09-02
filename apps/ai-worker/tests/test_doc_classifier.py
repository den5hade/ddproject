from app.doc_classifier import classify_document_type

LAB_MD = """## Page 1

Результаты лабораторных исследований

| Показатель | Значение | Ед. изм. | Референтный диапазон |
| :--- | :--- | :--- | :--- |
| Скорость оседания эритроцитов | 4 | мм/ч | |
"""

PRESCRIPTION_MD = """## Page 1

Рецепт

| Препарат | Дозировка |
| :--- | :--- |
| Амоксициллин | 500 мг |
"""

GENERIC_MD = """## Page 1

Записка врача. Пациенту рекомендован покой.
"""


def test_detects_laboratory_from_content():
    assert classify_document_type(LAB_MD) == "laboratory"


def test_detects_prescription_from_content():
    assert classify_document_type(PRESCRIPTION_MD) == "prescription"


def test_generic_content_defaults():
    assert classify_document_type(GENERIC_MD) == "default"


def test_explicit_client_lab_result_wins():
    assert classify_document_type(GENERIC_MD, client_type="lab_result") == "laboratory"


def test_explicit_client_prescription_wins():
    assert classify_document_type(GENERIC_MD, client_type="prescription") == "prescription"


def test_unknown_client_type_serial_falls_back_to_content():
    assert classify_document_type(LAB_MD, client_type="other") == "laboratory"
    assert classify_document_type(GENERIC_MD, client_type="doctor_report") == "default"


def test_empty_markdown_defaults():
    assert classify_document_type("") == "default"
    assert classify_document_type(None) == "default"
