"""Market-data provider adapters, behind one search()/quote() interface.

- **CoinGecko** (crypto): keyless, and quotes directly in GBP, so it works out
  of the box for anyone who clones the repo — no FX, no key.
- **Twelve Data** (equities/ETFs): opt-in via TWELVEDATA_API_KEY; absent → the
  provider simply returns nothing (crypto still works). The free tier is 800
  requests/day (8/min), which with the 1h price cache is ample. Non-GBP is
  converted via the provider's FX; GBX/GBp (LSE pence) is /100.

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
_TWELVE = "https://api.twelvedata.com"


@dataclass
class InstrumentHit:
    symbol: str
    name: str
    kind: str          # crypto | equity | etf
    provider: str      # coingecko | twelvedata
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


def _twelve_key() -> str:
    return os.environ.get("TWELVEDATA_API_KEY", "").strip()


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


# --- Twelve Data (equities / ETFs) ------------------------------------------ #
# provider_ref encodes the exchange to disambiguate cross-listed tickers:
# "SYMBOL" or "SYMBOL:EXCHANGE" (e.g. "VUSA:LSE").

def _twelve_search(query: str) -> list[InstrumentHit]:
    key = _twelve_key()
    if not key:
        return []
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(f"{_TWELVE}/symbol_search", params={"symbol": query, "outputsize": 8, "apikey": key})
            r.raise_for_status()
            data = r.json().get("data", [])[:8]
    except Exception as e:  # noqa: BLE001
        logger.info("twelvedata search failed: %s", e)
        return []
    hits = []
    for m in data:
        sym = m.get("symbol")
        if not sym:
            continue
        exch = m.get("exchange") or ""
        typ = (m.get("instrument_type") or "").lower()
        hits.append(InstrumentHit(
            symbol=sym, name=m.get("instrument_name") or sym,
            kind="etf" if "etf" in typ or "fund" in typ else "equity",
            provider="twelvedata", provider_ref=f"{sym}:{exch}" if exch else sym,
            currency=(m.get("currency") or "USD").upper(),
        ))
    return hits


def _fx_to_gbp(currency: str) -> Decimal | None:
    cur = (currency or "").upper()
    if cur == "GBP":
        return Decimal(1)
    if cur in ("GBX", "GBP.", "PENCE"):  # LSE pence → pounds
        return Decimal("0.01")
    key = _twelve_key()
    if not key:
        return None
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(f"{_TWELVE}/exchange_rate", params={"symbol": f"{cur}/GBP", "apikey": key})
            r.raise_for_status()
            rate = r.json().get("rate")
    except Exception as e:  # noqa: BLE001
        logger.info("twelvedata fx failed: %s", e)
        return None
    return _dec(rate)


def _twelve_quote(provider_ref: str, currency: str) -> Quote | None:
    key = _twelve_key()
    if not key:
        return None
    symbol, _, exchange = provider_ref.partition(":")
    params = {"symbol": symbol, "apikey": key}
    if exchange:
        params["exchange"] = exchange
    try:
        with httpx.Client(timeout=TIMEOUT, headers=_HEADERS) as c:
            r = c.get(f"{_TWELVE}/quote", params=params)
            r.raise_for_status()
            body = r.json()
    except Exception as e:  # noqa: BLE001
        logger.info("twelvedata quote failed: %s", e)
        return None
    if not isinstance(body, dict) or body.get("status") == "error":
        return None
    native = _dec(body.get("close"))
    # Prefer the currency the quote reports (LSE returns GBp/GBX in pence).
    fx = _fx_to_gbp(body.get("currency") or currency)
    if native is None or fx is None:
        return None
    return Quote(price_native=native, price_gbp=native * fx, as_of=datetime.now(timezone.utc))


# --- dispatch --------------------------------------------------------------- #

def search(query: str) -> list[InstrumentHit]:
    """Crypto first (it always works), then equities if a key is configured."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    return _coingecko_search(query) + _twelve_search(query)


def quote(provider: str, provider_ref: str, currency: str) -> Quote | None:
    if provider == "coingecko":
        return _coingecko_quote(provider_ref)
    if provider == "twelvedata":
        return _twelve_quote(provider_ref, currency)
    return None
