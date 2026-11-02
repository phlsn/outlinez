; Windows-Installer für Outlinez. Wird von build_windows.ps1 aufgerufen (setzt AppVersion und Stage).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Stage
  #define Stage "..\build\stage"
#endif

[Setup]
AppId={{6B0E3C1A-2F5D-4E7B-9A41-0D3C8E5F7A21}
AppName=Outlinez
AppVersion={#AppVersion}
AppVerName=Outlinez {#AppVersion}
AppPublisher=Outlinez
DefaultDirName={autopf}\Outlinez
DisableProgramGroupPage=yes
DisableDirPage=auto
; Standard: für alle Benutzer nach Program Files (Adminrechte). Ohne Adminrechte kann im
; Setup „nur für mich“ gewählt werden, dann landet alles in %LOCALAPPDATA%\Programs.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Outlinez-Setup-{#AppVersion}
SetupIconFile=..\assets\outlinez.ico
UninstallDisplayIcon={app}\assets\outlinez.ico
UninstallDisplayName=Outlinez
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
#ifdef Sign
SignTool=signtool
SignedUninstaller=yes
#endif

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.DesktopIcon=Verknüpfung auf dem Desktop anlegen
en.DesktopIcon=Create a desktop shortcut
de.Launch=Outlinez starten
en.Launch=Launch Outlinez
de.SetupTitle=Ersteinrichtung
en.SetupTitle=First-time setup
de.SetupDesc=Komponenten und KI-Modelle werden geladen (ca. 5 GB). Das dauert je nach Verbindung einige Minuten.
en.SetupDesc=Downloading components and AI models (about 5 GB). This takes a few minutes depending on your connection.
de.SetupFailed=Die Ersteinrichtung ist fehlgeschlagen (Code %1). Bitte Internetverbindung prüfen und das Setup erneut ausführen.%n%nProtokoll: %2
en.SetupFailed=First-time setup failed (code %1). Please check your internet connection and run setup again.%n%nLog: %2
de.NoWebView=Outlinez braucht die Microsoft Edge WebView2 Runtime, die auf diesem PC fehlt. Nach der Installation öffnet sich die Download-Seite.
en.NoWebView=Outlinez needs the Microsoft Edge WebView2 Runtime, which is missing on this PC. The download page will open after installation.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Outlinez"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\outlinez.ico"; AppUserModelID: "Outlinez.App"
Name: "{autodesktop}\Outlinez"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\outlinez.ico"; AppUserModelID: "Outlinez.App"; Tasks: desktopicon

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: postinstall nowait skipifsilent runasoriginaluser
Filename: "https://developer.microsoft.com/microsoft-edge/webview2/"; Flags: shellexec postinstall skipifsilent runasoriginaluser; Check: not HasWebView2

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.uv-cache"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\setup.log"
Type: dirifempty; Name: "{app}"

[Code]
const
  WebViewKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebViewKey32 = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  SetupPage: TOutputMarqueeProgressWizardPage;
  SetupLog: TStringList;

function HasWebView2: Boolean;
var
  Version: String;
begin
  Result := (RegQueryStringValue(HKLM, WebViewKey32, 'pv', Version) or RegQueryStringValue(HKCU, WebViewKey, 'pv', Version)
             or RegQueryStringValue(HKLM, WebViewKey, 'pv', Version)) and (Version <> '') and (Version <> '0.0.0.0');
end;

procedure InitializeWizard;
begin
  SetupPage := CreateOutputMarqueeProgressPage(CustomMessage('SetupTitle'), CustomMessage('SetupDesc'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if not HasWebView2 then
    MsgBox(CustomMessage('NoWebView'), mbInformation, MB_OK);
  Result := '';
end;

procedure OnSetupOutput(const S: String; const Error, FirstLine: Boolean);
begin
  SetupLog.Add(S);
  if Trim(S) <> '' then
    SetupPage.SetText(CustomMessage('SetupTitle'), Trim(S));
  SetupPage.Animate;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  LogFile: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  LogFile := ExpandConstant('{app}\setup.log');
  SetupLog := TStringList.Create;
  SetupPage.Show;
  try
    if not ExecAndLogOutput(ExpandConstant('{cmd}'), '/C ""' + ExpandConstant('{app}\setup.cmd') + '""',
                            ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode, @OnSetupOutput) then
      ResultCode := -1;
    SetupLog.SaveToFile(LogFile);
    if ResultCode <> 0 then
      MsgBox(FmtMessage(CustomMessage('SetupFailed'), [IntToStr(ResultCode), LogFile]), mbError, MB_OK);
  finally
    SetupPage.Hide;
    SetupLog.Free;
  end;
end;
