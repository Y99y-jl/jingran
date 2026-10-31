# -*- coding: utf-8 -*-
"""静默安装 + 等待完成（纯 Python，不调 powershell）。

为什么要这个脚本
----------------
早先的写法是「每 2 秒调一次 powershell 读 ProductVersion」，在沙箱环境里
每次子进程调用极慢，240 秒只能跑十几轮，结果安装明明 40 秒就完成了，
脚本却一路报「超时」（1.2.0 / 1.1.32 / 1.2.2 三次都这样）。

正确判据不是版本号，而是**哈希**：
安装完成的充分必要条件就是「已装 exe == 目标 dist 里的 exe」。
读 2 MB 文件算 sha256 是毫秒级，纯 Python，无子进程。

用法：
    python tools/wait_install.py <setup.exe> <dist_exe>
"""
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# 安装位置按当前用户解析，不硬编码本机路径（仓库要能给别人用）
INSTALLED = (Path(os.environ.get("LOCALAPPDATA", ""))
             / "Programs" / "井然" / "井然.exe")

# 完成判据不能只看 exe：Inno 会先替换 exe，再慢慢解压其余文件。
# 只等 exe 会「5 秒就当装完」，脚本一退出安装器跟着被回收 ——
# 结果是版本号变了、QML 还是旧的（最难发现的一类事故）。
# 所以同时盯几个文件，并额外要求「文件总数 3 秒不变」。
PROBE_RELS = ["井然.exe", "_internal/qml/Main.qml", "_internal/qml/Theme.qml"]


def sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None      # 安装中文件被占用 / 半写状态，下一轮再试


def count_files(root: Path) -> int:
    try:
        return sum(1 for _ in root.rglob("*") if _.is_file())
    except OSError:
        return -1


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    setup = Path(sys.argv[1])
    dist_exe = Path(sys.argv[2])
    if not setup.is_file():
        print("安装包不存在：%s" % setup)
        return 2
    if not dist_exe.is_file():
        print("目标 exe 不存在：%s" % dist_exe)
        return 2

    dist_root = dist_exe.parent
    inst_root = INSTALLED.parent
    want = {rel: sha(dist_root / rel) for rel in PROBE_RELS}
    want_files = count_files(dist_root)
    print("目标 %d 个文件，盯 %d 个探针文件" % (want_files, len(PROBE_RELS)),
          flush=True)
    for rel in PROBE_RELS:
        cur = sha(inst_root / rel)
        print("  %-28s 已装 %s…" % (rel, (cur or "无")[:12]), flush=True)

    if all(sha(inst_root / r) == h for r, h in want.items()):
        print("已经是目标版本，无需安装")
        return 0

    print("启动静默安装…", flush=True)
    subprocess.Popen(
        [str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         "/CLOSEAPPLICATIONS"],
        creationflags=0x00000008 | 0x00000200,
        close_fds=True,
    )

    t0 = time.time()
    stable_since = None
    last_cnt = -1
    while time.time() - t0 < 240:
        time.sleep(1.5)
        el = time.time() - t0
        probes_ok = all(sha(inst_root / r) == h for r, h in want.items())
        cnt = count_files(inst_root)
        if cnt != last_cnt:
            last_cnt, stable_since = cnt, el
        settled = stable_since is not None and (el - stable_since) >= 3.0
        if probes_ok and settled and cnt >= want_files - 2:
            time.sleep(1.5)
            print("安装完成，用时 %.0fs（%d 个文件）" % (el, cnt), flush=True)
            return 0
        if int(el) % 10 == 0:
            print("  …%.0fs  探针%s  文件 %d/%d"
                  % (el, "已就绪" if probes_ok else "未就绪", cnt, want_files),
                  flush=True)

    print("超时 240s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
