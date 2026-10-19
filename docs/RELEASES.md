# Releases

How a release is made here, and what it does not cover.

## What the script does

```
python scripts/release.py
```

It refuses rather than warns when it should:

- **Two different versions** between `src/cshcli/__init__.py` and
  `pyproject.toml` abort the build. A release with two versions is not
  reproducible.
- **A dirty working tree** aborts the build. A warning is the kind of thing
  that gets read once and then ignored.

Then it builds the wheel, writes `SHA256SUMS`, and verifies the **installed
copy** in a throwaway directory: it imports the modules, checks that the
version it reports is the one requested, and runs `--help` from the installed
copy rather than from the working tree. Testing the working tree would prove
nothing about the artefact.

## What it deliberately does not do

It does not sign anything, it does not publish anywhere, and it does not verify
the install on Linux, macOS or on Python versions other than the one running
it. Those need a machine and credentials that do not exist on the machine that
writes this file. A release procedure that claims otherwise is worse than one
that admits it, so the script prints the omission on every run.

Publishing is a manual step and stays manual while there is one owner.

## Signing

**The signing key exists.** The owner authorised its creation on 17 October 2026,
and `release.py` now signs by itself.

The public key lives inside the package, at `src/cshcli/release.pub`, and it is
the only part of the pair that ever leaves the owner's machine:

```
untrusted comment: minisign public key 5BECC463E66EA9A4
RWSkqW7mY8TsWwxeoiTSEHYJrTWUbthX8y1Kbnf8fZPW3smL3zue+nXl
```

Anyone can verify a download with that file alone:

```
minisign -Vm dist/SHA256SUMS -p src/cshcli/release.pub
```

Verified on this machine, in both directions, which is the point of doing it at
all:

- The signature on `SHA256SUMS` **verifies** with the published public key.
- A **different** real public key **rejects** it, and minisign says why: the key
  id does not match.
- Changing **one byte** of `SHA256SUMS` invalidates the signature; restoring the
  byte makes it verify again. A signature that cannot detect that is decoration.
- `release.py --require-signature` **refuses** with exit code 1 when no key is
  available, so publishing unsigned is a refusal and not a warning.

`minisign` 0.12 was checked before use: version reported by the binary itself,
and SHA-256 `5535be9e4e123831ebe6ef324aafe9dde507015c176191f9e20c3ad60567f9e1`.
Do that check again on every machine.

**The private key never goes in the repository, in `.cshcli/`, or in a backup
that syncs.** If someone else obtains it, they can sign as this project forever
and nothing downstream can tell the difference. It is password-protected, and
the password is stored beside it rather than inside it, so both files need
moving together.

Signing `SHA256SUMS` and not the wheel is deliberate: one signature covers
every artefact it lists, so adding a file later does not need a new key.

The older key id `RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3`,
formerly published in the README, **is not this project's key** and must not be
used to verify anything here.

## The updater checks the signature, and that changes what it installs

`cshcli update --apply` used to fetch the archive of `main` and compare it
against the first entry of the published checksum file. Two things were wrong
with that, and both mattered.

**It installed the wrong thing.** The checksum file lists every artefact of the
release, and the code took `sorted(digests)[0]` — whatever sorted first, not the
file it had downloaded. The digest it compared against belonged to a different
artefact, so the install was refused by its own checksum, and the URL it asked
for was an archive path that does not serve a single file.

**It trusted the wrong thing.** The checksum and the artefact came from the
same place. That proves the download was not corrupted in transit, and it
proves nothing about **who** published it. A checksum cannot distinguish the
project from anyone who can write to the place the release lives in. Only a
signature can, and the signature existed but nothing consumed it.

Now the updater takes the release's own assets, in this order, and stops at the
first one that fails:

1. `SHA256SUMS` from the release.
2. `SHA256SUMS.minisig` from the release. If it is not there, nothing is
   installed.
3. The signature is verified against the key **inside the installed package**,
   which did not come from the same download.
4. The wheel for this interpreter is chosen out of the signed checksum file,
   and only that file is downloaded.
5. Its checksum is checked against the signed file, and then it is installed.

**What the trust chain is, precisely.** The key in the wheel is the anchor for
every *subsequent* update, provided the copy of cshcli already installed is
itself trusted. For the **first** install there is no such anchor, and the key
has to be obtained out of band: from this repository, from the release page, or
from someone who already has it. That is a property of every project that signs
its releases, and it is why the key is published in the repository and not only
inside the package.

The whole path is proved end to end against a real HTTP server serving real
artefacts in `tests/test_update_end_to_end.py`: a signed release installs, and
a missing signature, an altered checksum file, a wheel that does not match, a
signature from another key and a machine with no `minisign` all install nothing.

## The release refuses a wheel that cannot verify anything

A wheel without `release.pub` installs perfectly, answers `--help`, and then
rejects every release without saying why. `release.py` therefore checks the
**installed** copy, not just the built one, and refuses the release when the
key is not there. The check is proved in both directions: a copy with the key
is accepted, and one without it is refused.

That is also why the key is declared as package data. A key that only lives in
the repository would be invisible to anyone who installed the package.

## `release.py` now signs by itself

That procedure became a flag. Put the key where the script can find it:

```
$env:CSHCLI_SIGNING_KEY = "$HOME/cshcli-tools/cshcli.key"
python scripts/release.py
```

The script finds `minisign` in `PATH`, in `CSHCLI_SIGNER`, or in the portable
copy under `~/cshcli-tools/bin/`, signs `SHA256SUMS`, and prints
`SHA256SUMS.minisig` next to it.

**With no key it still builds, and it says so**, in the same spirit as the rest
of the script: a release nobody asked to sign should not be blocked by it, but
it should never be silent either. To refuse instead:

```
python scripts/release.py --require-signature
```

`tests/test_release_sign.py` signs, verifies, tampers with the file and checks
that verification fails, signs with a second key and checks that the first
public key rejects it. Those four run against the real `minisign` when it is
installed and say why they were skipped when it is not.

## Bumping the version

```
python scripts/bump_version.py 0.6.0
```

It rewrites the version in `src/cshcli/__init__.py`, `pyproject.toml`,
`README.md`, `docs/STATUS.md`, `docs/USAGE.md` and `docs/CONTEXT.md`, and it
refuses rather than guessing:

- a version that is not three numeric parts;
- a version that does not move forward from the current one;
- **any file where its sentence no longer matches exactly once.** If the wording
  in those documents is ever rewritten, the script stops instead of editing a
  document it no longer understands.

`tests/test_bump_version.py` holds that last property in place: it asserts that
every target still matches exactly once in the real repository, so a reworded
document fails a test rather than failing silently at release time.

Still manual afterwards: the `CHANGELOG.md` entry, the `git tag`, and the commit.

## The release history

### 0.4.0 — 16 October 2026

`cshcli start` became a two-option menu that performs the setup, and the
coordinator became implicit, so no server is started first. A local wheel and
`SHA256SUMS` were built and the installed copy exercised; they are not signed or
published.

### 0.3.0 — 15 October 2026

A local wheel and `SHA256SUMS` were built and the installed copy was exercised.
They were not signed or published. The HTTP integration-queue work in the
current working tree is newer than that artefact, so the wheel must be rebuilt
after this work is committed before it can represent the source again.

### 0.2.0 — 15 October 2026

The coordination layer grew past the point where "local pilot" described it
honestly. Runner, task DAG, integration queue, deployments and budgets all
landed; the personal data guard was fixed to read the index instead of the
working tree; and the online plan was written.

Full notes in the [changelog](../CHANGELOG.md).

Verified before tagging: 423 tests pass with 4 skipped and a real SQLite, real
HTTP and a real git repository in every case. The wheel installs and answers
`--help` on Python 3.12.10, Windows.

### 0.1.0 — 14 October 2026

The local pilot: loopback coordinator, SQLite, projects, roles, invitations,
CAS memory, leases with fences, the CLI and the CI.

## Verifying an artefact you did not build

```
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" cshcli-0.2.0-py3-none-any.whl
```

Compare with `SHA256SUMS`. A mismatch means the file is not the one this
repository produced, and it should not be installed.

Checksums say the artefact is intact. They do not say who published it, which
is why signing is listed as not done rather than quietly assumed.