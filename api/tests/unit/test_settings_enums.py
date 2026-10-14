"""The settings API's enum names match the model enums (T-10-4a), so a new
strategy or cadence can't be added to one and forgotten in the other."""
import typing

from app.models import AccountRole, RepaymentCadence, RepaymentStrategy
from app.schemas import AccountRoleName, RepaymentCadenceName, RepaymentStrategyName


def test_api_enum_names_match_the_model_enums():
    assert set(typing.get_args(AccountRoleName)) == {r.value for r in AccountRole}
    assert set(typing.get_args(RepaymentStrategyName)) == {s.value for s in RepaymentStrategy}
    assert set(typing.get_args(RepaymentCadenceName)) == {c.value for c in RepaymentCadence}
    assert {"statement_balance"} <= set(typing.get_args(RepaymentStrategyName))
    assert {"card_due_date"} <= set(typing.get_args(RepaymentCadenceName))
