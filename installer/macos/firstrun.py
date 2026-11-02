"""Ersteinrichtung der Mac-App: Fenster mit Fortschritt, Rate, Restzeit und Abbrechen
(nur Standardbibliothek). Lädt Pakete und KI-Modelle nach DATA, setzt abgebrochene Downloads
beim nächsten Start fort und merkt sich die Version.

firstrun.py RESOURCES DATA [--headless]
"""

import sys
import threading
from pathlib import Path

from fetch import Cancelled, Setup

RES, DATA = Path(sys.argv[1]), Path(sys.argv[2])
HEADLESS = "--headless" in sys.argv
VERSION = (RES / "VERSION").read_text().strip()


def make_setup(report, cancel) -> Setup:
    return Setup(RES / "app" / "manifest.json", DATA / "models", DATA / "venv", RES / "bin" / "uv",
                 DATA / "downloads", report, cancel)


def finish_ok():
    (DATA / "venv" / ".outlinez-version").write_text(VERSION)


def headless():
    def report(title, permille, text):
        print(title or "", f"{permille / 10:.0f} %" if permille is not None else "", text, flush=True)

    try:
        make_setup(report, threading.Event()).run()
    except Exception as e:
        print("Fehler:", e, flush=True)
        sys.exit(1)
    finish_ok()


def gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("Outlinez")
    root.geometry("520x210")
    root.resizable(False, False)
    tk.Label(root, text="Outlinez wird eingerichtet", font=("Helvetica", 15, "bold")).pack(pady=(20, 2))
    tk.Label(root, text="Einmalig, danach läuft Outlinez ohne Internet.", fg="#666").pack()
    title = tk.Label(root, text="Starte …")
    title.pack(pady=(14, 2))
    bar = ttk.Progressbar(root, mode="determinate", maximum=1000, length=440)
    bar.pack(pady=4)
    detail = tk.Label(root, text="", fg="#777", font=("Helvetica", 11))
    detail.pack()
    button = ttk.Button(root, text="Abbrechen")
    button.pack(pady=10)

    cancel = threading.Event()
    result = {}

    def report(t, permille, text):
        def apply():
            if t:
                title.config(text=t)
            if permille is not None:
                bar.config(value=permille)
            detail.config(text=text)
        root.after(0, apply)

    def ask_cancel():
        if cancel.is_set():
            return
        if messagebox.askyesno("Outlinez", "Einrichtung abbrechen?\n\nBeim nächsten Start geht es an derselben Stelle weiter."):
            cancel.set()
            button.config(text="Wird abgebrochen …", state="disabled")

    def work():
        try:
            make_setup(report, cancel).run()
            finish_ok()
            result["status"] = "ok"
        except Cancelled:
            result["status"] = "cancelled"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        root.after(0, done)

    def done():
        if result["status"] == "error":
            title.config(text="Einrichtung fehlgeschlagen")
            detail.config(text=f"{result['error'][:120]}\nBitte Internetverbindung prüfen und Outlinez erneut öffnen.")
            button.config(text="Schließen", state="normal", command=root.destroy)
        else:
            root.destroy()

    button.config(command=ask_cancel)
    root.protocol("WM_DELETE_WINDOW", ask_cancel)
    threading.Thread(target=work, daemon=True).start()
    root.mainloop()
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    headless() if HEADLESS else gui()
