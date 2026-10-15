"""The holding kind registry (ADR-002 section 2, T-11-3a).

Every stored asset type and liability kind is one registry entry that says
how it reaches every surface. A kind that skips a surface fails here, so a
new kind can't miss net worth, Claude or demo mode the way budgets and loans
did. An unknown stored type fails closed: counted at its stored value.
"""
from dataclasses import replace

import pytest

from app.models.asset import ASSET_TYPES
from app.models.liability import LiabilityKind
from app.services.holdings import registry
from app.services.holdings.registry import (
    INVESTMENT_KINDS,
    KINDS,
    Surface,
    RegistryError,
    kind_for,
    validate,
)


def _kind(source, stored_type):
    return next(k for k in KINDS if (k.source, k.stored_type) == (source, stored_type))


def test_the_shipped_registry_is_valid():
    validate(KINDS)


def test_every_stored_type_has_an_entry():
    assert {k.stored_type for k in KINDS if k.source == "assets"} == set(ASSET_TYPES)
    assert {k.stored_type for k in KINDS if k.source == "liabilities"} == {k.value for k in LiabilityKind}


def test_each_kind_is_declared_once():
    keys = [(k.source, k.stored_type) for k in KINDS]
    assert len(keys) == len(set(keys))


def test_investments_are_the_owners_list():
    # Owner decision D1 (2026-10-15): savings and property are their own groups.
    assert {(k.source, k.stored_type) for k in INVESTMENT_KINDS} == {
        ("assets", "isa"), ("assets", "investment"), ("assets", "pension"), ("assets", "crypto"),
    }


@pytest.mark.parametrize("stored_type", ["mortgage", "loan", "other_liability"])
def test_legacy_asset_debts_are_debt_and_never_investments(stored_type):
    kind = _kind("assets", stored_type)
    assert kind.is_debt and not kind.is_investment and kind.group == "debt"


@pytest.mark.parametrize("stored_type", [k.value for k in LiabilityKind])
def test_liabilities_amortise_and_carry_the_repayment_link(stored_type):
    kind = _kind("liabilities", stored_type)
    assert kind.model == "amortisation"
    assert kind.link_role == "repayment"
    assert kind.is_debt and kind.group == "debt"


@pytest.mark.parametrize("stored_type", ["isa", "investment", "pension", "crypto"])
def test_investments_grow_and_take_a_contribution(stored_type):
    kind = _kind("assets", stored_type)
    assert (kind.model, kind.link_role, kind.group) == ("growth", "contribution", "investments")


# --- self-tests: the check fires --------------------------------------------

def test_a_kind_missing_a_surface_fails():
    isa = _kind("assets", "isa")
    surfaces = {s: text for s, text in isa.surfaces.items() if s is not Surface.CLAUDE}
    with pytest.raises(RegistryError, match="CLAUDE"):
        validate((replace(isa, surfaces=surfaces),))


def test_a_blank_surface_declaration_fails():
    isa = _kind("assets", "isa")
    with pytest.raises(RegistryError, match="DEMO"):
        validate((replace(isa, surfaces={**isa.surfaces, Surface.DEMO: "  "}),))


def test_a_debt_marked_as_an_investment_fails():
    loan = _kind("liabilities", "loan")
    with pytest.raises(RegistryError, match="investment"):
        validate((replace(loan, is_investment=True),))


def test_a_contribution_on_a_debt_fails():
    loan = _kind("assets", "loan")
    with pytest.raises(RegistryError, match="contribution"):
        validate((replace(loan, link_role="contribution"),))


def test_a_repayment_link_without_a_schedule_fails():
    isa = _kind("assets", "isa")
    with pytest.raises(RegistryError, match="repayment"):
        validate((replace(isa, link_role="repayment"),))


def test_a_docs_declaration_must_name_a_feature_doc():
    isa = _kind("assets", "isa")
    with pytest.raises(RegistryError, match="DOCS"):
        validate((replace(isa, surfaces={**isa.surfaces, Surface.DOCS: "see the wiki"}),))


def test_the_same_kind_twice_fails():
    isa = _kind("assets", "isa")
    with pytest.raises(RegistryError, match="twice"):
        validate((isa, isa))


# --- lookups ----------------------------------------------------------------

def test_kind_for_finds_a_stored_type():
    assert kind_for("assets", "pension") is _kind("assets", "pension")
    assert kind_for("liabilities", "bnpl") is _kind("liabilities", "bnpl")


@pytest.mark.parametrize("source", ["assets", "liabilities"])
def test_an_unknown_stored_type_fails_closed(source, caplog):
    kind = kind_for(source, "boat")
    # Held flat, never hidden by a tick box, no link; it keeps its table.
    assert kind.source == source
    assert kind.model == "flat"
    assert not kind.is_investment
    assert kind not in INVESTMENT_KINDS
    assert kind.link_role is None
    assert "unknown holding kind" in caplog.text and "boat" in caplog.text


def test_an_unknown_asset_type_counts_at_its_stored_sign():
    kind = kind_for("assets", "boat")
    assert (kind.group, kind.is_debt) == ("other", False)


def test_an_unknown_liability_kind_counts_as_debt():
    # Liabilities store the amount owed as positive: never add it as an asset.
    kind = kind_for("liabilities", "boat")
    assert (kind.group, kind.is_debt) == ("debt", True)


def test_the_unknown_kinds_declare_every_surface_too():
    validate((registry.UNKNOWN_ASSET, registry.UNKNOWN_LIABILITY))
