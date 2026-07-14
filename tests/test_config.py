"""
Test configuration module
"""
import os
import pytest
from core.config import validate_config, TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID


def test_validate_config_with_valid_values():
    """Test configuration validation with valid values"""
    # This test assumes environment variables are set
    try:
        result = validate_config()
        assert result is True
    except ValueError:
        # If env vars are not set, this is expected
        pytest.skip("Environment variables not set")


def test_validate_config_missing_token():
    """Test configuration validation with missing token"""
    original_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if original_token:
        del os.environ['TELEGRAM_BOT_TOKEN']
    
    try:
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is required"):
            validate_config()
    finally:
        if original_token:
            os.environ['TELEGRAM_BOT_TOKEN'] = original_token


def test_validate_config_missing_admin_id():
    """Test configuration validation with missing admin ID"""
    original_admin = os.environ.get('TELEGRAM_ADMIN_ID')
    if original_admin:
        del os.environ['TELEGRAM_ADMIN_ID']
    
    try:
        with pytest.raises(ValueError, match="TELEGRAM_ADMIN_ID is required"):
            validate_config()
    finally:
        if original_admin:
            os.environ['TELEGRAM_ADMIN_ID'] = original_admin
