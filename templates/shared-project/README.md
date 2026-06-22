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
   cp ~/Claude/claude-config/templates/shared-project/CLAUDE.md.template ./CLAUDE.md
   cp ~/Claude/claude-config/templates/shared-project/README.md.template ./README.md
   cp ~/Claude/claude-config/templates/shared-project/AUDIT.md.template ./AUDIT.md
   # If using git-crypt with collaborators (recommended for shared private repos):
   cp ~/Claude/claude-config/templates/shared-project/SETUP.md.template ./SETUP.md
   ```

3. Edit each file. **Important**: every reference to your personal layer or other private repos must be removed before sharing. Use the AUDIT.md checklist.

4. (Optional) Set up git-crypt with a shared key — see [`docs/git-crypt-guide.md`](../../docs/git-crypt-guide.md) and the "共有 git-crypt 鍵パターン" section in `conventions/shared-repo.md`. **If using git-crypt, fill in `SETUP.md` (collaborator-facing setup walkthrough)** with this-repo specific values: encrypted backup path, local key path, plaintext test file. CLAUDE.md should keep only a 1-2 line pointer to SETUP.md (not the full walkthrough — auto-load cost). Both files must be at the repo root (NOT in `docs/` if you have `docs/**` git-crypt encrypted, otherwise un-unlocked collaborators can't read them — catch-22).

5. Create the GitHub private repo and invite collaborators:
   ```bash
   gh repo create <owner>/<your-shared-project> --private --source=. --push
   gh api repos/<owner>/<your-shared-project>/collaborators/<collab> -X PUT
   ```

## Critical rules

- **Layer dependency**: shared projects can depend on `claude-config` (public, layer 1) only. NOT on your personal layer (`<your>-prefs/`, layer 3). See `conventions/shared-repo.md` for the rationale.
- **Audit before sharing**: Always run AUDIT.md before adding the first collaborator.
- **Standalone**: The repo's CLAUDE.md must work for someone who has no personal layer of their own.
- **README build placement**: build/quickstart/deploy lives in **README** for public repos and any repo with readers who don't open CLAUDE.md (contributors, users, forkers); in **CLAUDE.md / SETUP.md** for private repos read only by CLAUDE.md-readers. The home is keyed per-instruction on "does a README-only reader need it?". See [`CONVENTIONS.md` §README の流儀](../../CONVENTIONS.md#readme-style).
