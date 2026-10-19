from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__


REPOSITORY = "jtpydk5gyh-alt/cshcli"
ARCHIVE_ROOT = f"https://github.com/{REPOSITORY}/archive/refs/heads/main.zip"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_ASSETS = f"https://github.com/{REPOSITORY}/releases/download"
MAX_DOWNLOAD = 80 * 1024 * 1024
CHECKSUMS_NAME = "SHA256SUMS"
SIGNATURE_NAME = "SHA256SUMS.minisig"
PUBLIC_KEY = Path(__file__).with_name("release.pub")


class UpdateUnavailable(Exception):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str):
        raise UpdateUnavailable("a version must be text")
    cleaned = value.strip().lstrip("vV")
    parts = cleaned.split(".")
    if len(parts) != 3:
        raise UpdateUnavailable(f"cannot read {value!r} as a version")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise UpdateUnavailable(f"cannot read {value!r} as a version") from None


def newest_remote_version(opener=urllib.request.urlopen) -> str | None:
    request = urllib.request.Request(
        RELEASES_API, headers={"Accept": "application/vnd.github+json",
                               "User-Agent": "cshcli"})
    try:
        with opener(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise UpdateUnavailable(f"GitHub answered HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("GitHub could not be reached") from None
    except (ValueError, UnicodeError):
        raise UpdateUnavailable("GitHub sent something that is not JSON") from None
    tag = payload.get("tag_name")
    return tag if isinstance(tag, str) else None


def compare(installed: str, published: str | None) -> dict:
    report = {"installed": installed, "published": published,
              "action": "none", "from_main": published is None,
              "assets": RELEASE_ASSETS,
              "detail": ""}
    if published is None:
        report["action"] = "unknown"
        report["detail"] = (
            "No published release. Installing would fetch the head of main, "
            "which is neither versioned nor reviewed.")
        return report
    try:
        left, right = parse_version(installed), parse_version(published)
    except UpdateUnavailable as reason:
        report["action"] = "unknown"
        report["detail"] = f"{reason}."
        return report
    if left == right:
        report["action"] = "current"
        report["detail"] = "The installed version is the published one."
    elif right > left:
        report["action"] = "update"
        report["detail"] = f"{installed} is behind {published}."
    else:
        report["action"] = "ahead"
        report["detail"] = (f"{installed} is newer than the published {published}; "
                            "that is normal when installed from main.")
    return report


def parse_checksums(text: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip(), parts[1].strip().lstrip("*")
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
            digests[name] = digest
    return digests


def fetch_checksums(url: str, opener=urllib.request.urlopen) -> dict[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "cshcli"})
    try:
        with opener(request, timeout=15) as response:
            body = response.read(1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("The checksum file could not be downloaded") from None
    return parse_checksums(body.decode("utf-8", "replace"))


def verify(path: Path, expected: str) -> bool:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == expected.strip().lower()


def download(url: str, destination: Path, opener=urllib.request.urlopen) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "cshcli"})
    try:
        with opener(request, timeout=60) as response:
            payload = response.read(MAX_DOWNLOAD + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateUnavailable("The download could not be completed") from None
    if len(payload) > MAX_DOWNLOAD:
        raise UpdateUnavailable("The download is implausibly large; refusing it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def asset_url(tag: str, name: str) -> str:
    return f"{RELEASE_ASSETS}/{tag}/{name}"


def find_signer() -> str | None:
    found = shutil.which("minisign")
    if found:
        return found
    portable = Path(os.path.expanduser("~")) / "cshcli-tools" / "bin" / \
        "minisign-win64" / "x86_64" / "minisign.exe"
    return str(portable) if portable.exists() else None


def verify_signature(target: Path, signature: Path, public_key: Path = PUBLIC_KEY,
                     signer: str | None = None) -> dict:
    signer = signer or find_signer()
    if not signer:
        return {"valid": False, "detail": "minisign is not installed"}
    if not public_key.is_file():
        return {"valid": False, "detail": f"the public key is missing: {public_key}"}
    if not signature.is_file():
        return {"valid": False, "detail": "the release carries no signature"}
    result = subprocess.run(
        [signer, "-V", "-m", str(target), "-p", str(public_key),
         "-x", str(signature), "-q"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"valid": result.returncode == 0,
            "detail": "" if result.returncode == 0 else result.stderr.strip()[-200:]}


def select_wheel(digests: dict[str, str]) -> str:
    wheels = sorted(name for name in digests if name.endswith(".whl"))
    if not wheels:
        raise UpdateUnavailable("The published release carries no wheel")
    tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    exact = [name for name in wheels if f"-{tag}-" in name]
    if exact:
        return exact[0]
    universal = [name for name in wheels if "py3-none-any" in name]
    if universal:
        return universal[0]
    raise UpdateUnavailable(
        "The published release carries no wheel for this interpreter")


def install(source: Path, expected_digest: str, runner=None) -> dict:
    if not verify(source, expected_digest):
        source.unlink(missing_ok=True)
        raise UpdateUnavailable(
            "The checksum does not match; nothing was installed and the file was removed.")
    command = [sys.executable, "-m", "pip", "install", "--upgrade", str(source)]
    if runner is None:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    else:
        result = runner(command)
    if result.returncode != 0:
        raise UpdateUnavailable(f"pip refused the install: {result.stderr.strip()[-300:]}")
    return {"installed": str(source), "digest": expected_digest,
            "detail": "pip reported success."}


def apply_release(tag: str, destination: Path, opener=urllib.request.urlopen,
                  public_key: Path = PUBLIC_KEY, signer: str | None = None,
                  runner=None, assets: str = RELEASE_ASSETS) -> dict:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    checksums = destination / CHECKSUMS_NAME
    signature = destination / SIGNATURE_NAME
    download(f"{assets}/{tag}/{CHECKSUMS_NAME}", checksums, opener)
    try:
        download(f"{assets}/{tag}/{SIGNATURE_NAME}", signature, opener)
    except UpdateUnavailable:
        raise UpdateUnavailable(
            "The release carries no signature; nothing was installed.") from None
    verdict = verify_signature(checksums, signature, public_key, signer)
    if not verdict["valid"]:
        detail = verdict["detail"] or "the signature does not verify"
        raise UpdateUnavailable(
            f"The release is not signed by this project: {detail}. "
            "Nothing was installed.")
    digests = parse_checksums(checksums.read_text(encoding="utf-8", errors="replace"))
    if not digests:
        raise UpdateUnavailable("The published checksum file lists nothing usable")
    name = select_wheel(digests)
    target = destination / name
    download(f"{assets}/{tag}/{name}", target, opener)
    result = install(target, digests[name], runner)
    result["signature"] = {"verified": True, "key": str(public_key)}
    result["wheel"] = name
    return result


def current_version() -> str:
    return __version__
