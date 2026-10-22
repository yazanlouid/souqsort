---
name: release
description: Release a new SouqSort version through a release pull request, then tag it and publish the GitHub release. Runs only when invoked as /release.
argument-hint: "[VERSION] [title]"
disable-model-invocation: true
allowed-tools: Read Grep Glob Edit Bash(git status --porcelain) Bash(git switch *) Bash(git pull --ff-only) Bash(git describe --tags --abbrev=0) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git rev-parse *) Bash(uv lock) Bash(uv run --locked *) Bash(gh pr create *) Bash(gh pr checks *) Bash(gh pr view *) Bash(gh release create *) Bash(gh release view *)
---

Release SouqSort `$0` as "v$0: $1".

Rules:
- `$0` is a version such as `0.3.0`, higher than the latest tag. If it is not, or `$1` is empty, stop and tell me.
- Never push to `main`, and never move or delete a tag. Everything reaches `main` through the release pull request.
- Wait for my OK wherever a step says so.
- `git push`, `git tag` and `gh pr merge` are not pre-approved, because a pattern cannot rule out a flag such as `--force`, so each asks me first. Run them exactly as the steps give them.

Steps:
1. Check that `git status --porcelain` prints nothing, then `git switch main` and `git pull --ff-only`. Find the previous tag with `git describe --tags --abbrev=0` and show it. Compare `$0` with it, number by number (`0.10.0` is higher than `0.9.0`); if `$0` is not higher, stop and tell me before creating anything.
2. `git switch -c chore/release-$0`.
3. Set `version = "$0"` in `pyproject.toml` and run `uv lock`. Check that `git diff uv.lock` changes only SouqSort's own version.
4. In SPEC.md, mark this version done and tagged `v$0`, in the header and in §2. In the README, update Status and the roadmap for this version. Show me both diffs and wait for my OK.
5. Run `uv run --locked ruff format --check .`, `uv run --locked ruff check .`, `uv run --locked mypy src` and `uv run --locked pytest -q`. If one fails, stop and show it.
6. `git add pyproject.toml uv.lock SPEC.md README.md`, commit `chore: release $0`, push with `git push -u origin chore/release-$0`, and open a pull request titled "Release v$0" with `gh pr create`. Note its number.
7. Run `gh pr checks <number> --watch`. When both CI jobs pass, show the pull request link and wait for my OK to merge.
8. `gh pr merge <number> --merge --delete-branch`, then `git switch main` and `git pull --ff-only`.
9. Find the pull request's merge commit with `gh pr view <number> --json mergeCommit --jq .mergeCommit.oid`. Tag that commit, not whatever `main` points to now: `git tag -a v$0 <merge commit> -m "v$0: $1"`, then `git push origin v$0`.
10. `gh release create v$0 --verify-tag --title "v$0: $1" --generate-notes --notes-start-tag <the previous tag from step 1>`.
11. Show the release URL (`gh release view v$0 --json url --jq .url`) and the commit the tag points to (`git rev-parse "v$0^{commit}"`), which must be the merge commit from step 9.
