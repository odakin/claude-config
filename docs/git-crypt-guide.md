# Encrypting Sensitive Repos with git-crypt

> **日本語版**: [git-crypt-guide.ja.md](git-crypt-guide.ja.md)
>
> **Related**: [sensitive-repo-patterns.md](sensitive-repo-patterns.md) — design patterns for repositories containing sensitive data (filename/commit message hygiene, bootstrap chain design, public-surface minimization). One layer above tool mechanics.

[git-crypt](https://github.com/AGWA/git-crypt) transparently encrypts files in a Git repository. Files are encrypted on push and decrypted on clone/pull, so you work with plaintext locally while GitHub stores ciphertext.

## Quick Start

### 1. Install

```bash
brew install git-crypt    # macOS
sudo apt install git-crypt # Debian/Ubuntu
```

### 2. Initialize in a repo

```bash
cd my-sensitive-repo
git-crypt init
```

This generates a symmetric key inside `.git/git-crypt/`. You need to export it for backup and sharing.

### 3. Export the key

```bash
mkdir -p ~/.secrets
git-crypt export-key ~/.secrets/git-crypt.key
chmod 600 ~/.secrets/git-crypt.key
```

> **Why `~/.secrets/`?** `setup.sh` auto-detects this path and unlocks encrypted repos automatically during bootstrap (Step 5b). If you use a different path, update `setup.sh` accordingly.

> **One key for this repo only?** `setup.sh` tries `~/.secrets/<repo>.key` first and falls back to `~/.secrets/git-crypt.key`. For a repo you may share later, or one that holds other people's personal data, export to `~/.secrets/<repo>.key` instead: sharing it then hands over this repo's key only, with no [rotation](#rotate-key) first.

### 4. Configure `.gitattributes`

Create `.gitattributes` in the repo root to specify which files to encrypt:

```gitattributes
# Encrypt everything by default, whitelist exceptions
* filter=git-crypt diff=git-crypt

# Keep these unencrypted
CLAUDE.md !filter !diff
.gitignore !filter !diff
.gitattributes !filter !diff
```

Or encrypt specific directories only:

```gitattributes
# Encrypt only sensitive directories
data/** filter=git-crypt diff=git-crypt
private/** filter=git-crypt diff=git-crypt
SESSION.md filter=git-crypt diff=git-crypt
```

### 5. Commit, check, and push

Write `.gitattributes` before adding any sensitive file: a file committed before a pattern covers it stays in plaintext in the history.

```bash
git add .gitattributes
git add .  # encrypted files are added normally
git-crypt status
git commit -m "Initial commit (git-crypt encrypted)"
```

`git-crypt status` lists every file as `encrypted:` or `not encrypted:`; only the files you meant to leave readable should be in the second group. Before the first push, confirm that a committed blob really is ciphertext. Check it as a yes/no and never print its bytes, because if encryption failed those bytes are the plaintext. Push only inside the branch where the check passed; a `git push` on its own next line would run after a failed check too:

```bash
if git cat-file -p HEAD:<an encrypted file> | head -c 9 | grep -qa GITCRYPT; then
  echo encrypted && git push
else
  echo "PLAINTEXT - do not push"
fi
```

Files matching the `.gitattributes` patterns are now encrypted on GitHub.

## CLAUDE.md Template

Add this near the top of your repo's `CLAUDE.md`:

```markdown
**⚠️ このリポは private 必須。<reason>を含むため、絶対に public にしないこと。**

**git-crypt 有効。** <files> が読めない場合 → `brew install git-crypt` → `git-crypt unlock ~/.secrets/git-crypt.key`
```

## Using One Key for Multiple Repos

You can reuse the same key across repos instead of generating a new one per repo:

```bash
cd another-repo
git-crypt init           # generates a new key (ignored)
git-crypt unlock ~/.secrets/git-crypt.key  # replaces with your shared key
```

**Trade-off**: Simpler key management, but one compromised key exposes all repos. Acceptable when all repos belong to the same owner and threat model.

## <a id="rotate-key"></a>Rotating the Key (sharing a repo that used a reused key, or someone leaves)

Before sharing a repo that uses a reused key (above) with another person, give that repo its own key (handing over a reused key opens every repo). Do the same when someone leaves or the key may have leaked. Content stays the same; every encrypted file is re-encrypted with the new key:

```bash
# in an unlocked clone with no uncommitted changes
git-crypt status -e | awk '$1=="encrypted:"{print $2}' > /tmp/enc-paths
mkdir -p /tmp/plain && while IFS= read -r p; do mkdir -p "/tmp/plain/$(dirname "$p")"; cp -p "$p" "/tmp/plain/$p"; done < /tmp/enc-paths
git-crypt lock && rm -rf "$(git rev-parse --absolute-git-dir)/git-crypt" && git-crypt init
(cd /tmp/plain && find . -type f | sed 's#^\./##') | while IFS= read -r f; do cp -p "/tmp/plain/$f" "$f"; done
git add --renormalize . && git-crypt status | grep -c WARNING              # 0 = everything encrypted
git-crypt export-key ~/.secrets/<repo>.key && chmod 600 ~/.secrets/<repo>.key
git commit -m "git-crypt: rotate the key (no content change)" && git push
rm -rf /tmp/plain /tmp/enc-paths
```

- Commits before the rotation stay readable only with the old key. To re-encrypt old plaintext versions too, rewrite history ([`sensitive-repo-patterns.md`](sensitive-repo-patterns.md), Pattern 2-5).
- Generate and export keys, and commit the rotation, in the owner's terminal (observed: Claude Code's auto mode blocks key generation as a write to a secret store, and right after the rotation an agent-side check that reads HEAD's encrypted files cannot inspect them).
- Other clones must not pull while still unlocked with the old key: smudging new-key commits fails and changed encrypted files disappear from the worktree (observed). Order: place the new key → `git-crypt lock` → `git pull` (or the follow tool for rewritten history) → `git-crypt unlock ~/.secrets/<repo>.key`. A clone that already broke recovers with `git-crypt lock --force` → `git reset --hard origin/<branch>` → `git-crypt unlock <new key>`. `scripts/git-rewrite-follow.py` stops such a clone before resetting.

## Setting Up on Another Machine

1. Transfer the key file securely (e.g., encrypted backup, direct copy via SSH)
2. Place it at `~/.secrets/git-crypt.key` with `chmod 600`
3. Run `setup.sh` — it auto-detects and unlocks all git-crypt repos

Or unlock manually:

```bash
cd my-sensitive-repo
git-crypt unlock ~/.secrets/git-crypt.key
```

## Key Backup

**The key file is the only way to decrypt your data.** If you lose it and don't have a backup, encrypted files on GitHub are unrecoverable.

Recommended practices:
- **Keep the backup off the machine.** Another folder on the same disk is not a backup, because it is lost together with the machine. Use a place you can open from another device with a separate login (cloud storage, a password manager) or a USB drive.
- **Text form** for a password manager or a note field: `base64 -i ~/.secrets/<repo>.key | pbcopy` on macOS (`base64 -w0 ~/.secrets/<repo>.key` on Linux). Clear the clipboard afterwards with `pbcopy < /dev/null`.
- **Check that the backup restores before relying on it.** This round trip prints nothing secret:
  ```bash
  base64 -D -i <backup file> | cmp - ~/.secrets/<repo>.key && echo match
  ```
  On Linux, use `base64 -d <backup file>`. Making a backup and being able to open it are separate claims ([`secret-handoff.md#backup-round-trip`](../conventions/secret-handoff.md#backup-round-trip)).
- **Restore** with `base64 -D -i <backup file> -o ~/.secrets/<repo>.key && chmod 600 ~/.secrets/<repo>.key`.
- **Record where the backup is (the location, never the value) somewhere readable without the key**, such as the repo's plaintext `CLAUDE.md`. A note inside the encrypted part cannot be read at the moment you need it ([`secret-handoff.md#do-not-store-inside-the-lock`](../conventions/secret-handoff.md#do-not-store-inside-the-lock)).
- If you encrypt the backup itself, use a strong passphrase and keep the passphrase apart from the backup.
- Test restoration periodically

## Troubleshooting

### Files appear as binary after clone

The repo is locked. Run `git-crypt unlock ~/.secrets/git-crypt.key`.

### `git-crypt: command not found` during git operations

The git filter uses an absolute path to `git-crypt`. Check `.git/config`:

```ini
[filter "git-crypt"]
    smudge = "git-crypt" smudge
    clean = "git-crypt" clean
    required = true
```

If the path is absolute (e.g., `/usr/local/Cellar/git-crypt/0.8.0/bin/git-crypt`), update it after reinstalling or upgrading git-crypt.

### `setup.sh` doesn't unlock my repos

Step 5b only runs when both conditions are met:
- `git-crypt` is installed
- `~/.secrets/git-crypt.key` exists

If either is missing, the step is silently skipped.
