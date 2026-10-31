; 井然 —— Inno Setup 安装脚本（M41）
; 设计要点：
;   · PrivilegesRequired=lowest：装到 %LOCALAPPDATA%\Programs\井然，免管理员
;   · 数据目录 %LOCALAPPDATA%\井然\store 在程序目录之外，卸载流程不触碰
;     （脚本里刻意不写任何指向它的 [UninstallDelete]）
;   · 保留便携版：安装包只是把同一套文件复制到位 + 建快捷方式

#define AppName "井然"
#define AppVersion "1.2.7"
#define AppExe "井然.exe"
#define AppId "{{4F1C7A20-9E3B-4D6A-8C15-2B7E9A0D3C61}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=井然
DefaultDirName={localappdata}\Programs\井然
DefaultGroupName=井然
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\安装包
OutputBaseFilename=井然_安装程序_{#AppVersion}
SetupIconFile=..\resources\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; 不在卸载时删除任何数据目录（版本库在 %LOCALAPPDATA%\井然\store）
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\build_qml\dist_m103\井然\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\井然"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\井然"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即启动 井然"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只清理安装目录内可能由程序生成的临时文件；绝不列出数据目录
Type: filesandordirs; Name: "{app}\fontcheck.txt"
