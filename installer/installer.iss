; Söyle — Inno Setup script
;
; Compiled via scripts/build_installer.py, which reads the version from
; pyproject.toml and passes it as /DMyAppVersion=x.y.z. Don't run iscc
; on this file directly — the version placeholder would be empty.
;
; Produces: release\Soyle-Setup-<version>.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

; Brand-display name (with umlaut) — shown in installer UI, Start Menu,
; UAC dialog, Add/Remove Programs, tray tooltip.
#define MyAppName        "Söyle"
; ASCII slug — used for filesystem paths, exe filename, and the
; default install directory so command-line tools and scripts don't
; have to deal with the umlaut.
#define MyAppSlug        "Soyle"
#define MyAppPublisher   "Nurgisa Andasbek"
#define MyAppURL         "https://github.com/nurgysa/soyle"
#define MyAppExeName     "Soyle.exe"
; Stable GUID — identifies the product across versions for upgrade/uninstall.
; Fresh v4 UUID generated for the WhisperFlow → Söyle rebrand so that the
; new installer is NOT treated as an upgrade of any earlier WhisperFlow
; install (clean break, separate Add/Remove Programs entry).
#define MyAppId          "{{D0B5701D-4942-4B1A-BE14-73715F9FC2D4}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

; {autopf} resolves to %LocalAppData%\Programs on per-user installs and to
; Program Files on admin installs. One iss file → both scopes.
; Folder uses the ASCII slug (Soyle) so the path is well-behaved for
; command-line tools; the installer UI still shows "Söyle".
DefaultDirName={autopf}\{#MyAppSlug}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

OutputDir=..\release
; Output file uses the ASCII slug — `Soyle-Setup-1.0.0.exe` is friendlier
; for browser downloads and scp/curl than a name with umlaut.
OutputBaseFilename={#MyAppSlug}-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
SetupIconFile=..\src\soyle\assets\icon.ico

; Chrome-style minimal wizard: no welcome screen, no directory picker,
; no "ready to install" recap, no Tasks page (we always create the
; desktop shortcut, like Chrome does). The only interactive screens
; left are the progress bar and the "installation complete → Launch"
; checkbox, so the user experiences: double-click → progress → done.
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=no
; Auto-detect UI language from Windows locale (GetUserDefaultUILanguage)
; instead of showing a language picker on the first screen.
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

; x64 only — matches Whisper / CUDA / PySide6 wheels we bundle.
; `x64compatible` also allows ARM64 Windows 11 (x64 emulation).
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Windows 10 1809+ (October 2018) is the baseline for modern WinRT APIs,
; for the bundled UCRT, and for the version of ctranslate2 we ship.
; This line also gates Windows 11 (10.0.22000+) — no extra check needed.
MinVersion=10.0.17763

; Default to a per-user install: no admin required, works on locked-down
; corporate / school machines, and matches the user-scoped nature of the
; app (HKCU autostart entry, %APPDATA% config, Credential Manager key).
; Users who want a system-wide install can pick "Install for all users"
; in the first-screen dropdown, which triggers UAC and flips {autopf}
; to Program Files.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; Keep the same scope (per-user vs all-users) on upgrade installs so
; users don't accidentally end up with two copies.
UsePreviousPrivileges=yes

; If a previous install is still running, shut it down instead of
; demanding a reboot to replace the locked exe.
CloseApplications=force
RestartApplications=no

; The signing configuration is intentionally omitted until an Authenticode
; cert is in place. Without it Windows SmartScreen will warn on first
; install — users can click "More info → Run anyway". See docs/signing.md.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

; No [Tasks] section: we always create both the Start Menu group and the
; desktop shortcut, matching Chrome's behaviour. This eliminates the
; "Select Additional Tasks" wizard page — one less click for the user.

[Files]
; Bundle the entire PyInstaller --onedir output (uses ASCII slug too).
Source: "..\dist\{#MyAppSlug}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";                 Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"

[Run]
; `runasoriginaluser` drops admin token back to the logged-in user when
; the install was elevated. Required because Söyle uses low-level
; keyboard hooks + SendInput, and Windows UIPI blocks a high-integrity
; process from injecting into the user's foreground apps.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; We intentionally DO NOT touch %APPDATA%\Soyle on uninstall.
; User config, dictionary, API key (keyring), usage.json, and logs
; survive uninstall so re-installs are seamless. A future
; "complete uninstall" checkbox can be added if there's demand.
