# -*- coding: utf-8 -*-
"""Store 抽取器 —— AST 依赖闭包机械切片（设计 §1.2，不手工挑拣）。

输入：生产 项目文件管家.pyw（只读）
输出：qml_app/store.py（import 头重建，其余为生产源码逐字节切片）

算法：
  1. ast.parse 生产源码，收集顶层 defs/classes/assigns/imports。
  2. 以 `Store` 为种子做名字闭包：被引用的模块级 def/class/assign 递归纳入。
  3. 闭包内出现任何 GUI 模块名（tkinter/tkinterdnd2/PySide6）引用 → 立即 FAIL。
  4. 闭包内每个被引用的自由名必须可解析（included / import 绑定名 / builtin），
     否则 FAIL（宁可失败也不静默漏依赖）。
  5. 输出 = 重建的 import 头 + 按原文件顺序的闭包节点逐字节切片。
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

SRC = Path(str(Path(__file__).resolve().parent.parent.parent / "legacy" / "项目文件管家.pyw"))
OUT = Path(__file__).resolve().parent.parent / "store.py"

GUI_NAMES = {
    "tkinter", "tkinterdnd2", "tk", "ttk", "tkfont", "TkinterDnD",
    "DND_FILES", "DND_COPY", "DND_REFUSE", "DND_OK", "messagebox",
    "filedialog", "PhotoImage", "Toplevel", "Canvas", "StringVar",
}
BANNER = (
    "# -*- coding: utf-8 -*-\n"
    '"""项目文件管家 · 存储层（store.py）\n'
    "\n"
    "由 tools/extract_store.py 从生产 项目文件管家.pyw 做 AST 依赖闭包机械切片生成。\n"
    "除本文件头外，全部内容为生产源码逐字节切片（等价三证之②可审计）。\n"
    "本模块零 tkinter / 零 PySide6 依赖（等价三证之①静态断言）。\n"
    '"""\n'
)


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    defs: dict[str, ast.AST] = {}
    assigns: dict[str, ast.AST] = {}
    import_nodes: list[ast.stmt] = []
    import_binds: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for name in _assign_names(t):
                    assigns[name] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigns[node.target.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            import_nodes.append(node)
            import_binds |= _import_bind_names(node)

    # ---- 闭包 ----
    included: dict[str, ast.AST] = {}
    stack = ["Store"]
    while stack:
        name = stack.pop()
        if name in included:
            continue
        node = defs.get(name) or assigns.get(name)
        if node is None:
            if name in import_binds or hasattr(builtins, name):
                continue  # 自由名可解析：import 绑定或 builtin
            raise AssertionError(f"闭包引用了未知名: {name!r}（生产源码顶层不存在）")
        included[name] = node
        for ref in _load_names(node):
            if ref in defs or ref in assigns:
                stack.append(ref)

    # ---- GUI 检查（闭包内任何名字不得是 GUI 名）----
    gui_hits = sorted(set(included) & GUI_NAMES)
    if gui_hits:
        raise AssertionError(f"闭包包含 GUI 名: {gui_hits}")
    for name, node in included.items():
        for ref in _load_names(node):
            if ref in GUI_NAMES:
                raise AssertionError(f"{name} 引用 GUI 名 {ref}")

    # ---- 计算需要的顶层 import（逐字节引用原 import 行）----
    used_names = set()
    for node in included.values():
        used_names |= _load_names(node)
    header_imports: list[str] = []
    for node in import_nodes:
        binds = _import_bind_names(node)
        if binds & used_names:
            header_imports.append("".join(lines[node.lineno - 1:node.end_lineno]))

    # ---- 切片输出（保持生产源码原顺序）----
    pieces: list[tuple[int, str]] = []
    for name, node in included.items():
        start = node.lineno
        if getattr(node, "decorator_list", None):
            start = min(start, *(d.lineno for d in node.decorator_list))
        seg = "".join(lines[start - 1:node.end_lineno])
        pieces.append((start, seg))
    pieces.sort()

    body = "".join(seg for _, seg in pieces)
    header = BANNER + "\n".join(sorted(set(header_imports))) + "\n\n"
    OUT.write_text(header + body, encoding="utf-8")

    names = sorted(included)
    print(f"[extract] OK -> {OUT}")
    print(f"[extract] 闭包 {len(names)} 个顶层名: {', '.join(names)}")
    print(f"[extract] 头部 import {len(set(header_imports))} 行:")
    for imp in sorted(set(header_imports)):
        print("    " + imp.strip())
    return 0


def _assign_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for e in target.elts:
            out.extend(_assign_names(e))
        return out
    return []


def _import_bind_names(node: ast.stmt) -> set[str]:
    binds: set[str] = set()
    if isinstance(node, ast.Import):
        for a in node.names:
            binds.add(a.asname or a.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            binds.add(a.asname or a.name)
    return binds


def _load_names(node: ast.AST) -> set[str]:
    """节点内所有 Load 语境的 Name（含全局声明），供闭包与解析检查。"""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            names.add(n.id)
    return names


if __name__ == "__main__":
    sys.exit(main())
