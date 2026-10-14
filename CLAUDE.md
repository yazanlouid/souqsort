# SouqSort

GCC (KSA, UAE, Kuwait) e-commerce localisation and pricing engine with a Streamlit dashboard.
The full spec is in SPEC.md. Read the milestone you're working on (SPEC.md §10) before starting.

## Commands
- Install / sync dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one test file: `uv run pytest tests/test_money.py -q`
- Lint and auto-fix: `uv run ruff check . --fix`
- Format: `uv run ruff format .` (CI only checks: `uv run ruff format --check .`)
- Type-check: `uv run mypy src`
- CLI: `uv run python -m souqsort price --market KSA`
- Dashboard: `uv run streamlit run app/streamlit_app.py`

Always run Python through `uv run`. Never use `pip install` or a conda environment for this project.

## Non-negotiables
- IMPORTANT: money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are strings.
- Keep full precision; round once, at the shelf price, with `ROUND_HALF_UP` to the currency's minor units.
- `app/` holds no business logic. Streamlit only calls `souqsort` functions and displays results.
- Markets are data in `data/raw/gcc_config.json`, including their compliance, customs and de minimis rules. Never branch on a market code (no `if market == "KSA"`).
- No code in `src/` reads the clock (`datetime.now()`, `date.today()`) except the CLI entry point in `src/souqsort/cli.py`, which defaults `--ordered-at` to now through an injectable `now` callable. Everything else is passed a timezone-aware `ordered_at`.
- Engine functions return result objects (e.g. `PriceQuote`), not bare numbers.
- A product that a market does not allow is never priced for that market and never silently dropped. It is reported as not sold, with the reason.

## Workflow
- One milestone from SPEC.md at a time, on the branch SPEC.md §10 names for it. Never commit to `main` directly.
- Write or update the tests first, then implement.
- A task is done only when all four checks pass: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src` and `uv run pytest`. Show the output.
- Don't change code outside the current milestone without asking.
- If the spec is ambiguous, ask instead of guessing.
- Small commits with conventional messages (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `ci:`). Every commit leaves the suite green.
- Don't push, open a pull request or merge unless asked. A milestone reaches `main` through a pull request, and only when both CI jobs (Ubuntu and Windows) are green.

## Project tools
- `/verify` runs the same four checks as CI, each through `uv run --locked`, and ends with `verify: PASS` or `verify: FAIL (...)`.
- `/add-market CODE "Name"` adds a market as data only (`data/raw/gcc_config.json` and `tests/`), with tests for its worked example, price column and delivery cells. Only you can start it; Claude never runs it on its own.

## Environment
- Windows laptop. Claude Code runs commands through Git Bash; the commands above work in Git Bash and PowerShell.
- `zoneinfo` needs the `tzdata` package on Windows (it's a project dependency).
- The GitHub CLI (`gh`) is installed and signed in.
