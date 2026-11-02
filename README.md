# Outlinez

Lokaler Ersatz für remove.bg: entfernt Bildhintergründe mit dem Open-Source-Modell
[BiRefNet](https://github.com/ZhengPeng7/BiRefNet) (MIT-Lizenz, auch kommerziell nutzbar).
Alles läuft auf diesem Rechner, keine Bilder verlassen ihn.

## Starten

- **App:** Verknüpfung „Outlinez“ auf dem Desktop oder im Startmenü. Eigenes Fenster, keine Konsole.
  Verknüpfungen neu anlegen: `uv run install.py` (entfernen: `uv run install.py --remove`)
- **Im Browser:** Doppelklick auf `start.bat`, öffnet http://127.0.0.1:7860

## Installer (Windows)

```
powershell -ExecutionPolicy Bypass -File build_windows.ps1
```

Ergebnis: `dist\Outlinez-Setup-<Version>.exe` (ca. 13 MB). Das Setup braucht keine
Administratorrechte, installiert nach `%LOCALAPPDATA%\Programs\Outlinez` und lädt bei der
Installation Python, PyTorch und die KI-Modelle (ca. 5 GB) in den App-Ordner. Danach läuft
Outlinez offline; die Deinstallation entfernt alles wieder. Ohne NVIDIA-Grafikkarte läuft es
auf dem Prozessor (deutlich langsamer).

**Unsigniert** zeigt Windows beim Start des Setups „Der Computer wurde durch Windows geschützt“:
auf „Weitere Informationen“ und dann „Trotzdem ausführen“ klicken.
**Signieren** mit einem Code-Signing-Zertifikat (.pfx):

```
$env:OUTLINEZ_CERT = "C:\Pfad\zertifikat.pfx"; $env:OUTLINEZ_CERT_PASSWORD = "..."
powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Sign
```

Für eine neue Version die `version` in `pyproject.toml` erhöhen und neu bauen; das Setup
aktualisiert eine bestehende Installation.

## Installer (macOS) und Cloud-Build

Die Mac-Version (`Outlinez-<Version>-macOS-arm64.dmg`, Apple Silicon) baut GitHub Actions
(`.github/workflows/build.yml`), zusammen mit dem Windows-Setup:

- **Von Hand:** im Repository unter *Actions → Installer bauen → Run workflow*; die Dateien
  liegen danach unter *Artifacts* des Laufs.
- **Als Release:** `git tag v1.0.0` und `git push --tags` – der Workflow legt ein GitHub-Release
  mit DMG und Setup an.

Auf dem Mac: DMG öffnen, Outlinez in „Programme“ ziehen. Beim ersten Start richtet sich die App
einmalig ein (lädt ca. 2 GB nach `~/Library/Application Support/Outlinez`).
**Unsigniert** meldet macOS, dass die App nicht überprüft werden kann: unter
*Systemeinstellungen → Datenschutz & Sicherheit* auf „Trotzdem öffnen“ klicken.

**Signieren** (optional) über Repository-Secrets:
`MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_PASSWORD`, `MACOS_NOTARY_TEAM_ID`
(Apple Developer Program; das Zertifikat muss im Schlüsselbund des Build-Macs liegen) sowie
`WINDOWS_CERT_BASE64` und `WINDOWS_CERT_PASSWORD` für Windows.

## Funktionen

- Bilder oder ganze Ordner hineinziehen, auswählen oder mit Strg+V einfügen (JPG, PNG, WebP, TIF auch 16 Bit)
- Hintergrund transparent oder Farbe, auf Motiv zuschneiden (inkl. Schatten)
- **Schatten:** Schlagschatten, Bodenschatten oder perspektivisch; Deckkraft, Weichheit, Richtung, Länge
- **Formate:** PNG, WebP, JPG oder **PSD mit Ebenen**:
  - *Motiv* – Bild mit bearbeitbarer Ebenenmaske (nichts ist weggeschnitten)
  - *Schatten* – eigene Ebene, Füllmethode Multiplizieren
  - *Hintergrund* – Farbfläche (nur wenn eine Farbe gewählt ist)
  - *Original* – unbearbeitetes Foto, ausgeblendet
- **Speichern:** neben dem Original (`name-freigestellt.png`) oder in einen festen Ordner
- **Ordner überwachen:** neue Bilder in einem Ordner werden automatisch freigestellt und gespeichert
- Klick auf ein Ergebnis zeigt den Vorher/Nachher-Vergleich

Einstellungen liegen in `%APPDATA%\Outlinez\settings.json`, das Log der App in `app.log` daneben.

## Ganze Ordner per Kommandozeile

```
uv run cli.py C:\Fotos\Shooting
uv run cli.py C:\Fotos\Shooting -o C:\Fotos\freigestellt --crop --margin 3
uv run cli.py C:\Fotos\*.tif --model hr --bg ffffff --format jpg
uv run cli.py C:\Fotos\Produkte --format psd --shadow ground --shadow-opacity 0.6
```

Ohne `-o` landen die Ergebnisse im Unterordner `freigestellt` neben den Bildern.
Bereits vorhandene Ergebnisse werden übersprungen (`--overwrite` erzwingt Neuberechnung).

## Modelle

| Name       | Auflösung | Tempo (RTX 5080, 12 MP) | Wofür                         |
|------------|-----------|-------------------------|-------------------------------|
| `standard` | 1024 px   | ca. 0,3 s               | fast alles                    |
| `hr`       | 2048 px   | ca. 3 bis 8 s           | große Fotos mit feinen Kanten |

Die Modelle werden beim ersten Gebrauch von Hugging Face geladen (je ca. 900 MB) und
liegen danach in `%USERPROFILE%\.cache\huggingface`. Die Versionen sind in `core.py`
festgelegt, damit kein ungeprüfter neuer Code nachgeladen wird.

## Technik

- `core.py`: Bild lesen, Maske mit BiRefNet, Kantenfarben bereinigen (auf der GPU)
- `effects.py`: Schatten aus der Maske, Zusammensetzen der Ebenen
- `psd.py`: PSD-Schreiber mit Ebenenmasken (Dateiformat nach Adobe-Spezifikation)
- `export.py`: Zuschnitt, Hintergrund und Ausgabe als PNG/WebP/JPG/PSD
- `jobs.py`: Bildliste, Warteschlange, Einstellungen, Ordnerüberwachung
- `server.py`: lokaler Server (nur 127.0.0.1, mit Zugangsschlüssel pro Start)
- `app.py`: Programmfenster über pywebview (Edge WebView2)
- `cli.py`: Stapelverarbeitung
- Voraussetzung: [uv](https://docs.astral.sh/uv/); die Umgebung (Python 3.12, PyTorch
  mit CUDA 12.8) richtet `uv` beim ersten Start selbst ein
