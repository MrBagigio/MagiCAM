import zipfile
import os
import pathlib

def zip_dir(directory, zip_name):
    print(f"Zipping {directory} to {zip_name}...")
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # We want 'Payload' to be at the root of the zip.
        # 'directory' is 'tmp_extract', which contains 'Payload'.
        # So we walk 'tmp_extract' but calculate arcname relative to 'tmp_extract'.
        
        root_path = pathlib.Path(directory)
        
        has_payload = False
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = pathlib.Path(root) / file
                # Calculate archive name relative to tmp_extract root
                arcname = file_path.relative_to(root_path)
                
                # Verify that the first part of the path is 'Payload'
                if str(arcname).startswith("Payload") or str(arcname).startswith("Payload\\") or str(arcname).startswith("Payload/"):
                    has_payload = True
                
                print(f"Adding {arcname}")
                zipf.write(file_path, arcname)
        
        if not has_payload:
            print("WARNING: Payload folder not found in source!")

if __name__ == '__main__':
    if os.path.exists('tools/MagiCAM_repacked_python.ipa'):
        os.remove('tools/MagiCAM_repacked_python.ipa')
    
    # Ensure tmp_extract exists
    if not os.path.exists('tmp_extract'):
        print("Error: tmp_extract folder does not exist.")
    else:
        # Check inside tmp_extract
        if not os.path.exists(os.path.join('tmp_extract', 'Payload')):
             print("Error: tmp_extract/Payload does not exist.")
        else:
             zip_dir('tmp_extract', 'tools/MagiCAM_repacked_python.ipa')
             print("Repack complete: tools/MagiCAM_repacked_python.ipa")
