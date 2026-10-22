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
