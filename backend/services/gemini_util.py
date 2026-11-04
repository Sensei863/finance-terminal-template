import logging
import re
import time
from typing import Any, List, Optional

log = logging.getLogger(__name__)

# Explicit blocklist: NEVER select experimental or preview models
_MODEL_BLOCKLIST_TOKENS = (
    "preview",
    "experimental",
    "exp-",
    "exp",
    "test",
    "deprecated",
    "deprecate",
    "lite-preview",
)

# Modalities to exclude for general text / grounding tasks
_NON_TEXT_TOKENS = ("image", "tts", "audio", "video", "embed", "robotics", "live")


def _is_stable_model(model_name: str) -> bool:
    """Returns True only if model is a permanent stable GA release (no previews/experimental)."""
    name = str(model_name or "").lower()
    return not any(tok in name for tok in _MODEL_BLOCKLIST_TOKENS)


# In-memory circuit breaker for models experiencing timeouts or service degradation
_MODEL_FAILURE_REGISTRY = {}


def record_model_failure(model_name: str) -> None:
    """Records a failure or timeout timestamp to temporarily deprioritize the degraded model."""
    clean = str(model_name or "").split("/")[-1].lower()
    _MODEL_FAILURE_REGISTRY[clean] = time.time()
    log.warning(f"Applied dynamic circuit breaker penalty to '{clean}' due to timeout or error.")


def _get_model_penalty(model_name: str, cooldown_seconds: float = 600.0) -> float:
    """Returns a heavy score penalty if the model recently timed out (default 10 min cooldown)."""
    clean = str(model_name or "").split("/")[-1].lower()
    last_fail = _MODEL_FAILURE_REGISTRY.get(clean)
    if not last_fail:
        return 0.0
    elapsed = time.time() - last_fail
    if elapsed < cooldown_seconds:
        return 100.0
    return 0.0


def _rank_models(available_names: List[str], task: str = "text") -> List[str]:
    """
    Dynamically ranks available models purely using semantic version parsing
    and an adaptive runtime circuit breaker. Fully future-proof for any new Gemini releases.
    """
    stable = [m for m in available_names if _is_stable_model(m)]
    if not stable:
        log.warning("No stable models found after filtering out previews; using unfiltered list as emergency fallback.")
        stable = available_names

    if task == "search_grounding":
        filtered = [m for m in stable if "flash" in m.lower() and not any(t in m.lower() for t in _NON_TEXT_TOKENS)]
    elif task == "vision":
        filtered = [m for m in stable if "flash" in m.lower() and not any(t in m.lower() for t in ("tts", "audio", "embed"))]
    else:
        filtered = [m for m in stable if "flash" in m.lower() and not any(t in m.lower() for t in _NON_TEXT_TOKENS)]

    if not filtered:
        filtered = stable

    def model_score(name: str) -> float:
        short = name.split("/")[-1].lower()
        
        # Unversioned legacy alias tags (e.g. -latest) can point to fluctuating backends; deprioritize
        if "latest" in short:
            base_score = 0.0
        else:
            # Dynamically parse semantic version (e.g. gemini-3.1-flash -> 3.1, gemini-2.5-flash -> 2.5)
            match = re.search(r"gemini-(\d+(?:\.\d+)?)", short)
            base_score = float(match.group(1)) if match else 1.0
            
            # Standard flash gets slight preference over lite for higher extraction precision
            if "flash" in short and "lite" not in short:
                base_score += 0.05

        penalty = _get_model_penalty(short)
        return base_score - penalty

    return sorted(filtered, key=model_score, reverse=True)


def _normalize_genai_contents(contents, types_module):
    import base64
    if not isinstance(contents, list):
        return contents

    normalized = []
    for part in contents:
        if isinstance(part, dict) and "inline_data" in part:
            inline = part["inline_data"] or {}
            data = inline.get("data")
            mime = inline.get("mime_type", "application/pdf")
            if isinstance(data, str):
                try:
                    data = base64.standard_b64decode(data)
                except Exception:
                    data = data.encode("utf-8")
            if isinstance(data, (bytes, bytearray)):
                normalized.append(types_module.Part.from_bytes(data=bytes(data), mime_type=mime))
            else:
                normalized.append(part)
            continue
        elif isinstance(part, dict) and "data" in part and "mime_type" in part:
            data = part["data"]
            mime = part["mime_type"]
            if isinstance(data, str):
                try:
                    data = base64.standard_b64decode(data)
                except Exception:
                    data = data.encode("utf-8")
            if isinstance(data, (bytes, bytearray)):
                normalized.append(types_module.Part.from_bytes(data=bytes(data), mime_type=mime))
            else:
                normalized.append(part)
            continue
        normalized.append(part)
    return normalized


DEFAULT_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]
MODEL_REQUEST_TIMEOUT_SECONDS = 20.0


class GenAIModelWrapper:
    def __init__(self, client, model_name: str, types_module, fallback_models=None):
        self._client = client
        self._model_name = model_name
        self._types = types_module
        self._fallback_models = fallback_models if fallback_models is not None else DEFAULT_FALLBACK_MODELS

    def generate_content(self, contents, generation_config=None, timeout: float = MODEL_REQUEST_TIMEOUT_SECONDS, **kwargs):
        config_kwargs = {}
        if isinstance(generation_config, dict):
            config_kwargs = dict(generation_config)

        # Disable thinking budget for extraction/vision tasks to prevent unnecessary latency
        if "thinking_config" not in config_kwargs:
            config_kwargs["thinking_config"] = {"thinking_budget": 0}

        if timeout and "http_options" not in config_kwargs:
            config_kwargs["http_options"] = {"timeout": int(timeout * 1000)}

        try:
            config = self._types.GenerateContentConfig(**config_kwargs)
        except Exception:
            # If thinking_config or http_options is not supported on this SDK version, fall back gracefully
            config_kwargs.pop("thinking_config", None)
            try:
                config = self._types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
            except Exception:
                config_kwargs.pop("http_options", None)
                config = self._types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        models_to_try = [self._model_name] + [m for m in self._fallback_models if m != self._model_name]
        last_err = None

        normalized_contents = _normalize_genai_contents(contents, self._types)

        for model in models_to_try:
            m_clean = str(model).replace("models/", "")
            log.info(f"Attempting generate_content with model: {m_clean} (timeout: {timeout}s)")

            try:
                return self._client.models.generate_content(
                    model=m_clean,
                    contents=normalized_contents,
                    config=config,
                    **kwargs,
                )
            except Exception as e:
                err_msg = str(e).lower()
                is_retryable = any(term in err_msg for term in [
                    "503", "unavailable", "high demand", "overloaded", "temporarily", 
                    "429", "resource_exhausted", "quota", "timeout", "timed out", "not found", "404"
                ])
                if is_retryable:
                    record_model_failure(m_clean)
                if is_retryable and model != models_to_try[-1]:
                    log.warning(f"Model {m_clean} hit issue ({e}). Retrying with fallback model...")
                    last_err = e
                    continue
                else:
                    last_err = e

        if last_err:
            raise last_err


def _get_best_with_google_genai(api_key: str, task: str = "text"):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    try:
        available = []
        for m in client.models.list():
            name = m.name if hasattr(m, 'name') else str(m)
            available.append(name)

        if not available:
            raise RuntimeError("No Gemini models returned by API.")

        ranked = _rank_models(available, task=task)
        best = ranked[0]
        fallbacks = ranked[1:]
        log.info(f"Auto-selected Gemini model ({task}): {best}")
        return GenAIModelWrapper(client, best, types, fallback_models=fallbacks)
    except Exception as e:
        log.warning(f"Could not list models ({e}). Defaulting to gemini-flash-latest")
        return GenAIModelWrapper(client, "gemini-flash-latest", types, fallback_models=["gemini-2.5-flash"])


def get_best_gemini_model(api_key: str, search_grounding: bool = False, task: str = "text"):
    if not api_key:
        raise ValueError("API key must be provided.")

    selected_task = "search_grounding" if search_grounding else task

    try:
        return _get_best_with_google_genai(api_key, task=selected_task)
    except ImportError as exc:
        raise ImportError(
            "The app requires 'google-genai' for Gemini features. "
            "Install/update dependencies with: python -m pip install -r requirements.txt"
        ) from exc


def clean_json_text(text: str) -> str:
    import json
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE | re.IGNORECASE).strip()
    
    start_brace = cleaned.find("{")
    start_bracket = cleaned.find("[")
    
    start = -1
    if start_brace != -1 and start_bracket != -1:
        start = min(start_brace, start_bracket)
    elif start_brace != -1:
        start = start_brace
    else:
        start = start_bracket
        
    if start != -1:
        snippet = cleaned[start:]
        decoder = json.JSONDecoder()
        try:
            _, end_idx = decoder.raw_decode(snippet)
            return snippet[:end_idx]
        except json.JSONDecodeError:
            pass

        fixed_snippet = re.sub(r',(\s*[}\]])', r'\1', snippet)
        try:
            _, end_idx = decoder.raw_decode(fixed_snippet)
            return fixed_snippet[:end_idx]
        except json.JSONDecodeError:
            cleaned = fixed_snippet

    cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
    return cleaned


def get_best_gemini_model_name(client=None, task: str = "text") -> str:
    """Returns the top-ranked stable production Gemini model name (no models/ prefix)."""
    if client is not None:
        try:
            available = [m.name if hasattr(m, 'name') else str(m) for m in client.models.list()]
            ranked = _rank_models(available, task=task)
            return str(ranked[0]).replace("models/", "")
        except Exception:
            pass
    return "gemini-flash-latest"


def generate_content_with_fallback(
    client,
    contents,
    config=None,
    task: str = "text",
):
    """
    Executes generate_content with automatic fallback through ranked models
    if high-demand spikes (503 / 429) occur.
    """
    try:
        available = [m.name if hasattr(m, 'name') else str(m) for m in client.models.list()]
        ranked_models = _rank_models(available, task=task)
    except Exception:
        ranked_models = ["gemini-flash-latest", "gemini-2.5-flash"]

    try:
        from google.genai import types as genai_types
        normalized_contents = _normalize_genai_contents(contents, genai_types)
    except Exception:
        normalized_contents = contents

    last_err = None
    for model_name in ranked_models:
        m_clean = str(model_name).replace("models/", "")
        try:
            log.info(f"Generating content with model: {m_clean}")
            return client.models.generate_content(
                model=m_clean,
                contents=normalized_contents,
                config=config,
            )
        except Exception as e:
            err_msg = str(e).lower()
            is_transient = any(term in err_msg for term in ["503", "unavailable", "high demand", "overloaded", "429", "resource_exhausted", "quota"])
            if is_transient and model_name != ranked_models[-1]:
                log.warning(f"Model {m_clean} hit transient issue ({e}). Retrying with next stable fallback...")
                last_err = e
                continue
            else:
                raise e

    if last_err:
        raise last_err

