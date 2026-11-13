; Inno Setup – gera installer_output\CortesLive-Setup.exe
#define MyAppName "Cortes de Live"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{8D3F6A21-5B7C-4E19-9C4A-2F6E1B7D0A35}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\CortesLive
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\CortesLive.exe
OutputDir=installer_output
OutputBaseFilename=CortesLive-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes
SetupIconFile=assets\icon.ico

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: checkedonce

[Files]
Source: "dist\CortesLive\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\CortesLive.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\CortesLive.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CortesLive.exe"; Description: "Abrir o {#MyAppName}"; Flags: nowait postinstall skipifsilent
