# SouqSort

SouqSort is a localisation and pricing engine for a UK-based retailer launching in the GCC (Saudi Arabia,
the UAE and Kuwait). It turns a global catalogue priced in USD/GBP into market-ready shelf prices
(FX, freight, duty, VAT, rounding and charm endings) and delivery promises, and shows the result in a
Streamlit dashboard. v0.1 covers KSA end to end. All market data (FX rates, tax and duty rates, holidays)
is illustrative. See `SPEC.md` for the full specification.

## Running the tests

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```
