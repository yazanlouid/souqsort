# SouqSort

GCC (KSA, UAE, Kuwait) e-commerce localisation and pricing engine with a Streamlit dashboard.
The full spec is in SPEC.md. Read the milestone you're working on before starting.

## Commands
- Install / sync dependencies: `uv sync`
- Run all tests: `uv run pytest`
- Run one test file: `uv run pytest tests/test_money.py -q`
- Lint and auto-fix: `uv run ruff check . --fix`
- Format: `uv run ruff format .`
- Type-check: `uv run mypy src`
- CLI: `uv run python -m souqsort price --market KSA`
- Dashboard: `uv run streamlit run app/streamlit_app.py`

Always run Python through `uv run`. Never use `pip install` or a conda environment for this project.

## Non-negotiables
- IMPORTANT: money, rates and weights are `decimal.Decimal`, never `float`. In JSON they are strings.
- Keep full precision; round once, at the shelf price, with `ROUND_HALF_UP` to the currency's minor units.
- `app/` holds no business logic. Streamlit only calls `souqsort` functions and displays results.
- Markets are data in `data/raw/gcc_config.json`. Never branch on a market code (no `if market == "KSA"`).
- Code in `src/` never reads the clock (`datetime.now()`, `date.today()`). Pass a timezone-aware `ordered_at` in.
- Engine functions return result objects (e.g. `PriceQuote`), not bare numbers.

## Workflow
- One milestone from SPEC.md at a time. Write or update the tests first, then implement.
- A task is done only when `uv run pytest`, `uv run ruff check .` and `uv run mypy src` all pass. Show the output.
- Don't change code outside the current milestone without asking.
- If the spec is ambiguous, ask instead of guessing.
- Small commits with conventional messages (`feat:`, `fix:`, `test:`, `chore:`, `docs:`). Don't push unless asked.

## Environment
- Windows laptop. Claude Code runs commands through Git Bash; the commands above work in Git Bash and PowerShell.
- `zoneinfo` needs the `tzdata` package on Windows (it's a project dependency).
