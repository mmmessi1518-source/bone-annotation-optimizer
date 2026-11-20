from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent
datas = [(str(ROOT/'app.ico'), '.')]
# Retain dependency metadata/licenses alongside the runtime.
for distribution in ['PyQt5', 'PyQt5-Qt5', 'PyQt5-sip', 'numpy', 'Pillow', 'opencv-python-headless']:
    datas += copy_metadata(distribution)
a = Analysis([str(ROOT/'start.py')], pathex=[str(ROOT)], datas=datas,
             hiddenimports=['bone_optimizer.gui', 'bone_optimizer.cli', 'bone_optimizer.selfcheck'],
             excludes=['labelme', 'torch', 'torchvision', 'matplotlib', 'tkinter', 'PyQt6', 'PySide6'])
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BoneAnnotationOptimizer',
          console=False, icon=str(ROOT/'app.ico'))
cli = EXE(pyz, [('cli_entry', str(ROOT/'scripts/cli_entry.py'), 'PYSOURCE')], [],
          exclude_binaries=True, name='BoneAnnotationOptimizer-cli', console=True, icon=str(ROOT/'app.ico'))
coll = COLLECT(gui, cli, a.binaries, a.datas, name='BoneAnnotationOptimizer')
