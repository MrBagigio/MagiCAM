import zipfile
z=zipfile.ZipFile('tools/MagiCAM.ipa')
info=z.getinfo('Payload/MagiCAM.app/MagiCAM')
print('compressed:', info.compress_size, 'uncompressed:', info.file_size)
with z.open('Payload/MagiCAM.app/MagiCAM') as f:
    head = f.read(8)
    print('head hex:', head.hex())
    print('first bytes:', head)
