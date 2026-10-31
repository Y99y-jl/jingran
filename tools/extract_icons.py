# -*- coding: utf-8 -*-
"""从旧版 Tk 生产源码的 ICON_ASSETS 里导出图标 PNG（只读源，绝不修改）。

旧版把工具栏图标以 base64 PNG 内联在源码里（SDF 渲染，24 网格，线宽 1.6px，
圆头），没有外部图片文件。新版 QML 要用 Image 引用，必须先落盘成 PNG。

源：旧版 Tk 生产源码 `<仓库外的旧项目目录>/项目文件管家.pyw`
    （该目录不在本仓库内，具体路径见下方 SRC 变量）
    ICON_ASSETS: (名称, 主题) -> {物理尺寸: base64 PNG(透明底)}
输出：qml_app\\resources\\icons\\<name>_<light|dark>_<size>.png

用法：
    python extract_icons.py
"""
import ast
import base64
import hashlib
import pathlib
import sys

SRC = pathlib.Path(
    str(Path(__file__).resolve().parent.parent.parent / "legacy" / "项目文件管家.pyw"))
OUT = pathlib.Path(__file__).resolve().parent.parent / "resources" / "icons"


def load_assets() -> dict:
    """用 AST 静态取出 ICON_ASSETS 字面量（不执行旧版代码）。"""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "ICON_ASSETS":
                    return ast.literal_eval(node.value)
    raise SystemExit("[ERR] 源文件里没找到 ICON_ASSETS")


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"[ERR] 源文件不存在：{SRC}")
    assets = load_assets()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for (name, theme), sizes in sorted(assets.items()):
        for size, b64 in sorted(sizes.items()):
            raw = base64.b64decode(b64)
            if raw[:8] != b"\x89PNG\r\n\x1a\n":
                print(f"[WARN] 非 PNG 头，跳过 {name}/{theme}/{size}")
                continue
            p = OUT / f"{name}_{theme}_{size}.png"
            p.write_bytes(raw)
            rows.append((f"{name}_{theme}_{size}.png", len(raw),
                         hashlib.sha256(raw).hexdigest()[:16]))
    print(f"[OK] 输出目录：{OUT}")
    print(f"[OK] 写出 {len(rows)} 个 PNG（源：{SRC.name}，只读）")
    for n, sz, h in rows:
        print(f"    {n:<28} {sz:>6} B  sha256:{h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
