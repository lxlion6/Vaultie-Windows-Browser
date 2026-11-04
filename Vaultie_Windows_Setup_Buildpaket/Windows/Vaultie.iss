#define MyAppName "Vaultie"
#define MyAppVersion "3.3"
#define MyAppPublisher "Vaultie"
#define MyAppExeName "Vaultie.exe"

[Setup]
AppId={{D39DDB90-C0A7-4E22-8BE9-5ED45670874D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Vaultie
DefaultGroupName=Vaultie
OutputDir=installer_output
OutputBaseFilename=Vaultie-Setup
SetupIconFile=assets\vaultie.ico
UninstallDisplayIcon={app}\Vaultie.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsedUserAreasWarning=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Files]
Source: "dist\Vaultie\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Place an independent icon outside PyInstaller's _internal directory.
Source: "assets\vaultie.ico"; DestDir: "{app}\Icons"; DestName: "vaultie.ico"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Vaultie"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\Icons\vaultie.ico"
Name: "{userprograms}\Vaultie"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\Icons\vaultie.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Vaultie jetzt starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; No user browsing data deletion: existing local profiles and settings are retained.
Type: filesandordirs; Name: "{app}\_internal"
