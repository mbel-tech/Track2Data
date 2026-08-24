<#
.SYNOPSIS
    Authenticode-sign one file with the certificate held in CI secrets.

.DESCRIPTION
    Called twice by .github/workflows/release.yml: once for the raw
    PyInstaller Track2Data.exe (before Inno Setup wraps it, so the
    wrapped payload is signed too) and once for the resulting
    Track2Data-setup.exe.

    Reads CERT_PFX (base64-encoded .pfx) and CERT_PASSWORD from the
    environment rather than taking them as parameters, so the values
    never appear in a process-listing or in the workflow log.

    A timestamp is mandatory, not optional: without one, every signature
    this produces stops validating the day the certificate expires,
    rather than remaining valid for binaries signed while it was live.

.NOTES
    This is the generic signtool path, which works with any exportable
    .pfx. Certificates issued after the CA/Browser Forum's June 2023
    key-storage rules generally CANNOT be exported to a .pfx -- they live
    on a hardware token or in a cloud HSM, and need their provider's own
    signing action instead. See docs/CODE_SIGNING.md, which covers both.

    UNVERIFIED: this script has never run against a real certificate --
    the project has none yet. Treat the first signed build as the test.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    # DigiCert's timestamp server is free and does not require being their
    # customer. Any RFC-3161 responder works.
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Path)) {
    throw "Nothing to sign: $Path does not exist"
}

if (-not $env:CERT_PFX) {
    throw "CERT_PFX is not set; this script must not be called without signing credentials"
}

$pfxPath = Join-Path $env:RUNNER_TEMP "codesign.pfx"

try {
    [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:CERT_PFX))

    $signtool = Get-ChildItem `
        -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin" `
        -Filter "signtool.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "x64" } |
        Select-Object -First 1

    if (-not $signtool) {
        throw "signtool.exe not found in the Windows SDK on this runner"
    }

    Write-Host "Signing $Path"
    & $signtool.FullName sign `
        /f $pfxPath `
        /p $env:CERT_PASSWORD `
        /fd sha256 `
        /tr $TimestampUrl `
        /td sha256 `
        /v `
        $Path
    if ($LASTEXITCODE -ne 0) { throw "signtool sign failed with exit code $LASTEXITCODE" }

    & $signtool.FullName verify /pa /v $Path
    if ($LASTEXITCODE -ne 0) { throw "signtool verify failed with exit code $LASTEXITCODE" }
}
finally {
    # Remove the decoded key even if signing threw -- the runner's temp
    # directory outlives this step.
    if (Test-Path $pfxPath) {
        Remove-Item $pfxPath -Force
    }
}
