"""Market-data provider adapters, behind one search()/quote() interface.

- **CoinGecko** (crypto): keyless, and quotes directly in GBP, so it works out
  of the box for anyone who clones the repo — no FX, no key.
- **Alpha Vantage** (equities/ETFs): opt-in via ALPHAVANTAGE_API_KEY; absent →
  the provider simply returns nothing (crypto still works). USD is converted
  via the provider's FX; GBX (LSE pence) is /100.

Every network path fails soft (returns [] / None), never raises — pricing is a
best-effort enrichment, never allowed to break the Wealth page. Swap a paid
provider in here without touching the service or the schema.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 6.0
_HEADERS = {"User-Agent": "nilu-finance/1.0 (+https://finance.nilu.app)"}
_COINGECKO = "https://api.coingecko.com/api/v3"
_ALPHA = "https://www.alphavantage.co/query"


@dataclass
class InstrumentHit:
    symbol: str
    name: str
    kind: str          # crypto | equity | etf
    provider: str      # coingecko | alphavantage
    provider_ref: str
    currency: str      # native quote currency (GBP for coingecko here)


@dataclass
class Quote:
    price_native: Decimal
    price_gbp: Decimal
    as_of: datetime


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _alpha_key() -> str:
    return os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()


# --- CoinGecko (crypto) ----------------------------------------------------- #

def _coingecko_search(query: str) -> list[InstrumentHit]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(f"{_COINGECKO}/search", params={"query": query})
            r.raise_for_status()
            coins = r.json().get("coins", [])[:8]
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.info("coingecko search failed: %s", e)
        return []
    return [
        InstrumentHit(
            symbol=(c.get("symbol") or "").upper(), name=c.get("name") or "",
            kind="crypto", provider="coingecko", provider_ref=c.get("id") or "",
            currency="GBP",
        )
        for c in coins if c.get("id")
    ]


def _coingecko_quote(provider_ref: str) -> Quote | None:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(
                f"{_COINGECKO}/simple/price",
                params={"ids": provider_ref, "vs_currencies": "gbp", "include_last_updated_at": "true"},
            )
            r.raise_for_status()
            d = r.json().get(provider_ref)
    except Exception as e:  # noqa: BLE001
        logger.info("coingecko quote failed: %s", e)
        return None
    price = _dec(d.get("gbp")) if d else None
    if price is None:
        return None
    ts = d.get("last_updated_at")
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return Quote(price_native=price, price_gbp=price, as_of=as_of)


# --- Alpha Vantage (equities / ETFs) ---------------------------------------- #

def _alpha_search(query: str) -> list[InstrumentHit]:
    key = _alpha_key()
    if not key:
        return []
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(_ALPHA, params={"function": "SYMBOL_SEARCH", "keywords": query, "apikey": key})
            r.raise_for_status()
            matches = r.json().get("bestMatches", [])[:8]
    except Exception as e:  # noqa: BLE001
        logger.info("alphavantage search failed: %s", e)
        return []
    hits = []
    for m in matches:
        sym = m.get("1. symbol")
        if not sym:
            continue
        typ = (m.get("3. type") or "").lower()
        hits.append(InstrumentHit(
            symbol=sym, name=m.get("2. name") or sym,
            kind="etf" if "etf" in typ else "equity",
            provider="alphavantage", provider_ref=sym,
            currency=(m.get("8. currency") or "USD").upper(),
        ))
    return hits


def _fx_to_gbp(currency: str) -> Decimal | None:
    cur = currency.upper()
    if cur == "GBP":
        return Decimal(1)
    if cur in ("GBX", "GBP.", "PENCE"):  # LSE pence → pounds
        return Decimal("0.01")
    key = _alpha_key()
    if not key:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(_ALPHA, params={
                "function": "CURRENCY_EXCHANGE_RATE", "from_currency": cur,
                "to_currency": "GBP", "apikey": key,
            })
            r.raise_for_status()
            rate = r.json().get("Realtime Currency Exchange Rate", {}).get("5. Exchange Rate")
    except Exception as e:  # noqa: BLE001
        logger.info("alphavantage fx failed: %s", e)
        return None
    return _dec(rate)


def _alpha_quote(provider_ref: str, currency: str) -> Quote | None:
    key = _alpha_key()
    if not key:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(_ALPHA, params={"function": "GLOBAL_QUOTE", "symbol": provider_ref, "apikey": key})
            r.raise_for_status()
            raw = r.json().get("Global Quote", {}).get("05. price")
    except Exception as e:  # noqa: BLE001
        logger.info("alphavantage quote failed: %s", e)
        return None
    native = _dec(raw)
    fx = _fx_to_gbp(currency)
    if native is None or fx is None:
        return None
    return Quote(price_native=native, price_gbp=native * fx, as_of=datetime.now(timezone.utc))


# --- dispatch --------------------------------------------------------------- #

def search(query: str) -> list[InstrumentHit]:
    """Crypto first (it always works), then equities if a key is configured."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    return _coingecko_search(query) + _alpha_search(query)


def quote(provider: str, provider_ref: str, currency: str) -> Quote | None:
    if provider == "coingecko":
        return _coingecko_quote(provider_ref)
    if provider == "alphavantage":
        return _alpha_quote(provider_ref, currency)
    return None
