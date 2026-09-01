# Personal Layer Templates

Skeleton files for bootstrapping your own personal layer (layer 3 in the four-layer architecture).

See [`docs/personal-layer.md`](../../docs/personal-layer.md) for the conceptual overview.

## How to use

1. Pick a directory next to claude-config:
   ```bash
   mkdir -p ~/Claude/my-prefs
   cd ~/Claude/my-prefs
   ```

2. Drop the marker file (zero bytes):
   ```bash
   touch .claude-personal-layer
   ```

3. Copy the templates you want into your personal layer directory:
   ```bash
   cp ~/Claude/claude-config/templates/personal-layer/CLAUDE.md.template ./CLAUDE.md
   cp ~/Claude/claude-config/templates/personal-layer/repos.md.template ./repos.md
   cp ~/Claude/claude-config/templates/personal-layer/shared-project-keys.md.template ./shared-project-keys.md
   cp ~/Claude/claude-config/templates/personal-layer/user-profile.md.template ./user-profile.md
   mkdir -p codex
   cp ~/Claude/claude-config/templates/personal-layer/codex/AGENTS.md.template ./codex/AGENTS.md
   # optional: only if you use Dropbox-shared PDF folders (see conventions/dropbox-refs.md)
   cp ~/Claude/claude-config/templates/personal-layer/dropbox-collabs.yaml.template ./dropbox-collabs.yaml
   ```

4. Edit each file to fill in your information. The templates are intentionally minimal — add or remove sections to suit your workflow.

5. Optionally make it a private git repo for cross-machine sync:
   ```bash
   git init
   gh repo create my-prefs --private --source=. --push
   ```

6. Re-run claude-config setup.sh so the symlink at `~/Claude/CLAUDE.md` is updated:
   ```bash
   ~/Claude/claude-config/setup.sh
   ```

7. If you use Codex, edit the short `codex/AGENTS.md` private overlay, then
   explicitly bind this personal layer on every machine after cloning
   `claude-config`:
   ```bash
   ~/Claude/claude-config/scripts/setup-codex.sh --configure-safe-local --personal-layer "$(pwd)"
   ```
   This creates only that machine's layer-4 links, composite, and Hook trust
   state. The composite reads the public layer-1 source plus this short private
   overlay; it does not ingest the full `CLAUDE.md`. The marked layer must be
   explicitly supplied—there is no discovery. Keep the cross-machine bootstrap
   rule or command in this personal layer (layer 3), but never commit or link
the actual `~/.codex` directory into it. A safe managed `post-merge`
path refreshes the selected composite after personal-layer updates when
available; public-layer refresh follows once `setup.sh` has installed its
current post-merge hook. The audit reports otherwise. The installer refuses a
   user-managed conflict before changing anything; review it before opting
   into `--replace`. The durable Codex contract, including the autonomy and
   verification boundaries, is
   [codex/PARITY.md](../../codex/PARITY.md#codex-integration-sot); keep this
   template as a routing note rather than a second technical source.

## What goes in which file

- **CLAUDE.md** — your personal home instruction file. Lists which other files in this directory Claude should read and when.
- **repos.md** — your repo list with purpose and visibility. Replaces having repo lists in volatile MEMORY.md.
- **shared-project-keys.md** — mapping of shared-project repo names → local git-crypt key paths. Lets Claude auto-resolve unlock paths when working in shared projects.
- **user-profile.md** — your identity, signatures, account info. Used when Claude drafts emails or fills forms.
- **codex/AGENTS.md** — your concise Codex-specific private routing overlay.
  It is not a second `CLAUDE.md`; keep the detailed private rules in their
  existing sources and point Codex to them only when relevant.

You don't need all of them. Start with CLAUDE.md and add the rest as you find use cases.
