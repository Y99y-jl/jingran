# -*- coding: utf-8 -*-
"""清理项目里积累的构建产物 / 日志 / 旧安装包。

规则：
  · 只删**可重建**的东西（构建缓存、旧 dist、旧安装包、日志、诊断图）
  · 源码、资料包、当前 dist、最近 2 个安装包一律不动
  · 默认 dry-run，加 --do 才真删
"""
import shutil
import sys
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
DO = "--do" in sys.argv


def vkey(name: str):
    """'dist_m98' / '1.2.2' → 可比较的元组"""
    import re
    nums = re.findall(r"\d+", name)
    return tuple(int(x) for x in nums) if nums else (0,)


# 保留最新 2 个 dist（当前版 + 上一版），自动跟随，不写死版本号
_dists = sorted((QA / "build_qml").glob("dist_m*"), key=lambda p: vkey(p.name))
KEEP_DIST = {p.name for p in _dists[-2:]}

# 保留最新 3 个安装包
_setup_dir = QA.parent / "安装包"
_setups = sorted(_setup_dir.glob("井然_安装程序_*.exe"),
                 key=lambda p: vkey(p.stem)) if _setup_dir.is_dir() else []
KEEP_SETUP = {p.stem.replace("井然_安装程序_", "") for p in _setups[-3:]}

targets: list[tuple[Path, str]] = []

# 1) 构建缓存（全部，含最新的 —— 它只是中间产物，下次构建会重建）
for p in sorted(QA.glob("build_qml_work_m*")):
    targets.append((p, "构建缓存"))

# 2) 旧 dist
for p in sorted((QA / "build_qml").glob("dist_m*")):
    if p.name not in KEEP_DIST:
        targets.append((p, "旧产物"))

# 3) 根目录日志与诊断图
for p in sorted(QA.glob("*.log")):
    targets.append((p, "历史日志"))
for name in ("diag_before.png", "diag_after.png"):
    p = QA / name
    if p.is_file():
        targets.append((p, "诊断截图"))

# 4) 旧安装包
setup_dir = QA.parent / "安装包"
if setup_dir.is_dir():
    for p in sorted(setup_dir.glob("井然_安装程序_*.exe")):
        ver = p.stem.replace("井然_安装程序_", "")
        if ver not in KEEP_SETUP:
            targets.append((p, "旧安装包"))

# 5) 桌面临时截图目录（我在本轮任务里建的）
shots = Path.home() / "Desktop" / "_shots"
if shots.is_dir():
    targets.append((shots, "临时截图"))


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    t = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                t += f.stat().st_size
        except OSError:
            pass
    return t


total = 0
print("%-8s %10s  %s" % ("类型", "体积", "路径"), flush=True)
for p, kind in targets:
    s = size_of(p)
    total += s
    print("%-8s %7.1f MB  %s" % (kind, s / 1048576, p.name), flush=True)

print("\n共 %d 项，合计 %.0f MB" % (len(targets), total / 1048576), flush=True)

if not DO:
    print("（dry-run，加 --do 才真删）", flush=True)
    sys.exit(0)

ok, fail = 0, 0
for p, kind in targets:
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        ok += 1
    except Exception as e:
        fail += 1
        print("  失败 %s: %s" % (p.name, e), flush=True)
print("已删除 %d 项，失败 %d 项，释放约 %.0f MB"
      % (ok, fail, total / 1048576), flush=True)
