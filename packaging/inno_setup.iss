; Inno Setup script wrapping the PyInstaller-built Track2Data.exe into a
; Windows installer (issue #44). Unsigned for v1.0 -- Authenticode signing
; is deferred to v1.1, see docs/TECHNICAL_SPEC.md §10.3. Build with:
;   iscc packaging\inno_setup.iss
; expects dist\Track2Data.exe (from packaging/track2data.spec) to already
; exist; run after the PyInstaller build step, not standalone.

#define MyAppName "Track2Data"
; Inno Setup cannot import Python, so this is the one place the version
; can't reference track2data/_version.py directly. The release workflow
; passes the real version in with `iscc /DMyAppVersion=x.y.z`; the
; fallback below only applies to a bare local `iscc packaging\inno_setup.iss`
; and is deliberately marked so a stale value is visible rather than
; silently shipping as if it were the real version.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-local"
#endif
#define MyAppPublisher "Track2Data"
#define MyAppURL "https://github.com/mbel-tech/Track2Data"
#define MyAppExeName "Track2Data.exe"

[Setup]
AppId={{B6E1A6E1-8C1A-4B7B-9C3E-2E9E9C1F7A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Track2Data-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=icons\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
