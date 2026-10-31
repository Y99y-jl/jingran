# -*- mode: python ; coding: utf-8 -*-
"""pjm_qml PyInstaller spec（M1 冒烟雏形；M7 定稿）。

PoC 坑清单落实状态：
  #1 QML 进包      → datas=[('qml','qml')] + main.py 用 sys._MEIPASS 加载 ✅
  #2 hidden-imports → store.py 抽取后为静态 import，整体消失 ✅（无需任何条目）
  #3 QtNetwork     → 不排除（默认进入）✅
  #4 Qt6OpenGL.dll → 不排除（默认进入）✅
  #6 Basic 风格     → main.py QQuickStyle.setStyle("Basic") ✅
"""

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('qml', 'qml'), ('store.py', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'tkinterdnd2'],   # store.py 零 tkinter：−8MB 收益
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pjm_qml',
    debug=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='pjm_qml',
)
