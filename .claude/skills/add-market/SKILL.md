---
name: add-market
description: Add a market to SouqSort as config data only, with tests for its worked examples. Runs only when invoked as /add-market.
argument-hint: "[CODE] [Name]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash(uv run *) Bash(git diff *) Bash(git status *)
---

Add market `$0` ("$1") to SouqSort.

Rules:
- Markets are data. Change only `data/raw/gcc_config.json` and files under `tests/`. Never edit `src/` or `app/`. If the market cannot be expressed in the current config schema, stop and tell me what is missing instead of changing code.
- Take every value from SPEC.md if it specifies this market. Otherwise ask me for all missing values in one message. Never invent a tax rate, duty rate, threshold, exchange rate or holiday.
- Money, rates and weights are JSON strings. Holidays that depend on the moon are `"provisional": true`.
- Fill in every field the config schema requires, including compliance and customs rules if the schema has them.

Steps:
1. Read SPEC.md (§6.2, §7.8, §7.9, §8.2 and anything else about `$0`) and the current config.
2. Show me the market's JSON block and wait for my OK before writing it.
3. Add the block. If its currency is not in `fx.per_usd`, stop and ask me for the rate.
4. Show the market working: `uv run python -m souqsort price --market $0 --ordered-at 2026-10-15T10:30Z`.
5. In `tests/test_markets.py`, add for `$0`: the config loads it; its worked example from SPEC.md (shelf price exactly, margin to 3 dp); its column of the price list; its delivery examples.
6. Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src` and `uv run pytest -q`, and show the results.
7. Show `git diff --stat`. It must list only `data/raw/gcc_config.json` and files under `tests/`.
8. Propose the commit message `feat: add the $1 market` and wait for my OK.
