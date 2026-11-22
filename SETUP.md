# Setup on Windows (PowerShell)

Prerequisites: Git, uv, Docker Desktop (WSL 2 backend) and a `%UserProfile%\.wslconfig` that
contains `[wsl2]` and `memory=3GB` (then run `wsl --shutdown`).

```powershell
# 1. In the project folder (a clone of your GitHub repo, with these files extracted into it)
uv python install 3.12
uv sync --group dev

# 2. Local secrets file (never commit .env)
Copy-Item .env.example .env
# edit .env and add your keys; leave LLM_MODE=replay until Phase 2

# 3. Git identity: use your GitHub noreply address
git config user.name "Your Name"
git config user.email "ID+username@users.noreply.github.com"

# 4. Hooks (gitleaks, ruff, mypy, policy-doc sync)
uv run pre-commit install

# 5. Checks (all should pass at Phase 0)
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/render_policy.py --check
```

Editing the policy: change `policy/policy.yaml`, then run
`uv run python scripts/render_policy.py` to regenerate `docs/POLICY.md`. CI and the pre-commit
hook fail if they drift.

First commit (conventional commits):

```powershell
git add -A
git commit -m "chore: phase 0 scaffold, policy, taxonomy and ADRs"
git push
```

The first `pre-commit` run downloads hook environments (including Go for gitleaks) and can be
slow. Run `uv run pre-commit autoupdate` occasionally to refresh hook versions.
