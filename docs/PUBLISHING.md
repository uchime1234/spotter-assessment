# Publish after approval

This public candidate was created in a new local Git repository from a source-file allowlist. The private workspace had no usable Git repository, index, or history to inspect. The public branch contains only its new source-only history and synthetic data. If you later find another copy with restricted files committed, pause publication. Ignore rules do not remove tracked files or rewrite history. Create a new allowlisted repository with fresh history. If a contaminated commit has already reached a remote, coordinate cleanup with the host and rights holders before sharing it again.

Create an empty GitHub repository under your account without importing the private workspace or adding an initial commit. After approval, replace `OWNER` with the GitHub account or organization and run these commands from the public checkout. Commit reviewed changes in that checkout first.

```sh
git status --short
git diff --cached --name-only
git log --all --oneline
git log --all --name-only --format= | sort -u
git remote -v
git remote add origin https://github.com/OWNER/spotter-assessment.git
git push --set-upstream origin main
```

On Windows PowerShell, use `Sort-Object -Unique` in place of `sort -u`. If `origin` is already configured, verify its URL and skip the remote-add command.

The status and staged diff should be empty. Review every path in history before adding the remote. The only CSVs should be `fixtures/synthetic-prices.csv` and `fixtures/synthetic-stations.csv`. Use a new empty remote and pause if its history already contains commits. No push or upload is part of local preparation.
