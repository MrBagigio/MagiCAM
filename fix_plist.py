import plistlib
import pathlib

plist_path = pathlib.Path(r'tmp_extract/Payload/MagiCAM.app/Info.plist')

try:
    with open(plist_path, 'rb') as f:
        data = plistlib.load(f)
    
    print("Original keys:", list(data.keys()))
    
    if 'CFBundleExecutable' not in data:
        print("MISSING CFBundleExecutable. Adding it...")
        data['CFBundleExecutable'] = 'MagiCAM'
        
        with open(plist_path, 'wb') as f:
            plistlib.dump(data, f)
        print("Fixed Info.plist saved.")
    else:
        print("CFBundleExecutable already exists:", data['CFBundleExecutable'])

    # Verify
    with open(plist_path, 'rb') as f:
        newdata = plistlib.load(f)
        if 'CFBundleExecutable' in newdata:
             print("Verification: CFBundleExecutable is present:", newdata['CFBundleExecutable'])
        else:
             print("Verification FAILED.")

except Exception as e:
    print(f"Error: {e}")
