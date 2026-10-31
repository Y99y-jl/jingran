# -*- coding: utf-8 -*-
"""M49 验收：Ctrl 取消选中 / 拖入文件夹按目录结构建分类。"""
import json
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m49_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

import controller as cm  # noqa: E402

cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Basic")
c = cm.AppController(STORE)
st = c._store
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


# ---------- 准备 4 个文件 ----------
tmp = Path(tempfile.mkdtemp(prefix="m49_src_"))
for i in range(4):
    f = tmp / f"s{i}.txt"
    f.write_text(str(i), encoding="utf-8")
    st.commit_new(f, "v1")
c.reload_files()
c.setSelection("[]")
ids = [r["fid"] for r in c.model.rows]


def ev(d):
    return json.loads(c.fileEvent(json.dumps(d)))


def press(i, ctrl=False, anchor=-1):
    return ev({"op": "press", "row": ids[i], "x": 10, "y": 10, "ctrl": ctrl,
               "shift": False, "isTrash": False, "rowIndex": i,
               "modsAnchor": anchor})["selected"]


def release():
    return ev({"op": "release"})["selected"]


# 选中第 1 行
press(0)
release()
# Ctrl 加选第 2 行
press(1, ctrl=True, anchor=0)
sel2 = release()
check("C1 Ctrl 加选后共 2 个", len(sel2) == 2, len(sel2))
# Ctrl 点已选中的第 1 行 → 应只剩第 2 行
press(0, ctrl=True, anchor=1)
sel3 = release()
check("C2 Ctrl 点已选中行 = 取消该行（保留其余）",
      len(sel3) == 1 and sel3 == [ids[1]], sel3 == [ids[1]] or len(sel3))

# ---------- 拖入文件夹 ----------
proj = tmp / "高能量密度"
(proj / "复配包" / "深层").mkdir(parents=True)
(proj / "检测").mkdir(parents=True)
(proj / "说明.txt").write_text("root", encoding="utf-8")
(proj / "复配包" / "配方.docx").write_text("a", encoding="utf-8")
(proj / "复配包" / "深层" / "数据.xlsx").write_text("b", encoding="utf-8")
(proj / "检测" / "报告.pdf").write_text("c", encoding="utf-8")

urls = json.dumps([proj.as_uri()])
res = json.loads(c.dropInFiles(urls))
print("   dropInFiles →", res)
QTest_wait = 200

paths = {x["name"]: x for x in st.collections()}
check("F1 根文件夹建为一级分类", "高能量密度" in paths)
top = paths.get("高能量密度", {}).get("id")
sub_names = [x["name"] for x in st.collections() if x.get("parent") == top]
check("F2 子目录建为子分类", sorted(sub_names) == ["复配包", "检测"], sub_names)
deep = next((x for x in st.collections()
             if x.get("name") == "深层"), None)
check("F3 三级目录也建了子分类", deep is not None and deep.get("parent") is not None)

import unittest.mock as _  # noqa: E402
metas = st.all_files()
by_name = {}
for m in metas:
    by_name.setdefault(m.get("name"), []).append(m.get("category"))
check("F4 根目录文件落在根分类",
      by_name.get("说明.txt") == [top], by_name.get("说明.txt"))
sub1 = next((x for x in st.collections() if x.get("name") == "复配包"), {})
check("F5 子目录文件落在子分类",
      by_name.get("配方.docx") == [sub1.get("id")], by_name.get("配方.docx"))
deep_id = deep.get("id") if deep else None
check("F6 深层文件落在对应子分类",
      by_name.get("数据.xlsx") == [deep_id], by_name.get("数据.xlsx"))

print(f"\n===== M49 探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
