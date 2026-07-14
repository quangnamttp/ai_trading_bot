"""
Test utility functions
"""
from utils.utils import (
    format_number, format_percentage, format_currency,
    clamp, safe_divide, percentage_change
)


def test_format_number():
    """Test number formatting"""
    assert format_number(123.456, 2) == "123.46"
    assert format_number(123.456, 1) == "123.5"


def test_format_percentage():
    """Test percentage formatting"""
    assert format_percentage(0.1234, 2) == "12.34%"
    assert format_percentage(0.5, 1) == "50.0%"


def test_format_currency():
    """Test currency formatting"""
    assert format_currency(1500000) == "$1.50M"
    assert format_currency(1500) == "$1.50K"
    assert format_currency(500) == "$500.00"


def test_clamp():
    """Test value clamping"""
    assert clamp(5, 0, 10) == 5
    assert clamp(15, 0, 10) == 10
    assert clamp(-5, 0, 10) == 0


def test_safe_divide():
    """Test safe division"""
    assert safe_divide(10, 2) == 5.0
    assert safe_divide(10, 0) == 0.0
    assert safe_divide(10, 0, default=1.0) == 1.0


def test_percentage_change():
    """Test percentage change calculation"""
    assert percentage_change(100, 150) == 50.0
    assert percentage_change(100, 50) == -50.0
    assert percentage_change(0, 100) == 0.0
