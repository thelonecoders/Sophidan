; ===========================================================================
;  Academic Research Suite — Inno Setup 6 script
;  Produces: AcademicResearchSuite_v2.0.0_Setup.exe
;
;  Build:
;    1. Build the .exe first:  pyinstaller main.spec --clean --noconfirm
;    2. Open this file in Inno Setup Compiler (or run: iscc installer\ars.iss)
;    3. Output: installer\Output\AcademicResearchSuite_v2.0.0_Setup.exe
;
;  Inno Setup 6: https://jrsoftware.org/isdl.php
; ===========================================================================

#define ARSAppname      "Academic Research Suite"
#define ARSAppVersion   "2.0.0"
#define ARSAppPublisher "Academic Research Suite Contributors"
#define ARSAppURL       "https://github.com/your-username/academic-research-suite"
#define ARSAppExeName   "AcademicResearchSuite.exe"

[Setup]
; NOTE: AppId must be unique — generate a fresh GUID with Ctrl+G in Inno Setup
;       before publishing your own fork.
AppId={{8C2A5F31-7B4E-4C3D-9D7B-1F9E2A3C4D5E}
AppName={#ARSAppname}
AppVersion={#ARSAppVersion}
AppVerName={#ARSAppname} {#ARSAppVersion}
AppPublisher={#ARSAppPublisher}
AppPublisherURL={#ARSAppURL}
AppSupportURL={#ARSAppURL}/issues
AppUpdatesURL={#ARSAppURL}/releases
DefaultDirName={pf}\AcademicResearchSuite
DefaultGroupName={#ARSAppname}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#ARSAppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
OutputDir=Output
OutputBaseFilename=AcademicResearchSuite_{#ARSAppVersion}_Setup
LicenseFile=..\LICENSE
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"
Name: "quicklaunchicon"; Description: "Create a &Quick Launch icon"; GroupDescription: "Additional icons:"; Flags: unchecked; OnlyBelowVersion: 0,6.1

[Files]
; Pull in the entire PyInstaller dist folder recursively.
Source: "..\dist\AcademicResearchSuite\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#ARSAppname}"; Filename: "{app}\{#ARSAppExeName}"
Name: "{group}\Uninstall {#ARSAppname}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#ARSAppname}"; Filename: "{app}\{#ARSAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\{#ARSAppname}"; Filename: "{app}\{#ARSAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#ARSAppExeName}"; Description: "{cm:LaunchProgram,{#ARSAppname}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up user data on uninstall — comment out if you want to preserve
; projects/databases across reinstalls.
Type: filesandordirs; Name: "{localappdata}\AcademicResearchSuite"
