"""Build Windows executables with PyInstaller.

    python -m pip install pyinstaller
    python packaging/build.py

Produces:
    dist/BetterMechanic.exe                     single file (unpacks itself on start)
    dist/BetterMechanic-<version>-win64.zip     portable folder (starts faster)
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from bettermechanic import __version__  # noqa: E402

# Qt modules the app never uses: keeps the download small.
EXCLUDES = ['PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtPdf',
            'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtMultimedia', 'PySide6.Qt3DCore',
            'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
            'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtBluetooth', 'PySide6.QtPositioning',
            'tkinter', 'unittest', 'pydoc']


def version_file(path):
    v = tuple(int(x) for x in (__version__.split('.') + ['0', '0', '0'])[:4])
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'BetterMechanic'),
    StringStruct('FileDescription', 'BetterMechanic photo culling and tagging'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', 'BetterMechanic'),
    StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
    StringStruct('OriginalFilename', 'BetterMechanic.exe'),
    StringStruct('ProductName', 'BetterMechanic'),
    StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")


def pyinstaller(onefile, work):
    os.makedirs(work, exist_ok=True)
    vf = os.path.join(work, 'version.txt')
    version_file(vf)
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
            '--name', 'BetterMechanic', '--icon', os.path.join(HERE, 'icon.ico'),
            '--version-file', vf,
            '--add-data', f'{os.path.join(ROOT, "bettermechanic", "assets")}{os.pathsep}bettermechanic/assets',
            '--workpath', os.path.join(work, 'build'), '--specpath', work,
            '--distpath', os.path.join(work, 'dist'),
            '--onefile' if onefile else '--onedir']
    for m in EXCLUDES:
        args += ['--exclude-module', m]
    args.append(os.path.join(HERE, 'launcher.py'))
    subprocess.run(args, check=True, cwd=ROOT)
    return os.path.join(work, 'dist')


def main():
    dist = os.path.join(ROOT, 'dist')
    work = os.path.join(ROOT, 'build')
    shutil.rmtree(dist, ignore_errors=True)
    os.makedirs(dist)
    out = pyinstaller(True, os.path.join(work, 'onefile'))
    shutil.copy2(os.path.join(out, 'BetterMechanic.exe'), os.path.join(dist, 'BetterMechanic.exe'))
    out = pyinstaller(False, os.path.join(work, 'onedir'))
    folder = os.path.join(dist, f'BetterMechanic-{__version__}-win64')
    shutil.copytree(os.path.join(out, 'BetterMechanic'), folder)
    shutil.copy2(os.path.join(ROOT, 'LICENSE'), folder)
    shutil.make_archive(folder, 'zip', dist, os.path.basename(folder))
    # the Lightroom Classic plugin on its own (the app installs it too)
    plugin = os.path.join(ROOT, 'bettermechanic', 'assets', 'BetterMechanic.lrplugin')
    shutil.make_archive(os.path.join(dist, f'BetterMechanic-Lightroom-Plugin-{__version__}'), 'zip',
                        os.path.dirname(plugin), os.path.basename(plugin))
    for f in sorted(os.listdir(dist)):
        p = os.path.join(dist, f)
        if os.path.isfile(p):
            print(f'{f}: {os.path.getsize(p) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
