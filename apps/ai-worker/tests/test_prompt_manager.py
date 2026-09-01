import pytest
from app.prompts import PromptManager


def test_load_ocr_prompt(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    prompt = manager.load_prompt("ocr")

    assert "system_prompt" in prompt
    assert "model" in prompt
    assert "temperature" in prompt


def test_load_structuring_prompt_default(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    prompt = manager.load_prompt("structuring", "default")

    assert "system_prompt" in prompt
    assert "formatter" in prompt["system_prompt"].lower()


def test_load_structuring_prompt_lab_report(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    prompt = manager.load_prompt("structuring", "lab_report")

    assert "system_prompt" in prompt
    assert "lab report" in prompt["system_prompt"].lower()


def test_load_canonical_prompt_default(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    prompt = manager.load_prompt("canonical", "default")

    assert "system_prompt" in prompt
    assert "json" in prompt["system_prompt"].lower()
    assert prompt["temperature"] == 0.0


def test_load_canonical_prompt_laboratory(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    prompt = manager.load_prompt("canonical", "laboratory")

    assert "system_prompt" in prompt
    assert "results" in prompt["system_prompt"].lower()


def test_load_unknown_category_raises(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    with pytest.raises(FileNotFoundError):
        manager.load_prompt("does_not_exist")


def test_caching_returns_same_object(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    first = manager.load_prompt("ocr")
    second = manager.load_prompt("ocr")
    assert first is second


def test_reload_clears_cache(prompts_dir):
    manager = PromptManager(str(prompts_dir))
    manager.load_prompt("ocr")
    assert manager._cache

    manager.reload_prompts()
    assert not manager._cache
