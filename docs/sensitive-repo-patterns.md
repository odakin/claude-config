# Design Patterns for Git Repositories Containing Sensitive Data

> **日本語版 (primary)**: [sensitive-repo-patterns.ja.md](sensitive-repo-patterns.ja.md)
>
> This English version is an overview; the Japanese version has the full text and examples.

Design patterns for repositories that need to track sensitive data (customer investigations, internal network topology, incident postmortems, etc.) under version control while keeping outsiders from extracting information even if the repo exists.

The mechanics of encryption tools (git-crypt, etc.) are covered in [git-crypt-guide.md](git-crypt-guide.md). This document is a layer above: **what to put where, and in what shape, so that information does not leak outside the encrypted layer.**

## <a id="part-1-public-surface"></a>Part 1: Recognize the Public Surface

**git-crypt (and similar tools) encrypt only file contents.** Everything else remains in plaintext in the git history and is exposed to anyone with read access, even if you only intend the repo to be private:

- File paths and directory structure
- Commit messages, author names, emails, timestamps
- `.gitattributes` contents (including comments)
- `.gitignore` contents
- Repo name, description, topics
- Branch and tag names
- The mere fact the repo exists

**Practice**: Before publishing, walk through a public-surface checklist (see the Japanese version, Part 1-2) and verify every item.

## <a id="part-2-encryption"></a>Part 2: Encryption Configuration

**Pattern 2-1: Prefer default-encrypt over allow-list.**

```gitattributes
* filter=git-crypt diff=git-crypt
.gitattributes !filter !diff
.gitignore !filter !diff
README.md !filter !diff
```

New files are encrypted automatically. No one forgets to add a filter line. The plaintext side is intentionally minimal.

**Pattern 2-2:** `.gitattributes` cannot itself be encrypted (chicken-and-egg with git-crypt's filter resolution). Accept this, and minimize its content: no explanatory comments, just the filter directives.

**Pattern 2-3:** Comments in `.gitattributes` explaining *why* files are encrypted are themselves a leak of operational intent. Strip them.

## <a id="part-3-minimize"></a>Part 3: Minimize the Public Surface

**Pattern 3-1: Slug design.** Do not encode identities in filenames. Use opaque slugs (`a.md`, `b.md`, `n1.md`) and keep the slug-to-identity mapping only in an encrypted `INDEX` file. Semantic fragments (`ac`, `tok`, `bnk`) are combinable into guesses and should be avoided.

**Pattern 3-2: Commit messages are permanent and visible.** Use generic labels only: `Add note`, `Update note`, `Refine skeleton`, `Reorganize`. Put the details inside the encrypted file, not in the commit history. Even after a force-rewrite, traces persist in packfiles and reflogs.

**Pattern 3-3: Structurally guard the plaintext README.** A clone-time README is often needed to tell readers how to unlock. But plaintext drifts over time as people add "just a little context". Defense:

1. **Fix its role** to "unlock instructions only" via a warning comment inside the file.
2. **Enforce structural constraints** with a pre-commit hook:
   - Size cap (e.g., ≤ 800 bytes)
   - ASCII-only (excludes most non-Latin proper nouns)
   - No IPv4 dotted-quad pattern
   - FQDN allowlist (only `github.com` or other pre-approved domains)
   - URL scheme hosts match the same allowlist
3. **Store the hook script in the encrypted side** so the script's logic and allowlists do not themselves leak.
4. Structural constraints (size/encoding/patterns) beat keyword blacklists: they need no maintenance, do not leak, and catch novel identifiers.

## <a id="part-4-bootstrap"></a>Part 4: Bootstrap Design

**Pattern 4-1: Document the full chain from zero to readable state on a fresh machine.** Do not leave any step buried in encrypted files that cannot be read before unlock. Common gaps:

- How does the key reach the new machine?
- If the key is encrypted for transport, how is the passphrase shared?
- Post-unlock setup steps (hook installation, etc.) — inline the one-liner into the plaintext README or link to a cross-reference that does not require unlock.

**Pattern 4-2: A "not here" pointer must always come with a "here" pointer.** If you write *"this secret is not recorded in this file"*, the reader is left stranded. Always add *"its canonical location is at X"*.

**Pattern 4-3: Cross-machine vs machine-local.** Information stored in machine-local caches (IDE state, LLM auto-memory, OS keychain, machine-specific config paths) is invisible on other machines. Before saving anywhere, ask:

> **"If I open a fresh session on another machine, will this information be there?"**

If no, and the information is not inherently machine-specific, use a git-synced location (or equivalent cross-machine sync) instead.

## <a id="part-5-discipline"></a>Part 5: Operational Discipline

**Pattern 5-1: Forcing functions beat discipline.** Where the same kind of mistake recurs, do not rely on "try harder." Install structural defenses: secure defaults, pre-commit hooks, always-loaded gate questions, size caps, design-level impossibility (opaque slugs).

**Pattern 5-2: Same-day sweep.** When you add a new rule, audit the existing codebase for pre-existing violations in the same work unit. Otherwise the new rule loses credibility and the old violations linger.

**Pattern 5-3: Post-implementation review.** Treat "implementation + review + fix" as one unit. Use a four-axis review:

| Axis | Question |
|---|---|
| Consistency | Do cross-references, numbers, section titles, paths match across files? |
| Non-contradiction | Does the change conflict with existing rules or templates? |
| Efficiency | Are there duplications, size drift, or redundant sources of truth? |
| Safety | Is any personal, credential, or org-identifying info in the public surface? |

**Pattern 5-4: Examples co-age with the rule.** When you refine a design rule, the examples cited in the old rule may become violations under the new rule. Check and either correct them, annotate them as historical, or delete them. Leaving a self-contradictory example undermines the new rule.

## <a id="appendix-checklists"></a>Appendix: Checklists

See the Japanese version's Appendix A/B/C for:

- Repository creation checklist
- New-note-addition checklist
- Periodic audit checklist

## <a id="related-documents"></a>Related documents

- [git-crypt-guide.md](git-crypt-guide.md) — tool-level usage (install, init, export-key, remote machine setup)
- [convention-design-principles.md](convention-design-principles.md) — meta-level principles for writing conventions

## Changelog

- **2026-04-09**: Initial version. Patterns extracted from the implementation of a private encrypted notes repository and generalized for public sharing.
