from decimal import Decimal

import pytest
from app.core.config import Settings
from app.core.enums import IssueType, RiskLevel
from app.services.policy import RiskEngine


@pytest.mark.parametrize(
    "amount,risk",
    [
        ("999.99", RiskLevel.LOW),
        ("1000.00", RiskLevel.HIGH),
        ("1000.01", RiskLevel.HIGH),
    ],
)
def test_high_amount_threshold_is_inclusive(amount, risk):
    engine = RiskEngine(Settings(_env_file=None))
    actual, rules = engine.assess(Decimal(amount), IssueType.CANCEL)
    assert actual == risk
    assert ("HIGH_AMOUNT" in rules) == (risk == RiskLevel.HIGH)
