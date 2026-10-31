# -*- coding: utf-8 -*-
"""安装后全量校验：把安装目录与构建产物逐文件比哈希。

为什么需要：Inno 遇到被锁定的文件（Defender 实时扫描/文件占用）会**静默跳过**，
安装照样"成功"。实测 1.2.5 第一次装完，exe 和 Theme.qml 是新的、
DialogHost/VersionPane 还是旧版——只看几个探针文件会漏。
"""
import hashlib
import os
import sys
from pathlib import Path

def _latest_dist() -> Path:
    """取 build_qml 下编号最大的 dist（不写死版本号）。"""
    base = Path(__file__).resolve().parent.parent / "build_qml"
    ds = sorted(base.glob("dist_m*"), key=lambda p: int(p.name.split("m")[-1]))
    return (ds[-1] / "井然") if ds else (base / "dist" / "井然")


# 安装位置按当前用户解析，不硬编码本机路径（仓库要能给别人用）
INST = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "井然"
DIST = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_dist()

# 安装目录比 dist 多出这些（Inno 自己的卸载器），不参与比对
SKIP_PREFIX = {"unins", "$"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


mismatch, missing, checked = [], [], 0
for src in DIST.rglob("*"):
    if not src.is_file():
        continue
    rel = src.relative_to(DIST)
    if rel.name.lower().startswith(("unins",)):
        continue
    dst = INST / rel
    if not dst.is_file():
        missing.append(str(rel))
        continue
    checked += 1
    if sha(src) != sha(dst):
        mismatch.append(str(rel))

print("比对 %d 个文件" % checked)
if missing:
    print("缺失 %d 个：" % len(missing))
    for m in missing[:10]:
        print("  " + m)
if mismatch:
    print("内容不一致 %d 个：" % len(mismatch))
    for m in mismatch[:10]:
        print("  " + m)
if not missing and not mismatch:
    print("全部一致 ✓")
sys.exit(1 if (missing or mismatch) else 0)
