# SouqSort — Specification (v0.1)

> The single source of truth for building SouqSort with Claude Code.
> Work one milestone at a time (M0 → M6). Each milestone lists its acceptance tests.

## 1. What SouqSort is

SouqSort is a localisation and pricing engine for a UK-based retailer launching its catalogue in three GCC markets: Saudi Arabia (KSA), the UAE and Kuwait. It turns a global catalogue priced in USD/GBP into market-ready shelf prices and delivery promises, and shows the result in a Streamlit dashboard. Later versions add compliance rules, a `GCC_EXPANSION_REPORT.md` generator and a data pipeline.

**Demo user:** an expansion director who picks a market, adjusts tariffs and sees what happens to prices, margins and delivery dates.

## 2. Scope

### v0.1 (this spec): KSA end to end
- Load and validate the global catalogue and the market config.
- Price every product for KSA: FX → freight → duty → VAT → rounding → charm ending, plus margin.
- Estimate the delivery date for an order placed at a given time.
- Show the result in a Streamlit grid with a duty slider and search, and print the same result from a CLI.

### Later (do NOT build in v0.1)
- **v0.2:** UAE and Kuwait added through config only; compliance rules (banned attributes, missing-Arabic-name flag); de minimis thresholds.
- **v0.3:** a simple `GCC_EXPANSION_REPORT.md` from a template, with a download button.
- **Mid-project upgrades:** calculation traces and a price waterfall; data pipeline (catalogue generator, DuckDB bronze/silver/gold tables, quarantine, run manifest, reconciliation check); decision-led report (tariff pass-through slider, breakeven, sensitivity, market scorecard); CI.
- **Late:** FastAPI adapter, deployment, README polish, ADRs.

## 3. Non-negotiables (also in CLAUDE.md)

1. Money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are strings.
2. Keep full precision through every step; round once, at the shelf price.
3. `app/` contains no business logic. It calls `souqsort` and displays results.
4. Markets are data. No code branches on a market code.
5. Code in `src/` never reads the clock. Callers pass a timezone-aware `ordered_at`.
6. Engine functions return result objects (e.g. `PriceQuote`), not bare numbers.

## 4. Tech stack

- Python 3.12, managed with **uv** (src layout, package name `souqsort`).
- Runtime dependencies: `pydantic` (v2), `pandas`, `streamlit`, `tzdata`.
  - `tzdata` is required on Windows, which has no system timezone database for `zoneinfo`.
- Dev dependencies: `pytest`, `hypothesis`, `ruff`, `mypy`.
- Standard library: `decimal`, `zoneinfo`, `datetime`, `argparse`, `json`, `dataclasses`.

## 5. Project structure (v0.1)

```
souqsort/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── SPEC.md
├── .gitignore
├── .gitattributes            # * text=auto eol=lf
├── data/
│   └── raw/
│       ├── global_products.json
│       └── gcc_config.json
├── src/
│   └── souqsort/
│       ├── __init__.py
│       ├── __main__.py       # enables `python -m souqsort`
│       ├── models.py         # Pydantic models
│       ├── loaders.py        # load + validate JSON
│       ├── pricing/
│       │   ├── __init__.py
│       │   ├── money.py      # rounding, charm endings, formatting
│       │   ├── fx.py         # currency conversion
│       │   └── landed_cost.py  # price_product() -> PriceQuote
│       ├── logistics/
│       │   ├── __init__.py
│       │   └── calendar.py   # business days, delivery estimate
│       ├── pipeline.py       # localise_catalogue()
│       └── cli.py
├── app/
│   └── streamlit_app.py
└── tests/
    ├── conftest.py
    ├── fixtures/             # small JSON configs used only by tests
    ├── test_models_loaders.py
    ├── test_money.py
    ├── test_landed_cost.py
    ├── test_calendar.py
    ├── test_pipeline.py
    └── test_cli.py
```

## 6. Data inputs

### 6.1 `data/raw/global_products.json`

```json
{
  "catalogue_version": "2026-10-01",
  "products": [
    {
      "sku": "ELEC-HP-001",
      "name": { "en": "Wireless Noise-Cancelling Headphones", "ar": "سماعات لاسلكية عازلة للضوضاء" },
      "category": "electronics",
      "hs_code": "851830",
      "base_price": "149.99",
      "currency": "USD",
      "unit_cost": "62.00",
      "weight_kg": "0.35",
      "attributes": { "contains_alcohol": false, "contains_pork": false, "contains_lithium_battery": true }
    }
  ]
}
```

Rules:
- `sku` is unique. `currency` is `USD` or `GBP`.
- `base_price` and `unit_cost` are > 0; `weight_kg` is ≥ 0. All three are strings.
- `base_price` is the global retail price before any tax or duty. `unit_cost` is what the retailer pays, in the same currency.
- `name.ar` may be `null`. Flag it; never crash.
- A money or weight field given as a JSON number (e.g. `149.99` without quotes) must be rejected with a clear error.

The v0.1 catalogue has **12 hand-written products** that together include:
1. the USD headphones above, exactly (worked example A);
2. the GBP bag from §7.3, exactly (worked example B);
3. a heavy item (≥ 10 kg) where freight is a large share of the price;
4. a cheap item (< 10 USD) where the charm ending moves the price noticeably;
5. a zero-weight item (e.g. a digital gift card);
6. at least two items with `name.ar: null`;
7. one item with `contains_alcohol: true` and one with `contains_pork: true` (used by compliance in v0.2);
8. at least four categories, at least one with a duty override and at least one without.

### 6.2 `data/raw/gcc_config.json` (v0.1 contains KSA only)

```json
{
  "config_version": "2026-10-01",
  "fx": {
    "as_of": "2026-10-01",
    "source": "manual snapshot (illustrative)",
    "per_usd": { "USD": "1", "SAR": "3.7500", "AED": "3.6725", "KWD": "0.3070", "GBP": "0.7450" }
  },
  "markets": {
    "KSA": {
      "name": "Saudi Arabia",
      "currency": { "code": "SAR", "minor_units": 2, "charm_ending": "0.95" },
      "tax": { "vat_rate": "0.15", "source": "illustrative - verify before quoting", "effective_from": "2020-07-01" },
      "customs": { "default_duty_rate": "0.05", "category_overrides": { "fashion": "0.12" } },
      "calendar": {
        "timezone": "Asia/Riyadh",
        "weekend": ["FRI", "SAT"],
        "order_cutoff_local": "14:00",
        "holidays": [
          { "date": "2027-02-22", "name": "Founding Day", "provisional": false }
        ]
      },
      "logistics": { "freight_per_kg_usd": "4.50", "linehaul_business_days": 3, "last_mile_business_days": 2 }
    }
  }
}
```

Rules:
- `per_usd[X]` is units of X per 1 USD. Convert A → B as `amount / per_usd[A] * per_usd[B]`.
- `minor_units` is 2 for SAR and AED, 3 for KWD.
- Rates are fractions given as strings (`"0.15"` = 15%).
- `charm_ending` may be `null`, meaning no charm pricing.
- Weekend days use `MON` … `SUN`.
- Validation must reject unknown currency codes, negative rates, an invalid timezone and a malformed cutoff time.

## 7. Pricing rules (v0.1: all costs are passed through to the customer)

### 7.1 Steps
All values are in the market currency and keep full precision until step 7.

1. `goods = convert(base_price, product currency → market currency)`
2. `freight = convert(freight_per_kg_usd × weight_kg, USD → market currency)`
3. `cif = goods + freight`
4. `duty_rate = category_overrides.get(category, default_duty_rate) + duty_adjustment` (see §7.4)
5. `duty = cif × duty_rate`
6. `vat = (cif + duty) × vat_rate`
7. `gross = cif + duty + vat`, then `rounded = gross` rounded to `minor_units` with `ROUND_HALF_UP`
8. `shelf_price = charm(rounded)`: if `rounded` already ends with `charm_ending`, keep it; otherwise move **up** to the next price with that ending. Charm pricing never lowers a price.
9. Margin:
   - `cost_local = convert(unit_cost, product currency → market currency)`
   - `goods_revenue = shelf_price / (1 + vat_rate) − freight − duty`
   - `margin_pct = (goods_revenue − cost_local) / goods_revenue`

**Display rule:** components (goods, freight, duty, VAT) are rounded to minor units for display only. Their displayed sum can differ from `shelf_price` because of rounding and the charm uplift; `shelf_price` is authoritative.

### 7.2 Worked example A: headphones (USD) in KSA

| Step | Value (SAR) |
|---|---|
| goods | 149.99 × 3.75 = 562.4625 |
| freight | 0.35 kg × 4.50 = 1.575 USD → 5.90625 |
| cif | 568.36875 |
| duty (5%) | 28.4184375 |
| vat (15%) | 89.518078125 |
| gross | 686.305265625 |
| rounded | 686.31 |
| **shelf_price** | **686.95** |
| margin_pct | 0.587 (to 3 dp; cost 62.00 USD = 232.50 SAR) |

### 7.3 Worked example B: bag (GBP) in KSA

Product: `FASH-BAG-014`, "Leather Crossbody Bag", category `fashion` (12% override), base price 89.00 GBP, unit cost 31.50 GBP, 0.80 kg, `name.ar: null`.

| Step | Value (SAR) |
|---|---|
| goods | 89.00 / 0.7450 × 3.75 = 447.98657718… |
| freight | 0.80 kg × 4.50 = 3.60 USD → 13.50 |
| cif | 461.48657718… |
| duty (12%) | 55.37838926… |
| vat (15%) | 77.52974497… |
| gross | 594.39471141… |
| rounded | 594.39 |
| **shelf_price** | **594.95** |
| margin_pct | 0.646 (to 3 dp) |

### 7.4 Duty slider
- `duty_adjustment` is a `Decimal` fraction added to every category's duty rate (`"0.03"` = +3 percentage points). Default 0.
- The UI and CLI take whole percentage points (0 to 20) and convert at the boundary (3 → `Decimal("0.03")`).
- The engine takes it as a parameter. The config file is never modified.

### 7.5 Money edge cases (all must be tested)
- `12.3455` with 3 minor units → `12.346`; `12.34` with 3 minor units formats as `"12.340"`.
- `0.0005` with 3 minor units → `0.001` (`ROUND_HALF_UP`; banker's rounding would give `0.000`).
- `10.005` with 2 minor units → `10.01`.
- Charm with ending `0.95`: `686.31 → 686.95`; `686.95 → 686.95`; `686.96 → 687.95`; `9.00 → 9.95`.
- Charm with 3 minor units and ending `0.950`: `4.200 → 4.950`.
- A float anywhere in money input → validation error.
- 0% VAT (test fixture market): `vat` is exactly 0, and nothing ever formats as `-0.000`.

## 8. Delivery rules (v0.1: destination calendar only)

- Input: `ordered_at` (timezone-aware `datetime`) and the market config. A naive datetime raises an error.
- Convert `ordered_at` to the market timezone.
- A business day is not a weekend day and not a listed holiday (provisional holidays count as holidays).
- **Dispatch day** = the local order date if it is a business day and the local time is before the cutoff; otherwise the next business day. An order at exactly the cutoff time misses it.
- **Delivery date** = the Nth business day after the dispatch day, where N = `linehaul_business_days + last_mile_business_days` (5 for KSA).
- Keep `add_business_days(start, n, weekend, holidays)` generic. A later two-leg version (UK origin calendar, then destination calendar) should only need to chain two calls.

### 8.1 Worked examples (KSA: Fri–Sat weekend, Asia/Riyadh = UTC+3, cutoff 14:00, N = 5)

| Order (UTC) | Local (Riyadh) | Dispatch | Delivery |
|---|---|---|---|
| 2026-10-11 07:00 | Sun 10:00 | Sun 2026-10-11 | Sun 2026-10-18 |
| 2026-10-11 11:00 | Sun 14:00 (exactly at cutoff) | Mon 2026-10-12 | Mon 2026-10-19 |
| 2026-10-15 10:30 | Thu 13:30 | Thu 2026-10-15 | Thu 2026-10-22 |
| 2026-10-15 20:59 | Thu 23:59 | Sun 2026-10-18 | Sun 2026-10-25 |
| 2026-10-15 22:30 | Fri 01:30 (weekend in Riyadh) | Sun 2026-10-18 | Sun 2026-10-25 |
| 2026-10-15 20:59, with a test-only holiday on Mon 2026-10-19 | Thu 23:59 | Sun 2026-10-18 | Mon 2026-10-26 |

## 9. Interfaces (suggested)

Adjust these if there is a good reason, and say why.

```python
# models.py (Pydantic v2)
class ProductName(BaseModel): en: str; ar: str | None
class Product(BaseModel): sku, name: ProductName, category, hs_code, base_price: Decimal,
                          currency, unit_cost: Decimal, weight_kg: Decimal, attributes: dict[str, bool]
class MarketConfig(BaseModel): code, name, currency, tax, customs, calendar, logistics
class GccConfig(BaseModel): config_version, fx, markets: dict[str, MarketConfig]

# pricing/landed_cost.py
@dataclass(frozen=True)
class PriceStep:          # filled in a later milestone; keep the type from day one
    name: str
    basis: Decimal
    rate: Decimal | None
    amount: Decimal
    source: str           # e.g. "KSA.customs.category_overrides.fashion"

@dataclass(frozen=True)
class PriceQuote:
    sku: str
    market: str
    currency: str
    goods: Decimal
    freight: Decimal
    duty: Decimal
    vat: Decimal
    gross: Decimal
    shelf_price: Decimal
    margin_pct: Decimal
    steps: tuple[PriceStep, ...] = ()

def price_product(product: Product, market: MarketConfig, fx: FxTable,
                  duty_adjustment: Decimal = Decimal("0")) -> PriceQuote: ...

# logistics/calendar.py
def is_business_day(d: date, weekend: frozenset[int], holidays: frozenset[date]) -> bool: ...
def add_business_days(start: date, n: int, weekend: frozenset[int], holidays: frozenset[date]) -> date: ...

@dataclass(frozen=True)
class DeliveryEstimate:
    ordered_at_local: datetime
    dispatch_date: date
    delivery_date: date

def estimate_delivery(ordered_at: datetime, market: MarketConfig) -> DeliveryEstimate: ...

# pipeline.py
@dataclass(frozen=True)
class LocalisedProduct:
    sku: str
    name_en: str
    name_ar: str | None
    category: str
    quote: PriceQuote
    delivery: DeliveryEstimate
    flags: tuple[str, ...]   # v0.1: "missing_arabic_name"

def localise_catalogue(products: list[Product], config: GccConfig, market_code: str,
                       ordered_at: datetime,
                       duty_adjustment: Decimal = Decimal("0")) -> list[LocalisedProduct]: ...
```

## 10. Milestones (v0.1)

For every milestone: tests first, then code. Done means `uv run pytest`, `uv run ruff check .` and `uv run mypy src` all pass, then commit.

### M0: Skeleton
- uv project (src layout, Python 3.12) with the dependencies in §4.
- Folder structure from §5 with empty modules (a docstring only).
- `.gitignore` (Python, `.venv/`, `outputs/`, `.claude/settings.local.json`) and `.gitattributes` (`* text=auto eol=lf`).
- README stub: one paragraph plus how to run the tests.
- Ruff and mypy configured in `pyproject.toml` (mypy strict for `src/`, with the `pydantic.mypy` plugin).
- One smoke test that imports `souqsort`.
- **Accept:** all three commands pass.

### M1: Models, loaders, data
- Pydantic models for §6, loaders that reject floats in money fields with a clear message, and the data files (12 products, KSA config).
- **Tests:** valid files load; float money rejected; unknown currency rejected; duplicate SKU rejected; invalid timezone rejected; `name.ar: null` accepted.

### M2: Money
- Minor-unit rounding (`ROUND_HALF_UP`), charm-up and formatting with an exact number of decimals.
- **Tests:** every case in §7.5, plus Hypothesis properties:
  - a rounded value has exactly `minor_units` decimals;
  - `charm(x) >= x`;
  - `charm(charm(x)) == charm(x)`.

### M3: FX and landed cost
- `convert()` and `price_product()` following §7, including `duty_adjustment`.
- **Tests:**
  - worked examples A and B exactly (`shelf_price`) and margin to 3 dp;
  - category override vs default duty;
  - zero weight gives zero freight;
  - 0% VAT fixture;
  - Hypothesis: a higher `duty_adjustment` never gives a lower `shelf_price`.

### M4: Delivery calendar
- The rules in §8.
- **Tests:**
  - every row of §8.1;
  - a naive datetime raises;
  - Hypothesis: the delivery date is never a weekend day or holiday, and a later order never gets an earlier delivery date.

### M5: Pipeline and CLI
- `localise_catalogue()`.
- CLI: `uv run python -m souqsort price --market KSA [--duty-adjust 3] [--ordered-at 2026-10-15T20:59Z] [--csv out.csv]`. It prints a table: SKU, English name, shelf price (formatted), margin %, delivery date, flags.
- `--ordered-at` defaults to now. The CLI reads the clock, not the engine.
- **Tests:** integration test over the sample data; CLI exits 0 and prints the expected columns.

### M6: Streamlit dashboard
- `app/streamlit_app.py`:
  - **Sidebar:** market selector filled from the config (KSA only for now), duty slider (0–20 percentage points), order date and time pickers (default now, in market local time), search box (SKU or English name).
  - **Main area:** the data grid and two headline metrics: average margin, and the number of flagged products.
  - Prices display with exactly the currency's minor units.
- No business logic in the app.
- **Accept:** `uv run streamlit run app/streamlit_app.py` starts, and a manual check confirms:
  - moving the slider changes prices;
  - search filters rows;
  - a Thursday-evening order time gives Sunday-based delivery dates.
- Then tag `v0.1.0`.

## 11. Decisions log (turn into ADRs later)
- Decimal everywhere; strings in JSON.
- Round once, at the shelf price, with `ROUND_HALF_UP`.
- Charm pricing only rounds up.
- v0.1 passes all costs through to the customer (pass-through slider later).
- v0.1 uses the destination calendar only (two-leg later).
- No de minimis in v0.1 (added in v0.2).
- All market data is illustrative and labelled as such.
