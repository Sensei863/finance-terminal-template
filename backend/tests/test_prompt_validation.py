import pytest
from backend.routers.system import validate_prompt_template

def test_matched_braces_valid_placeholders():
    valid_prompt = "Stock {{ticker}} with price {{price}} is in {{industry}}."
    # Should not raise exception
    validate_prompt_template("deep_dive_stock", valid_prompt)

def test_mismatched_braces_raises_error():
    mismatched_prompt = "Stock {{ticker} is down."
    with pytest.raises(ValueError):
        validate_prompt_template("deep_dive_stock", mismatched_prompt)

def test_invalid_placeholder_raises_error():
    invalid_ph_prompt = "Stock {{ticker}} has invalid field {{nonexistent_field}}."
    with pytest.raises(ValueError):
        validate_prompt_template("deep_dive_stock", invalid_ph_prompt)

def test_invalid_characters_in_placeholder_raises_error():
    bad_chars_prompt = "Stock {{ticker!}} is invalid."
    with pytest.raises(ValueError):
        validate_prompt_template("deep_dive_stock", bad_chars_prompt)
