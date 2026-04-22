; WhisperFlow — Inno Setup script
;
; Compiled via scripts/build_installer.py, which reads the version from
; pyproject.toml and passes it as /DMyAppVersion=x.y.z. Don't run iscc
; on this file directly — the version placeholder would be empty.
;
; Produces: release\WhisperFlow-Setup-<version>.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName      "WhisperFlow"
#define MyAppPublisher "nurgisa"
#define MyAppURL       "https://github.com/nurgisa/whisperflow"
#define MyAppExeName   "WhisperFlow.exe"
; Stable GUID — identifies the product across versions for upgrade/uninstall.
; Regenerate ONLY if doing a major breaking fork.
#define MyAppId        "{{A1F3B2C4-D5E6-47F8-9012-WHISPERFLOW001}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

OutputDir=..\release
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern

; x64 only — matches Whisper / CUDA / PySide6 wheels we bundle.
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Windows 10 1809+ (October 2018) is the baseline for modern WinRT APIs
; and the version of ctranslate2 we bundle.
MinVersion=10.0.17763

PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; The signing configuration is intentionally omitted until an Authenticode
; cert is in place. Without it Windows SmartScreen will warn on first
; install — users can click "More info → Run anyway". See docs/release.md.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Bundle the entire PyInstaller --onedir output.
Source: "..\dist\WhisperFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";                 Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";           Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; We intentionally DO NOT touch %APPDATA%\WhisperFlow on uninstall.
; User config, dictionary, API key (keyring), usage.json, and logs
; survive uninstall so re-installs are seamless. A future
; "complete uninstall" checkbox can be added if there's demand.
