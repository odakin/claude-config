> Publication note: this is a retrospective reviewer record. `inputs/` names below identify the supplied historical snapshots, not live code or files embedded in this document. Their identities are in [snapshot-manifests.json](snapshot-manifests.json). Full working copies are retained as historical case evidence; they are not additional sources of policy. The adopted baseline is [ab95786](https://github.com/odakin/claude-config/commit/ab95786a1eb0930b941e96e24bf878cc7b0f01f5).

# Independent review handoff inventory

## Status and provenance

This document is a retrospective organization of existing reviewer replies and
tool-output summaries. It is not a new review, measurement, execution log, or
adoption decision. No experiment was rerun to produce this document.

The reviewer did not save the original stdin experiment scripts as reusable
files. They remain **unsaved and have not been reconstructed**. This handoff
does not replace missing raw execution logs with newly generated ones.

The evidence record and round-by-round findings are in
[REVIEW-RESULTS.md](REVIEW-RESULTS.md). Both documents use portable snapshot and
source-relative names. They omit personal, host, and session identifiers and
machine-specific absolute paths.

## Existing supplied material

The following were supplied by the implementation side, rather than generated
by the reviewer:

- `REVIEW-SPEC.md` and `inputs/MANIFEST.json`.
- The `inputs/before/` and `inputs/after/` snapshots.
- `inputs/revised/` and `inputs/REVISED-MANIFEST.json`.
- The supplied files in `inputs/revision3/` through `inputs/revision9/`, with
  their corresponding `REVISION3-MANIFEST.json` through
  `REVISION9-MANIFEST.json`.
- `inputs/PATHSPEC-REVIEW.md`.

The manifests and review specifications were checked for existence during the
inventory. Not every revision is a complete standalone checkout: some contain
only changed files. Execution layouts used the supplied unchanged helpers and
adapters where needed.

These snapshots are evidence of what was reviewed. Their presence does not
establish that the same bytes are installed, trusted, committed, or dispatched
by a running application.

## Reviewer-created artifacts

| Work | Artifacts originally created | Preservation status |
|---|---|---|
| Initial candidate review | Read-only source inspection and findings sent in replies | No experiment script or result file created |
| `revised` through `revision4` | Python stdin harnesses, disposable Git repositories, synthetic transcripts and approval state, copied snapshot code | Temporary artifacts removed; scripts were not saved; results were returned through tool stdout and replies |
| Native patch comparison for `revision5` and `revision6` | Temporary engine copies, synthetic input/output files, `predictions.json`, `predictions6.json`, `framing-patch.txt`, candidate files, a second-round fixture directory, a guard fixture repository, synthetic transcript/state | Explicitly removed after comparison; the native-comparison directory was later confirmed absent |
| Pathspec review for `revision7` and `revision8` | Disposable execution layouts and Git repositories, synthetic manuscript files, actual Git staging/commit comparisons | Removed by normal `TemporaryDirectory` cleanup; scripts were not saved; results were stdout only |
| Working-directory review for `revision9` | Copied adapters and engines, a disposable repository, synthetic events/state | Removed by normal cleanup; the final adapter-fixture directory was later confirmed absent |
| Runtime diagnostic proposal | Written risk/design feedback only | No diagnostic implementation or log was created or read by this reviewer |
| Wiring-scope design comparison | Written critique and synthetic examples only | No implementation, executable experiment, proposal file, or board note was created by this reviewer |

Other temporary directories were managed by successful `TemporaryDirectory`
contexts. Their deletion is supported by normal completion of those contexts;
the inventory did not search the entire temporary filesystem for residuals.

The first attempted interpreter invocation failed before the experiment ran
because of a local toolchain prerequisite. No fixture was created by that
attempt. Subsequent experiments selected the already available alternate
Python/Git executables without changing toolchain settings or accepting a
license. Machine-specific executable paths are intentionally not retained here.

Apart from these two retrospective Markdown documents, no durable
reviewer-generated filesystem artifact is being handed over.

## Findings already represented in supplied regression sources

“Represented” means the relevant test code was observed in a supplied snapshot.
It does not mean the reviewer verified the current live repository or a final
commit containing that code.

| Finding or behavior | Supplied regression location |
|---|---|
| Manifest-declared files must not disappear through the extension filter; Git type and executable mode changes; mode-bound approval | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` structural policy cases |
| Literal bypass across newlines; quoted operators and output/heredoc examples | `inputs/revision8/scripts/agent-rule-guard.py`, `selftest()` shell cases |
| Protected symlink referents, retarget approval identity, and full-hook output/heredoc behavior | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` symlink and display-command cases |
| Directory symlink components, implementation protection, unrelated sibling control, and repository-boundary rejection | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` directory-link cases |
| Question-UI answers versus echoed questions; known generated user-role envelopes | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` transcript cases |
| Native Add newline, patch framing, Update from a file without its final newline, and deletion to an empty file | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` patch cases; corresponding migration cases in `inputs/revision6/bootstrap/manuscript-claim-guard.py` |
| Directory/glob/magic/exclusion selection, pending additions, bundled add options, stale index restoration, adjacent untracked files, force and dry-run | `inputs/revision8/hooks/manuscript-claim-guard.test.sh`, Git pathspec section |
| Missing Codex tool workdir, unsafe cwd inference, explicit absolute Git invocation, and dry-run controls | `inputs/revision9/scripts/manuscript-claim-guard.py`, `selftest()` working-directory cases; `inputs/revision9/codex/hooks/codex-hooks.test.sh` |
| Reported Desktop event boundary and supported invocation form | `inputs/revision9/codex/PARITY.md`, native lifecycle hook discussion |

The full independent harnesses were not incorporated as files. In particular,
the reviewer's three-distinct-snapshot symlink fixture, native-byte comparison
tables, Python grammar checks, and extended malformed-workdir adapter matrix
were returned through tool output and replies. Do not describe them as saved
standalone regression scripts.

## Evidence ownership and limits

- The reviewer directly exercised native `tools.apply_patch` against synthetic
  files and compared the resulting bytes with guard reconstruction.
- The observation that a native shell execution hook omitted the tool's
  working directory was reported by the implementation side. The reviewer
  assessed the diagnostic design and independently replayed synthetic events
  through copied adapters. These are different kinds of evidence.
- The reviewer did not create or inspect the implementation side's temporary
  native-event diagnostic log.
- Round-specific accepts were limited to the supplied candidate and stated
  checks. They are not blanket guarantees for all shell syntax, Git options,
  transcript formats, runtime dispatch, trust state, or future revisions.
- Wiring-scope feedback remained an unadopted design critique. Later
  performance work and the final scope decision belong to a separate handoff
  and were not reviewed here.

## Placement guidance for the receiving editor

This inventory and `REVIEW-RESULTS.md` are case/evidence records, not new
normative rule documents. Existing ownership can be preserved as follows:

| Material | Existing owner or destination type |
|---|---|
| General rule-change authority and scope-preservation requirements | `conventions/agent-rule-ownership.md` |
| Manuscript-specific editing authority | `conventions/manuscript-claim-ownership.md` |
| Product/runtime event boundary and supported Codex invocation form | `codex/PARITY.md` |
| Detection, reconstruction, selection, and approval behavior | The corresponding engine and adapter regression tests |
| Historical findings, reproduction descriptions, limited verdicts, and unavailable artifacts | A portable case/evidence record such as `REVIEW-RESULTS.md` |
| Unadopted wiring-scope alternatives | A clearly marked proposal, not an adopted rule |
| Session/index/README entries | References and status only |

No move to those destinations and no live-source edit was performed by this
reviewer. If an unsaved harness is reconstructed later, label that newly saved
artifact as a reconstruction. If old replies are transcribed into a log, label
the result as a retrospective transcription rather than a new execution.
