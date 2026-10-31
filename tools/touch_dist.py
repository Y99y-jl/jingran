"""构建后、打包前，把 dist 目录里所有文件的时间戳刷成「现在」。

为什么需要：
    PyInstaller 打包时**保留源文件的修改时间**。如果源码是几天前改的，
    dist 里的文件时间戳就会比已安装目录里的旧。Inno Setup 安装时按
    「目标文件不比源文件旧就跳过」处理，结果新版本装完，那些 QML 文件
    还是旧的——exe 换了、界面没换，是最难发现的一类事故
    （1.1.25 实测：Main.qml / DialogHost.qml / AppComboBox.qml 三个文件
    没更新，界面看起来完全没变化）。

用法：
    python tools/touch_dist.py build_qml/dist_mNN
"""
import os
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python tools/touch_dist.py <dist目录>")
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print("目录不存在:", root)
        return 2
    now = time.time()
    n = 0
    for r, _dirs, files in os.walk(root):
        for f in files:
            try:
                os.utime(os.path.join(r, f), (now, now))
                n += 1
            except OSError:
                pass
    print("已刷新 %d 个文件的时间戳: %s" % (n, root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
