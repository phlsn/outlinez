"""Ersteinrichtung der Mac-App: Fenster mit Fortschritt, Rate, Restzeit und Abbrechen
(nur Standardbibliothek). Lädt Pakete und KI-Modelle nach DATA, setzt abgebrochene Downloads
beim nächsten Start fort und merkt sich die Version.

firstrun.py RESOURCES DATA [--headless]
"""

import queue
import sys
import threading
import traceback
from pathlib import Path

from fetch import Cancelled, Setup

RES, DATA = Path(sys.argv[1]), Path(sys.argv[2])
HEADLESS = "--headless" in sys.argv
VERSION = (RES / "VERSION").read_text().strip()
LOG = DATA / "setup.log"


def make_setup(report, cancel) -> Setup:
    return Setup(RES / "app" / "manifest.json", DATA / "models", DATA / "venv", RES / "bin" / "uv",
                 DATA / "downloads", report, cancel)


def finish_ok():
    (DATA / "venv" / ".outlinez-version").write_text(VERSION)


def log(text: str):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


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
    # Tk darf nur aus dem Hauptthread angefasst werden (auf dem Mac blockiert sonst der Download-Thread).
    # Der Download-Thread legt Meldungen deshalb nur in eine Queue, das Fenster holt sie regelmäßig ab.
    messages: queue.Queue = queue.Queue()
    result = {}

    def report(t, permille, text):
        messages.put(("progress", t, permille, text))

    def work():
        try:
            make_setup(report, cancel).run()
            finish_ok()
            messages.put(("done", "ok", ""))
        except Cancelled:
            messages.put(("done", "cancelled", ""))
        except Exception as e:
            log(traceback.format_exc())
            messages.put(("done", "error", str(e)))

    def poll():
        try:
            while True:
                msg = messages.get_nowait()
                if msg[0] == "progress":
                    _, t, permille, text = msg
                    if t:
                        title.config(text=t)
                    if permille is not None:
                        bar.config(value=permille)
                    detail.config(text=text)
                else:
                    finish(msg[1], msg[2])
                    return
        except queue.Empty:
            pass
        root.after(150, poll)

    def finish(status, error):
        result["status"] = status
        if status == "error":
            title.config(text="Einrichtung fehlgeschlagen")
            detail.config(text=f"{error[:120]}\nBitte Internetverbindung prüfen und Outlinez erneut öffnen.")
            button.config(text="Schließen", state="normal", command=root.destroy)
        else:
            root.destroy()

    def ask_cancel():
        if cancel.is_set():
            return
        if messagebox.askyesno("Outlinez", "Einrichtung abbrechen?\n\nBeim nächsten Start geht es an derselben Stelle weiter."):
            cancel.set()
            button.config(text="Wird abgebrochen …", state="disabled")
            # Sicherheitsnetz: falls der Download-Thread nicht reagiert, Fenster trotzdem schließen
            root.after(5000, lambda: (result.setdefault("status", "cancelled"), root.destroy()))

    button.config(command=ask_cancel)
    root.protocol("WM_DELETE_WINDOW", ask_cancel)
    threading.Thread(target=work, daemon=True).start()
    root.after(150, poll)
    root.lift()
    root.attributes("-topmost", True)
    root.after(500, lambda: root.attributes("-topmost", False))
    root.mainloop()
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    try:
        headless() if HEADLESS else gui()
    except SystemExit:
        raise
    except Exception:
        log(traceback.format_exc())
        raise
