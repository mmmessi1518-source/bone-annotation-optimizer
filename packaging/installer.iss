#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif

[Setup]
AppId={{D7B99389-6C9C-4CF2-8A34-DAE993D7A142}
AppName=Bone Annotation Optimizer
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\BoneAnnotationOptimizer
DefaultGroupName=Bone Annotation Optimizer
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=BoneAnnotationOptimizer-{#AppVersion}-setup-win64
SetupIconFile=..\app.ico
UninstallDisplayIcon={app}\BoneAnnotationOptimizer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\BoneAnnotationOptimizer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Bone Annotation Optimizer"; Filename: "{app}\BoneAnnotationOptimizer.exe"
Name: "{autodesktop}\Bone Annotation Optimizer"; Filename: "{app}\BoneAnnotationOptimizer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BoneAnnotationOptimizer.exe"; Description: "Launch Bone Annotation Optimizer"; Flags: nowait postinstall skipifsilent
