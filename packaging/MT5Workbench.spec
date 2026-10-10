# Windows x64 single-file build. Run via build.ps1 from the project root.
from pathlib import Path
import re

from PyInstaller.utils.hooks import collect_all, collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)

root = Path(SPECPATH).parent
version = re.search(r'__version__ = "([\d.]+)"',
                    (root / "src/mt5_workbench/__init__.py").read_text("utf-8")).group(1)
version_parts = tuple(map(int, version.split("."))) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts, mask=0x3f,
                     flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "MT5 Workbench"),
        StringStruct("FileDescription", "MT5 黄金交易工作台"),
        StringStruct("FileVersion", version),
        StringStruct("ProductName", "MT5 Workbench"),
        StringStruct("ProductVersion", version),
        StringStruct("OriginalFilename", "MT5Workbench.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [0x0409, 1200])])],
)
datas, binaries, hiddenimports = collect_all("MetaTrader5")
datas += collect_data_files("mt5_workbench")
a = Analysis([str(root / "packaging/launcher.py")], pathex=[str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports + ["numpy"],
             excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "PySide6.QtWebEngineQuick"], noarchive=False)
# Qt uses Windows' ICU. Unrelated ICU from PATH (e.g. Poppler) can break Qt.
# Filter before embedding the archive: a one-file EXE cannot be patched afterward.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="MT5Workbench",
          debug=False, strip=False, upx=False, console=False, version=version_info)
