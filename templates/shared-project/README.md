# Shared Project Templates

Skeleton files for bootstrapping a new shared-project layer (layer 2 in the four-layer architecture).

A **shared project** is a private repo that you collaborate on with a small team — e.g. an admin or coordination repo, a research collaboration, etc. Unlike your personal layer (layer 3, only you), a shared project has multiple humans editing it.

See [`docs/personal-layer.md`](../../docs/personal-layer.md) for the layer model and [`conventions/shared-repo.md`](../../conventions/shared-repo.md) for the operational rules.

## How to use

1. Create the new repo:
   ```bash
   mkdir -p ~/Claude/<your-shared-project>
   cd ~/Claude/<your-shared-project>
   git init
   ```

2. Copy templates:
   ```bash
   cp ~/Claude/claude-config/templates/shared-project/AGENTS.md.template ./AGENTS.md
   cp ~/Claude/claude-config/templates/shared-project/CLAUDE.md.template ./CLAUDE.md
   cp ~/Claude/claude-config/templates/shared-project/README.md.template ./README.md
   cp ~/Claude/claude-config/templates/shared-project/AUDIT.md.template ./AUDIT.md
   # If using git-crypt with collaborators (recommended for shared private repos):
   cp ~/Claude/claude-config/templates/shared-project/SETUP.md.template ./SETUP.md
   ```

3. Edit each file. **Important**: every reference to your personal layer or other private repos must be removed before sharing. Use the AUDIT.md checklist.

4. (Optional) Set up git-crypt with a shared key — see [`docs/git-crypt-guide.md`](../../docs/git-crypt-guide.md) and the "共有 git-crypt 鍵パターン" section in `conventions/shared-repo.md`. **If using git-crypt, fill in `SETUP.md` (collaborator-facing setup walkthrough)** with this-repo specific values: encrypted backup path, local key path, plaintext test file. CLAUDE.md should keep only a 1-2 line pointer to SETUP.md (not the full walkthrough — auto-load cost). Both files must be at the repo root (NOT in `docs/` if you have `docs/**` git-crypt encrypted, otherwise un-unlocked collaborators can't read them — catch-22).

5. (If the project builds PDFs) **Do not commit the built PDFs** — each version is stored whole in history (no delta), see [`conventions/repo-history-growth.md`](../../conventions/repo-history-growth.md). Install the push-triggered publisher instead: `python3 ~/Claude/claude-config/scripts/install-pdf-publish.py install . --dest <shared-folder> --doc '<doc>.tex' --build '<cmd>'`. It vendors [`pdf-publish/`](pdf-publish/) into `tools/pdf-publish/`, ignores the built PDFs, and installs a pre-push hook that builds (if stale) and copies the pushed documents' PDFs into a shared Dropbox folder in the background. Each clone runs `sh tools/pdf-publish/install-hook.sh` once.

6. (If collaborators need per-person setup — their own tokens, tools, a section to read first) **Let the repo check it at session start** instead of writing it in the invitation: `python3 ~/Claude/claude-config/scripts/install-collaborator-check.py install . --item '<line>' ...`. It vendors [`collaborator-check/`](collaborator-check/) into `tools/collaborator-check/`, writes `.collaborator-check.conf`, and adds a project SessionStart hook to `.claude/settings.json` (and un-ignores it in `.gitignore`). Missing items are reported with how to fix them; nothing is printed once everything is in place. See [`conventions/shared-repo.md#collaborator-check`](../../conventions/shared-repo.md#collaborator-check). Converting an existing owner-only repo instead of starting a new one: [`#convert-owner-repo-to-shared`](../../conventions/shared-repo.md#convert-owner-repo-to-shared).

   - **If the project runs computations in Python**, add the Python entry point in the same call: `--item 'python tools/py -- <purpose>' --python-version 3.13`. It vendors [`python-env/py`](python-env/py) into `tools/py`, writes `.python-version` (the version the authors verified with), ignores `.venv/`, and makes the session-start check report only what needs a human (no interpreter of the declared version on this machine). `tools/py` creates the venv on first use, follows `requirements.txt`, and stops with install instructions instead of silently building a venv on another Python. Scripts call `tools/py`, never `.venv/bin/python`. Check the declaration against the pinned requirements with `python3 ~/Claude/claude-config/scripts/python-pin-floor.py requirements.txt`. `tools/py` runs under bash on macOS, Linux, WSL and Windows (Git Bash); what it picks and what it advises on each environment is the table in [`conventions/python-env.md#python-env-environments`](../../conventions/python-env.md#python-env-environments). See [`conventions/python-env.md`](../../conventions/python-env.md).

7. Create the GitHub private repo and invite collaborators:
   ```bash
   gh repo create <owner>/<your-shared-project> --private --source=. --push
   gh api repos/<owner>/<your-shared-project>/collaborators/<collab> -X PUT
   ```

## Critical rules

- **Layer dependency**: shared projects can depend on `claude-config` (public, layer 1) only. NOT on your personal layer (`<your>-prefs/`, layer 3). See `conventions/shared-repo.md` for the rationale.
- **Audit before sharing**: Always run AUDIT.md before adding the first collaborator.
- **Deterministic agent entry point**: Keep a tracked, non-empty, ordinary root `AGENTS.md`; it is a thin dispatcher to `CLAUDE.md` and `SESSION.md`, not a second rule corpus.
- **Standalone**: The repo's AGENTS.md and CLAUDE.md must work for someone who has no personal layer of their own.
- **README build placement**: the source of truth for build/quickstart/deploy is **CLAUDE.md / SETUP.md** in every repo. Public repos and any repo with readers who don't open CLAUDE.md (contributors, users, forkers) also carry a user-facing copy of those commands in **README**; change both in the same commit. Whether an instruction is copied into README is keyed per-instruction on "does a README-only reader need it?". See [`CONVENTIONS.md` §README の流儀](../../CONVENTIONS.md#readme-style).
