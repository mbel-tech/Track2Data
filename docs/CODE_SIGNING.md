# Code signing

How to turn on signed Track2Data releases, and why they are not on yet.

Everything described here is already wired into
[`.github/workflows/release.yml`](../.github/workflows/release.yml). No
workflow edits are needed to enable signing — each platform's signing
steps activate the moment the corresponding repository secrets exist,
and are skipped entirely when they don't. Enabling signing is a
secrets-only change.

---

## 1. Why releases are unsigned today

Not an oversight, and not purely a cost decision. There is a sequencing
constraint that cannot be worked around:

> **SignPath Foundation** — the standard free code-signing route for
> open-source projects — requires that *"the project must already be
> released in the form that should be signed"*, and that executables
> have "verifiable reputation".
> ([signpath.org/terms](https://signpath.org/terms))

So the first Track2Data release is necessarily unsigned. It is the
release that makes the project eligible to apply for free signing.
Attempting to sign before publishing anything is not a matter of effort
or budget — the free route is closed until a public release exists.

This is why [`docs/TECHNICAL_SPEC.md`](TECHNICAL_SPEC.md) §10.3 plans
v1.0 as unsigned with signing in v1.1, and why the README documents the
per-OS trust path for unsigned binaries.

**What unsigned actually costs the user:** a SmartScreen warning on
Windows, a Gatekeeper block on macOS needing a right-click → Open, and
nothing at all on Linux. Every release publishes SHA-256 sums so a
download can still be verified. This is a friction problem, not a
security hole — but it is real friction for non-technical researchers,
which is the reason to fix it.

---

## 2. Recommended order

1. **Cut the first release unsigned.** Nothing below is possible before
   this.
2. **Linux GPG signing — do this immediately after.** It is free,
   needs no third party, and no approval process. See §3.3.
3. **Apply to SignPath Foundation for Windows signing** once the project
   has a release and some usage history. Free, and covers the platform
   where the warning is worst. See §3.1.
4. **Decide on macOS separately.** There is no free route — Apple
   charges $99/year with no open-source exemption. See §3.2.

Windows first is deliberate: SmartScreen on an unsigned installer is the
scariest-looking warning of the three, and it is the one with a free fix.

---

## 3. Per-platform setup

### 3.1 Windows (Authenticode)

**Options, cheapest first:**

| Route | Cost | Notes |
|---|---|---|
| [SignPath Foundation](https://signpath.org/apply) | free | For OSS. Requires an existing release (§1). Certificate is held by the Foundation, which signs on the project's behalf. |
| [Certum Open Source](https://certum.store/open-source-code-signing-code.html) | ~€70–100/yr | Cheap, but requires identity verification and ships on a hardware token. |
| [Azure Trusted Signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) | ~$10/mo | Microsoft-managed. Eligibility has historically required a multi-year verifiable organisation history — check before relying on it. |
| Traditional OV/EV cert | $200–600/yr | No advantage here over the above. |

**Important:** since the CA/Browser Forum's June 2023 key-storage rules,
most newly issued certificates **cannot be exported to a `.pfx`** — the
private key lives on a hardware token or in a cloud HSM. The generic
`signtool` path in
[`packaging/sign_windows.ps1`](../packaging/sign_windows.ps1) therefore
only works with a certificate you can actually export.

SignPath and Azure Trusted Signing both provide their own GitHub Action
instead. If you take either route, replace the two
`./packaging/sign_windows.ps1` calls in `release.yml` with that
provider's action — the surrounding step ordering stays correct as-is.

**Secrets for the `.pfx` route:**

| Secret | Value |
|---|---|
| `WINDOWS_CERT_PFX_BASE64` | The `.pfx`, base64-encoded: `base64 -w0 cert.pfx` |
| `WINDOWS_CERT_PASSWORD` | Its export password |

### 3.2 macOS (Developer ID + notarisation)

Requires [Apple Developer Program](https://developer.apple.com/programs/)
membership — **$99/year, with no free or open-source tier**. This is the
only route; unlike Windows, there is no sponsored alternative.

From the Developer portal, create a **Developer ID Application**
certificate (not "Mac App Distribution" — that is for the App Store),
export it as a `.p12`, and create an
[app-specific password](https://support.apple.com/en-us/102654) for
notarisation.

| Secret | Value |
|---|---|
| `MACOS_CERTIFICATE_P12` | The `.p12`, base64-encoded |
| `MACOS_CERTIFICATE_PASSWORD` | Its export password |
| `MACOS_SIGNING_IDENTITY` | e.g. `Developer ID Application: Jane Doe (AB12CD34EF)` |
| `MACOS_NOTARY_APPLE_ID` | The Apple ID email |
| `MACOS_NOTARY_PASSWORD` | The app-specific password |
| `MACOS_NOTARY_TEAM_ID` | The 10-character Team ID |

Notarisation needs the **hardened runtime**, which by default breaks a
PyInstaller bundle. The entitlements that fix it live in
[`packaging/entitlements.plist`](../packaging/entitlements.plist), each
one annotated with the specific failure it addresses. If notarisation
still rejects a build, `xcrun notarytool log <submission-id>` returns
the precise reason — usually a bundled binary that needs signing too.

### 3.3 Linux (detached GPG signature)

Free, and the only one you can do entirely yourself right now.

```bash
# Generate a signing key (once)
gpg --full-generate-key

# Export the private key for CI
gpg --armor --export-secret-keys YOUR_KEY_ID
```

| Secret | Value |
|---|---|
| `GPG_PRIVATE_KEY` | The ASCII-armoured private key |
| `GPG_PASSPHRASE` | Its passphrase |

Publish the **public** key so users can verify — the release notes
should link to it, and it is worth putting on a keyserver.

The `.AppImage` itself is signed detached, so its bytes stay identical
to what the published SHA-256 sum covers; the signature travels as a
sibling `.asc` file, attached to the release automatically when present.

---

## 4. Adding the secrets

Repository → Settings → Secrets and variables → Actions → New repository
secret. Add only the ones for the platform you are enabling; the others
stay skipped.

For base64-encoding a certificate:

```bash
base64 -w0 certificate.p12    # Linux
base64 -i certificate.p12     # macOS
```

Never commit a certificate, key, or password to the repository — the
workflow reads all of them from secrets, and the signing steps
deliberately pass them via environment variables rather than
interpolating them into shell commands, so they cannot leak into a
workflow log.

---

## 5. Verifying a signed release

```bash
# Windows (PowerShell)
Get-AuthenticodeSignature .\Track2Data-setup.exe | Format-List

# macOS -- the second command is the one that proves notarisation
codesign --verify --deep --strict --verbose=2 /Applications/Track2Data.app
spctl --assess --type execute --verbose /Applications/Track2Data.app

# Linux
gpg --verify Track2Data-x86_64.AppImage.asc Track2Data-x86_64.AppImage
```

---

## 6. Status

| Platform | Implemented | Verified against a real certificate |
|---|---|---|
| Windows | yes (`packaging/sign_windows.ps1`) | **no** |
| macOS | yes (in `release.yml`) | **no** |
| Linux GPG | yes (in `release.yml`) | **no** |

The signing steps have been validated only in the sense that they are
syntactically correct (`actionlint` clean) and that they skip cleanly
when no secrets are configured, leaving the unsigned release path
working. **None has ever run against a real certificate**, because the
project has none. Treat the first signed release as the real test, and
expect to iterate — notarisation in particular usually needs a round or
two.
