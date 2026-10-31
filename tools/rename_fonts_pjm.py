# -*- coding: utf-8 -*-
"""M40：把随包字体改成独有字体族名，彻底避开系统同名 Noto Sans SC 冲突。

只改 name 表（1/3/4/6/16/17），glyph/cmap/OS-2/metrics 一律不动。
写临时文件后 os.replace 原子覆盖（本机对已存在源文件直接写会 PermissionError）。
"""
import os
from pathlib import Path

from fontTools.ttLib import TTFont

# 按脚本位置推导，不依赖具体机器上的目录结构
FD = Path(__file__).resolve().parent.parent / "resources" / "fonts"

PAIRS = [  # 长串优先，避免半截替换
    ("Noto Sans SC", "PJM Sans SC"),
    ("NotoSansSC", "PJMSansSC"),
    ("Inter SemiBold", "PJM Num SemiBold"),
    ("Inter Medium", "PJM Num Medium"),
    ("Inter Regular", "PJM Num Regular"),
    ("Inter-SemiBold", "PJMNum-SemiBold"),
    ("Inter-Medium", "PJMNum-Medium"),
    ("Inter-Regular", "PJMNum-Regular"),
]

# 需要补 nameID16 的文件（400 与 Inter-Regular 原本没有排版家族名记录）
ADD16 = {"NotoSansSC-400.ttf": "PJM Sans SC", "Inter-Regular.ttf": "PJM Num"}


def rename_text(s: str) -> str:
    if s == "Inter":
        return "PJM Num"
    for a, b in PAIRS:
        s = s.replace(a, b)
    return s


def main() -> None:
    for f in sorted(FD.glob("*.ttf")):
        t = TTFont(str(f))
        name = t["name"]
        changed = []
        for rec in list(name.names):
            # 21/22/25 = WWS 家族名/子族名/变体名——DirectWrite 优先用它，
            # 漏改会导致 Qt 仍按旧族名解析（Inter-Medium 实测踩过）
            if rec.nameID not in (1, 3, 4, 6, 16, 17, 21, 22, 25):
                continue
            try:
                s = rec.toUnicode()
            except Exception:
                continue
            s2 = rename_text(s)
            if s2 != s:
                name.setName(s2, rec.nameID, rec.platformID,
                             rec.platEncID, rec.langID)
                changed.append((rec.nameID, s, s2))
        if f.name in ADD16:
            nid16 = [r for r in name.names if r.nameID == 16]
            if not nid16:
                for pid, peid, lid in ((3, 1, 0x409), (1, 0, 0)):
                    name.setName(ADD16[f.name], 16, pid, peid, lid)
                changed.append((16, "<missing>", ADD16[f.name]))
        tmp = f.with_suffix(".pjm.tmp")
        t.save(str(tmp))
        t.close()
        os.replace(tmp, f)
        print(f"[{f.name}] {len(changed)} 条名字记录改写")
        for nid, a, b in changed[:6]:
            print(f"    id{nid}: {a!r} -> {b!r}")

    # 复核
    print("\n---- 复核 ----")
    for f in sorted(FD.glob("*.ttf")):
        t = TTFont(str(f), lazy=True)
        n = t["name"]
        fam = sorted({r.toUnicode() for r in n.names if r.nameID == 1})
        typ = sorted({r.toUnicode() for r in n.names if r.nameID == 16})
        print(f"{f.name:22s} family1={fam} family16={typ}")
        t.close()


if __name__ == "__main__":
    main()
