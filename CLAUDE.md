# SouqSort

GCC (KSA, UAE, Kuwait) e-commerce localisation and pricing engine for single products and whole orders, with a Streamlit dashboard and an expansion report.
The full spec is in SPEC.md. Read the milestone you're working on (SPEC.md §11) before starting.

## Commands
- Install / sync dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one test file: `uv run pytest tests/test_money.py -q`
- Lint and auto-fix: `uv run ruff check . --fix`
- Format: `uv run ruff format .` (CI only checks: `uv run ruff format --check .`)
- Type-check: `uv run mypy src`
- CLI: `uv run python -m souqsort price --market KSA`
- Order: `uv run python -m souqsort order --market KSA --sample headphones-and-bag` (or `--item SKU[:QTY]`, repeated)
- Report: `uv run python -m souqsort report` (writes `outputs/GCC_EXPANSION_REPORT.md`; `--ordered-at` needs a UTC offset)
- Regenerate the sample report: `uv run python -m souqsort report --ordered-at 2026-10-15T09:00Z --out docs/GCC_EXPANSION_REPORT.md`
- Dashboard: `uv run streamlit run app/streamlit_app.py`

Always run Python through `uv run`. Never use `pip install` or a conda environment for this project.

## Non-negotiables
- IMPORTANT: money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are strings.
- Keep full precision; round once, at the shelf price, with `ROUND_HALF_UP` to the currency's minor units. An amount an order adds at checkout is rounded once too, with no price ending; an order's totals are exact sums.
- `app/` holds no business logic. Streamlit only calls `souqsort` functions and displays results.
- Markets are data in `data/raw/gcc_config.json`, including their compliance, customs, de minimis and parcel fee rules. Never branch on a market code (no `if market == "KSA"`).
- No code in `src/` reads the clock (`datetime.now()`, `date.today()`) except the CLI entry point in `src/souqsort/cli.py`, which defaults `--ordered-at` to now through an injectable `now` callable. Everything else is passed a timezone-aware `ordered_at`.
- Engine functions return result objects (e.g. `PriceQuote`), not bare numbers.
- A product that a market does not allow is never priced for that market and never silently dropped. It is reported as not sold, with the reason.
- The expansion report is a pure function of the catalogue, the config, the sample orders and the order time: the same inputs give the same bytes on every OS. Its template only places text; every number is formatted in Python from `Decimal`.

## Workflow
- One milestone from SPEC.md at a time, on the branch SPEC.md §11 names for it. Never commit to `main` directly.
- Write or update the tests first, then implement.
- A task is done only when all four checks pass: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src` and `uv run pytest`. Show the output.
- Don't change code outside the current milestone without asking.
- If the spec is ambiguous, ask instead of guessing.
- Small commits with conventional messages (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `ci:`). Every commit leaves the suite green.
- Don't push, open a pull request or merge unless asked. A milestone reaches `main` through a pull request, and only when both CI jobs (Ubuntu and Windows) are green.

## Project tools
- `/verify` runs the same four checks as CI, each through `uv run --locked`, and ends with `verify: PASS` or `verify: FAIL (...)`.
- `/add-market CODE "Name"` adds a market as data only (`data/raw/gcc_config.json` and `tests/`), with tests for its worked example, price column and delivery cells. Only you can start it; Claude never runs it on its own.
- `/release VERSION "title"` releases a version: a release pull request (version, `uv.lock`, SPEC.md and README), then, after CI and your OK, the merge, an annotated tag and the GitHub release. Only you can start it; Claude never runs it on its own.
- A `PostToolUse` hook (`.claude/settings.json` → `.claude/hooks/format_python.py`) runs `ruff format` on each `.py` file Claude writes or edits inside the project. It only formats, never lints. On a syntax error it exits 2 with ruff's message and the edit stands.
- The `money-reviewer` subagent (`.claude/agents/money-reviewer.md`) checks a branch against the money rules in SPEC.md §3 and §7 (and §9 for the report): Decimal only, one rounding, FX, duty and VAT bases, de minimis, orders and checkout lines, compliance, no market codes, no clock. It reads and runs the tests but never edits. Use it after changing `src/souqsort/pricing/`, `src/souqsort/report/`, `compliance.py`, `pipeline.py`, `orders.py` or `data/raw/*.json`, before `/code-review`.

## Environment
- Windows laptop. Claude Code runs commands through Git Bash; the commands above work in Git Bash and PowerShell.
- `zoneinfo` needs the `tzdata` package on Windows (it's a project dependency).
- The GitHub CLI (`gh`) is installed and signed in.
- Git Bash rewrites an argument that starts with / as a Windows path; prefix the command with MSYS_NO_PATHCONV=1 when an argument must start with / (an issue title that names a slash command, for example).
