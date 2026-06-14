"""Deliverable ZIP packaging — DESIGN.md §9.6."""
import os
import zipfile

HOW_TO_USE = """QRS HELPER — HOW TO USE THESE FILES
=====================================

card_print.png
    The complete framed card at print quality (300 dpi, 4.25" x 5.5").
    Use this for print applications: flyers, table tents, mailers.

card_print.svg
    The same framed card as a vector file. Open in design programs
    (Adobe Illustrator, Inkscape, Affinity) when you need to scale the
    card to any size without quality loss.

qr_raw.png
    The QR code only, with no card frame. Use this when placing the
    QR code into an existing design or document.

qr_raw.svg
    The QR code only, as a vector file. Best quality for professional
    print work.

Tips
----
- Always test-scan the QR code from a printed proof before mass printing.
- Do not shrink the QR code below 0.8" x 0.8" in print.
- Keep clear space around the QR code so scanners can read it easily.
"""


def build_zip(out_dir, files):
    """files: dict of {archive_name: absolute_path}. Returns zip path."""
    zip_path = os.path.join(out_dir, "package.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in files.items():
            if path and os.path.exists(path):
                zf.write(path, arcname)
        zf.writestr("HOW_TO_USE.txt", HOW_TO_USE)
    return zip_path
