> Publication note: this is a retrospective reviewer record. `inputs/` names below identify the supplied historical snapshots, not live code or files embedded in this document. Their identities are in [snapshot-manifests.json](snapshot-manifests.json). Full working copies are retained as historical case evidence; they are not additional sources of policy. The adopted baseline is [ab95786](https://github.com/odakin/claude-config/commit/ab95786a1eb0930b941e96e24bf878cc7b0f01f5).

# Agent-rule controls: retrospective independent review record

## What this record is

This is a **retrospective organization of existing reviewer replies and
tool-output summaries** covering the initial candidate through `revision9`,
followed by a design-only wiring-scope discussion. It contains no new
measurement, implementation, adoption decision, or performance comparison.

Original experiment harnesses were mostly Python scripts supplied to stdin.
They were **not saved and have not been reconstructed**. Complete raw logs were
not exported as durable local artifacts. This record preserves the reported
findings, procedures, result summaries, and limits; it does not invent missing
logs or present a summary as a fresh run.

The supplied sources used the logical names under `inputs/`. Artifact status
and source-ownership guidance are recorded in [HANDOFF.md](HANDOFF.md).

## Review boundary and method

The initial task concerned general safeguards against agents changing,
reinterpreting, or weakening applicable rules while preserving authorized
ordinary work and existing manuscript controls. The reviewer treated supplied
source instructions as review objects, not commands to execute.

The initial assessment used source inspection. Later rounds used independently
created, disposable fixtures with:

- Explicitly selected supplied snapshots and copied unchanged dependencies.
- Synthetic repositories, manuscript text, identities, transcript messages,
  and approval records, with no real user or repository data.
- Isolated Git configuration and fixture-local approval state.
- Direct predicate/hook calls and, where stated, subprocess invocation of the
  supplied thin adapters or Git entry point.
- Separate classification of a rule rejection and `inspection unavailable`.
- Actual Git selection/staging/commit checks for the pathspec counterexamples.
- Actual native `tools.apply_patch` writes for the patch-byte comparison.
- Normal cleanup of disposable directories; no production configuration edits.

Tests passing in a fixture were not taken as authorization, proof of live hook
dispatch, or proof that a later candidate was unchanged.

## Round record

### Initial candidate: changes needed

The first report was based on source inspection and explicit code arguments;
its proposed counterexamples had not yet been independently executed by the
reviewer at that point.

1. **P1 — Declared gate implementations disappeared through the extension
   filter.** A manifest entry such as `scripts/release.rb` was accepted, but
   `relevant_text_file()` filtered `.rb` before Claude Edit, Codex patch, or Git
   inspection reached the authority predicate. The proposed correction was to
   let explicit protection outrank the convenience extension list.
2. **P1 — Git structural changes were not protected.** `changes_for_repo()`
   excluded type-change status `T`; content-only comparison also missed removal
   of an executable bit. A protected extra hook could retain all its text while
   a runner's executable-file test stopped invoking it. The report called for
   type/mode inspection and approval binding to the intended attribute change.
3. **P1 — Newlines were lost by the shell lexer.** The proposed example
   `echo preparing` followed on the next line by `git push --no-verify` became
   one non-Git segment because newline remained lexer whitespace.
4. **P2 — Quoted operators were treated as executable separators.** For
   example, `printf '%s\n' ';' git push --no-verify` is output, whereas
   `git commit -m ';' --no-verify` is an actual bypass. Removing quote provenance
   before classifying the semicolon confused these cases.
5. **Conditional compatibility finding.** A nested same-quote f-string
   required Python 3.12 syntax despite invocation through unversioned Python.
   The finding was conditional on the supported runtime range.

The general normative direction, separation of operation authority from rule
change authority, and distinction between persisted trust and live dispatch
were considered coherent. No installation or live-runtime guarantee was made.

### `revised`: original examples fixed; changes still needed

Independent fixtures confirmed that the original extension, type/mode,
newline, and quote examples behaved as intended after correction. Positive
controls included ordinary edits and output commands. Correct mode approval
passed; changes to the mode or content hash did not reuse that approval.
Python 3.11 grammar checks passed for the two engines.

Three additional findings were measured:

1. **P1 — A declared file symlink lost its protection after resolution.** With
   `scripts/release.rb` pointing to `impl.rb` and only the link declared,
   editing through the link returned no denial; staging only the implementation
   also yielded no protected changes. The lexical protected identity was lost
   when `target_identity()` resolved the referent.
2. **P2 — A same-mode symlink retarget could not use its normal approval.** A
   tracked `AGENTS.md` link changed from one policy file to another. Git reported
   `AGENTS.md :: authority:file`, but approval was stored under the new referent
   name, leaving the link entry unapproved.
3. **P2 — Full-hook command inspection reintroduced output/heredoc false
   positives.** The new bypass parser allowed output examples, but the old
   `commit_targets()` later found a `git` token at a non-executable position.
   With an unapproved protected change staged, printf and quoted-heredoc
   examples were denied for that unrelated protected change.

These were policy-result mismatches, not checker crashes disguised as
rejections.

### `revision3`: direct-link fixes confirmed; directory-link P1 remained

The reviewer independently confirmed the preceding three original
counterexamples were corrected:

- Declared link edits and staged referent changes were rejected for authority.
- Retarget approval used the same link-entry identity reported by the gate.
- Output and heredoc examples passed through the full hook.
- Actual multiline commits, commits after heredocs, and shell-wrapper commits
  still reached the policy check; literal bypasses were rejected.
- Old and new direct-link referents from HEAD/index remained protected.
- Direct repository-external protected links produced inspection failure.
- Synthetic question-UI envelopes excluded echoed questions and retained
  answers across the tested transcript representations.

One additional **P1** was demonstrated:

```text
protect_paths = ["release.rb"]
release.rb -> current/check.rb
current -> v1
v1/check.rb contains the required check
```

Only the final path was tested for being a symlink. The directory component
`current` was not resolved, so neither editing through `release.rb` nor staging
`v1/check.rb` caused a denial. Pointing `current` to a fixture directory outside
the repository also failed to produce the intended inspection error. The
proposed correction was component-wise resolution per snapshot, preserving
both intermediate control links and the reached implementation.

### `revision4`: limited accept

The independent fixture reported **22 successful checks** and no new P1/P2 in
the requested recheck. It covered:

- The prior directory-link edit and staged-referent counterexamples.
- Protection of intermediate link entries and actual implementation files.
- Three distinct targets in HEAD, index, and worktree, with all three reached
  implementations retained in the protected set.
- An unrelated sibling file remaining editable and committable.
- Repository-external parent-directory links rejected as inspection failure.
- Link approval identity, exact mode binding, command-output controls, actual
  commit/bypass rejection, question-UI handling, and Python grammar checks.

The 21 supplied manifest hashes matched at the time of that check. Acceptance
was limited to those sources and tests, not deployment or full interpreter
coverage.

### `revision5`: native-byte fix partly confirmed; newline P2 remained

The limited final and migration candidates changed Add reconstruction and
handling of framing text after `End Patch`. The reviewer compared predictions
with native `tools.apply_patch` writes in a disposable fixture.

Add of ordinary lines, empty Add, a blank line, multiline Add, ordinary Update,
and full deletion matched the observed native bytes. A standalone framing
example also demonstrated that the previous parser treated trailing patch
framing as hunk content, while the candidate reconstructed the intended file.

A remaining **P2** was independently observed in both candidates:

```text
Original bytes:  b'alpha'
Update:          -alpha / +beta
Reconstruction:  b'beta'
Native bytes:    b'beta\n'
```

The discrepancy predated the limited delta but still caused exact candidate
hash disagreement. It was reported as a remaining reconstruction problem,
not a newly introduced regression.

Separate synthetic authorization checks showed that unapproved protected Add
was denied, the correctly recorded candidate was allowed, and a different
candidate remained denied.

### `revision6`: limited accept of final and migration deltas

Native writes for **nine case types** were compared with reconstruction by
both candidates under two patch-framing endings: **36 comparisons**, all
matching. This does not mean native tooling was invoked 36 times.

The cases included ordinary/empty/blank/multiline Add, ordinary Update,
Update without an original final newline, an interior-line framing example,
and complete deletion with and without the original final newline.

For both candidates, a protected Update was denied before approval, allowed
with the exact native-byte candidate, and denied after the candidate content
changed. Rejection was attributed to the policy rather than inspection failure.
Python 3.11 grammar and both manifest hashes were also checked.

No new P1/P2 was reported in this limited delta. Native fixture files and the
temporary prediction JSON files were explicitly deleted afterward.

### `revision7`: pathspec changes needed

The separate pathspec requirement was supplied in
`inputs/PATHSPEC-REVIEW.md`. Fourteen main cases behaved as expected, including
ordinary pending directory additions, plain/dotted directories, quoted globs,
top magic from a subdirectory, exclusions, add/update distinctions, and Git
selection failure reported as inspection failure.

Three counterexamples were measured against actual Git:

1. **P1 — Bundled add options were not recognized.**
   `git add -Av && git commit -m x` was allowed, while actual Git staged a new
   protected manuscript. The parser handled exact standalone flags but did not
   recognize the short-option bundle.
2. **P2 — Pending add failed to replace a stale index-only change.** HEAD and
   worktree contained the original equation, while the index contained a
   changed equation. An ordinary file was also staged. The hook denied
   `git add plain/ && git commit -m x`; actual Git removed the obsolete staged
   equation change and successfully committed only the ordinary file.
3. **P2 — A path-only commit incorrectly included adjacent untracked files.**
   A directory contained a tracked ordinary modification and an untracked
   manuscript. The hook denied `git commit -m x -- plain/` for the new
   manuscript, but actual Git committed only the tracked file and left the
   manuscript untracked.

### `revision8`: limited accept of pathspec corrections

The three counterexamples were replayed independently and corrected. The
reviewer reported **24 successful checks**, including:

- Short-option bundles and tracked-only update behavior.
- Replacement of index-only changes by pending add.
- Exclusion of untracked neighbors from path-only commits without add.
- Inclusion of new files actually selected by preceding add.
- Explicit force of ignored files and nonmutating add dry-run behavior, also
  checked against actual Git.
- Directory/glob/magic/exclusion/cwd behavior and selector error classification.

The three supplied manifest hashes matched. No new P1/P2 was reported in the
limited review; all Git options and shell forms were not claimed to be covered.

### Runtime diagnostic and cwd design feedback

The reviewer assessed a proposed narrow diagnostic that would record event
shape without command/content text. Feedback recommended restricting it to the
targeted review invocation, retaining type information, avoiding raw fallback
serialization, using a private regular output file, and verifying restoration
afterward. The reviewer did not implement or inspect that diagnostic.

The implementation side subsequently reported a native runtime observation:
the shell tool's actual working directory was not included in the hook input,
while the task directory remained present. This is received evidence, not a
native observation independently repeated by this reviewer.

The reviewer pointed out that these forms cannot prove where the final commit
executes:

```text
(cd <REPOSITORY>); git commit -m x
false && cd <REPOSITORY>; git commit -m x
cd <REPOSITORY> || true; git commit -m x
```

The placeholders above are illustrative, not executable commands. Flattened
shell tokens lose subshell scope and conditional execution. The feedback also
required rejecting malformed workdir values and retaining harmless dry-runs.

### `revision9`: limited accept of the missing-cwd boundary

The candidate required each relevant Git call to provide its own absolute
repository argument when Codex tool workdir was unavailable, rather than
inferring it from `cd`, `env`, or the task directory. A valid absolute tool
workdir retained the existing inspection path. Claude event-cwd behavior was
kept separate.

The reviewer invoked copied thin adapters in subprocesses with synthetic
events. **Thirty cases** behaved as expected:

- Missing, empty, relative, and wrong-type workdir values were rejected with
  the working-directory inspection reason.
- Parentheses, conditional `cd`, environment-directory wrappers, child shells,
  relative Git directory arguments, and an unbound later Git call were not
  accepted as proof of the actual repository.
- Explicit absolute Git repository selection or a valid absolute tool workdir
  reached the normal protected-equation rejection rather than failing
  inspection.
- Ordinary selected-file commits, status, and add/commit dry-runs were allowed.
- Claude event-cwd behavior and literal bypass rejection remained intact.

The three supplied hashes matched. The PARITY explanation was considered
consistent with this limited implementation boundary. This was synthetic
adapter evidence, not a fresh native runtime-dispatch probe.

## Wiring-scope design discussion: no adoption verdict

The later request was design-only and explicitly did not authorize rule,
engine, or wiring changes. The reviewer made no implementation and selected no
option for adoption.

| Alternative | Main concern recorded | Ordinary-edit cost recorded |
|---|---|---|
| Marker block opt-in narrows implicit wiring protection | Early exit, an outer condition, a removed caller, or externally changed variables/functions/environment can disable an unchanged protected block | Easier payload edits, but greater responsibility for maintaining the full dependency boundary |
| Protect mention lines and surrounding control | A fixed window misses remote control; syntax-tree ancestry still does not cover callers, variable definitions, imports, sourced files, and environment dependencies | Potentially smaller scopes, but language-dependent complexity and less predictable false positives/negatives |
| Keep whole-file implicit wiring protection | Preserves same-file control flow, but does not automatically protect external implementations, settings, or environment; literal-name detection is not complete discovery | Comments, fixtures, and diagnostic edits can require a new whole-file candidate record |
| Separate a small protected wrapper from an optional diagnostic child payload and existing operation gates | Moving mandatory decision logic into the child would merely move the weakness; a child process is not a privilege boundary | Can localize stable control code if the payload cannot choose whether the real gate runs or how failure is interpreted |

Cross-cutting observations returned in that discussion:

- Independent protection sources should remain additive. A narrower implicit
  wiring rule must not subtract `authority:file`, manifest, marker, or canonical
  reference protection.
- Adding an opt-in marker that removes existing whole-file protection is itself
  a rule-scope change and requires the corresponding decision.
- Marker grammar becomes a critical boundary if the surrounding file is no
  longer protected. Duplicate IDs, missing ends, and ambiguous nesting must not
  hide an earlier protected block.
- A comment may be mere explanation, a marker, a canonical reference, or input
  consumed by a generator. Blindly stripping comment-looking text is unsafe.
- Heredoc content used as output is different from heredoc content executed by
  a shell or interpreter. `source` and `eval` can turn apparent data back into
  executable control.
- A small wrapper must retain mandatory gate selection, invocation conditions,
  and failure behavior. Optional diagnostic output must not authorize bypass,
  replace gate success, or be evaluated as shell code.
- A canary reports diagnostic evidence about a fixture. It is not the gate for
  a later real edit or commit and does not authorize that operation.
- Process separation alone does not stop a child with the same filesystem
  privileges from modifying enforcement files. Existing independent locks and
  operation gates remain necessary.

These points remain proposal material unless adopted through the appropriate
decision process. They are not new normative rules established by this record.

## Unsaved scripts and unavailable original logs

| Experiment family | What can be recovered from this record | What was not preserved |
|---|---|---|
| Predicate/authority and symlink fixtures | Synthetic arrangements, observed classifications, corrected boundary, and supplied regression locations | Original stdin harness files and a durable full stdout log |
| Native patch-byte comparison | Case types, the exact reported newline counterexample, comparison count, authorization controls | Deleted prediction JSON files, native output fixtures, original full harness source as a saved file |
| Pathspec experiments | Commands, staged/worktree arrangements, native Git outcomes, and expected classification | Original disposable repositories and complete standalone experiment scripts |
| Working-directory adapter experiments | Event dimensions, tested invocation categories, reasons for allow/deny, and limited result count | Original standalone harness and full durable event/result log |
| Diagnostic and wiring design feedback | The returned design concerns and their unadopted status | No reviewer diagnostic script, runtime log, performance result, or implementation existed |

The supplied engine and hook regression sources are the preserved executable
examples. The original independent scripts remain **unsaved, not
reconstructed**. Any future reconstruction must be labeled as such and must not
be represented as the original executed artifact.

## Limits carried forward

No round established universal natural-language authorization, complete shell
interpretation, all Git option semantics, all transcript transport formats,
OS-level isolation, production installation, persisted trust, or live dispatch.
Candidate hashes and fixture success are evidence with scope, not adoption or
permission. Later performance changes and the final wiring-scope decision were
handed to a different work context and are outside this record.
