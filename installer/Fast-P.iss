#define AppVersion GetEnv("FAST_P_VERSION")
#define AppSourceDir GetEnv("FAST_P_DIST_DIR")
#define InstallerOutputDir GetEnv("FAST_P_INSTALLER_DIR")

[Setup]
AppId={{7DD467B6-8EE8-4C15-A532-C12529772899}
AppName=Fast-P 比价截图工具
AppVersion={#AppVersion}
AppPublisher=Fast-P
DefaultDirName={localappdata}\Programs\Fast-P
DefaultGroupName=Fast-P
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#InstallerOutputDir}
OutputBaseFilename=Fast-P-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\Fast-P.exe
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Fast-P 比价截图工具"; Filename: "{app}\Fast-P.exe"
Name: "{autodesktop}\Fast-P 比价截图工具"; Filename: "{app}\Fast-P.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Fast-P.exe"; Description: "启动 Fast-P"; Flags: nowait postinstall skipifsilent
