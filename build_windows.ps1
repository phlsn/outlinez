# Baut den Windows-Installer dist\Outlinez-Setup-<Version>.exe
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Signieren (optional): Code-Signing-Zertifikat als .pfx angeben
#   $env:OUTLINEZ_CERT = "C:\Pfad\zertifikat.pfx"; $env:OUTLINEZ_CERT_PASSWORD = "..."
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Sign

param([switch]$Sign)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$stage = Join-Path $root "build\stage"

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup fehlt: winget install JRSoftware.InnoSetup" }
$uv = (Get-Command uv -ErrorAction Stop).Source
$version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value

Write-Host "Outlinez $version"
uv lock --check --directory $root
if ($LASTEXITCODE -ne 0) { throw "uv.lock ist nicht aktuell: 'uv lock' ausführen" }

# Dateien für die installierte App zusammenstellen
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force "$stage\bin", "$stage\static", "$stage\assets" | Out-Null
$sources = "app.py", "server.py", "core.py", "effects.py", "export.py", "psd.py", "jobs.py", "paths.py", "cli.py", "setup_models.py",
           "pyproject.toml", "uv.lock", "README.md"
foreach ($f in $sources) { Copy-Item "$root\$f" $stage }
Copy-Item "$root\static\*" "$stage\static"
Copy-Item "$root\assets\outlinez.ico" "$stage\assets"
Copy-Item "$root\installer\setup.cmd", "$root\installer\THIRD-PARTY.txt" $stage
Copy-Item $uv "$stage\bin\uv.exe"

# Python direkt mitliefern: uv würde es sonst beim Installieren laden und dabei eine
# Verzeichnisverknüpfung anlegen, die manche Sicherheitsrichtlinien blockieren (Fehler 448).
cmd /c "uv python install 3.12 >nul 2>&1"   # uv meldet auf stderr; PowerShell 5.1 hielte das für einen Fehler
$pyDir = Get-ChildItem (uv python dir) -Directory -Filter "cpython-3.12.*-windows-x86_64-none" |
    Sort-Object { [version]($_.Name -replace '^cpython-([\d.]+)-.*$', '$1') } | Select-Object -Last 1 -ExpandProperty FullName
if (-not ($pyDir -and (Test-Path "$pyDir\python.exe"))) { throw "Python 3.12 nicht gefunden" }
robocopy $pyDir "$stage\python" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Python konnte nicht kopiert werden" }
New-Item -ItemType File "$stage\.installed" | Out-Null   # schaltet core.py auf Modelle im App-Ordner

$args = @("/DAppVersion=$version", "/DStage=$stage", "/Q")
if ($Sign) {
    if (-not ($env:OUTLINEZ_CERT -and (Test-Path $env:OUTLINEZ_CERT))) { throw "OUTLINEZ_CERT zeigt auf kein Zertifikat" }
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe |
        Where-Object FullName -match "x64" | Sort-Object FullName -Descending | Select-Object -First 1
    $cmd = "`"$($signtool.FullName)`" sign /f `"$env:OUTLINEZ_CERT`" /p `"$env:OUTLINEZ_CERT_PASSWORD`" /fd sha256 /tr http://timestamp.digicert.com /td sha256 `$f"
    $args += "/DSign", "/Ssigntool=$cmd"
}
& $iscc @args "$root\installer\outlinez.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup ist fehlgeschlagen" }

$out = Get-Item "$root\dist\Outlinez-Setup-$version.exe"
Write-Host ("Fertig: {0} ({1:N1} MB)" -f $out.FullName, ($out.Length / 1MB))
