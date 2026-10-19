# SouqSort — Specification (v0.3)

> The single source of truth for building SouqSort with Claude Code.
> Work one milestone at a time (M0 → M14). Each milestone lists its acceptance tests.
> v0.1 (M0–M6) is done and tagged `v0.1.0`. v0.2 (**M7 → Fix #2 → M8 → M9 → M10 → Release**) is done and tagged `v0.2.0`. v0.3 runs **M11 → M12 → M13 → M14 → Release**. Each step has its own branch and reaches `main` through a pull request with green CI.

## 1. What SouqSort is

SouqSort is a localisation and pricing engine for a UK-based retailer launching its catalogue in three GCC markets: Saudi Arabia (KSA), the UAE and Kuwait. It turns a global catalogue priced in USD/GBP into market-ready shelf prices and delivery promises, and shows the result in a Streamlit dashboard. v0.2 added the UAE and Kuwait, compliance rules and de minimis. v0.3 adds `GCC_EXPANSION_REPORT.md`, which puts every market and both shipping models side by side for one order. Later versions add a data pipeline.

**Demo user:** an expansion director who picks a market and a shipping model, adjusts tariffs and sees what happens to prices, margins and delivery dates, then downloads a report that compares the markets.

## 2. Scope

### v0.1: KSA end to end (done, tag `v0.1.0`)
- Load and validate the global catalogue and the market config.
- Price every product for KSA: FX → freight → duty → VAT → rounding → charm ending, plus margin.
- Estimate the delivery date for an order placed at a given time.
- Show the result in a Streamlit grid with a duty slider and search, and print the same result from a CLI.

### v0.2: three markets, compliance, de minimis (done, tag `v0.2.0`)
- **CI:** every push to `main` and every pull request runs the format check, lint, type check and tests on Ubuntu and Windows. Two non-negotiables also get tests that enforce them.
- **UAE and Kuwait,** added to the config with no change to `src/` or `app/`, plus a 13th product above the de minimis thresholds.
- **Compliance:** each market lists the product attributes it does not allow. Those products are reported as not sold, never priced and never silently dropped.
- **De minimis and a shipping model switch:** *consolidated import* (the default) keeps the v0.1 prices; *direct parcel* uses parcel freight and waives duty under each market's threshold.
- **GitHub issues:** #1 lowercase categories (M9), #2 CSV formula injection (Fix #2), #3 order-time pickers on a market switch (M8).
- **Claude Code, one new feature per milestone:** GitHub Actions and a `/verify` skill (M7), an `/add-market` skill with arguments (M8), a format-on-edit hook (M9), a `money-reviewer` subagent (M10), `gh release` (Release).

### v0.3: the expansion report
- **`GCC_EXPANSION_REPORT.md`** (§9): one order, every market in the config, both shipping models, today's duty rates plus three tariff rises. Six sections, each opening with sentences computed from its figures, and a summary of those sentences at the top: markets side by side, consolidated or parcel, tariff exposure, how a price is built, pricing risks, and what is not sold.
- **Two ways to get it:** a `report` CLI command and a download button in the dashboard.
- **Reproducible:** the same catalogue, config and order time give the same bytes on every OS. A sample for a fixed order lives in `docs/`, and a test keeps it current.
- **Claude Code:** a `/release` skill that turns the release steps into one command, used to ship v0.3.0.

### Later (do NOT build in v0.3)
- **Pricing refinements:** per-parcel fees and minimum charges (for example ZATCA's SAR 15 declaration fee on e-store shipments up to SAR 1,000); different transit times for parcels; orders of several items (a threshold applies to a whole order, while v0.2 prices each product as a one-item order); VAT relief for low-value imports; tobacco and nicotine attributes; insurance in CIF; a price ladder for KWD (§7.9.4).
- **Mid-project upgrades:** calculation traces (`PriceStep`) and a price waterfall in the dashboard; data pipeline (catalogue generator, DuckDB bronze/silver/gold tables, quarantine, run manifest, reconciliation check); a tariff pass-through slider and breakeven analysis. (v0.3's report covers tariff sensitivity and a market scorecard.)
- **An AI-written summary** for the report, as its own milestone: written only from the report's figures, with a check that rejects any number that is not among them.
- **Late:** FastAPI adapter, deployment and a live demo, README polish, ADRs.

## 3. Non-negotiables (also in CLAUDE.md)

1. Money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are strings.
2. Keep full precision through every step; round once, at the shelf price.
3. `app/` contains no business logic. It calls `souqsort` and displays results.
4. Markets are data, including their compliance, customs and de minimis rules. No code branches on a market code.
5. No code in `src/` reads the clock except the CLI entry point in `cli.py`, which defaults `--ordered-at` to now through an injectable `now` callable. Everything else is passed a timezone-aware `ordered_at`.
6. Engine functions return result objects (e.g. `PriceQuote`), not bare numbers.
7. A product that a market does not allow is never priced for that market and never silently dropped. It is reported as not sold, with the reason.
8. The expansion report is a pure function of the catalogue, the config and the order time: the same inputs give the same bytes on every OS. Its template only places text; every number is formatted in Python, from `Decimal`.

## 4. Tech stack

- Python 3.12, managed with **uv** (src layout, package name `souqsort`).
- Runtime dependencies: `pydantic` (v2), `pandas`, `streamlit`, `tzdata`, and from M11 `jinja2` (the report's template).
  - `tzdata` is required on Windows, which has no system timezone database for `zoneinfo`.
- Dev dependencies: `pytest`, `hypothesis`, `ruff`, `mypy`.
- Standard library: `decimal`, `zoneinfo`, `datetime`, `argparse`, `json`, `dataclasses`.
- CI (from M7): GitHub Actions on Ubuntu and Windows (`.github/workflows/ci.yml`). v0.2 added no dependencies. v0.3 makes `jinja2` a direct one; Streamlit already installs it, so `uv.lock` gains no package.

## 5. Project structure (v0.3)

```
souqsort/
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
├── CLAUDE.md
├── SPEC.md
├── .gitignore
├── .gitattributes            # * text=auto eol=lf
├── .github/
│   ├── workflows/ci.yml      # M7
│   └── dependabot.yml        # M7
├── .claude/
│   ├── settings.json         # M9: the format hook (settings.local.json stays ignored)
│   ├── hooks/
│   │   └── format_python.py  # M9
│   ├── skills/
│   │   ├── verify/SKILL.md   # M7
│   │   ├── add-market/SKILL.md  # M8
│   │   └── release/SKILL.md  # M14
│   └── agents/
│       └── money-reviewer.md # M10; widened to the report in M11
├── docs/
│   ├── dashboard.png         # the README screenshot
│   └── GCC_EXPANSION_REPORT.md  # M13: the sample report (§9.5)
├── outputs/                  # gitignored; where the report command writes by default
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
│       ├── compliance.py     # M9: screen_products()
│       ├── pricing/
│       │   ├── __init__.py
│       │   ├── money.py      # rounding, charm endings, formatting
│       │   ├── fx.py         # currency conversion
│       │   ├── customs.py    # M10: de minimis, assess_duty()
│       │   └── landed_cost.py  # price_product() -> PriceQuote
│       ├── logistics/
│       │   ├── __init__.py
│       │   └── calendar.py   # business days, delivery estimate
│       ├── pipeline.py       # localise_catalogue(), localise_and_summarise()
│       ├── display.py        # display rows shared by the CLI and the dashboard
│       ├── report/           # M11–M13: the expansion report (§9)
│       │   ├── __init__.py   # build_report(), render_report()
│       │   ├── figures.py    # ExpansionReport and its parts, all Decimal
│       │   ├── text.py       # formatting, sentences, render_report()
│       │   └── templates/
│       │       └── expansion_report.md.j2
│       └── cli.py            # the price and report commands
├── app/
│   └── streamlit_app.py
└── tests/
    ├── conftest.py           # shared fixtures
    ├── helpers.py
    ├── fixtures/             # small JSON configs used only by tests
    │   ├── zero_vat_config.json
    │   └── de_minimis_boundary_config.json  # M10
    ├── test_models_loaders.py
    ├── test_money.py
    ├── test_landed_cost.py
    ├── test_calendar.py
    ├── test_pipeline.py
    ├── test_display.py
    ├── test_cli.py
    ├── test_app.py           # the dashboard, run headlessly with Streamlit's AppTest
    ├── test_architecture.py  # M7: no floats in src/; no market codes in src/ or app/; M11: templates
    ├── test_markets.py       # M8: per-market worked examples, price lists, delivery rows
    ├── test_compliance.py    # M9
    ├── test_format_hook.py   # M9
    ├── test_customs.py       # M10
    ├── test_report_figures.py  # M11–M13
    ├── test_report_text.py   # M11–M13: formatting, sentences, the template context
    └── test_report_sample.py # M13: docs/GCC_EXPANSION_REPORT.md stays current
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
- From M9, `attributes` is a fixed schema: exactly `contains_alcohol`, `contains_pork` and `contains_lithium_battery`, each a JSON boolean. A missing or unknown key is rejected.
- From M9 (issue #1), `category` must match `^[a-z][a-z0-9_]*$`. The keys of `customs.category_overrides` must match the same pattern, so an override can never miss its category because of a capital letter.

The catalogue has **13 hand-written products** (12 in v0.1; the 13th arrives in M8) that together include:
1. the USD headphones above, exactly (worked example A);
2. the GBP bag from §7.3, exactly (worked example B);
3. a heavy item (≥ 10 kg) where freight is a large share of the price;
4. a cheap item (< 10 USD) where the charm ending moves the price noticeably;
5. a zero-weight item: `DIGI-LIC-050`, "Photo Editor Pro Licence (digital download)", USD, `weight_kg: "0"`, category `digital` (0% duty override);
6. at least two items with `name.ar: null`;
7. one item with `contains_alcohol: true` and one with `contains_pork: true` (used by compliance in v0.2);
8. at least four categories, at least one with a duty override and at least one without;
9. `HOME-ESP-031`, placed after `HOME-KTL-030`, exactly as below. It is the only product whose CIF is above 1,000 in SAR and AED, so parcel mode shows both sides of de minimis. It is heavy, so it also shows what parcel freight costs.

```json
{
  "sku": "HOME-ESP-031",
  "name": { "en": "Bean-to-Cup Espresso Machine", "ar": "ماكينة إسبريسو أوتوماتيكية بمطحنة مدمجة" },
  "category": "home",
  "hs_code": "851671",
  "base_price": "649.00",
  "currency": "GBP",
  "unit_cost": "389.00",
  "weight_kg": "9.80",
  "attributes": { "contains_alcohol": false, "contains_pork": false, "contains_lithium_battery": false }
}
```

M8 also fixes `HOME-KTL-030`'s `hs_code` from `851671` to `851679`: heading 8516.71 is coffee and tea makers, and electric kettles are 8516.79. HS codes are not used in any calculation.

### 6.2 `data/raw/gcc_config.json` (v0.2: KSA, UAE, Kuwait)

The top of the file is as in v0.1:

```json
{
  "config_version": "2026-10-01",
  "fx": {
    "as_of": "2026-10-01",
    "source": "manual snapshot (illustrative)",
    "per_usd": { "USD": "1", "SAR": "3.7500", "AED": "3.6725", "KWD": "0.3070", "GBP": "0.7450" }
  },
  "markets": { "KSA": { }, "UAE": { }, "KWT": { } }
}
```

The final v0.2 shape of a market, shown for the UAE. Fields marked M9 or M10 arrive in those milestones; until then a market has the v0.1 fields only. (JSON has no comments: the `// M9` marks are for this document only.)

```json
"UAE": {
  "name": "United Arab Emirates",
  "currency": { "code": "AED", "minor_units": 2, "charm_ending": "0.99" },
  "tax": { "vat_rate": "0.05", "source": "illustrative - verify before quoting", "effective_from": "2018-01-01" },
  "customs": {
    "default_duty_rate": "0.05",
    "category_overrides": { "digital": "0.00" },
    "de_minimis": {                                                        // M10
      "threshold": "1000.00",
      "applies": "at_or_below",
      "excluded_attributes": ["contains_alcohol"],
      "source": "illustrative, modelled on Dubai Customs from 2026-08-03: no customs duty on e-commerce goods not exceeding AED 1,000, except tobacco, nicotine and alcohol, including food preparations containing alcohol"
    }
  },
  "compliance": {                                                          // M9
    "banned_attributes": ["contains_pork"],
    "source": "illustrative - the retailer holds no licence to sell pork products in the UAE; verify before quoting"
  },
  "calendar": {
    "timezone": "Asia/Dubai",
    "weekend": ["SAT", "SUN"],
    "order_cutoff_local": "15:00",
    "holidays": [
      { "date": "2026-12-02", "name": "National Day", "provisional": false },
      { "date": "2026-12-03", "name": "National Day", "provisional": false },
      { "date": "2027-01-01", "name": "New Year's Day", "provisional": false },
      { "date": "2027-03-09", "name": "Eid al-Fitr", "provisional": true },
      { "date": "2027-03-10", "name": "Eid al-Fitr", "provisional": true },
      { "date": "2027-03-11", "name": "Eid al-Fitr", "provisional": true }
    ]
  },
  "logistics": {
    "freight_per_kg_usd": "4.00",
    "parcel_freight_per_kg_usd": "8.00",                                   // M10
    "linehaul_business_days": 3,
    "last_mile_business_days": 1
  }
}
```

All three markets:

| Field | KSA (v0.1 values kept) | UAE | KWT |
|---|---|---|---|
| `name` | Saudi Arabia | United Arab Emirates | Kuwait |
| currency, minor units, charm | SAR, 2, `0.95` | AED, 2, `0.99` | KWD, 3, `0.950` |
| VAT, `effective_from` | `0.15`, 2020-07-01 | `0.05`, 2018-01-01 | `0`, 2026-10-01 (Kuwait has no VAT) |
| default duty; overrides | `0.05`; fashion `0.12`, digital `0.00` | `0.05`; digital `0.00` | `0.05`; digital `0.00` |
| de minimis (M10) | `1000.00`, `below`, none excluded | `1000.00`, `at_or_below`, `contains_alcohol` | `null` |
| banned attributes (M9) | `contains_alcohol`, `contains_pork` | `contains_pork` | `contains_alcohol`, `contains_pork` |
| timezone | Asia/Riyadh (UTC+3) | Asia/Dubai (UTC+4) | Asia/Kuwait (UTC+3) |
| weekend | FRI SAT | SAT SUN | FRI SAT |
| order cutoff | 14:00 | 15:00 | 13:00 |
| freight; parcel freight (USD/kg, M10) | `4.50`; `9.00` | `4.00`; `8.00` | `5.00`; `10.00` |
| linehaul + last mile (business days) | 3 + 2 | 3 + 1 | 3 + 2 |

`source` strings not shown above:
- KSA and UAE tax: "illustrative - verify before quoting" (as in v0.1). KWT tax: "illustrative - Kuwait has no VAT; verify before quoting".
- KSA and KWT compliance: "illustrative - alcohol and pork products are not allowed; verify before quoting".
- KSA de minimis: "illustrative, modelled on ZATCA: no customs duty on e-store purchases under SAR 1,000 including shipping and insurance; VAT still due".

Holidays. Every market lists its public holidays up to 2027-03-31. Eid dates depend on the moon and are provisional.

| Date | KSA | UAE | KWT |
|---|---|---|---|
| Wed 2026-12-02, Thu 2026-12-03 | – | National Day | – |
| Fri 2027-01-01 | – | New Year's Day | New Year's Day |
| Mon 2027-02-22 | Founding Day (v0.1) | – | – |
| Thu 2027-02-25 | – | – | National Day |
| Fri 2027-02-26 | – | – | Liberation Day |
| Tue 2027-03-09 to Thu 2027-03-11 | Eid al-Fitr (provisional) | Eid al-Fitr (provisional) | Eid al-Fitr (provisional) |

Rules:
- `per_usd[X]` is units of X per 1 USD. Convert A → B as `amount * per_usd[B] / per_usd[A]`. Multiply first: the product is exact, so only the division can round, and a result with a finite decimal expansion stays exact.
- `minor_units` is 2 for SAR and AED, 3 for KWD.
- Rates are fractions given as strings (`"0.15"` = 15%).
- `charm_ending` may be `null`, meaning no charm pricing.
- Weekend days use `MON` … `SUN`.
- Validation must reject unknown currency codes, negative rates, an invalid timezone, a malformed cutoff time and a config with no markets.
- `compliance` is required in every market (M9). `banned_attributes` may be empty; each name must be an attribute from §6.1, with no duplicates. `source` is not empty.
- `customs.de_minimis` is required in every market (M10) and may be `null`, meaning no de minimis. When set: `threshold` > 0, in the market currency; `applies` is `"below"` or `"at_or_below"`; `excluded_attributes` follows the rule for `banned_attributes`; `source` is not empty.
- `logistics.parcel_freight_per_kg_usd` is required (M10) and ≥ 0.
- These fields are required rather than defaulted, so a market cannot end up with "nothing banned" or "no de minimis" because a field was left out.
- Test fixtures get the same fields. `tests/fixtures/zero_vat_config.json`: an empty banned list (M9), `"de_minimis": null` and parcel freight `9.00` (M10).

## 7. Pricing rules (all costs are passed through to the customer)

### 7.1 Steps
All values are in the market currency and keep full precision until step 7.

1. `goods = convert(base_price, product currency → market currency)`
2. `freight = convert(freight_per_kg × weight_kg, USD → market currency)`, where `freight_per_kg` is `freight_per_kg_usd` for a consolidated import (the default, and v0.1's only model) and `parcel_freight_per_kg_usd` for a direct parcel (§7.7)
3. `cif = goods + freight`
4. `duty_rate = 0` if de minimis applies (§7.7.2); otherwise `duty_rate = category_overrides.get(category, default_duty_rate) + duty_adjustment` (see §7.4)
5. `duty = cif × duty_rate`
6. `vat = (cif + duty) × vat_rate`
7. `gross = cif + duty + vat`, then `rounded = gross` rounded to `minor_units` with `ROUND_HALF_UP`
8. `shelf_price = charm(rounded)`: if `rounded` already ends with `charm_ending`, keep it; otherwise move **up** to the next price with that ending. Charm pricing never lowers a price.
9. Margin:
   - `cost_local = convert(unit_cost, product currency → market currency)`
   - `goods_revenue = shelf_price / (1 + vat_rate) − freight − duty`
   - `margin_pct = (goods_revenue − cost_local) / goods_revenue`

**Display rule:** components (goods, freight, duty, VAT) are rounded to minor units for display only. Their displayed sum can differ from `shelf_price` because of rounding and the charm uplift; `shelf_price` is authoritative.

**`PriceQuote` (from M10)** also records `shipping`, `duty_rate` (the rate applied to CIF) and `duty_waived` (true when de minimis applied). The CLI and the dashboard show a Duty column: "waived" for a waived product, otherwise the rate with one decimal ("5.0%"; "15.0%" for fashion in KSA at +3 pp).

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
- It never changes whether de minimis applies, and a product whose duty is waived pays no duty at any adjustment (§7.7.2).

### 7.5 Money edge cases (all must be tested)
- `12.3455` with 3 minor units → `12.346`; `12.34` with 3 minor units formats as `"12.340"`.
- `0.0005` with 3 minor units → `0.001` (`ROUND_HALF_UP`; banker's rounding would give `0.000`).
- `10.005` with 2 minor units → `10.01`.
- Charm with ending `0.95`: `686.31 → 686.95`; `686.95 → 686.95`; `686.96 → 687.95`; `9.00 → 9.95`.
- Charm with 3 minor units and ending `0.950`: `4.200 → 4.950`.
- A float anywhere in money input → validation error.
- 0% VAT (test fixture market): `vat` is exactly 0, and nothing ever formats as `-0.000`.

### 7.6 Compliance (v0.2, M9)
- A product is **not sold** in a market if one of its attributes is `true` and listed in the market's `banned_attributes`. Its reasons are those attributes, in the order the market lists them.
- Products are screened before they are priced. A product that is not sold is never priced for that market and never silently dropped (§3 rule 7): `localise_and_summarise` returns it in `excluded`, the CLI prints it after the table and the dashboard lists it under the grid.
- Both lists keep catalogue order.
- The headline metrics, the grid and the CSV cover the products for sale. The dashboard adds a fourth metric, "Not sold in CODE".
- `localise_catalogue` stays the lower-level function: it prices exactly the products it is given and does not screen. Everything that shows a market (CLI, dashboard, the v0.3 report) uses `localise_and_summarise`.
- Sample data: KSA sells 11 of the 13 products (not `GROC-VAN-061`, `contains_alcohol`; not `GROC-GUM-062`, `contains_pork`), the UAE 12 (not `GROC-GUM-062`) and Kuwait 11 (as KSA).
- The CLI shows reason codes (`contains_pork`). The dashboard shows labels: "Contains alcohol", "Contains pork", "Contains lithium battery".

### 7.7 De minimis and the shipping model (v0.2, M10)

#### 7.7.1 Shipping models
- `consolidated` (default): orders travel together as one commercial import, so de minimis never applies. Freight is `freight_per_kg_usd`. Prices are exactly the v0.1 prices.
- `parcel`: each order is shipped and cleared on its own, as a one-item parcel. Freight is `parcel_freight_per_kg_usd`, and duty is waived when the market's de minimis rule applies.
- Delivery dates are the same in both models in v0.2.
- The model is a scenario parameter, like `duty_adjustment`: the CLI takes `--shipping`, the dashboard has a radio, and the config never stores it.

#### 7.7.2 When de minimis applies
In parcel mode, de minimis applies to a product when all three hold:
1. the market's `de_minimis` is not `null`;
2. none of the product's `true` attributes is in `excluded_attributes`;
3. its `cif`, in the market currency at full precision, is below the threshold (`"below"`) or at or below it (`"at_or_below"`).

When it applies, the duty rate is 0, whatever the category and the duty adjustment: the slider never changes whether a product is waived, or what a waived product pays. VAT is still charged, on CIF since there is no duty.

### 7.8 Worked examples (v0.2)

#### C: headphones in the UAE (consolidated)

| Step | Value (AED) |
|---|---|
| goods | 149.99 × 3.6725 = 550.838275 |
| freight | 0.35 kg × 4.00 = 1.40 USD → 5.1415 |
| cif | 555.979775 |
| duty (5%) | 27.79898875 |
| vat (5%) | 29.1889381875 |
| gross | 612.9677019375 |
| rounded | 612.97 |
| **shelf_price** | **612.99** |
| margin_pct | 0.587 (cost 62.00 USD = 227.695 AED) |

#### D: headphones in Kuwait (consolidated, 3 minor units, no VAT)

| Step | Value (KWD) |
|---|---|
| goods | 149.99 × 0.3070 = 46.04693 |
| freight | 0.35 kg × 5.00 = 1.75 USD → 0.53725 |
| cif | 46.58418 |
| duty (5%) | 2.329209 |
| vat (0%) | 0 |
| gross | 48.913389 |
| rounded | 48.913 |
| **shelf_price** | **48.950** |
| margin_pct | 0.587 (cost 62.00 USD = 19.034 KWD) |

#### E: headphones in KSA, direct parcel (de minimis applies)

| Step | Value (SAR) |
|---|---|
| goods | 562.4625 |
| freight | 0.35 kg × 9.00 = 3.15 USD → 11.8125 |
| cif | 574.275, below 1,000.00, so de minimis applies |
| duty | 0 (waived) |
| vat (15%) | 86.14125 |
| gross | 660.41625 |
| rounded | 660.42 |
| **shelf_price** | **660.95** (consolidated: 686.95) |
| margin_pct | 0.587 |

#### F: vanilla extract in the UAE, direct parcel (alcohol is excluded from de minimis)

| Step | Value (AED) |
|---|---|
| goods | 12.99 × 3.6725 = 47.705775 |
| freight | 0.15 kg × 8.00 = 1.20 USD → 4.407 |
| cif | 52.112775, under the threshold, but `contains_alcohol` is excluded |
| duty (5%) | 2.60563875 |
| vat (5%) | 2.7359206875 |
| gross | 57.4543344375 |
| rounded | 57.45 |
| **shelf_price** | **57.99** (consolidated: 55.99) |
| margin_pct | 0.688 |

#### G: espresso machine in KSA, direct parcel (above the threshold)

| Step | Value (SAR) |
|---|---|
| goods | 649.00 / 0.7450 × 3.75 = 3266.77852348… |
| freight | 9.80 kg × 9.00 = 88.20 USD → 330.75 |
| cif | 3597.52852348…, not below 1,000.00 |
| duty (5%) | 179.87642617… |
| vat (15%) | 566.61074244… |
| gross | 4344.01569211… |
| rounded | 4344.02 |
| **shelf_price** | **4344.95** (consolidated: 4144.95; parcel at +3 pp: 4468.95) |
| margin_pct | 0.401 (cost 389.00 GBP = 1958.05369127… SAR) |

#### H: the threshold itself (test fixture)

`tests/fixtures/de_minimis_boundary_config.json` has two markets, `TEST-BELOW` (`"applies": "below"`) and `TEST-AT-OR-BELOW` (`"applies": "at_or_below"`). Both use currency `XTS` (the ISO 4217 code reserved for testing) at `per_usd` `"4.0000"`, 2 minor units, no charm ending, VAT 0, duty 0.05, threshold `1000.00`, no excluded attributes, nothing banned, and freight and parcel freight `0`. The calendar can copy KSA's. A zero-weight USD product then has CIF = 4 × its price, exactly. Parcel mode:

| `base_price` (USD) | cif (XTS) | `below` | `at_or_below` |
|---|---|---|---|
| 249.99 | 999.96 | waived → 999.96 | waived → 999.96 |
| 250.00 | 1000.00 | duty → **1050.00** | waived → **1000.00** |
| 250.01 | 1000.04 | duty → 1050.04 | duty → 1050.04 |

### 7.9 Price lists (v0.2)

#### 7.9.1 Consolidated (M8)

These come out of the v0.1 engine with no code change. † = not sold in that market from M9 on (`price_product` still prices it; the market view lists it as not sold).

| SKU | KSA (SAR) | UAE (AED) | KWT (KWD) |
|---|---|---|---|
| ELEC-HP-001 | 686.95 | 612.99 | 48.950 |
| ELEC-CHG-002 | 184.95 | 164.99 | 13.950 |
| FASH-BAG-014 | 594.95 | 496.99 | 39.950 |
| FASH-SCF-015 | 293.95 | 246.99 | 19.950 |
| SPRT-KTB-020 | 593.95 | 498.99 | 44.950 |
| HOME-KTL-030 | 237.95 | 209.99 | 17.950 |
| HOME-ESP-031 | 4144.95 | 3685.99 | 296.950 |
| BEAU-LIP-040 | 16.95 | 14.99 | 1.950 |
| BEAU-SRM-041 | 111.95 | 99.99 | 7.950 |
| DIGI-LIC-050 | 340.95 | 304.99 | 24.950 |
| GROC-TEA-060 | 34.95 | 29.99 | 2.950 |
| GROC-VAN-061 | 61.95 † | 55.99 | 4.950 † |
| GROC-GUM-062 | 22.95 † | 19.99 † | 1.950 † |

#### 7.9.2 Direct parcel (M10)

w = duty waived by de minimis.

| SKU | KSA (SAR) | UAE (AED) | KWT (KWD) |
|---|---|---|---|
| ELEC-HP-001 | 660.95 w | 589.99 w | 49.950 |
| ELEC-CHG-002 | 179.95 w | 159.99 w | 13.950 |
| FASH-BAG-014 | 546.95 w | 485.99 w | 41.950 |
| FASH-SCF-015 | 264.95 w | 236.99 w | 19.950 |
| SPRT-KTB-020 | 875.95 w | 721.99 w | 70.950 |
| HOME-KTL-030 | 249.95 w | 218.99 w | 19.950 |
| HOME-ESP-031 | 4344.95 | 3844.99 | 312.950 |
| BEAU-LIP-040 | 15.95 w | 14.99 w | 1.950 |
| BEAU-SRM-041 | 108.95 w | 96.99 w | 8.950 |
| DIGI-LIC-050 | 340.95 w | 304.99 w | 24.950 |
| GROC-TEA-060 | 37.95 w | 32.99 w | 2.950 |
| GROC-VAN-061 | 61.95 w † | 57.99 | 4.950 † |
| GROC-GUM-062 | 25.95 w † | 21.99 w † | 1.950 † |

A digital licence counts as waived even though its duty rate is already 0: "waived" means only that de minimis applied.

#### 7.9.3 What the switch shows

Light, valuable items get cheaper as parcels (headphones in KSA: 686.95 → 660.95). Heavy or cheap items get dearer, because parcel freight costs twice as much per kg (kettlebell: 593.95 → 875.95; tea: 34.95 → 37.95). The espresso machine pays duty either way, plus the extra freight (4144.95 → 4344.95). In Kuwait a parcel is never cheaper, because there is no de minimis. This is the comparison the v0.3 report builds on.

#### 7.9.4 Kuwait's charm ending

One dinar is about 3.26 USD, so ending every KWD price in `.950` can add almost a whole dinar. Lip balm: 1.157 → 1.950 (+69%), with a 0.844 margin against 0.741 in KSA. This is kept on purpose (§12) as a finding for the v0.3 report: KWD needs a finer price ladder for cheap items.

## 8. Delivery rules (destination calendar only)

- Input: `ordered_at` (timezone-aware `datetime`) and the market config. A naive datetime raises an error.
- Convert `ordered_at` to the market timezone.
- A business day is not a weekend day and not a listed holiday (provisional holidays count as holidays).
- **Dispatch day** = the local order date if it is a business day and the local time is before the cutoff; otherwise the next business day. An order at exactly the cutoff time misses it.
- The cutoff is compared as a moment in time, not as a clock reading: an order makes it only if it comes before the moment the cutoff time is reached on the local order date. On a clock-change day, a cutoff in a repeated hour is its first occurrence, and a cutoff in a skipped hour falls an hour later on the clock (01:30 in `Europe/London` on a spring-forward day behaves as 02:30 BST). A later order therefore never gets an earlier dispatch day. The GCC timezones have no clock changes, so §8.1 and §8.2 are unaffected.
- **Delivery date** = the Nth business day after the dispatch day, where N = `linehaul_business_days + last_mile_business_days` (5 for KSA and Kuwait, 4 for the UAE).
- Both shipping models (§7.7.1) use the same calendar and transit days in v0.2.
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

### 8.2 Three markets (v0.2, M8)

The same moment in all three markets. Each cell: local order time → dispatch → delivery.

| Order (UTC) | KSA | UAE | KWT | What it shows |
|---|---|---|---|---|
| Thu 2026-10-15 09:30 | Thu 12:30 → Thu 15 → **Thu 22** | Thu 13:30 → Thu 15 → **Wed 21** | Thu 12:30 → Thu 15 → **Thu 22** | the UAE's shorter last mile |
| Thu 2026-10-15 10:30 | Thu 13:30 → Thu 15 → **Thu 22** | Thu 14:30 → Thu 15 → **Wed 21** | Thu 13:30, after the 13:00 cutoff → Sun 18 → **Sun 25** | Kuwait's earlier cutoff |
| Fri 2026-10-16 07:00 | Fri 10:00, weekend → Sun 18 → **Sun 25** | Fri 11:00, a UAE business day → Fri 16 → **Thu 22** | Fri 10:00, weekend → Sun 18 → **Sun 25** | the UAE works on Fridays |
| Tue 2026-12-01 08:00 | → Tue 12-01 → **Tue 12-08** | → Tue 12-01 → **Wed 12-09** | → Tue 12-01 → **Tue 12-08** | UAE National Day, 2–3 Dec |
| Wed 2027-02-24 07:00 | → Wed 02-24 → **Wed 03-03** | → Wed 02-24 → **Tue 03-02** | → Wed 02-24 → **Thu 03-04** | Kuwait's National and Liberation Days |
| Mon 2027-03-08 07:00 | → Mon 03-08 → **Thu 03-18** | → Mon 03-08 → **Wed 03-17** | → Mon 03-08 → **Thu 03-18** | Eid al-Fitr (provisional) |

The second row's KSA cell is §8.1's third row, unchanged.

## 9. The expansion report (v0.3)

`GCC_EXPANSION_REPORT.md` answers the demo user's real question: which market, which shipping model, and what goes wrong with prices. It puts every market and both shipping models side by side for one order. Appendix A is the report for the sample data, exactly.

### 9.1 Scope
- **One input:** `ordered_at`, a timezone-aware instant. The report prices the catalogue for that order in every market in the config, in config order, under both shipping models (§7.7.1).
- **Duty rates:** today's (no duty adjustment), plus the rises in `TARIFF_RISES_POINTS = (5, 10, 20)` percentage points as stress tests (§9.2.3). The dashboard's slider, shipping model and search never change the report.
- **One source of numbers:** every market view comes from `localise_and_summarise`, so the report, the CLI and the dashboard always agree, and products a market does not allow are never priced (§3 rule 7).
- **Provenance:** the report names the data it was built from (`config_version`, `fx.as_of`, `catalogue_version`), not the SouqSort version, so a release does not change it.
- **Format:** Markdown, UTF-8, `\n` line endings on every OS, ending with a single newline. No timestamp other than the order's.

### 9.2 Figures

All figures stay `Decimal` until they are formatted (§9.3). Averages are unweighted means over the products a market sells. A market that sells nothing has no averages (`None`, shown as `-`).

#### 9.2.1 Markets side by side (M11)
Per market, with consolidated imports and today's rates:
- **products for sale and not sold** (§7.6);
- **average margin:** `summary.average_margin_pct`;
- **above catalogue price:** the mean of `shelf_price / goods − 1`. `goods` is the catalogue price converted to the market currency (§7.1 step 1), so the ratio is free of currency and markets compare directly. It includes freight, duty, VAT and the price ending. Base prices are > 0, so `goods` is never 0.
- **VAT rate, the order's local time, the cut-off and the delivery date.** The delivery comes from `estimate_delivery(ordered_at, market)` (§8), which needs no product, so a market that sells nothing still has one. Delivery is the same in both shipping models (§8).

| Market | For sale | Not sold | Average margin | Above catalogue price | Ordered (local) | Delivered |
|---|---|---|---|---|---|---|
| KSA | 11 | 2 | 64.6% | +41.2% | Thu 12:00, cut-off 14:00 | Thu 2026-10-22 |
| UAE | 12 | 1 | 64.9% | +24.7% | Thu 13:00, cut-off 15:00 | Wed 2026-10-21 |
| KWT | 11 | 2 | 66.6% | +33.1% | Thu 12:00, cut-off 13:00 | Thu 2026-10-22 |

(Order at 2026-10-15 09:00 UTC, before every cut-off. The delivery dates are those of §8.2's first row.)

#### 9.2.2 Consolidated or parcel (M12)
- Per market, for each product for sale in catalogue order: the consolidated and the parcel shelf prices, the change `parcel / consolidated − 1`, and the parcel quote's `duty_rate` and `duty_waived`.
- A product is **cheaper**, **dearer** or **unchanged** by comparing the two shelf prices themselves, never the rounded change.
- Per market: the three counts, and how many parcel quotes have `duty_waived`.

| Market | Cheaper | Dearer | Unchanged | Duty waived |
|---|---|---|---|---|
| KSA | 6 | 4 | 1 | 10 of 11 |
| UAE | 5 | 5 | 2 | 10 of 12 |
| KWT | 0 | 6 | 5 | 0 of 11 |

Every price in this section is in §7.9.1 (consolidated) or §7.9.2 (parcel).

#### 9.2.3 Tariff exposure (M12)
- Per market and shipping model, for each rise in `TARIFF_RISES_POINTS`: `summary.average_price_change_pct` of `localise_and_summarise(..., duty_adjustment_from_points(rise), shipping)`. That figure already compares each product with its price at 0 pp in the same model (§11.1, M6).
- `HEADLINE_TARIFF_RISE_POINTS = 10` is the rise the opening sentence quotes. It must be one of `TARIFF_RISES_POINTS`.
- Parcels in KSA and the UAE barely move, because de minimis waives duty at any adjustment (§7.4).
- Kuwait has no VAT and no de minimis, so before the price ending both of its models rise by exactly the same amount: 4.78%, 9.57% and 19.13% on average. The gaps in the table come only from KWD prices stepping in whole dinars (§7.9.4). The price ending absorbs some rises and turns others into a jump of a whole dinar.

| Market | Shipping | +5 pp | +10 pp | +20 pp |
|---|---|---|---|---|
| KSA | consolidated | +4.6% | +9.0% | +18.6% |
| KSA | parcel | +0.4% | +0.9% | +1.7% |
| UAE | consolidated | +4.9% | +9.3% | +19.2% |
| UAE | parcel | +0.8% | +1.5% | +3.2% |
| KWT | consolidated | +3.8% | +7.6% | +16.0% |
| KWT | parcel | +6.3% | +9.4% | +17.7% |

#### 9.2.4 How a price is built (M13)
- **The sample product** is the first product in catalogue order that every market sells. In the sample data that is `ELEC-HP-001`, the headphones of worked examples A, C, D and E. If no product is sold everywhere, the section has no tables.
- Per market: the sample product's consolidated and parcel quotes, shown as goods ("Catalogue price, converted"), freight, duty, VAT, a "Rounding and price ending" line and the shelf price.
- Each component is rounded for display (§7.1, display rule). The rounding line is `shelf_price` minus the sum of the four displayed components, so every column adds up exactly to the shelf price. In KSA's parcel column it is 660.95 − (562.46 + 11.81 + 0.00 + 86.14) = **0.54**, although `shelf_price − gross` is 0.53375. The report's method notes say so. When the rounded gross already has the price ending, the line can be a minor unit or two below zero (`-0.01`); it is shown as it is.
- A waived duty shows as `0.00 (waived)`.

| Market (headphones) | Consolidated: freight, duty, VAT, rounding → shelf | Parcel: freight, duty, VAT, rounding → shelf |
|---|---|---|
| KSA | 5.91, 28.42, 89.52, 0.64 → **686.95** | 11.81, 0.00 (waived), 86.14, 0.54 → **660.95** |
| UAE | 5.14, 27.80, 29.19, 0.02 → **612.99** | 10.28, 0.00 (waived), 28.06, 0.81 → **589.99** |
| KWT | 0.537, 2.329, 0.000, 0.037 → **48.950** | 1.075, 2.356, 0.000, 0.472 → **49.950** |

Goods: 562.46 SAR, 550.84 AED, 46.047 KWD.

#### 9.2.5 Pricing risks (M13)
- A product for sale is a **pricing risk** in a market when its consolidated `shelf_price / gross − 1` is greater than `PRICE_ENDING_ALERT = Decimal("0.10")`: rounding and the price ending (§7.1 steps 7 and 8) added more than 10% to it. Exactly 10% is not a risk.
- Listed in market order, then catalogue order.
- The sample data has two, both in Kuwait (§7.9.4): `BEAU-LIP-040` 1.157 → 1.950 (+68.5%) and `GROC-TEA-060` 2.458 → 2.950 (+20.0%). The next highest are Kuwait's charger (+5.8%) and kettle (+5.1%). In KSA and the UAE the largest is the lip balm, at +4.6% and +3.7%.

#### 9.2.6 Not sold (M11)
Every market's excluded products (§7.6), in market order then catalogue order, with their reasons as labels ("Contains alcohol"). Sample data: KSA and Kuwait exclude `GROC-VAN-061` and `GROC-GUM-062`; the UAE excludes `GROC-GUM-062`.

### 9.3 Text

#### 9.3.1 Formatting
- **Money:** the currency's minor units, `ROUND_HALF_UP`, with commas between thousands: `4,144.95`, `312.950`. Formatted from `Decimal` with `round_minor` and `f"{amount:,f}"`, never through `float`.
- **Percentages:** one decimal, `ROUND_HALF_UP`. A change, and the figure above the catalogue price, take a `+` when they are positive after rounding (`+41.2%`, `-3.8%`, `0.0%`); nothing ever shows as `-0.0%`. Rates (VAT, duty, the 10% alert) and margins have no sign (`15.0%`, `64.6%`).
- **Dates and times:** `Thu 2026-10-22`; a local order time `Thu 2026-10-15 12:00`; a cut-off `14:00`. The header gives the order in UTC.
- **Markets:** the code in sentences and in most tables (`KSA`); code and name in per-market headings and in the first column of the markets table (`KSA (Saudi Arabia)`); code and currency in the build-up headings (`KSA (SAR)`).
- **Lists in a sentence** join with commas and a final "and": "6 of 11 products in KSA, 5 of 12 in UAE and 0 of 11 in KWT". Clauses that already contain "and" join with semicolons and a final "; and".
- **Counts:** "1 product", otherwise "products".
- **Table cells** that come from the data escape `|` as `\|` and turn line breaks into spaces.
- **Shipping models** in tables use the dashboard labels: "Consolidated import", "Direct parcel".

#### 9.3.2 Sentences
Each section opens with its sentences. The summary at the top repeats them all as bullets, in section order. With the sample data:

1. **Markets side by side**, two sentences:
   - "On average, shelf prices sit 24.7% above the catalogue price in UAE, 33.1% in KWT and 41.2% in KSA." Lowest first, comparing the full-precision averages; exact ties keep config order; markets that sell nothing are left out. If none sells anything: "No market has products for sale."
   - "For this order, delivery is on Thu 2026-10-22 in KSA, Wed 2026-10-21 in UAE and Thu 2026-10-22 in KWT." Every market, config order.
2. **Consolidated or parcel:** "Direct parcels are cheaper than consolidated imports for 6 of 11 products in KSA, 5 of 12 in UAE and 0 of 11 in KWT." Config order; markets that sell nothing are left out; none: "No market has products for sale."
   - Each market's subsection opens with its rule: "No duty on a parcel whose CIF is below 1,000.00 SAR." / "No duty on a parcel whose CIF is at or below 1,000.00 AED, except products containing alcohol." / "No de minimis rule, so every parcel pays duty." Excluded attributes read as "alcohol", "pork" and "a lithium battery", several joined with "or".
   - Then "Parcels are cheaper for 6 of 11 products, dearer for 4 and unchanged for 1." and, only when the market has a rule, "Duty is waived on 10 of them." A market that sells nothing: "No products are for sale." and no table.
3. **Tariff exposure:** "A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for direct parcels in KSA; 9.3% and 1.5% in UAE; and 7.6% and 9.4% in KWT." Config order; markets that sell nothing are left out; none: "No market has products for sale."
4. **How a price is built:** "Wireless Noise-Cancelling Headphones (ELEC-HP-001) is the first product every market sells. Shipped as a direct parcel instead of a consolidated import, its price changes by -3.8% in KSA, -3.8% in UAE and +2.0% in KWT." None sold everywhere: "No product is sold in every market, so there is no price to break down."
5. **Pricing risks:** "The price ending adds more than 10.0% to 2 products: BEAU-LIP-040 in KWT (+68.5%) and GROC-TEA-060 in KWT (+20.0%)." None: "No price ending adds more than 10.0% to any product."
6. **Not sold:** "Out of 13 products, KSA cannot sell 2, UAE 1 and KWT 2." Every market, config order. Nothing excluded anywhere: "Every market can sell every product."

### 9.4 Layout
Appendix A shows the layout exactly. In order:
1. `# GCC expansion report`, the scenario sentence (the order in UTC and the data it was built from) and the illustrative-data warning as a quote.
2. `## Summary`: the sentences of §9.3.2 as bullets.
3. `## Markets side by side`: the sentences, then one row per market: Market, Currency, VAT, For sale, Not sold, Above catalogue price, Average margin, Ordered (local time), Cut-off, Delivered.
4. `## Consolidated or parcel`: the sentence, then per market `### KSA (Saudi Arabia)`, its rule and counts, and SKU, Product, Consolidated (SAR), Direct parcel (SAR), Change, Parcel duty ("waived" or the rate).
5. `## Tariff exposure`: the sentence, then Market, Shipping model and one column per rise (`+5 pp` …), two rows per market.
6. `## How a price is built`: the sentence, then per market `### KSA (SAR)` and a table of Step, Consolidated import, Direct parcel. The shelf price row is bold.
7. `## Pricing risks`: the sentence, then Market, SKU, Product, Before the price ending, Shelf price, Added. No table when there are none.
8. `## Not sold`: the sentence, then Market, SKU, Product, Reasons. No table when nothing is excluded.
9. `## How these figures are made`: the method notes, as bullets.

Number columns are right-aligned. There is exactly one blank line between blocks, and no trailing spaces.

#### 9.4.1 Template rules
- `src/souqsort/report/templates/expansion_report.md.j2`, loaded with `jinja2.PackageLoader("souqsort.report", "templates")` into an `Environment` with `undefined=StrictUndefined`, `autoescape=False` (Markdown, not HTML: cells are escaped as §9.3.1 says), `trim_blocks=True`, `lstrip_blocks=True` and `keep_trailing_newline=True`.
- **The template only places text.** `render_report` passes it strings, and lists and dicts of strings, nothing else; a test walks the whole context to prove it. Every number is formatted in Python first.
- The template has no arithmetic and uses none of the filters `float`, `int`, `round`, `sum`, `abs` or `format`. It names no market code and no currency code: `tests/test_architecture.py` checks both, as it checks `src/` and `app/` for market codes (§3 rule 4).

### 9.5 The sample report (M13)
- `docs/GCC_EXPANSION_REPORT.md` is the report for `ordered_at = 2026-10-15T09:00Z` over the sample data: 12:00 in Riyadh and Kuwait, 13:00 in Dubai, before every cut-off. It is Appendix A exactly, and the README links to it.
- `tests/test_report_sample.py` builds the same report and compares it with the file byte for byte. On a mismatch it says how to regenerate the file: `uv run python -m souqsort report --ordered-at 2026-10-15T09:00Z --out docs/GCC_EXPANSION_REPORT.md`.
- Every figure in Appendix A was checked while writing this spec against an independent re-implementation of §7 and §8 that does not import `souqsort`.

### 9.6 CLI and dashboard
- **CLI:** `uv run python -m souqsort report [--ordered-at ISO] [--out PATH] [--catalogue PATH] [--config PATH]`.
  - `--ordered-at` parses as for `price`, but must carry an offset (`Z` or `±HH:MM`): without one, `price` reads the time on the market's clock, and the report has no single market. Without an offset it exits 2 with `argument --ordered-at: the report covers every market, so give a UTC offset, e.g. 2026-10-15T09:00Z`. Default: now, from the injectable `now`.
  - `--out` defaults to `outputs/GCC_EXPANSION_REPORT.md` (`outputs/` is gitignored). Its folder is created if needed. It refuses to overwrite the `--catalogue` or `--config` file, as `--csv` does. The file is written as UTF-8 with `\n` line endings.
  - Prints one line, `Wrote the expansion report to outputs/GCC_EXPANSION_REPORT.md` (the path as given). A data file that cannot be read, or a report that cannot be written, exits 1 with a message, as `price` does.
- **Dashboard:** in the sidebar, under the search box, a "Download expansion report" button (`st.download_button`), file name `GCC_EXPANSION_REPORT.md`, MIME type `text/markdown`, with the help text "Every market and both shipping models for the order date and time above, at today's duty rates. The duty slider, shipping model and search don't change it."
  - It uses the same `ordered_at` as the page: the pickers on the selected market's clock (issue #3). Thu 2026-10-15 12:00 picked in KSA therefore downloads exactly the sample report.
  - Building and rendering the report takes about 20 ms on the sample data, so it runs on every rerun without caching.

## 10. Interfaces (suggested)

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

### 10.1 v0.2 changes

```python
# models.py
AttributeName = Literal["contains_alcohol", "contains_pork", "contains_lithium_battery"]
CategoryName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
ShippingModel = Literal["consolidated", "parcel"]

class ProductAttributes(_Model):          # M9; a test checks it has exactly the AttributeName fields
    contains_alcohol: StrictBool
    contains_pork: StrictBool
    contains_lithium_battery: StrictBool
    def has(self, name: AttributeName) -> bool: ...

class Product(_Model): ...                # category: CategoryName; attributes: ProductAttributes
class ComplianceConfig(_Model):           # M9
    banned_attributes: tuple[AttributeName, ...]
    source: NonEmptyStr
class DeMinimisRule(_Model):              # M10
    threshold: PositiveDecimal
    applies: Literal["below", "at_or_below"]
    excluded_attributes: tuple[AttributeName, ...]
    source: NonEmptyStr
class CustomsConfig(_Model): ...          # category_overrides: dict[CategoryName, ...]; de_minimis: DeMinimisRule | None (required key)
class LogisticsConfig(_Model): ...        # + parcel_freight_per_kg_usd: NonNegativeDecimal
class MarketConfig(_Model): ...           # + compliance: ComplianceConfig

# compliance.py (M9)
@dataclass(frozen=True)
class ExcludedProduct:
    sku: str
    name_en: str
    reasons: tuple[AttributeName, ...]    # in the market's listed order

@dataclass(frozen=True)
class ComplianceScreen:
    sellable: tuple[Product, ...]
    excluded: tuple[ExcludedProduct, ...]

def screen_products(products: Sequence[Product], market: MarketConfig) -> ComplianceScreen: ...

# pricing/customs.py (M10)
@dataclass(frozen=True)
class DutyAssessment:
    rate: Decimal                         # applied to CIF; 0 when waived
    waived: bool                          # de minimis applied

def de_minimis_applies(cif: Decimal, rule: DeMinimisRule | None,
                       attributes: ProductAttributes) -> bool: ...
def assess_duty(product: Product, market: MarketConfig, cif: Decimal,
                duty_adjustment: Decimal, shipping: ShippingModel) -> DutyAssessment: ...

# pricing/landed_cost.py (M10)
class PriceQuote: ...                     # + shipping: ShippingModel, duty_rate: Decimal, duty_waived: bool (before steps)
def price_product(product, market, fx, duty_adjustment=Decimal("0"),
                  shipping: ShippingModel = "consolidated") -> PriceQuote: ...
# Raises ValueError for a shipping model that is not one of ShippingModel's values.

# pipeline.py
def localise_catalogue(products, config, market_code, ordered_at, duty_adjustment=Decimal("0"),
                       shipping: ShippingModel = "consolidated") -> list[LocalisedProduct]: ...
# Prices exactly the products it is given. It does not screen for compliance. It checks
# shipping up front, as it checks duty_adjustment, so a bad value is never blamed on the first SKU.

@dataclass(frozen=True)
class LocalisedCatalogue:
    items: tuple[LocalisedProduct, ...]   # products for sale
    excluded: tuple[ExcludedProduct, ...] # M9
    summary: CatalogueSummary             # unchanged; covers items only

def localise_and_summarise(products, config, market_code, ordered_at, duty_adjustment=Decimal("0"),
                           shipping: ShippingModel = "consolidated") -> LocalisedCatalogue: ...
# Checks duty_adjustment and shipping first (plain TypeError/ValueError), then the market
# (LocalisationError), then screens, then prices what is for sale. The baseline uses the
# same products and shipping model at 0 pp.

# display.py
class DisplayRow: ...                     # + duty_percent: str ("5.0"; "0.0" when waived), duty_waived: bool
class GridRow: ...                        # + duty: str ("5.0%" or "waived")
@dataclass(frozen=True)
class ExcludedGridRow:
    sku: str
    name_en: str
    reasons: str                          # labels: "Contains pork"
def excluded_grid_rows(excluded: Sequence[ExcludedProduct]) -> list[ExcludedGridRow]: ...
SHIPPING_LABELS: dict[ShippingModel, str] # {"consolidated": "Consolidated import", "parcel": "Direct parcel"}
```

### 10.2 CLI and dashboard text (v0.2; the tests check it)
- CLI summary line ends with `   Shipping: consolidated` (or `parcel`). The table columns are SKU, Name, Shelf price (CODE), Margin %, Duty, Delivery, Flags. After the table, when something is not sold: a blank line, `Not sold in KSA (2):`, then SKU, Name and the reason codes, joined with commas.
- CSV (products for sale only): `sku,name_en,currency,shelf_price,margin_percent,duty_percent,duty_waived,delivery_date,flags`, with `duty_waived` as `true`/`false`.
- `--shipping {consolidated,parcel}`, default `consolidated`; any other value exits with code 2.
- Dashboard sidebar: a "Shipping model" radio under the market selector, with the two labels and this help: "Consolidated: orders travel as one commercial import, so de minimis never applies. Direct parcel: each order is cleared on its own; under the market's threshold it pays no duty, but parcel freight costs more per kg."
- Dashboard main area: the caption adds "Shipping: Consolidated import"; the metrics are Average margin, Flagged products, Average price change vs 0 pp, and Not sold in CODE; the scope caption is "All 11 products for sale in KSA; search filters the table only"; under the grid, "Not sold in KSA" with a table of SKU, Name and Reason. Search filters the main grid only.
- Messages under the grid: "The catalogue has no products." / "No product in the catalogue can be sold in KSA." / "No product matches the search."

### 10.3 v0.3 changes

```python
# report/figures.py: everything Decimal, nothing formatted
TARIFF_RISES_POINTS: tuple[int, ...] = (5, 10, 20)   # M12
HEADLINE_TARIFF_RISE_POINTS = 10                     # M12; must be in TARIFF_RISES_POINTS
PRICE_ENDING_ALERT = Decimal("0.10")                 # M13

@dataclass(frozen=True)
class MarketOverview:                     # M11, §9.2.1 and §9.2.6
    code: str
    name: str
    currency: str
    vat_rate: Decimal
    for_sale: int
    not_sold: tuple[ExcludedProduct, ...]
    average_margin_pct: Decimal | None
    average_above_catalogue_pct: Decimal | None
    cutoff: time
    delivery: DeliveryEstimate

@dataclass(frozen=True)
class ProductComparison:                  # M12, §9.2.2
    sku: str
    name_en: str
    consolidated_price: Decimal
    parcel_price: Decimal
    change_pct: Decimal
    parcel_duty_rate: Decimal
    parcel_duty_waived: bool

@dataclass(frozen=True)
class ShippingComparison:                 # M12
    code: str
    name: str
    currency: str
    minor_units: int
    de_minimis: DeMinimisRule | None
    products: tuple[ProductComparison, ...]
    # properties: cheaper, dearer, unchanged, waived (counts)

@dataclass(frozen=True)
class TariffExposure:                     # M12, §9.2.3
    code: str
    shipping: ShippingModel
    average_change_pct: tuple[Decimal | None, ...]   # one per TARIFF_RISES_POINTS

@dataclass(frozen=True)
class PriceBuildUp:                       # M13, §9.2.4
    code: str
    currency: str
    minor_units: int
    consolidated: PriceQuote
    parcel: PriceQuote

@dataclass(frozen=True)
class PricingRisk:                        # M13, §9.2.5
    code: str
    sku: str
    name_en: str
    minor_units: int
    gross: Decimal
    shelf_price: Decimal
    added_pct: Decimal

@dataclass(frozen=True)
class SampleProduct:                      # M13: the first product every market sells
    sku: str
    name_en: str

@dataclass(frozen=True)
class ExpansionReport:
    ordered_at: datetime
    config_version: str
    fx_as_of: date
    catalogue_version: str
    product_count: int
    markets: tuple[MarketOverview, ...]       # M11, config order
    shipping: tuple[ShippingComparison, ...]  # M12
    tariffs: tuple[TariffExposure, ...]       # M12, market then shipping model
    sample_product: SampleProduct | None      # M13, §9.2.4
    build_ups: tuple[PriceBuildUp, ...]       # M13
    pricing_risks: tuple[PricingRisk, ...]    # M13

def build_report(catalogue: Catalogue, config: GccConfig, ordered_at: datetime) -> ExpansionReport: ...
# ValueError for a naive ordered_at; LocalisationError as localise_and_summarise raises it.
def price_ending_added(quote: PriceQuote) -> Decimal: ...   # M13: shelf_price / gross - 1

# report/text.py: formatting, sentences and the template context; strings only
type ContextValue = str | Sequence[ContextValue] | Mapping[str, ContextValue]
def report_context(report: ExpansionReport) -> Mapping[str, ContextValue]: ...
# The template's context: strings only (§9.4.1), so mypy checks the rule as well as the test.
# Sequence and Mapping rather than list and dict, so that list[dict[str, str]] rows type-check.
def render_report(report: ExpansionReport) -> str: ...      # the Markdown of §9.3 and §9.4

# report/__init__.py re-exports build_report and render_report.

# cli.py: a second subcommand
#   report [--ordered-at ISO] [--out PATH] [--catalogue PATH] [--config PATH]   (§9.6)
```

## 11. Milestones

For every milestone: tests first, then code. Done means `uv run pytest`, `uv run ruff check .` and `uv run mypy src` all pass, then commit. From M7, done also means `uv run ruff format --check .` passes (`/verify` runs all four) and both CI jobs are green on the pull request. Every commit leaves the suite green.

### 11.1 v0.1 (done, tag `v0.1.0`)

#### M0: Skeleton
- uv project (src layout, Python 3.12) with the dependencies in §4.
- Folder structure from §5 with empty modules (a docstring only).
- `.gitignore` (Python, `.venv/`, `outputs/`, `.claude/settings.local.json`) and `.gitattributes` (`* text=auto eol=lf`).
- README stub: one paragraph plus how to run the tests.
- Ruff and mypy configured in `pyproject.toml` (mypy strict for `src/`, with the `pydantic.mypy` plugin).
- One smoke test that imports `souqsort`.
- **Accept:** all three commands pass.

#### M1: Models, loaders, data
- Pydantic models for §6, loaders that reject floats in money fields with a clear message, and the data files (12 products, KSA config).
- **Tests:** valid files load; float money rejected; unknown currency rejected; duplicate SKU rejected; invalid timezone rejected; `name.ar: null` accepted.

#### M2: Money
- Minor-unit rounding (`ROUND_HALF_UP`), charm-up and formatting with an exact number of decimals.
- **Tests:** every case in §7.5, plus Hypothesis properties:
  - a rounded value has exactly `minor_units` decimals;
  - `charm(x) >= x`;
  - `charm(charm(x)) == charm(x)`.

#### M3: FX and landed cost
- `convert()` and `price_product()` following §7, including `duty_adjustment`.
- **Tests:**
  - worked examples A and B exactly (`shelf_price`) and margin to 3 dp;
  - category override vs default duty;
  - zero weight gives zero freight;
  - 0% VAT fixture;
  - Hypothesis: a higher `duty_adjustment` never gives a lower `shelf_price`.

#### M4: Delivery calendar
- The rules in §8.
- **Tests:**
  - every row of §8.1;
  - a naive datetime raises;
  - Hypothesis: the delivery date is never a weekend day or holiday, and a later order never gets an earlier delivery date.

#### M5: Pipeline and CLI
- `localise_catalogue()`.
- CLI: `uv run python -m souqsort price --market KSA [--duty-adjust 3] [--ordered-at 2026-10-15T20:59Z] [--csv out.csv]`. It prints a table: SKU, English name, shelf price (formatted), margin %, delivery date, flags.
- `--ordered-at` defaults to now. The CLI reads the clock, not the engine.
- **Tests:** integration test over the sample data; CLI exits 0 and prints the expected columns.

#### M6: Streamlit dashboard
- `app/streamlit_app.py`:
  - **Sidebar:** market selector filled from the config (KSA only for now), duty slider (0–20 percentage points), order date and time pickers (default now, in market local time; the time picker steps by one minute, so both sides of the cutoff can be picked), search box (SKU or English name: a case-insensitive match on any part of either).
  - **Main area:** the data grid and three headline metrics: average margin, the number of flagged products, and the average price change against a 0 pp duty adjustment.
    - Both averages are unweighted means over the products. The price change of a product is `(shelf_price − shelf_price at 0 pp) / shelf_price at 0 pp`. It is there because v0.1 passes duty through to the customer, so average margin barely moves with the slider.
    - The metrics always cover the whole market; search filters the grid only. A caption under the metrics says so, with the real product count and market code.
  - Prices display with exactly the currency's minor units. Price and margin reach the grid as `Decimal`, not text, so the grid sorts them by value.
  - The grid shows each flag as a label a person can read (`missing_arabic_name` → "No Arabic name"), in a column wide enough not to cut it short. The CLI table and CSV keep the codes.
  - An empty catalogue and a search with no match each get their own message under the grid.
- No business logic in the app. What it needs lives in `src/` and is shared with the CLI where both use it:
  - `logistics/calendar.py`: `in_market_time()` (an order time without an offset is market-local, for `--ordered-at` and for the pickers) and `to_market_time()`;
  - `pipeline.py`: `MAX_DUTY_ADJUST_POINTS`, `duty_adjustment_from_points()`, and `localise_and_summarise()` → `LocalisedCatalogue` (the items plus a `CatalogueSummary`). It builds the 0 pp baseline itself, so no caller has to pair one up; the v0.3 report takes its numbers from the same call;
  - `display.py`: `grid_rows()` (built on `display_rows()`), `search_products()`, `display_summary()`.
- The app reads the clock once per session, for the picker defaults. `src/` still does not, apart from the CLI entry point.
- **Accept:** `uv run streamlit run app/streamlit_app.py` starts, and `tests/test_app.py` confirms headlessly:
  - moving the slider changes prices, and the price-change metric with them;
  - search filters rows and leaves the metrics alone;
  - a Thursday-evening order time gives Sunday-based delivery dates.
- AppTest does not render a browser. One manual look confirms that clicking the price header sorts by value and that prices show the currency's minor units.
- Then tag `v0.1.0`.

### 11.2 v0.2 (done, tag `v0.2.0`)

Every step uses the same flow: `git switch -c <branch>` → plan mode → commits → `git push -u origin <branch>` → `gh pr create --fill` → `gh pr checks --watch` → `gh pr merge --merge --delete-branch` → `git switch main && git pull`.

#### M7: CI and guard rails
Branch `chore/m7-ci`.
- This SPEC.md and the v0.2 CLAUDE.md, committed first as `docs: add the v0.2 spec`.
- `.github/workflows/ci.yml` and `.github/dependabot.yml`. setup-uv's `version` is what `uv --version` prints on the laptop.
- Hypothesis: no profile is registered and `tests/conftest.py` is unchanged. Hypothesis loads its built-in `ci` profile by itself on GitHub Actions (`derandomize=True, deadline=None, database=None, print_blob=True`, `too_slow` suppressed); the default profile runs everywhere else.
- `tests/test_architecture.py`:
  - no float literal and no use of the name `float` anywhere in `src/` (a call, a type annotation or a type alias), except as the class argument of `isinstance(...)`, which keeps the `isinstance(value, bool | int | float)` guard in `models.py` allowed;
  - no string literal in `src/` or `app/` equals a market code from `data/raw/gcc_config.json` (§3 rule 4, enforced).
- `.claude/skills/verify/SKILL.md`: the `/verify` skill.
- README: a CI badge (the URL uses the owner from `gh repo view --json nameWithOwner`).
- Optional: a ruleset on `main` that requires a pull request and both `checks` jobs. Optional: push a deliberately failing test to a scratch branch once, watch CI fail, delete the branch.
- **Accept:** both CI jobs green on the pull request and again on `main` after the merge; `/verify` ends with `verify: PASS`.

#### Fix #2: CSV formula injection
Branch `fix/csv-formulas`. Claude reads the issue itself with `gh issue view 2`.
- A CSV cell is written with a leading `'` when it starts with `=`, `+`, `-`, `@`, a tab or a carriage return, unless the whole cell is a plain decimal number (`^-?\d+(\.\d+)?$`, such as a negative margin `-12.3`).
- Every CSV cell, CSV only. The terminal table is unchanged.
- **Tests:** a catalogue name `=HYPERLINK("http://example.com","x")` is written as `'=HYPERLINK("http://example.com","x")`; `+1`, `-1+2`, `@SUM(A1)` and a name starting with a tab get the prefix; `-12.3`, `686.95` and ordinary names do not.
- Commit `fix: neutralise spreadsheet formulas in the CSV export`, with `Fixes #2` in the message.
- **Accept:** CI green; the merge closes issue #2.

#### M8: UAE and Kuwait as data; issue #3
Branch `feat/m8-uae-kuwait`. Commits, in order:
1. `feat: add an espresso machine to the sample catalogue`: the product and the kettle fix from §6.1. With the M8 data, 36 of today's tests fail: about 20 places hard-code 12 products, and the rest check averages, SKU lists or the market list. Replace the hard-coded counts with one constant in `tests/helpers.py` (`SAMPLE_PRODUCT_COUNT = 13`). Add `tests/test_markets.py` with the KSA column of §7.9.1.
2. `feat: list Eid al-Fitr 2027 in the KSA calendar`: the three provisional days, and the KSA cells of §8.2.
3. `chore: add the /add-market skill`: `.claude/skills/add-market/SKILL.md`, and a line for it under "Project tools" in CLAUDE.md.
4. `/add-market UAE "United Arab Emirates"` → `feat: add the United Arab Emirates market`: the v0.1 fields of the UAE block (§6.2), worked example C (§7.8), the UAE column of §7.9.1 and the UAE cells of §8.2.
5. `/add-market KWT Kuwait` → `feat: add the Kuwait market`: the same, with worked example D.
6. `fix: keep the picked order time when switching markets`, with `Fixes #3`.

Commits 1, 2, 4 and 5 change only `data/raw/` and `tests/`. Commit 3 changes `.claude/` and CLAUDE.md. Commit 6 changes `app/` and `tests/`. Nothing in `src/` changes in M8.

Issue #3:
- **What happens today** (checked with AppTest on a three-market config, Streamlit 1.65): the date and time pickers have keys, so after the first run Streamlit keeps their values and ignores the new `value=` default. Switching from KSA to the UAE keeps "13:30" and reads it as 13:30 in Dubai, even if nobody touched the pickers.
- **Decision:** keep that behaviour, on purpose. The pickers hold a local date and time, read on the selected market's clock, exactly as the CLI reads `--ordered-at` without an offset. Make the code say so:
  - set `order_date` and `order_time` in `st.session_state` once per session (the opening time on the selected market's clock, to the minute), and stop passing `value=`;
  - help text: "Local time in the selected market ({timezone}). Switching markets keeps the date and time."
- **AppTest:** pick Thu 2026-10-15 13:30 in KSA: every delivery is Thu 2026-10-22. Switch to KWT: the pickers still say 13:30, the caption says Asia/Kuwait, and every delivery is Sun 2026-10-25, because 13:30 is after Kuwait's 13:00 cutoff. Switch to the UAE: Wed 2026-10-21.

Other tests: the config loads three markets; worked examples C and D exactly, with margins to 3 dp; all 39 cells of §7.9.1 through `price_product`; every cell of §8.2 through `estimate_delivery`; `--market UAE` prints AED with 2 decimals and `--market KWT` KWD with 3; an unknown market lists `KSA, KWT, UAE`; the market selector has three options (`test_app.py` line 180) and switching changes the currency header and prices.

- **Accept:** CI green; every v0.1 KSA number unchanged; `git diff --stat main` shows nothing under `src/`.

#### M9: compliance, typed attributes, format hook
Branch `feat/m9-compliance`. Commits, in order:
1. `chore: format Python files after each edit with a Claude Code hook`: `.claude/settings.json` and `.claude/hooks/format_python.py`, `tests/test_format_hook.py`, and a line for the hook under "Project tools" in CLAUDE.md. The hook test checks that it formats a messy `.py` file in a temporary project, leaves a `.md` file and a file outside the project alone, exits 2 with ruff's message on a syntax error, and ignores input that is not JSON. Then restart Claude Code and try it once: ask Claude to write `scratch.py` containing `x=1`, check it now says `x = 1`, delete it.
2. `feat: validate product attributes and category names`, with `Fixes #1`: `ProductAttributes`, `AttributeName` and `CategoryName` (§10.1).
   - **Tests:** a missing, unknown or non-boolean attribute is rejected; `"Fashion"` is rejected as a category and as an override key; `AttributeName` lists exactly the fields of `ProductAttributes`. Tests that build products with `attributes={}` switch to a shared `NO_ATTRIBUTES` helper.
3. `feat: screen products against each market's compliance rules`: the `compliance` blocks and fixtures (§6.2), `compliance.py`, `localise_and_summarise` screening first and returning `excluded`, the CLI moving to `localise_and_summarise` and printing what is not sold, and the dashboard metric and table (§7.6, §10.2).
   - **Config tests:** `compliance` missing → rejected; an unknown or duplicate banned attribute → rejected; an empty list → accepted.
   - **`screen_products`:** KSA excludes VAN (`contains_alcohol`) and GUM (`contains_pork`); the UAE excludes GUM only; KWT both. Both lists keep catalogue order. A product with two banned attributes lists both, in the market's order. An empty list excludes nothing.
   - **Pipeline:** for KSA, `localise_and_summarise` returns 11 items and 2 excluded, with the summary and the baseline over the same 11. An unknown market or a bad `duty_adjustment` fails exactly as before. `localise_catalogue` still prices what it is given.
   - **CLI:** KSA prints `Not sold in KSA (2):` after the table, with SKU, name and codes. The CSV has 11 rows and neither excluded SKU. The zero-VAT fixture market prints no such section.
   - **Dashboard:** the "Not sold in KSA" metric is 2 and the UAE's is 1; the table shows labels ("Contains pork"); a catalogue of only banned products shows "No product in the catalogue can be sold in KSA."; the scope caption says "All 11 products for sale in KSA; search filters the table only".
- **Accept:** CI green; 11 / 12 / 11 products for sale; the hook formats a file Claude edits.

#### M10: de minimis and the shipping model
Branch `feat/m10-de-minimis`. Commits, in order:
1. `chore: add the money-reviewer subagent`: `.claude/agents/money-reviewer.md`, and a line for it under "Project tools" in CLAUDE.md.
2. `feat: add parcel freight and de minimis rules to the market config`: models, data and fixtures (§6.2), and `tests/fixtures/de_minimis_boundary_config.json` (§7.8, example H). No price changes yet: apart from the new config-validation tests, the suite passes unchanged.
3. `feat: price direct parcels with de minimis`: `ShippingModel`, `pricing/customs.py`, `price_product(..., shipping)`, the new `PriceQuote` fields and `shipping` through the pipeline (§7.1, §7.7, §10.1).
4. `feat: show duty and the shipping model in the CLI and dashboard`: `--shipping`, the radio, the Duty column, the two CSV columns and the captions (§10.2).

Before opening the pull request: "Use the money-reviewer subagent to review this branch against main". Fix what it finds, then run `/code-review`.

- **Config tests:** the `de_minimis` key missing → rejected; `null` → accepted; a threshold ≤ 0, an unknown `applies` value or an unknown excluded attribute → rejected; `parcel_freight_per_kg_usd` missing or negative → rejected.
- **`de_minimis_applies`:** the six cells of example H, an excluded attribute, a `null` rule. Hypothesis: if it applies at some CIF, it applies at every lower CIF under the same rule.
- **`price_product`:**
  - examples E, F, G and H exactly, margins to 3 dp, and `duty_rate`, `duty_waived` and `shipping` as in the examples;
  - all 39 cells of §7.9.2;
  - consolidated prices equal §7.9.1 for every product and market (regression);
  - a waived product has the same shelf price at 0 and at 20 pp;
  - an unknown `shipping` raises `ValueError`;
  - Hypothesis: consolidated quotes never depend on the de minimis rule (any rule, or none, gives the same quote), and a higher duty adjustment never lowers a price in parcel mode either.
- **Display and CLI:** Duty shows "5.0%", "15.0%" (KSA fashion at +3 pp) and "waived"; `--shipping parcel` changes prices and the summary line ends with "Shipping: parcel"; `--shipping bulk` exits with code 2; the CSV header is as in §10.2.
- **Dashboard:** the radio switches prices; the Duty column shows "waived"; the price-change metric still compares against 0 pp in the same shipping model; the caption names the model.
- **Accept:** CI green; the money-reviewer's and `/code-review`'s findings resolved; every number in §7.8 and §7.9 holds.

#### Release v0.2.0
Branch `chore/release-0.2.0`.
- `pyproject.toml` version `0.2.0`, then `uv lock` so CI's lock check passes.
- README: the three markets, compliance, the shipping switch with one example from §7.9.3, CLI examples with `--market UAE --shipping parcel`, a fresh `docs/dashboard.png`.
- SPEC.md: delete the appendix that listed the files to create in v0.2 (every one of them now exists and is its own source of truth) and mark v0.2 done in §2.
- After the merge: `git tag -a v0.2.0 -m "v0.2.0: UAE, Kuwait, compliance, de minimis"` and `git push origin v0.2.0`.
- Releases: `gh release create v0.1.0 --title "v0.1.0: KSA end to end" --notes "..."` (deferred from v0.1), then `gh release create v0.2.0 --title "v0.2.0: three markets, compliance, de minimis" --generate-notes`, which writes the notes from the merged pull requests.

### 11.3 v0.3

The flow of §11.2 again: a branch per step, plan mode, commits, a pull request, both CI jobs green, merge. Before each pull request of M11, M12 and M13: "Use the money-reviewer subagent to review this branch against main", fix what it finds, then `/code-review`. M14: `/code-review` only.

Each milestone ends with a report that runs. Its sections must match Appendix A exactly, apart from the summary, which only lists the sections built so far.

#### M11: the report's foundation
Branch `feat/m11-report`. Commits, in order:
1. `docs: add the v0.3 spec`: this SPEC.md and the v0.3 CLAUDE.md.
2. `chore: point the money-reviewer at the report`: the two changes to `.claude/agents/money-reviewer.md` in Appendix B.
3. `feat: add the expansion report with markets side by side and what is not sold`:
   - `uv add jinja2`, which adds it to `pyproject.toml`; Streamlit already installs it, so the lock gains no package;
   - the `report` package (§10.3) with `MarketOverview` and `build_report`, the formatting and sentence rules of §9.3, and the template with the header, the summary, "Markets side by side", "Not sold" and the method notes;
   - the `report` CLI command (§9.6);
   - the template checks in `tests/test_architecture.py` (§9.4.1).
- **Figures:** for 2026-10-15 09:00 UTC, the three rows of §9.2.1 and the not-sold lists of §9.2.6. Markets come in config order. A naive `ordered_at` raises `ValueError`.
- **Text:**
  - money with thousands separators (`4144.95` → `4,144.95`, `312.95` with 3 minor units → `312.950`);
  - signs (`0.4124` → `+41.2%`; `-0.00049` → `0.0%`, never `-0.0%`);
  - list joins with 1, 2 and 3 items, "1 product" against "2 products", and `|` and line breaks in a product name;
  - both sentences of §9.3.2 item 1, and item 6, for the sample data and for each edge case: a market that sells nothing (left out of the price sentence, `-` in its row), no market selling anything, and nothing excluded anywhere.
- **Template:** the context holds only strings (walk it); a template that mentions `KSA` or `SAR`, or uses `|round`, fails the architecture test (test the guard on small samples, as the market-code guard is tested).
- **CLI:**
  - writes `outputs/GCC_EXPANSION_REPORT.md` by default and `--out` anywhere, creating the folder;
  - the file has `\n` line endings and no `\r`, on Windows too;
  - prints `Wrote the expansion report to <path>`;
  - an `--ordered-at` without an offset exits 2 with the message of §9.6;
  - `--out` pointing at the catalogue or config exits 2 and leaves the file alone;
  - an unreadable data file exits 1;
  - without `--ordered-at` it uses the injected `now`.
- **Accept:** CI green; `uv run python -m souqsort report --ordered-at 2026-10-15T09:00Z` writes a report whose "Markets side by side" and "Not sold" sections are Appendix A's, character for character.

#### M12: consolidated or parcel, and tariff exposure
Branch `feat/m12-parcels-tariffs`. Commits, in order:
1. `feat: compare consolidated imports with direct parcels in the report`: `ShippingComparison`, its section and its sentences.
2. `feat: show each market's tariff exposure in the report`: `TariffExposure`, its section and its sentence.
- **Figures:**
  - the 34 product rows: every price equals §7.9.1 (consolidated) and §7.9.2 (parcel), and every "waived" equals a `w` there;
  - the counts of §9.2.2;
  - the 18 cells of §9.2.3.
- **Text:**
  - the three rule sentences of §9.3.2 item 2: `below`, `at_or_below` with an exclusion, and none;
  - a rule excluding two attributes reads "except products containing alcohol or pork";
  - "Duty is waived on …" appears only for a market with a rule;
  - the tariff sentence with its semicolons.
- **Hypothesis:** for any market and model, the average change is never negative and never smaller for a bigger rise.
- **Accept:** CI green; the two sections are Appendix A's.

#### M13: how a price is built, pricing risks, the sample
Branch `feat/m13-build-up-risks`. Commits, in order:
1. `feat: show how one price is built in each market`: `SampleProduct`, `PriceBuildUp` and its section.
2. `feat: flag price endings that add more than 10%`: `price_ending_added`, `PricingRisk` and its section.
3. `docs: add the sample expansion report`: `docs/GCC_EXPANSION_REPORT.md`, written by the CLI for `2026-10-15T09:00Z`, and `tests/test_report_sample.py` (§9.5).
- **Build-up:**
  - the six columns of §9.2.4, with KSA's parcel rounding line 0.54;
  - "(waived)" exactly when `duty_waived`;
  - a property over every product, market and model: the four displayed components plus the rounding line equal the shelf price;
  - with no product sold everywhere, the sentence of §9.3.2 item 4 and no tables.
- **Risks:**
  - the two rows of §9.2.5;
  - `price_ending_added` on hand-built quotes: gross `1.00` with shelf `1.10` is exactly 10% and not a risk, `1.11` is;
  - with no risks, the "No price ending …" sentence and no table.
- **Accept:** CI green; `docs/GCC_EXPANSION_REPORT.md` is identical to Appendix A (extract the block and `diff` it once); the sample test passes on both CI jobs.

#### M14: dashboard download, README, `/release`
Branch `feat/m14-report-download`. Commits, in order:
1. `feat: download the expansion report from the dashboard`: the sidebar button of §9.6.
2. `docs: add the expansion report to the README`:
   - a section after "Sample run" with what the report covers, the `report` command, a link to `docs/GCC_EXPANSION_REPORT.md` and three of its findings (parcels in KSA, the 10 pp tariff rise, Kuwait's lip balm);
   - a retaken `docs/dashboard.png` with the v0.2 scenario (UAE, Direct parcel, +3 pp, 2026/10/15, 14:59), so the screenshot shows the button.
   - Status and the roadmap wait for the release.
3. `chore: add the /release skill`: `.claude/skills/release/SKILL.md` from Appendix B, and its line under "Project tools" in CLAUDE.md (Appendix B). Every file in Appendix B now exists, so delete that appendix in the same commit. Restart Claude Code afterwards so the skill loads.
- **AppTest:**
  - the sidebar has the button with its label, file name and help text;
  - Thu 2026-10-15 12:00 picked in KSA offers exactly the sample report. If AppTest cannot read the button's data, check instead that the app builds the report for 2026-10-15 09:00 UTC;
  - moving the slider, switching the shipping model or searching does not change the report;
  - switching to the UAE at the same picker time offers the report for 08:00 UTC (12:00 in Dubai);
  - the button is still there when the search matches nothing.
- **Accept:** CI green; the downloaded file opens as the sample report; `/release` is listed when typing `/` in a new session.

#### Release v0.3.0
In a fresh Claude Code session on an up-to-date `main`: `/release 0.3.0 "the expansion report"`. The skill:
1. makes the branch `chore/release-0.3.0`, bumps the version and runs `uv lock`;
2. marks v0.3 done in this spec's header and §2, and updates the README's Status and roadmap, then waits for your OK;
3. opens the pull request "Release v0.3.0" and waits for CI, then for your OK to merge;
4. merges, tags `v0.3.0` with the message "v0.3.0: the expansion report", and creates the GitHub release with notes generated from the pull requests merged since `v0.2.0`.

The sample report does not change: it names the data, not the version (§9.1).

- **Accept:** the release page lists the pull requests for M11 to M14 and the release; `v0.3.0` is an annotated tag on the merge commit.

## 12. Decisions log (turn into ADRs later)

### v0.1
- Decimal everywhere; strings in JSON.
- Round once, at the shelf price, with `ROUND_HALF_UP`.
- Charm pricing only rounds up.
- v0.1 passes all costs through to the customer (pass-through slider later).
- v0.1 uses the destination calendar only (two-leg later).
- No de minimis in v0.1 (added in v0.2).
- All market data is illustrative and labelled as such.

### v0.2
- CI runs on Ubuntu and Windows: the project is built on Windows, and most servers run Linux. Both must pass.
- Actions are pinned to commits with the version in a comment; Dependabot proposes updates monthly. CI uses the laptop's uv version, and `UV_LOCKED` fails the build on a stale `uv.lock`.
- Hypothesis's built-in `ci` profile is used as it is. It loads by itself on GitHub Actions and has no deadlines: shared runners are slow and uneven, and a deadline there fails for no reason. It runs fixed examples, so a red run points at the change; the laptop runs random ones.
- Ruff does not format Markdown: the code blocks in SPEC.md and the README are sketches for people, not code to run.
- Two non-negotiables are now enforced by tests: no floats in `src/`, and no market code in `src/` or `app/`.
- Product attributes are a fixed schema, so a typo in a market's rules fails when the config loads. Adding an attribute is then a code change, which is accepted.
- `compliance`, `de_minimis` and parcel freight are required fields. "Nothing banned" and "no de minimis" must be written out.
- A product a market does not allow is reported as not sold, never priced and never silently dropped (§3 rule 7).
- The shipping model defaults to consolidated, which keeps every v0.1 price. Parcel mode has its own freight rate, so the switch is a real trade-off, not a free discount. Delivery is the same in both models in v0.2.
- De minimis compares the full-precision CIF in the market currency, per one-item order, waives duty only and ignores the duty slider. KSA's rule is "below" (ZATCA: "less than SAR 1,000"); the UAE's is "at or below" (Dubai Customs: "not exceeding AED 1,000"), excluding alcohol; Kuwait has none.
- The UAE is modelled on Dubai Customs' rules.
- The 13th product is an espresso machine rather than a laptop: laptops are usually duty-free in the GCC under the WTO Information Technology Agreement, so a 5% duty on one would look wrong.
- Kuwait keeps the `0.950` charm ending although it adds up to 69% to cheap items: the distortion is a finding for the v0.3 report, not a bug.
- Issue #3: the pickers keep the picked local date and time when the market changes, as the CLI reads `--ordered-at` without an offset. The order's instant therefore moves with the market's timezone. Rejected alternative: keep the instant and change the picker values, which surprises the user and needs a callback and a new helper.
- Every market lists holidays up to the same date (2027-03-31), so delivery comparisons are fair. KSA gains Eid al-Fitr 2027 (provisional).
- The format hook only formats. `ruff check --fix` would delete an import that Claude adds in one edit and uses in the next.
- Pull requests merge with a merge commit, which keeps the small conventional commits and shows where each milestone begins and ends.
- The dashboard's Duty column is text, so one column can show a rate or "waived". It therefore sorts as text ("12.0%" before "5.0%"); price and margin still sort by value, and the CSV keeps the rate and the waiver in separate columns. Rejected alternative: a number column plus a waived column, which would be unticked for every product in the default consolidated mode.
- Market rules are a snapshot, not dated: every order is priced under the current config, whatever its date. VAT's `effective_from` is a record, not a switch, and an order dated before 2026-08-03 still gets the UAE waiver.

### v0.3
- The report covers every market and both shipping models for one order, at today's duty rates plus fixed tariff rises. The dashboard's slider, shipping model and search never change it, so a downloaded report never depends on how the page was left.
- It names its data (config version, FX date, catalogue version), not the SouqSort version, so a release leaves the sample unchanged.
- `report --ordered-at` needs a UTC offset. For `price`, a time without one is read on the market's clock, and the report has no single market.
- Numbers are formatted in Python and the template only places text. A template filter can never turn a `Decimal` into a `float`, and the no-market-codes rule extends to the template.
- Jinja2 becomes a direct dependency in M11. Streamlit already installs it, so the lock gains no package.
- "Above catalogue price" compares with `goods`, the catalogue price converted to the market currency, so it is free of currency and the markets compare directly. It includes VAT, so KSA's 15% shows.
- Markets side by side uses consolidated imports, the default. Parcels get their own section, with counts rather than an average. A mean over products would say KSA's parcels sit further above the catalogue price (+51.3% against +41.2%), because the kettlebell rises 47.5%, although parcels are cheaper for 6 of 11 products.
- The price build-up is in the report only, made from `PriceQuote`'s components. `PriceStep` traces and a dashboard waterfall stay in "Later".
- The build-up's rounding line absorbs display rounding so that every column adds up, and the method notes say so.
- Pricing risks flag a price ending that adds more than 10%, a named constant. With the sample data only Kuwait is flagged: the finding v0.2 kept for this report (§7.9.4).
- No AI summary in v0.3. The report's value is exact, reproducible figures. If a summary comes, it gets its own milestone, writing only from the report's figures and checked against them.
- No live demo in v0.3.
- Reports go to `outputs/` (gitignored) by default. `docs/GCC_EXPANSION_REPORT.md` is the one committed report, and a test keeps it current.
- Four milestones, split by report section, so each ends with a report that runs and a pull request small enough for both reviewers.
- `/release` turns the steps of Release v0.2.0 into one command. It stops for an OK before the merge, never pushes to `main` and never moves a tag.

## 13. Sources

Market data stays illustrative. These are the rules it is modelled on:
- ZATCA, customs for e-store customers (duty exemption under SAR 1,000, including shipping and insurance; VAT still due): https://zatca.gov.sa/en/RulesRegulations/Taxes/Pages/customs_individual/e-stores-customers.aspx
- Arab News, Saudi customs fee changes (SAR 15 declaration fee on e-store shipments up to SAR 1,000): https://www.arabnews.com/node/2570542/amp
- Khaleej Times, Dubai Customs exemption up to AED 1,000 from 2026-08-03, with its exclusions: https://www.khaleejtimes.com/business/dubai-customs-exempt-goods-import-duty-amendments
- Gulf Today, the same announcement: https://www.gulftoday.ae/news/2026/08/05/dubai-customs-exempts-e-commerce-shipments-up-to-dhs1000-from-customs-duties
- Goods Across Borders, Kuwait (no duty-free threshold for commercial parcels; 5% GCC common tariff): https://www.goodsacrossborders.com/importing/into/kuwait
- VATupdate, Kuwait leaves VAT out of its 2026–2030 fiscal plan: https://www.vatupdate.com/2026/07/24/kuwait-keeps-vat-off-the-table-no-adoption-in-the-2026-2030-fiscal-plan/

Tools:
- Claude Code docs: skills https://code.claude.com/docs/en/skills, hooks https://code.claude.com/docs/en/hooks, hooks guide https://code.claude.com/docs/en/hooks-guide, subagents https://code.claude.com/docs/en/sub-agents
- Jinja template designer documentation (whitespace control, filters): https://jinja.palletsprojects.com/templates
- Streamlit `st.download_button`: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button

## Appendix A: the sample report

`docs/GCC_EXPANSION_REPORT.md` for `ordered_at = 2026-10-15T09:00Z` over the sample data (§9.5). Everything between the fences, exactly; the file ends with a single newline after the last line.

````markdown
# GCC expansion report

An order placed on Thu 2026-10-15 at 09:00 UTC, priced in every market in the config with both shipping models. Built from market config 2026-10-01, FX rates as of 2026-10-01 and catalogue 2026-10-01.

> All market data is illustrative. Do not use it to quote real prices or delivery dates.

## Summary

- On average, shelf prices sit 24.7% above the catalogue price in UAE, 33.1% in KWT and 41.2% in KSA.
- For this order, delivery is on Thu 2026-10-22 in KSA, Wed 2026-10-21 in UAE and Thu 2026-10-22 in KWT.
- Direct parcels are cheaper than consolidated imports for 6 of 11 products in KSA, 5 of 12 in UAE and 0 of 11 in KWT.
- A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for direct parcels in KSA; 9.3% and 1.5% in UAE; and 7.6% and 9.4% in KWT.
- Wireless Noise-Cancelling Headphones (ELEC-HP-001) is the first product every market sells. Shipped as a direct parcel instead of a consolidated import, its price changes by -3.8% in KSA, -3.8% in UAE and +2.0% in KWT.
- The price ending adds more than 10.0% to 2 products: BEAU-LIP-040 in KWT (+68.5%) and GROC-TEA-060 in KWT (+20.0%).
- Out of 13 products, KSA cannot sell 2, UAE 1 and KWT 2.

## Markets side by side

On average, shelf prices sit 24.7% above the catalogue price in UAE, 33.1% in KWT and 41.2% in KSA. For this order, delivery is on Thu 2026-10-22 in KSA, Wed 2026-10-21 in UAE and Thu 2026-10-22 in KWT.

| Market | Currency | VAT | For sale | Not sold | Above catalogue price | Average margin | Ordered (local time) | Cut-off | Delivered |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| KSA (Saudi Arabia) | SAR | 15.0% | 11 | 2 | +41.2% | 64.6% | Thu 2026-10-15 12:00 | 14:00 | Thu 2026-10-22 |
| UAE (United Arab Emirates) | AED | 5.0% | 12 | 1 | +24.7% | 64.9% | Thu 2026-10-15 13:00 | 15:00 | Wed 2026-10-21 |
| KWT (Kuwait) | KWD | 0.0% | 11 | 2 | +33.1% | 66.6% | Thu 2026-10-15 12:00 | 13:00 | Thu 2026-10-22 |

## Consolidated or parcel

Direct parcels are cheaper than consolidated imports for 6 of 11 products in KSA, 5 of 12 in UAE and 0 of 11 in KWT.

### KSA (Saudi Arabia)

No duty on a parcel whose CIF is below 1,000.00 SAR. Parcels are cheaper for 6 of 11 products, dearer for 4 and unchanged for 1. Duty is waived on 10 of them.

| SKU | Product | Consolidated (SAR) | Direct parcel (SAR) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 686.95 | 660.95 | -3.8% | waived |
| ELEC-CHG-002 | 65W USB-C Charger | 184.95 | 179.95 | -2.7% | waived |
| FASH-BAG-014 | Leather Crossbody Bag | 594.95 | 546.95 | -8.1% | waived |
| FASH-SCF-015 | Silk Scarf | 293.95 | 264.95 | -9.9% | waived |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 593.95 | 875.95 | +47.5% | waived |
| HOME-KTL-030 | Electric Kettle 1.7 L | 237.95 | 249.95 | +5.0% | waived |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 4,144.95 | 4,344.95 | +4.8% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 16.95 | 15.95 | -5.9% | waived |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 111.95 | 108.95 | -2.7% | waived |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 340.95 | 340.95 | 0.0% | waived |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 34.95 | 37.95 | +8.6% | waived |

### UAE (United Arab Emirates)

No duty on a parcel whose CIF is at or below 1,000.00 AED, except products containing alcohol. Parcels are cheaper for 5 of 12 products, dearer for 5 and unchanged for 2. Duty is waived on 10 of them.

| SKU | Product | Consolidated (AED) | Direct parcel (AED) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 612.99 | 589.99 | -3.8% | waived |
| ELEC-CHG-002 | 65W USB-C Charger | 164.99 | 159.99 | -3.0% | waived |
| FASH-BAG-014 | Leather Crossbody Bag | 496.99 | 485.99 | -2.2% | waived |
| FASH-SCF-015 | Silk Scarf | 246.99 | 236.99 | -4.0% | waived |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 498.99 | 721.99 | +44.7% | waived |
| HOME-KTL-030 | Electric Kettle 1.7 L | 209.99 | 218.99 | +4.3% | waived |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 3,685.99 | 3,844.99 | +4.3% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 14.99 | 14.99 | 0.0% | waived |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 99.99 | 96.99 | -3.0% | waived |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 304.99 | 304.99 | 0.0% | waived |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 29.99 | 32.99 | +10.0% | waived |
| GROC-VAN-061 | Pure Vanilla Extract | 55.99 | 57.99 | +3.6% | 5.0% |

### KWT (Kuwait)

No de minimis rule, so every parcel pays duty. Parcels are cheaper for 0 of 11 products, dearer for 6 and unchanged for 5.

| SKU | Product | Consolidated (KWD) | Direct parcel (KWD) | Change | Parcel duty |
|---|---|---:|---:|---:|---|
| ELEC-HP-001 | Wireless Noise-Cancelling Headphones | 48.950 | 49.950 | +2.0% | 5.0% |
| ELEC-CHG-002 | 65W USB-C Charger | 13.950 | 13.950 | 0.0% | 5.0% |
| FASH-BAG-014 | Leather Crossbody Bag | 39.950 | 41.950 | +5.0% | 5.0% |
| FASH-SCF-015 | Silk Scarf | 19.950 | 19.950 | 0.0% | 5.0% |
| SPRT-KTB-020 | Cast Iron Kettlebell 16 kg | 44.950 | 70.950 | +57.8% | 5.0% |
| HOME-KTL-030 | Electric Kettle 1.7 L | 17.950 | 19.950 | +11.1% | 5.0% |
| HOME-ESP-031 | Bean-to-Cup Espresso Machine | 296.950 | 312.950 | +5.4% | 5.0% |
| BEAU-LIP-040 | Lip Balm | 1.950 | 1.950 | 0.0% | 5.0% |
| BEAU-SRM-041 | Vitamin C Serum 30 ml | 7.950 | 8.950 | +12.6% | 5.0% |
| DIGI-LIC-050 | Photo Editor Pro Licence (digital download) | 24.950 | 24.950 | 0.0% | 0.0% |
| GROC-TEA-060 | English Breakfast Tea, 80 bags | 2.950 | 2.950 | 0.0% | 5.0% |

## Tariff exposure

A 10 pp tariff rise lifts average prices by 9.0% for consolidated imports and 0.9% for direct parcels in KSA; 9.3% and 1.5% in UAE; and 7.6% and 9.4% in KWT.

| Market | Shipping model | +5 pp | +10 pp | +20 pp |
|---|---|---:|---:|---:|
| KSA | Consolidated import | +4.6% | +9.0% | +18.6% |
| KSA | Direct parcel | +0.4% | +0.9% | +1.7% |
| UAE | Consolidated import | +4.9% | +9.3% | +19.2% |
| UAE | Direct parcel | +0.8% | +1.5% | +3.2% |
| KWT | Consolidated import | +3.8% | +7.6% | +16.0% |
| KWT | Direct parcel | +6.3% | +9.4% | +17.7% |

## How a price is built

Wireless Noise-Cancelling Headphones (ELEC-HP-001) is the first product every market sells. Shipped as a direct parcel instead of a consolidated import, its price changes by -3.8% in KSA, -3.8% in UAE and +2.0% in KWT.

### KSA (SAR)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 562.46 | 562.46 |
| Freight | 5.91 | 11.81 |
| Duty | 28.42 | 0.00 (waived) |
| VAT | 89.52 | 86.14 |
| Rounding and price ending | 0.64 | 0.54 |
| **Shelf price** | **686.95** | **660.95** |

### UAE (AED)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 550.84 | 550.84 |
| Freight | 5.14 | 10.28 |
| Duty | 27.80 | 0.00 (waived) |
| VAT | 29.19 | 28.06 |
| Rounding and price ending | 0.02 | 0.81 |
| **Shelf price** | **612.99** | **589.99** |

### KWT (KWD)

| Step | Consolidated import | Direct parcel |
|---|---:|---:|
| Catalogue price, converted | 46.047 | 46.047 |
| Freight | 0.537 | 1.075 |
| Duty | 2.329 | 2.356 |
| VAT | 0.000 | 0.000 |
| Rounding and price ending | 0.037 | 0.472 |
| **Shelf price** | **48.950** | **49.950** |

## Pricing risks

The price ending adds more than 10.0% to 2 products: BEAU-LIP-040 in KWT (+68.5%) and GROC-TEA-060 in KWT (+20.0%).

| Market | SKU | Product | Before the price ending | Shelf price | Added |
|---|---|---|---:|---:|---:|
| KWT | BEAU-LIP-040 | Lip Balm | 1.157 | 1.950 | +68.5% |
| KWT | GROC-TEA-060 | English Breakfast Tea, 80 bags | 2.458 | 2.950 | +20.0% |

## Not sold

Out of 13 products, KSA cannot sell 2, UAE 1 and KWT 2.

| Market | SKU | Product | Reasons |
|---|---|---|---|
| KSA | GROC-VAN-061 | Pure Vanilla Extract | Contains alcohol |
| KSA | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |
| UAE | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |
| KWT | GROC-VAN-061 | Pure Vanilla Extract | Contains alcohol |
| KWT | GROC-GUM-062 | Gummy Bears (pork gelatine) | Contains pork |

## How these figures are made

- Each product is priced as a one-item order, and every cost is passed on to the customer.
- Prices use today's duty rates. A tariff rise adds percentage points to every duty rate.
- Above catalogue price compares the shelf price with the catalogue price converted at the config's FX rates, so it includes freight, duty, VAT and the price ending.
- Averages are unweighted means over the products a market sells.
- Price components are rounded for display, and the rounding line makes each column add up to the shelf price, which is exact.
- Markets side by side and pricing risks use consolidated imports, the default shipping model.
- Delivery dates are the same for both shipping models.
````

## Appendix B: files for v0.3

Copy these exactly, in the milestone each one names. Once a file exists it is its own source of truth, so M14 deletes this appendix once the last of them exists.

### `.claude/agents/money-reviewer.md` (M11): two changes

The `description` line becomes:

```yaml
description: Reviews SouqSort changes that touch money, pricing, FX, customs, de minimis, compliance, market data or the expansion report's figures against the project's money rules. Use after changing src/souqsort/pricing/, src/souqsort/report/, compliance.py, pipeline.py or data/raw/*.json, before /code-review.
```

"Read SPEC.md §3 and §7 first." becomes "Read SPEC.md §3 and §7 first, and §9 when the report changes." A tenth rule follows the ninth:

```markdown
10. The expansion report computes its figures from engine results in Decimal and rounds only when it formats them. Its template receives text only: no float, no arithmetic and no number formatting in the template. The same inputs give the same bytes.
```

### `.claude/skills/release/SKILL.md` (M14)

```markdown
---
name: release
description: Release a new SouqSort version through a release pull request, then tag it and publish the GitHub release. Runs only when invoked as /release.
argument-hint: "[VERSION] [title]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Edit Bash(git *) Bash(gh *) Bash(uv *)
---

Release SouqSort `$0` as "v$0: $1".

Rules:
- `$0` is a version such as `0.3.0`, higher than the latest tag. If it is not, or `$1` is empty, stop and tell me.
- Never push to `main`, and never move or delete a tag. Everything reaches `main` through the release pull request.
- Wait for my OK wherever a step says so.

Steps:
1. Check that the working tree is clean, then `git switch main` and `git pull --ff-only`. Find the previous tag with `git describe --tags --abbrev=0` and show it.
2. `git switch -c chore/release-$0`.
3. Set `version = "$0"` in `pyproject.toml` and run `uv lock`. Check that `git diff uv.lock` changes only SouqSort's own version.
4. In SPEC.md, mark this version done and tagged `v$0`, in the header and in §2. In the README, update Status and the roadmap for this version. Show me both diffs and wait for my OK.
5. Run `uv run --locked ruff format --check .`, `uv run --locked ruff check .`, `uv run --locked mypy src` and `uv run --locked pytest -q`. If one fails, stop and show it.
6. Commit `chore: release $0`, push with `git push -u origin chore/release-$0`, and open a pull request titled "Release v$0" with `gh pr create`.
7. Run `gh pr checks --watch`. When both CI jobs pass, show the pull request link and wait for my OK to merge.
8. `gh pr merge --merge --delete-branch`, then `git switch main` and `git pull --ff-only`.
9. `git tag -a v$0 -m "v$0: $1"`, then `git push origin v$0`.
10. `gh release create v$0 --verify-tag --title "v$0: $1" --generate-notes --notes-start-tag <the previous tag from step 1>`.
11. Show the release URL and the commit the tag points to.
```

### CLAUDE.md, under "Project tools" (M14)

```markdown
- `/release VERSION "title"` releases a version: a release pull request (version, `uv.lock`, SPEC.md and README), then, after CI and your OK, the merge, an annotated tag and the GitHub release. Only you can start it; Claude never runs it on its own.
```
