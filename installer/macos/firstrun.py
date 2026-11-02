"""Ersteinrichtung der Mac-App mit kleinem Fortschrittsfenster (nur Standardbibliothek).

firstrun.py RESOURCES DATA [--headless]
Lädt die Python-Pakete (uv sync) und die KI-Modelle nach DATA und merkt sich die Version.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path

RES, DATA = Path(sys.argv[1]), Path(sys.argv[2])
HEADLESS = "--headless" in sys.argv
UV = RES / "bin" / "uv"
STEPS = [
    ("Lade Komponenten (ca. 1 GB) …", [str(UV), "sync", "--frozen", "--no-progress", "--project", str(RES / "app")]),
    ("Lade KI-Modelle (ca. 900 MB) …", [str(DATA / "venv" / "bin" / "python"), str(RES / "app" / "setup_models.py")]),
]


def run(report) -> bool:
    env = {**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
    log = open(DATA / "setup.log", "w", encoding="utf-8")
    for title, cmd in STEPS:
        report(title, "")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=RES / "app")
        for line in proc.stdout:
            log.write(line)
            log.flush()
            if line.strip():
                report(title, line.strip()[:90])
        if proc.wait() != 0:
            report("Einrichtung fehlgeschlagen", f"Bitte Internetverbindung prüfen. Protokoll: {DATA / 'setup.log'}")
            return False
    (DATA / "venv" / ".outlinez-version").write_text((RES / "VERSION").read_text().strip())
    return True


def main():
    if HEADLESS:
        sys.exit(0 if run(lambda t, d: print(t, d, flush=True)) else 1)

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Outlinez")
    root.geometry("460x170")
    root.resizable(False, False)
    tk.Label(root, text="Outlinez wird eingerichtet", font=("Helvetica", 15, "bold")).pack(pady=(22, 4))
    tk.Label(root, text="Einmalig, dauert je nach Verbindung einige Minuten.", fg="#666").pack()
    title = tk.Label(root, text="")
    title.pack(pady=(14, 2))
    detail = tk.Label(root, text="", fg="#888", font=("Helvetica", 10))
    detail.pack()
    bar = ttk.Progressbar(root, mode="indeterminate", length=380)
    bar.pack(pady=8)
    bar.start(12)
    result = {}

    def report(t, d):
        root.after(0, lambda: (title.config(text=t), detail.config(text=d)))

    def work():
        result["ok"] = run(report)
        root.after(0, finish)

    def finish():
        bar.stop()
        if result["ok"]:
            root.destroy()
        else:
            bar.pack_forget()
            tk.Button(root, text="Schließen", command=root.destroy).pack(pady=6)

    threading.Thread(target=work, daemon=True).start()
    root.mainloop()
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
