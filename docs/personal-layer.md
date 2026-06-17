# Personal Layer — odakin's four-layer architecture
<!-- slug index: personal-layer.index.yaml — cross-ref sections by #slug (stable), not §-number. See convention-design-principles §14.2 / §14.7. -->

> **日本語版**: 同じファイル内で日本語セクションを併記しています。

## <a id="what-is-personal-layer"></a>What is the personal layer?

Claude Code conventions live in **four layers**, numbered by **audience size** (largest to smallest):

| # | Layer | Example | Audience | Depends on |
|---|---|---|---|---|
| 1 | Common conventions | this `claude-config` repo | public / shared (any Claude Code user) | — |
| 2 | Shared project layer | a private repo you share with collaborators (e.g. an admin or research repo) | the project's collaborator set | layer 1 only |
| 3 | **Personal layer** | `<base>/<your>-prefs/` (a private repo or local dir of your own) | only you, **across all your machines** (cross-machine) | layers 1, 2 |
| 4 | Volatile memory | `~/.claude/.../memory/MEMORY.md` | only you, **on this specific machine** (machine-local — captures facts that wouldn't be true on another of your machines) | any |

The numbering follows audience containment: `public ⊃ collaborator set ⊃ owner-cross-machine ⊃ this-machine-only`, so a smaller layer number always means a wider audience. This makes the dependency rule directional and intuitive — a layer can only depend on layers with **smaller or equal** numbers.

> **History note**: as of **2026-05-01** the numbering was changed to align with audience size (layers 2 and 3 were swapped — old `2 = personal / 3 = shared` became new `2 = shared / 3 = personal`). Commit messages and docs from before that date may use the old numbering; if you see "layer 2 = personal layer" in older commit logs, that's the old scheme. See `claude-config/DESIGN.md §「4 層モデルの renumber: layer 2 ↔ 3 swap (2026-05-01)」` for the rationale and full impact map.

**Core rule**: each layer may only depend on layers whose audience contains its own. So a shared-project layer (layer 2) can reference claude-config (layer 1, public) but **must not depend on** your personal layer (layer 3, only you), because your collaborators cannot see your personal layer.

**Direction, stated plainly (so the 上層/下層 framing is never flipped).** A *smaller* number = *wider* audience = the **upper / foundational** layer (上層); a *larger* number = *narrower* audience = a **lower** layer (下層). Layer 1 (claude-config) is the topmost 上層; layer 4 (memory) is the bottom 下層. **A reference or dependency that points from a lower layer *up* to a wider one (下層 → 上層 — e.g. personal layer → claude-config, layer 3 → 1) is ALLOWED; it is the normal, intended direction**, exactly what the "Depends on" column grants. The **only forbidden direction is the reverse**: a wider-audience layer structurally depending on a narrower one (上層 → 下層 — e.g. layer 2 → 3), because that wider audience cannot see the narrower layer. So you never need to hesitate to point *up* the stack — pointing 下層 → 上層 is free. The restriction only bites pointing *down* (上層 → 下層), and even there a *mention* (as opposed to a structural dependency) is still fine — see the next section.

### <a id="what-depend-means-structural-dependency-vs-mention"></a>What "depend" means: structural dependency vs. mention

The rule above bans **structural dependencies** across layer boundaries, not **mentions**. The distinction matters because the harm comes from one but not the other — and conflating them produces docs that are *less* helpful to the wider audience, not more safe.

| | 依存 (structural dependency) | 言及 (mention / 名指し) |
|---|---|---|
| **Definition** | A's correctness or operability requires B (= reader cannot use A without access to B) | A's docs inform the reader that B exists, but A is self-contained (= reader can use A without ever touching B) |
| **Effect on reader without B** | A breaks / is unreadable | A still works; reader just knows the larger system better |
| **Across-layer rule** | ❌ Forbidden when B is in a smaller-audience layer than A (= the canonical Core rule) | ✅ Allowed when accompanied by an explicit boundary statement (see below) |

**Mention is not a layer violation.** Naming a smaller-audience artifact in a wider-audience doc is just informational. What's forbidden is making the wider audience's experience *depend on* access to the smaller-audience artifact.

#### Why mention is fine in principle

- claude-config's `setup.sh` (layer 1, public) detects personal-layer (layer 3) directories by *name* (`<owner>-prefs/`). An L1 script can know what an L3 name looks like without depending on any specific L3 content.
- This very document mentions personal-layer locations from inside layer 1 — that's informational, not a dependency.
- 名指し ≠ access dependency。 Telling a reader "B exists, you don't need it" is more useful than abstract paraphrase ("managed separately by the owner") that hides the system structure. The latter is the *worse* failure mode: collaborator can't even ask informed questions about the boundary.

#### The boundary statement requirement

When you mention a smaller-audience artifact in a wider-audience doc, **include a boundary statement at the same spot** so the reader doesn't misread the mention as an implicit dependency:

- "Collaborators don't need access to this; the current repo is self-contained."
- "This is owner-only / machine-local; other environments don't have it and don't need to."
- "Informational reference only — the upstream is managed separately by the owner."

Without a boundary statement, a mention drifts into implicit dependency: the reader thinks "ah, I need that one too" and goes looking, hits 404 or permission-denied, gets confused.

#### What's still forbidden across layer boundaries

Mention covers **names** of repos / concepts. The following are **structural** by nature and remain forbidden when crossing into a smaller audience:

- **Internal file paths** into a smaller-audience layer (e.g. `<owner>-prefs/something.md` written inside an L2 doc). A path invites navigation, which *is* dependency. Repo name alone (`<owner>-prefs`) is mention; `<owner>-prefs/something.md` is dependency.
- **Absolute filesystem paths** like `/Users/<owner>/...` — these don't work in another environment regardless of intent.
- **Owner-specific identifiers** (email addresses, calendar IDs, secret-file paths) — these are owner data; the layer rule isn't the only reason to omit them (privacy / leak prevention is the primary, see [`conventions/shared-repo.md`](../conventions/shared-repo.md) §「公開前の Audit」).

The compact rule: **name it, don't path into it.**

#### Where to enforce

Per-layer documents apply this principle to their own boundary. The L2-specific application (= what an L2 shared-project repo may or may not contain) lives in [`conventions/shared-repo.md`](../conventions/shared-repo.md) §「L2 における「名指し」 の適用 (boundary 明示付き)」, which references this section as the canonical source. The L1-specific application (= claude-config itself as a public repo) adds a **separate leak-prevention axis** on top of the layer rule, documented in `claude-config/CLAUDE.md` §「安全規則（公開リポ）」. The leak axis is stricter: even mention with a boundary statement is governed by an explicit exception list, because once a name appears in public git history, the boundary statement cannot un-publish it.

### <a id="why-layer-4-isolates-machine-local"></a>Why does layer 4 isolate machine-local facts?

Each step downward narrows the audience by **one meaningful boundary**:

- 1 → 2: drops "the public" → narrows to people who collaborate on a specific project
- 2 → 3: drops "your collaborators" → narrows to **you alone**, but still **any of your machines** (you might run Claude Code on a laptop, a desktop, or both)
- 3 → 4: drops "your other machines" → narrows to **this single machine**, the one running Claude right now

The 3 → 4 step matters because **the same person can have facts that differ across their machines**: hostname-specific symptoms, OS-version drift, hardware quirks (e.g. one machine is Apple Silicon, another is Intel; one has a flaky USB hub; `brew install foo` fails on a Tier 2 OS/arch combination but succeeds on the other — see [`conventions/install-failures.md`](../conventions/install-failures.md) for the registry pattern; etc.). Layer 4 is the audience-minimized place to record those — writing them at layer 3 would falsely propagate them to machines they don't apply to. **Layer 4 exists to absorb the difference between your machines as the smallest meaningful audience unit.**

This shows up in practice as a three-way decision when you have a machine-specific fact:

- A fact like your name, email, or signing identity → **layer 3** (true on every machine of yours)
- A fact like "on this hostname, this app hangs once a week" → **layer 4** (only true on that one machine, no relevance to your other machines)
- A fact that **describes the difference between your machines** ("home machine = ARM, work machine = Intel, with different package-manager behaviour") → **layer 3** (the *contrast itself* is a cross-machine fact about your fleet, even though it references machine-specific values)

The third case is the subtle one. If a fact is *about* the differences between your machines (a comparison, a branching table, a "fleet snapshot"), it's already cross-machine in nature: the audience for "my fleet has these two machines with these specs" is your whole fleet, not one machine. Branching tables in your personal layer that say "on machine A do X, on machine B do Y" belong at layer 3 because the branching structure itself is the cross-machine fact.

A useful heuristic: **if the fact would feel incomplete without mentioning the other machine (because it's a comparison or a branch), it's layer 3. If the fact stands alone as an observation about one machine and the other machine is irrelevant to it, it's layer 4.** When in doubt, prefer layer 3 with a branching table — pure layer-4-only facts are rarer than they feel.

## <a id="when-to-create-personal-layer"></a>When should you create a personal layer?

You should create one when you start having:
- preferences that span multiple projects (writing style, identity blocks, signature lines)
- a list of repos you maintain
- per-machine secret paths (e.g. where you keep git-crypt keys for shared projects)
- personal workflow rules you want Claude to remember automatically

If you only ever work in one repo and have nothing to share between projects, you don't need a personal layer at all. claude-config alone is enough.

## <a id="layout"></a>Layout

A personal layer is a **directory** (typically a private git repo, but a local-only directory works) containing:

```
<your>-prefs/
├── .claude-personal-layer        # marker file (zero bytes) — claude-config setup.sh detects this
├── CLAUDE.md                     # the personal home instruction file (~/Claude/CLAUDE.md symlinks here)
├── repos.md                      # your repo list (optional, replaces having it in MEMORY.md)
├── shared-project-keys.md        # mapping of shared-project repo names → local key paths (optional)
├── user-profile.md               # identity, signatures, account info (optional)
├── dropbox-collabs.yaml          # Dropbox shared-PDF registry (optional, see conventions/dropbox-refs.md)
└── ...                           # other personal rule files
```

When the personal layer contains `dropbox-collabs.yaml`, `claude-config/setup.sh` automatically:
1. runs `scripts/setup-dropbox-refs.sh` to create per-repo `dropbox-refs/` symlinks pointing into your Dropbox install
2. installs a `post-merge` git hook in the personal layer so subsequent `git pull` regenerates the symlinks

See [`conventions/dropbox-refs.md`](../conventions/dropbox-refs.md) for the schema and full details.

The **marker file** `.claude-personal-layer` is the canonical signal that this directory is a personal layer. claude-config's `setup.sh` looks for it under `~/Claude/*/` (or whichever base directory you use) and, if it finds exactly one match, links `~/Claude/CLAUDE.md` to that directory's `CLAUDE.md`.

## <a id="creating-personal-layer"></a>Creating your own personal layer

1. Make a directory next to claude-config:
   ```bash
   mkdir -p ~/Claude/my-prefs
   cd ~/Claude/my-prefs
   touch .claude-personal-layer
   ```
2. Optionally make it a private git repo:
   ```bash
   git init
   gh repo create my-prefs --private --source=. --push
   ```
3. Copy the templates from `claude-config/templates/personal-layer/` and fill them in (see [templates README](../templates/personal-layer/README.md)).
4. Re-run `claude-config/setup.sh` so the symlink at `~/Claude/CLAUDE.md` is updated to point at your new layer.

## <a id="multiple-personal-layers"></a>Multiple personal layers? Override?

If `setup.sh` finds **more than one** directory with the marker, it errors out and asks you to disambiguate via the `CLAUDE_PERSONAL_LAYER` environment variable:

```bash
CLAUDE_PERSONAL_LAYER=~/Claude/work-prefs ./setup.sh
```

To opt out entirely (e.g. on a shared machine), use:

```bash
CLAUDE_PERSONAL_LAYER=none ./setup.sh
```

## <a id="shared-project-key-mapping"></a>Shared-project key mapping

If you participate in shared-project layers that use git-crypt with shared keys (one common pattern: the key file lives in a Dropbox folder shared with the team, each team member places it at their preferred local path), put the local paths in `shared-project-keys.md`:

```markdown
# Shared Project Key Paths

| Project    | Local key path                  |
|------------|---------------------------------|
| my-project | ~/.secrets/my-project.key       |
```

Claude reads this file via the personal-layer cascade and uses the right path automatically when entering a shared-project repo. Without this file, Claude falls back to the convention path `~/.secrets/<project-name>.key`.

## <a id="owner-automation-shared-project"></a>Owner automation acting on a shared project

The key-mapping section above handles the case where a **shared** layer needs a **private** thing (a key). The opposite direction needs a rule too: an **owner automation** (layer 3 or 4 — runs on the owner's machine, reads owner-private inputs, holds the owner's credentials) that **writes into a shared-project (layer 2) repo**. The canonical example is a nightly publisher that mirrors an owner-private source-of-truth into a shared website, or a bot that posts generated content into a shared repo.

The Core rule forces the automation **itself** to sit at the owner's layer: it structurally depends on owner-private inputs (a private SoT, an OAuth token, a machine-pinned scheduler), so a copy living in the layer-2 repo would be **dead code for collaborators** — they can't run it, they lack the inputs. That placement is correct and unavoidable.

But "the code lives at layer 3" must not become "the mechanism is invisible at layer 2." Separate two things:

- **Gating private *data* is legitimate** — collaborators don't get to see the owner's private SoT (unconfirmed drafts, contacts, pre-public coordination). That's privacy, not opacity.
- **Hiding the *mechanism* is a defect** — if collaborators open the shared repo and find files materializing with no visible explanation of what produces them, what the contract is, or how to operate it when the owner is away, that is exactly the inaccessible opacity to forbid. The shared repo's audience is *affected by* the automation; they must be able to see and reason about it.

**Requirement — the automation must announce itself in the shared repo.** Per the depend-vs-mention rule, naming the owner-private SoT (with a boundary statement) is allowed and *encouraged*; what you add is a layer-2 contract doc stating:

1. **Which files are machine-generated / owned** by the automation, vs. which are hand-editable.
2. **Its write discipline** — create-only? idempotent overwrite? — so a collaborator knows whether their hand-edits survive.
3. **What the SoT is and who owns it** (mention + boundary statement: "lives in the owner's private repo; you don't need access — edit the generated files here directly").
4. **How to observe its health** (heartbeat / dashboard) and **how to run or trigger the parts collaborators can** (e.g. the deterministic build usually already lives in the shared repo).
5. **Bus factor** — who to contact / how the shared parts are operated if the owner is unavailable.

**Stronger form (preferred when feasible): split the seam.** Extract the *deterministic engine* (the part that takes a SoT and renders output) into the shared repo so its **logic is readable and runnable at layer 2**, and leave only the owner-private inputs + credentials + scheduling at the owner's layer. Then the shared repo holds transparent logic that is gated solely on private *data* — the ideal end-state. When the SoT itself already lives in the shared repo (so nothing private is read), the whole pipeline can be layer-2-native, with only an owner-private *trigger* (e.g. email detection) remaining at layer 3.

**Don't split the seam by *copying* a fact into two editable SoTs.** When a record has both a private aspect (pipeline / draft / contacts) and a public aspect (the published content), the tempting wrong move is to keep the whole record in the owner's private SoT *and copy the public part into the shared repo*. Now the same fact (a title, a date) lives in two independently-editable places — they drift, and you've violated single-source-of-truth. Instead:

- **Partition, don't duplicate — one fact, one home.** Public fields live *only* in the shared published SoT; private fields (contacts, negotiation status, declined candidates) live *only* in the owner's ops SoT. No field is authoritative in both. The two files hold *different* data partitioned by sensitivity, not two copies of the same data.
- **Promotion across the publish boundary is a MOVE (handoff), not a copy.** Pre-publish, the draft of the public content lives in the owner's ops SoT. At publish, its authoritative home becomes the shared published SoT, and the ops SoT *relinquishes* it (keeps only the private remainder + a key/pointer such as a slug). So at any instant each fact sits in exactly one place — it's one logical SoT physically partitioned by lifecycle (draft → published), like draft/published or hot/cold storage, not two SoTs for the same data.
- A create-only mirror is the *copy* anti-pattern in disguise: it seeds the shared copy once, then both sides are hand-editable and silently diverge. If you find one, convert it to a move (the shared side becomes authoritative; the owner side stops carrying the public fields).

This is the forward-direction analog of key-mapping: keep the private bit private, but never let the shared audience hit a wall they can neither see nor reason about — and never let the same fact have two homes.

## <a id="faq"></a>FAQ

**Q. Is the personal layer required?**
No. claude-config works without one. The default `~/Claude/CLAUDE.md` from `templates/root-CLAUDE.md.default` is installed instead.

**Q. Should the personal layer be a git repo?**
Recommended for cross-machine sync, but a local-only directory is fine. Both work with the marker-file detection.

**Q. Can other people see my personal layer?**
Only if you make it a public repo. Default: keep it private (or local-only). Personal layers typically contain identity info, signatures, repo lists, and per-machine paths — not state secrets, but still personal.

**Q. How do I migrate from an existing setup that hard-coded a specific dir name?**
Just create the marker file in your existing dir: `touch ~/Claude/<your-dir>/.claude-personal-layer`. Re-run `setup.sh`. The detection picks it up regardless of the directory name.
