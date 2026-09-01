from pathlib import Path

import yaml


class PromptManager:
    """Load and cache AI prompts from YAML configuration files."""

    def __init__(self, prompts_dir: str | Path) -> None:
        self._prompts_dir = Path(prompts_dir)
        self._cache: dict[str, dict] = {}

    def load_prompt(self, category: str, doc_type: str = "default") -> dict:
        """Load a prompt configuration.

        Args:
            category: Prompt category (e.g., "ocr", "structuring").
            doc_type: Document type (e.g., "default", "lab_report", "prescription").

        Returns:
            Prompt config dict with system_prompt, model, temperature.
        """
        cache_key = f"{category}:{doc_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        prompt_file = self._prompts_dir / f"{category}.yaml"
        if not prompt_file.exists():
            raise FileNotFoundError(f"prompt file not found: {prompt_file}")

        with open(prompt_file, encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}

        if category in ("structuring", "canonical"):
            prompts = config.get("prompts", {})
            prompt_config = prompts.get(doc_type, prompts.get("default", {}))
        else:
            prompt_config = config

        self._cache[cache_key] = prompt_config
        return prompt_config

    def reload_prompts(self) -> None:
        """Clear the cache so prompts are re-read from disk."""
        self._cache.clear()


__all__ = ["PromptManager"]
