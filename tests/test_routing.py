import pytest

from app.routing import get_department


@pytest.mark.parametrize(
    "category,expected",
    [
        ("PAYMENT", "BILLING"),
        ("REFUND", "BILLING"),
        ("DELIVERY", "LOGISTICS"),
        ("ORDER", "SALES_SUPPORT"),
        ("ACCOUNT", "ACCOUNT_SUPPORT"),
        ("TECHNICAL", "TECH_SUPPORT"),
        ("SUBSCRIPTION", "CUSTOMER_SUCCESS"),
        ("OTHER", "GENERAL_SUPPORT"),
    ],
)
def test_known_categories(category, expected):
    assert get_department(category) == expected


def test_lowercase_accepted():
    assert get_department("payment") == "BILLING"


def test_unknown_category_falls_back():
    assert get_department("SOMETHING_NEW") == "GENERAL_SUPPORT"
