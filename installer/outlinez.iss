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
de.SetupDesc=Komponenten und KI-Modelle werden einmalig geladen (ca. 3,8 GB). Danach läuft Outlinez ohne Internet.
en.SetupDesc=Downloading components and AI models once (about 3.8 GB). Afterwards Outlinez works offline.
de.CancelButton=Abbrechen
en.CancelButton=Cancel
de.CancelConfirm=Download abbrechen? Outlinez wird dann wieder vollständig entfernt.
en.CancelConfirm=Cancel the download? Outlinez will then be removed completely.
de.Cancelling=Wird abgebrochen …
en.Cancelling=Cancelling …
de.CancelledHeading=Installation abgebrochen
en.CancelledHeading=Installation cancelled
de.CancelledText=Outlinez wurde wieder entfernt. Sie können das Setup jederzeit erneut starten.
en.CancelledText=Outlinez has been removed again. You can run setup again at any time.
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
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\app.py"""; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: SetupSucceeded
Filename: "https://developer.microsoft.com/microsoft-edge/webview2/"; Flags: shellexec postinstall skipifsilent runasoriginaluser; Check: SetupSucceeded and not HasWebView2

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\downloads"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\setup.log"
Type: dirifempty; Name: "{app}"

[Code]
const
  WebViewKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebViewKey32 = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  SetupPage: TOutputProgressWizardPage;
  CancelButton: TNewButton;
  SetupLog: TStringList;
  Section: String;
  Cancelled, Failed: Boolean;

function HasWebView2: Boolean;
var
  Version: String;
begin
  Result := (RegQueryStringValue(HKLM, WebViewKey32, 'pv', Version) or RegQueryStringValue(HKCU, WebViewKey, 'pv', Version)
             or RegQueryStringValue(HKLM, WebViewKey, 'pv', Version)) and (Version <> '') and (Version <> '0.0.0.0');
end;

function EnableWindow(hWnd: HWND; bEnable: BOOL): BOOL; external 'EnableWindow@user32.dll stdcall';

function SetupSucceeded: Boolean;
begin
  Result := not (Cancelled or Failed);
end;

function CancelFile: String;
begin
  Result := ExpandConstant('{tmp}\cancel');
end;

procedure CancelClick(Sender: TObject);
begin
  if MsgBox(CustomMessage('CancelConfirm'), mbConfirmation, MB_YESNO) = IDYES then
  begin
    SaveStringToFile(CancelFile, 'x', False);  // fetch.py beendet sich, sobald die Datei auftaucht
    CancelButton.Enabled := False;
    CancelButton.Caption := CustomMessage('Cancelling');
  end;
end;

procedure InitializeWizard;
begin
  SetupPage := CreateOutputProgressPage(CustomMessage('SetupTitle'), CustomMessage('SetupDesc'));
  CancelButton := TNewButton.Create(SetupPage);
  CancelButton.Parent := SetupPage.Surface;
  CancelButton.Caption := CustomMessage('CancelButton');
  CancelButton.Width := ScaleX(110);
  CancelButton.Height := ScaleY(24);
  CancelButton.Left := SetupPage.SurfaceWidth - CancelButton.Width;
  CancelButton.Top := SetupPage.ProgressBar.Top + SetupPage.ProgressBar.Height + ScaleY(16);
  CancelButton.OnClick := @CancelClick;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  if not HasWebView2 then
    MsgBox(CustomMessage('NoWebView'), mbInformation, MB_OK);
  Result := '';
end;

// fetch.py meldet "@@S <Abschnitt>" und "@@P <Promille> <Text>", alles andere ist Protokoll
procedure OnSetupOutput(const S: String; const Error, FirstLine: Boolean);
var
  Rest: String;
  P: Integer;
begin
  // Inno sperrt das Fenster, solange ein Programm läuft; der Abbrechen-Knopf muss aber klickbar sein
  EnableWindow(WizardForm.Handle, True);
  if Copy(S, 1, 4) = '@@S ' then
  begin
    Section := Copy(S, 5, MaxInt);
    SetupPage.SetText(Section, '');
    SetupLog.Add(Section);
  end
  else if Copy(S, 1, 4) = '@@P ' then
  begin
    Rest := Copy(S, 5, MaxInt);
    P := Pos(' ', Rest);
    SetupPage.SetProgress(StrToIntDef(Copy(Rest, 1, P - 1), 0), 1000);
    SetupPage.SetText(Section, Copy(Rest, P + 1, MaxInt));
  end
  else
    SetupLog.Add(S);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  LogFile, Params: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  LogFile := ExpandConstant('{app}\setup.log');
  Params := ExpandConstant('"{app}\fetch.py" --manifest "{app}\manifest.json" --hf-home "{app}\models" ' +
    '--venv "{app}\.venv" --uv "{app}\bin\uv.exe" --work "{app}\downloads" --compile "{app}" ') +
    '--cancel-file "' + CancelFile + '"';
  SetupLog := TStringList.Create;
  Section := CustomMessage('SetupTitle');
  SetupPage.SetProgress(0, 1000);
  SetupPage.Show;
  try
    if not ExecAndLogOutput(ExpandConstant('{app}\python\python.exe'), Params, ExpandConstant('{app}'),
                            SW_HIDE, ewWaitUntilTerminated, ResultCode, @OnSetupOutput) then
      ResultCode := -1;
    SetupLog.SaveToFile(LogFile);
    if ResultCode = 3 then
    begin
      // Abgebrochen: alles wieder entfernen (Dateien, Verknüpfungen, Eintrag in der Programmliste)
      Cancelled := True;
      Exec(ExpandConstant('{uninstallexe}'), '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
           ewWaitUntilTerminated, ResultCode);
    end
    else if ResultCode <> 0 then
    begin
      Failed := True;
      MsgBox(FmtMessage(CustomMessage('SetupFailed'), [IntToStr(ResultCode), LogFile]), mbError, MB_OK);
    end;
  finally
    SetupPage.Hide;
    SetupLog.Free;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and Cancelled then
  begin
    WizardForm.FinishedHeadingLabel.Caption := CustomMessage('CancelledHeading');
    WizardForm.FinishedLabel.Caption := CustomMessage('CancelledText');
  end;
end;
