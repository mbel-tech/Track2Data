# Release checklist (signed releases)

Everything below that can be automated is; the steps marked **maintainer** need
accounts, certificates or keys that only the project owner holds. Background and
per-platform detail: [`CODE_SIGNING.md`](CODE_SIGNING.md).

## One-time setup (maintainer)

1. Confirm a first public release exists on the Releases page. SignPath's free
   OSS programme requires a published release before it will issue a certificate.
2. Apply for Windows signing (SignPath Foundation) and/or obtain the macOS
   Developer ID certificate; generate the GPG key for the Linux AppImage
   (`CODE_SIGNING.md` §3).
3. Add the repository secrets listed in `CODE_SIGNING.md` §3 / §4. Set **all**
   secrets for a platform or **none**: a partial set fails the release job early
   (see below) instead of half-signing.
4. Publish the GPG public key somewhere users can fetch it.

## Before every release

- [ ] `CHANGELOG.md` `[Unreleased]` moved under the new version; version bumped
      (`tests/test_version_consistency.py` guards the places that must agree).
- [ ] `CI passed` is green on the commit to be tagged.
- [ ] Optional dry run of the credential check, locally or in a scratch workflow:
      `python packaging/check_signing_readiness.py` prints `sign`, `skip` or
      `partial` per platform (names only, never values; exit 1 on `partial`).

## Tag and publish

- [ ] Push the tag; `release.yml` builds the three platforms, signs the ones whose
      secrets are complete, and publishes `SHA256SUMS.txt`.
- [ ] Read the *Detect available signing credentials* step output: each platform
      should say `sign` (or `skip` on purpose).

## Verify what was published

```bash
python packaging/verify_release.py Track2Data-setup.exe --sums SHA256SUMS.txt
python packaging/verify_release.py Track2Data-x86_64.AppImage \
    --sums SHA256SUMS.txt --sig Track2Data-x86_64.AppImage.asc
```

Then the platform checks from `CODE_SIGNING.md` §5 (`Get-AuthenticodeSignature`,
`codesign --verify`, `spctl --assess`).

## Known risks on the first signed run

The signing steps have never run against a real certificate, so expect to iterate:

- `signtool /f <pfx>` cannot sign with certificates issued after mid-2023, which
  must live on a hardware token or cloud HSM; SignPath's own action replaces the
  `.pfx` route in that case.
- `codesign --deep` is discouraged by Apple; if notarisation rejects the bundle,
  sign nested binaries individually, innermost first.
- `appimagetool` is downloaded unpinned in `release.yml`; pin a release and
  checksum once the first successful build is known.
