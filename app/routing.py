from typing import Dict

DEPARTMENTS: Dict[str, str] = {
    "PAYMENT": "BILLING",
    "REFUND": "BILLING",
    "DELIVERY": "LOGISTICS",
    "ORDER": "SALES_SUPPORT",
    "ACCOUNT": "ACCOUNT_SUPPORT",
    "TECHNICAL": "TECH_SUPPORT",
    "SUBSCRIPTION": "CUSTOMER_SUCCESS",
    "OTHER": "GENERAL_SUPPORT",
}


def get_department(category: str) -> str:
    """Маршрутизация по категории. Решает Python, а не модель."""
    return DEPARTMENTS.get(str(category).upper(), "GENERAL_SUPPORT")
