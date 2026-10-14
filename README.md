# SouqSort

[![CI](https://github.com/yazanlouid/souqsort/actions/workflows/ci.yml/badge.svg)](https://github.com/yazanlouid/souqsort/actions/workflows/ci.yml)

SouqSort is a localisation and pricing engine for a UK-based retailer launching its catalogue in the
GCC. It turns a global catalogue priced in USD/GBP into market-ready shelf prices (FX, freight,
duty, VAT, rounding and charm endings), margins and delivery dates. It is built for an expansion
director who picks a market, moves a tariff slider and sees what happens to prices, margins and
delivery promises, in a Streamlit dashboard or from the command line. Saudi Arabia (KSA) is live
today; the UAE and Kuwait come next.

> [!IMPORTANT]
> **All market data is illustrative.** FX rates, VAT and duty rates, freight costs, holidays and the
> product catalogue are sample values written for this demo. Do not use them to quote real prices or
> delivery dates.

![SouqSort dashboard: KSA prices, margins and delivery dates with a +3 pp duty adjustment](docs/dashboard.png)

## Sample run

The same scenario as the screenshot: KSA, duty up 3 percentage points, ordered on Thursday
15 October 2026 at 13:59 Riyadh time.

```console
$ uv run python -m souqsort price --market KSA --duty-adjust 3 --ordered-at 2026-10-15T13:59+03:00
Market: KSA (Saudi Arabia)   Ordered at: 2026-10-15 13:59 Asia/Riyadh   Duty adjustment: +3 pp

SKU           Name                                         Shelf price (SAR)  Margin %  Delivery    Flags
------------  -------------------------------------------  -----------------  --------  ----------  -------------------
ELEC-HP-001   Wireless Noise-Cancelling Headphones                    705.95     58.7%  2026-10-22  -
ELEC-CHG-002  65W USB-C Charger                                       190.95     64.7%  2026-10-22  -
FASH-BAG-014  Leather Crossbody Bag                                   610.95     64.7%  2026-10-22  missing_arabic_name
FASH-SCF-015  Silk Scarf                                              301.95     73.3%  2026-10-22  -
SPRT-KTB-020  Cast Iron Kettlebell 16 kg                              610.95     64.5%  2026-10-22  -
HOME-KTL-030  Electric Kettle 1.7 L                                   243.95     61.7%  2026-10-22  -
BEAU-LIP-040  Lip Balm                                                 16.95     73.3%  2026-10-22  -
BEAU-SRM-041  Vitamin C Serum 30 ml                                   114.95     71.8%  2026-10-22  -
DIGI-LIC-050  Photo Editor Pro Licence (digital download)             350.95     70.0%  2026-10-22  -
GROC-TEA-060  English Breakfast Tea, 80 bags                           34.95     66.3%  2026-10-22  missing_arabic_name
GROC-VAN-061  Pure Vanilla Extract                                     63.95     68.6%  2026-10-22  -
GROC-GUM-062  Gummy Bears (pork gelatine)                              22.95     71.7%  2026-10-22  -
```

The order lands one minute before the 14:00 cut-off, so it ships the same day and arrives five
business days later, skipping the Friday–Saturday weekend. `--ordered-at` is fixed here so the
output is reproducible; without it the CLI uses the current time.

## What makes it tricky

- **Money.** `Decimal` throughout, rounded once with `ROUND_HALF_UP`: 0.0005 at 3 decimals gives
  0.001, where banker's rounding would give 0.000. Charm endings never lower a price
  (686.96 becomes 687.95, not 686.95). KWD uses 3 decimals, not 2.
- **Tax order.** Duty is charged on CIF (goods + freight); VAT is charged on CIF + duty.
- **FX order.** Multiply before dividing. Dividing first turned an exact 0.075 into 0.07499…97,
  which rounds to 0.07 instead of 0.08.
- **Delivery.** Orders are converted to market time first: Thursday 22:30 UTC is already Friday,
  the weekend, in Riyadh. The cut-off is compared as a moment in time, so a clock change can't make
  a later order arrive earlier.
- **Errors.** A product that can't be priced fails with a message naming its SKU; unexpected bugs
  keep their traceback.
- **Tests.** 600+ tests, including Hypothesis property tests, headless dashboard tests (Streamlit's
  `AppTest`) and architecture tests that keep the clock and pandas out of the engine.

## Install and run

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.12 if you don't have it.

```sh
git clone https://github.com/yazanlouid/souqsort.git
cd souqsort
uv sync
```

| To | Run |
|---|---|
| Price a market from the CLI | `uv run python -m souqsort price --market KSA` |
| Open the dashboard | `uv run streamlit run app/streamlit_app.py` |
| Run the tests | `uv run pytest` |
| Lint and type-check | `uv run ruff check .` and `uv run mypy src` |

CLI options for `price`:

| Option | Meaning |
|---|---|
| `--market CODE` | Market code from the config (required). |
| `--duty-adjust POINTS` | Whole percentage points added to every duty rate, 0 to 20. Default 0. |
| `--ordered-at ISO` | Order date and time, e.g. `2026-10-15T20:59Z`. Without an offset it is read as local time in the market. Default: now. |
| `--csv PATH` | Also write the rows to a CSV file. |

## Design rules

- **Decimal money.** Money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are
  strings, and a number where a string belongs is rejected when the file is loaded.
- **Round once.** Every step keeps full precision. The only rounding is at the shelf price, with
  `ROUND_HALF_UP` to the currency's minor units; the charm ending then only ever moves a price up.
- **Markets as config.** A market is an entry in `data/raw/gcc_config.json`: currency, VAT, duty
  rates, weekend, holidays, cut-off, freight. No code branches on a market code.
- **No clock in the engine.** The engine never reads the current time; it is always passed a
  timezone-aware `ordered_at`. Only the entry points read the clock: the CLI, through an injectable
  `now` callable, and the dashboard, for its picker defaults. Every result is reproducible and
  testable.

The full rules, with worked examples, are in [SPEC.md](SPEC.md).

## How it was built

- **Spec first.** [SPEC.md](SPEC.md) set the rules, worked examples and acceptance tests before any
  code.
- **Test-first milestones.** Each milestone was planned and built test-first with
  [Claude Code](https://claude.com/claude-code).
- **Independent review.** The work was reviewed by an independent AI code review. I triaged every
  finding; deferred items are tracked as
  [GitHub issues](https://github.com/yazanlouid/souqsort/issues).

## Status

**v0.1.0: Saudi Arabia (KSA) end to end.** Catalogue and config validation, landed-cost pricing with
margins, delivery estimates, the CLI and the dashboard.

Roadmap:

- **v0.2:** the UAE and Kuwait, added through config only; compliance rules (banned product
  attributes); de minimis thresholds.
- **v0.3:** a `GCC_EXPANSION_REPORT.md` generated from a template, with a download button in the
  dashboard.
