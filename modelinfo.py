"""Die KI-Modelle (ohne Abhängigkeiten, damit Build-Skripte es lesen können)."""

MODELS = {
    # name: (Hugging-Face-Repo, festgelegte Version, Eingabeauflösung)
    "standard": ("ZhengPeng7/BiRefNet", "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4", 1024),
    "hr": ("ZhengPeng7/BiRefNet_HR", "a7a562f6fd16021180f2f4348f4de003a2d3d1e1", 2048),
}
