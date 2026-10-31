# -*- mode: python ; coding: utf-8 -*-
# 项目文件管家 QML 版 —— PyInstaller 规格（PoC 六坑条款落实，M7 定稿）。
# 坑#1：qml 进包（datas + _MEIPASS）；坑#2：store.py 已独立 → tkinter 隐藏导入消失；
# 坑#3：QtNetwork.dll 必留（QtQml.pyd 硬依赖）；坑#4：Qt6OpenGL 必留；
# 坑#5：裁剪走构建期过滤（spec 内滤 a.datas/a.binaries，逐项后跑 exe 验证）；
# 坑#6：QQuickStyle.setStyle("Basic")（Python 侧，零 conf 依赖）。

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # M17 任务8：resources/（工具栏图标 PNG + app_icon.ico）随包分发，
    # 否则发布包里图标全丢、exe 无文件图标。
    datas=[('qml', 'qml'), ('resources', 'resources')],
    hiddenimports=['difflib', 'unicodedata'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)

# ---- 构建期裁剪过滤（PoC m3_trim.py 清单的声明式版本；Basic 风格保留）----
_TRIM_PATTERNS = [
    'opengl32sw', 'translations', 'qmltooling',
    'PySide6/QtSvg', 'PySide6/Qt6Svg',
    'PySide6/QtTest', 'PySide6/Qt6Test',
    'Qt6Timeline', 'QtTimeline',
    'Qt6VectorImage', 'Qt6Pdf', 'Qt6QuickDialogs2', 'QtQuickDialogs2',
    'Qt/labs', 'Qt6Labs',
    # M41 瘦身：只用 Basic 风格 → 其余 5 套 Controls2 样式（合计约 13.4MB）
    'Qt6QuickControls2Imagine', 'Qt6QuickControls2Material',
    'Qt6QuickControls2Universal', 'Qt6QuickControls2Fusion',
    'Qt6QuickControls2FluentWinUI3', 'Qt6QuickControls2WindowsStyle',
    'Controls/Imagine', 'Controls/Material', 'Controls/Universal',
    'Controls/Fusion', 'Controls/FluentWinUI3', 'Controls/Windows',
    # M41：QtOpenGL 的 Python 绑定不能裁——PySide6.QtQuick 运行时依赖它
    # （实测裁掉后启动即 ImportError: could not import 'PySide6.QtQuick'）
    # M41：全程不联网 → OpenSSL 与 TLS/网络信息插件无入口
    'libcrypto-3', 'libssl-3', 'plugins/tls', 'plugins/networkinformation',
]
_TRIM_KEEP = ('Controls/Basic', 'Qt6Quick.dll', 'QtNetwork.dll', 'Qt6OpenGL')


def _keep_entry(name: str) -> bool:
    n = name.replace('\\', '/')
    if any(k in n for k in _TRIM_KEEP):
        return True
    return not any(t.lower() in n.lower() for t in _TRIM_PATTERNS)


a.datas = [x for x in a.datas if _keep_entry(x[0])]
a.binaries = [x for x in a.binaries if _keep_entry(x[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='井然',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # M17 任务7：exe 文件图标（旧版 app_icon.ico 同源，9 档 16→256）
    icon='resources/app_icon.ico',
    # M74：Windows 版本资源（右键属性→详细信息 可见版本；由 tools/gen_version.py
    # 从 VERSION 生成，别再手改这个 txt）
    version='installer/version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='井然',
)
