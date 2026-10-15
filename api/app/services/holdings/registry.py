"""The holding kind registry (ADR-002 section 2).

One entry per stored type: every `assets.asset_type` and every
`liabilities.kind`. Each entry says how the kind is projected, whether it is
debt or an investment, which commitment link it can carry, and how it reaches
every surface. `tests/unit/test_holding_registry.py` runs `validate`, so a
kind that leaves a surface undeclared fails CI.

Fail closed: a stored type with no entry maps to `UNKNOWN_ASSET` (counted
at its stored value and sign) or `UNKNOWN_LIABILITY` (counted as debt), held
flat and never hidden by a tick box.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

log = logging.getLogger(__name__)

Source = Literal["assets", "liabilities", "card_plans"]
Group = Literal["investments", "savings", "property", "other", "debt"]
Model = Literal["growth", "amortisation", "flat"]
LinkRole = Literal["contribution", "repayment"]


class Surface(Enum):
    NET_WORTH = "net worth"
    PROJECTION = "projection"
    COMMITMENTS = "commitments"
    CASHFLOW = "cashflow"
    CLAUDE = "claude"
    DEMO = "demo"
    PURGE = "purge"
    DOCS = "docs"


class RegistryError(ValueError):
    """The registry breaks a rule; the message names the kind and the rule."""


# eq=False: kinds are singletons compared by identity, and hashable even
# though `surfaces` is a mapping.
@dataclass(frozen=True, eq=False)
class HoldingKind:
    source: Source
    stored_type: str
    group: Group
    model: Model
    is_debt: bool
    is_investment: bool
    link_role: LinkRole | None
    surfaces: Mapping[Surface, str]

    @property
    def key(self) -> str:
        return f"{self.source}:{self.stored_type}"


# Shared declarations: each kind below still names every surface, through one
# of these, so the CI check sees them all.
_GROWTH_ASSET = {
    Surface.NET_WORTH: "balance sheet and history at its latest valuation",
    Surface.PROJECTION: "compounds at its own growth % (holdings engine)",
    Surface.CASHFLOW: "no: a holding's value is not cash",
    Surface.CLAUDE: "list_holdings and net_worth in cashflow_summary",
    Surface.DEMO: "sample assets in ui/src/lib/sampleAccount.ts",
    Surface.PURGE: "assets, asset_valuations, asset_flows in _OWNED_BY_USER",
    Surface.DOCS: "docs/features/net-worth.md",
}
_INVESTMENT = {
    **_GROWTH_ASSET,
    Surface.NET_WORTH: "Investments group; the Include investments choice",
    Surface.COMMITMENTS: "its contribution is a linked commitment (commitment_links)",
    Surface.CASHFLOW: "its linked contribution leaves cash on its day",
    Surface.CLAUDE: "list_holdings, investments_total and net_worth in cashflow_summary",
}
_NO_LINK = {Surface.COMMITMENTS: "no: no contribution link for this kind yet"}
_LEGACY_DEBT = {
    **_GROWTH_ASSET,
    **_NO_LINK,
    Surface.NET_WORTH: "Loans and finance group at its (negative) latest valuation",
    Surface.PROJECTION: "held flat unless the user set a growth %; stops at zero",
    Surface.CLAUDE: "no: aggregate only (net_worth in cashflow_summary); never in list_holdings",
}
_LIABILITY = {
    Surface.NET_WORTH: "Loans and finance group via net_worth.liabilities_total",
    Surface.PROJECTION: "follows its amortisation schedule when linked, else flat",
    Surface.COMMITMENTS: "its repayment is a linked commitment (linked_commitment_id)",
    Surface.CASHFLOW: "its linked repayment leaves cash on its day",
    Surface.CLAUDE: "no: aggregate only (liabilities_total in cashflow_summary); no lender names",
    Surface.DEMO: "sample liabilities in ui/src/lib/sampleAccount.ts",
    Surface.PURGE: "liabilities in _OWNED_BY_USER",
    Surface.DOCS: "docs/features/liabilities.md",
}


def _asset(stored_type: str, group: Group, surfaces: Mapping[Surface, str], **flags) -> HoldingKind:
    return HoldingKind(
        source="assets", stored_type=stored_type, group=group, model="growth",
        is_debt=flags.get("is_debt", False), is_investment=flags.get("is_investment", False),
        link_role=flags.get("link_role"), surfaces=surfaces,
    )


def _liability(stored_type: str) -> HoldingKind:
    return HoldingKind(
        source="liabilities", stored_type=stored_type, group="debt", model="amortisation",
        is_debt=True, is_investment=False, link_role="repayment", surfaces=_LIABILITY,
    )


KINDS: tuple[HoldingKind, ...] = (
    _asset("isa", "investments", _INVESTMENT, is_investment=True, link_role="contribution"),
    _asset("investment", "investments", _INVESTMENT, is_investment=True, link_role="contribution"),
    _asset("pension", "investments", _INVESTMENT, is_investment=True, link_role="contribution"),
    _asset("crypto", "investments", _INVESTMENT, is_investment=True, link_role="contribution"),
    _asset("savings", "savings", {**_GROWTH_ASSET, **_NO_LINK}),
    _asset("property", "property", {**_GROWTH_ASSET, **_NO_LINK}),
    _asset("other", "other", {**_GROWTH_ASSET, **_NO_LINK}),
    _asset("mortgage", "debt", _LEGACY_DEBT, is_debt=True),
    _asset("loan", "debt", _LEGACY_DEBT, is_debt=True),
    _asset("other_liability", "debt", _LEGACY_DEBT, is_debt=True),
    _liability("loan"),
    _liability("finance"),
    _liability("bnpl"),
    _liability("mortgage"),
    # A card instalment plan (T-12-5, owner D3/D4).
    HoldingKind(
        source="card_plans", stored_type="card_plan", group="debt", model="amortisation",
        is_debt=True, is_investment=False, link_role=None, surfaces={
            Surface.NET_WORTH: "only once its card has gone (standalone debt); inside its card never on its own (owner D4)",
            Surface.PROJECTION: "standalone: falls by its instalments; inside its card: not projected on its own",
            Surface.COMMITMENTS: "no: its instalment and fee go into the card's amount due (D3)",
            Surface.CASHFLOW: "instalment + fee on the card's due dates until a statement covers them (T-12-5b)",
            Surface.CLAUDE: "no: not listed; a standalone plan counts in liabilities_total in cashflow_summary",
            Surface.DEMO: "no: no screen shows plans until T-12-7b, which adds a sample plan",
            Surface.PURGE: "card_plans in _OWNED_BY_USER",
            Surface.DOCS: "docs/features/liabilities.md",
        },
    ),
)

INVESTMENT_KINDS: frozenset[HoldingKind] = frozenset(k for k in KINDS if k.is_investment)

_UNKNOWN = {
    Surface.PROJECTION: "held flat at its stored value",
    Surface.COMMITMENTS: "no: an unknown kind carries no link",
    Surface.CASHFLOW: "no: a holding's value is not cash",
    Surface.DEMO: "no: sample data has no unknown kinds",
    Surface.PURGE: "purged with its source table",
    Surface.DOCS: "docs/features/net-worth.md",
}
# Fail closed, keeping the table's meaning: an unknown asset counts at its
# stored value and sign; an unknown liability (stored as a positive amount
# owed) counts as debt, never as an asset.
UNKNOWN_ASSET = HoldingKind(
    source="assets", stored_type="unknown", group="other", model="flat",
    is_debt=False, is_investment=False, link_role=None,
    surfaces={**_UNKNOWN, Surface.NET_WORTH: "counted at its stored value and sign, never hidden",
              Surface.CLAUDE: "list_holdings as kind unknown, unless worth less than nothing"},
)
UNKNOWN_LIABILITY = HoldingKind(
    source="liabilities", stored_type="unknown", group="debt", model="flat",
    is_debt=True, is_investment=False, link_role=None,
    surfaces={**_UNKNOWN, Surface.NET_WORTH: "counted as debt at its entered balance, never hidden",
              Surface.CLAUDE: "no: aggregate only (liabilities_total); never in list_holdings"},
)

_BY_KEY = {(k.source, k.stored_type): k for k in KINDS}
_DOCS = re.compile(r"^docs/features/[a-z0-9-]+\.md$")


def kind_for(source: Source, stored_type: str) -> HoldingKind:
    """The registry entry for a stored type; an unknown kind of the same
    table (fail closed) if none."""
    kind = _BY_KEY.get((source, stored_type))
    if kind is None:
        # The plaintext stored type only: never a name or an id.
        log.warning("unknown holding kind %s:%s counted flat at its stored value", source, stored_type)
        return UNKNOWN_LIABILITY if source == "liabilities" else UNKNOWN_ASSET
    return kind


def validate(kinds: Iterable[HoldingKind]) -> None:
    """Raise RegistryError on the first kind that breaks a rule."""
    seen: set[tuple[str, str]] = set()
    for kind in kinds:
        if (kind.source, kind.stored_type) in seen:
            raise RegistryError(f"{kind.key} is declared twice")
        seen.add((kind.source, kind.stored_type))
        for surface in Surface:
            if not kind.surfaces.get(surface, "").strip():
                raise RegistryError(f"{kind.key} does not declare surface {surface.name}")
        if not _DOCS.match(kind.surfaces[Surface.DOCS]):
            raise RegistryError(f"{kind.key}: DOCS must name a docs/features/*.md file")
        if kind.is_debt and kind.is_investment:
            raise RegistryError(f"{kind.key}: a debt can never be an investment")
        if kind.link_role == "contribution" and (kind.is_debt or kind.model != "growth"):
            raise RegistryError(f"{kind.key}: a contribution link needs a growth asset")
        if kind.link_role == "repayment" and not (kind.is_debt and kind.model == "amortisation"):
            raise RegistryError(f"{kind.key}: a repayment link needs an amortising debt")
