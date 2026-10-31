# -*- coding: utf-8 -*-
"""Diff 纯逻辑（H2——设计 §M4；生产 _diff_build_payload L10658 平移）。

零解析红线：文本判定只看扩展名白名单（生产 _diff_is_text L10477），
绝不解 zip/读内容猜类型；编码 utf-8→gbk 回退，仍失败按二进制降级
（_diff_read_text L10482）。512KB/2000 行门禁（生产 L10468-10469）。
纯内存纯函数——后台线程可跑，Qt 零依赖（主线程 QTimer 回填）。
"""

from __future__ import annotations

import difflib
import os
import unicodedata
from pathlib import Path

DIFF_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".ini",
    ".cfg", ".conf", ".json", ".yml", ".yaml", ".xml", ".html",
    ".htm", ".css", ".js", ".ts", ".py", ".pyw", ".bat", ".ps1",
    ".sh", ".sql", ".c", ".h", ".cpp", ".hpp", ".java", ".cs",
    ".go", ".rs",
}
DIFF_MAX_BYTES = 512 * 1024      # 生产 L10468
DIFF_MAX_LINES = 2000            # 生产 L10469（截断门禁）


def is_text(name: str) -> bool:
    """零解析判定：只看扩展名白名单（生产 _diff_is_text）。"""
    return os.path.splitext(str(name))[1].lower() in DIFF_TEXT_EXTS


def read_text(path: Path) -> str | None:
    """utf-8 → gbk → None（按二进制降级，不报错——生产 _diff_read_text）。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def chip_clip(text: str, max_full: int = 8) -> str:
    """chip 截断：最多 max_full 个全角字宽（半角算半个），截断补「…」
    （生产 _chip_clip L1965 逐字节平移；W/F 记 2 其余记 1）。"""
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    limit = max_full * 2
    width = 0
    out: list[str] = []
    for ch in s:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if width + w > limit:
            return "".join(out) + "…"
        width += w
        out.append(ch)
    return "".join(out)


def build_payload(pa: Path, pb: Path, name: str, va: dict, vb: dict) -> dict:
    """_diff_build_payload 平移（无 Tk/state 依赖）。

    返回 dict：kind ∈ {binary, same_text, text}；text 时 rows=[(kind,
    old_no, new_no, text, word_spans)]；banner=(same, is_text)；note 截断提示。
    """
    same = (str(va.get("sha256") or "") == str(vb.get("sha256") or "")
            and va.get("sha256"))
    banner = {"same": bool(same), "isText": is_text(name)}
    if not is_text(name):
        return {"kind": "binary", "va": va, "vb": vb,
                "banner": banner}
    ta = read_text(pa)
    tb = read_text(pb)
    if ta is None or tb is None:
        return {"kind": "binary", "va": va, "vb": vb, "banner": banner,
                "note": "文件编码无法按文本读取，已降级为元数据对比"}
    if same:
        return {"kind": "same_text", "banner": banner}
    big = max(Path(pa).stat().st_size, Path(pb).stat().st_size)
    note = ""
    if big > DIFF_MAX_BYTES:
        note = ("文件较大（%.1f MB），已只对比前 %d 行"
                % (big / 1048576.0, DIFF_MAX_LINES))
    la = ta.splitlines()[:DIFF_MAX_LINES]
    lb = tb.splitlines()[:DIFF_MAX_LINES]
    sm = difflib.SequenceMatcher(a=la, b=lb, autojunk=False)
    counts = {"del": 0, "ins": 0}
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"kind": "eq", "oldNo": i1 + k + 1, "newNo": j1 + k + 1,
                             "text": la[i1 + k], "wa": None, "wb": None})
        elif tag == "delete":
            for k in range(i2 - i1):
                counts["del"] += 1
                rows.append({"kind": "del", "oldNo": i1 + k + 1, "newNo": "",
                             "text": la[i1 + k], "wa": None, "wb": None})
        elif tag == "insert":
            for k in range(j2 - j1):
                counts["ins"] += 1
                rows.append({"kind": "ins", "oldNo": "", "newNo": j1 + k + 1,
                             "text": lb[j1 + k], "wa": None, "wb": None})
        else:                                   # replace：词级 1:1 对
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                ca = la[i1 + k] if i1 + k < i2 else ""
                cb = lb[j1 + k] if j1 + k < j2 else ""
                wa = wb = None
                if ca and cb:
                    wm = difflib.SequenceMatcher(a=ca, b=cb)
                    wa = [(op[1], op[2]) for op in wm.get_opcodes()
                          if op[0] in ("delete", "replace")]
                    wb = [(op[3], op[4]) for op in wm.get_opcodes()
                          if op[0] in ("insert", "replace")]
                if ca:
                    counts["del"] += 1
                    rows.append({"kind": "rep_a", "oldNo": i1 + k + 1, "newNo": "",
                                 "text": ca, "wa": wa, "wb": None})
                if cb:
                    counts["ins"] += 1
                    rows.append({"kind": "rep_b", "oldNo": "", "newNo": j1 + k + 1,
                                 "text": cb, "wa": None, "wb": wb})
    return {"kind": "text", "rows": rows, "counts": counts,
            "banner": banner, "note": note}
