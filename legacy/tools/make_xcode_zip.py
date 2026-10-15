"""
Create a zip archive of the Xcode-ready folder for easy download/transfer.
Usage: python make_xcode_zip.py
"""
import zipfile
import os

src = os.path.join(os.path.dirname(__file__), '..', 'swift', 'Xcode-ready')
out = os.path.join(os.path.dirname(__file__), '..', 'swift', 'MagiCAM_Xcode.zip')

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        for f in files:
            fp = os.path.join(root, f)
            arc = os.path.relpath(fp, os.path.join(src, '..'))
            z.write(fp, arc)

print('Created', out)
