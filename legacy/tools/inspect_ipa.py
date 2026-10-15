import zipfile, plistlib, json
z = zipfile.ZipFile('tools/MagiCAM.ipa')
data = z.read('Payload/MagiCAM.app/Info.plist')
pl = plistlib.loads(data)
print(json.dumps(pl, indent=2))
