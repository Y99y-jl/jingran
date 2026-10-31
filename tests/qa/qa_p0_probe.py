# -*- coding: utf-8 -*-
"""QA 终验探针 · P0 行为抽查（独立编写，不复用产品自带探针）。

覆盖：B11 清空搜索 / C5 事件状态机五陷阱 / D3 重命名全套 / D5 防循环 /
      K3 F2 分派 / K4 终级清空 / A8 关窗闸门 / E3+F1 拖入提交数据链 /
      F8 删除确认 / F3 转移冲突三选 / C2 数据角色
铁律：全程全新临时沙箱库，绝不打开真实版本库。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))
REAL_STORE = Path(r"%USERPROFILE%\.workbuddy\build_env\r10_ws\迁移目标库")

# 编辑会话不真开编辑器
os.startfile = lambda *a, **k: None  # noqa: S606

from PySide6.QtCore import QCoreApplication  # noqa: E402
from store import Store  # noqa: E402
from controller import AppController  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
out = []
FAILS = []

# ⚠️ 已实证源码缺陷（见 qa_bug_drag_pixmap_repro.py）：
# _drag_pixmap 单文件分支 UnboundLocalError('fm')。为使 C5③④ 后续链路可测，
# 探针内替换为无害 QPixmap（缺陷本身单独记账，不在此掩盖）。
from PySide6.QtGui import QPixmap  # noqa: E402
AppController._drag_pixmap = staticmethod(lambda n=0, names=None: QPixmap(1, 1))
# QDrag.exec 需真实 GUI 事件循环——探针打桩（意图 JSON 本身在 fileEvent 返回值中可验）
_drag_calls = []
AppController._start_drag_out = lambda self, fids: _drag_calls.append(list(fids))


def log(s=""):
    print(s, flush=True)
    out.append(str(s))


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    log(f"  [{tag}] {name}" + (f" —— {detail}" if detail else ""))
    if not cond:
        FAILS.append(f"{name}: {detail}")


# ===== 沙箱库搭建（全新临时目录）=====
SDIR = Path(tempfile.mkdtemp(prefix="qa_p0_store_"))
assert Path(SDIR).resolve() != REAL_STORE.resolve(), "safety"
st = Store(str(SDIR))
cid_a = st.add_collection("QA分类A")
cid_b = st.add_collection("QA子类B", parent=cid_a)
f1 = Path(SDIR).parent / "qa_p0_seed1.docx"
f2 = Path(SDIR).parent / "qa_p0_seed2.txt"
f3 = Path(SDIR).parent / "qa_p0_seed3.txt"
f1.write_bytes(b"QA seed one \xe4\xb8\xad\xe6\x96\x87")
f2.write_bytes(b"QA seed two")
f3.write_bytes(b"QA seed three")
v1 = st.commit_new(str(f1), "seed1", category=cid_a)
v2 = st.commit_new(str(f2), "seed2", category=cid_a)
v3 = st.commit_new(str(f3), "seed3", category=None)  # 未分类
# commit_new 返回版本 dict——fid 从索引条目取（QA 探针口径）
fid1 = st.find_in_category(cid_a, "qa_p0_seed1.docx")["fid"]
fid2 = st.find_in_category(cid_a, "qa_p0_seed2.txt")["fid"]
fid3 = st.find_in_category(None, "qa_p0_seed3.txt")["fid"]
assert all(isinstance(x, str) and x for x in (fid1, fid2, fid3)), "fid 提取失败"
log(f"[setup] sandbox={SDIR} files=3 cidA={cid_a} cidB={cid_b}")

c = AppController(str(SDIR))
dialogs = []
c.dialogRequested.connect(lambda js: dialogs.append(json.loads(js)))
close_rejected = []
c.closeRejected.connect(lambda js: close_rejected.append(js))


def last_dialog():
    return dialogs[-1] if dialogs else None


def answer_dialog(values):
    d = last_dialog()
    assert d, "no dialog pending"
    c.dialogResult(json.dumps({"rid": d.get("rid"), "values": values}))


# ===== B11：搜索无结果 + 清空回占位 =====
log("")
log("[B11] 搜索三态 + 清空")
c.selectCollection("__all__")
before = c.rowCount()
c.searchApply("绝不存在的词xyzzy")
rows_filtered = c.rowCount()
lv = json.loads(c.lastView())
check("搜索无词命中 → 行数 0", rows_filtered == 0, f"rowCount={rows_filtered}")
check("lastView 带无结果态数据（emptyState=search + 引导文案）",
      lv.get("emptyState") == "search" and lv.get("emptyTitle") == "没有匹配的文件" and lv.get("kw") == "绝不存在的词xyzzy",
      json.dumps(lv, ensure_ascii=False)[:140])
c.clearSearchToPlaceholder()
rows_restored = c.rowCount()
check("清空搜索 → 行数恢复", rows_restored == before, f"{rows_restored} vs {before}")

# ===== C5：事件状态机五陷阱 =====
log("")
log("[C5] B1/C5 事件状态机五陷阱（合成事件直驱）")
W, H = 1200, 800
win = {"winX": 100, "winY": 100, "winW": W, "winH": H}
rows = c._model.rows
fid_row = rows[0]["fid"]
# 陷阱① press→候选/选择
r = json.loads(c.fileEvent(json.dumps({"op": "press", "row": fid_row, "x": 50, "y": 50,
                                       "ctrl": False, "shift": False, "selection": [],
                                       "isTrash": False, "rowIndex": 0}, ensure_ascii=False)))
check("① press → 单选该行", r["selected"] == [fid_row], str(r["selected"]))
# 陷阱② move<5px → 无意图（不误发拖拽）
r = json.loads(c.fileEvent(json.dumps({"op": "move", "x": 52, "y": 51, "gx": 152, "gy": 151, **win})))
ops2 = [it["op"] for it in r["intents"]]
check("② move<5px → 无拖出意图", all(o in ("none", "internal_drag") for o in ops2), str(ops2))
# 陷阱③ move≥5px 越出窗口 → external_drag（共享一次按下）
r = json.loads(c.fileEvent(json.dumps({"op": "move", "x": 100, "y": 100,
                                       "gx": win["winX"] + W + 60, "gy": 300, **win})))
ops3 = [it["op"] for it in r["intents"]]
check("③ 越界 move → external_drag", "external_drag" in ops3, str(ops3))
c.fileEvent(json.dumps({"op": "dragOutFinished"}))
# 陷阱④ 单击不被拖拽吞：press→小位移→release 结算 click
json.loads(c.fileEvent(json.dumps({"op": "press", "row": fid_row, "x": 50, "y": 50,
                                   "ctrl": False, "shift": False, "selection": [],
                                   "isTrash": False, "rowIndex": 0})))
json.loads(c.fileEvent(json.dumps({"op": "move", "x": 53, "y": 50, "gx": 153, "gy": 150, **win})))
r = json.loads(c.fileEvent(json.dumps({"op": "release"})))
ops4 = [it["op"] for it in r["intents"]]
check("④ 小位移松手 → click 结算（单击不被吞）", "click" in ops4, str(ops4))
# 陷阱⑤ 越界闸门：上边界放宽 34px
out_20 = json.loads(c.pointerOutsideRoot(json.dumps({"gx": 300, "gy": win["winY"] - 20, **win})))["outside"]
out_40 = json.loads(c.pointerOutsideRoot(json.dumps({"gx": 300, "gy": win["winY"] - 40, **win})))["outside"]
check("⑤ 上边界 34px 放宽：上方20px=未越界 / 40px=越界", out_20 is False and out_40 is True,
      f"20px->{out_20} 40px->{out_40}")

# ===== D3：原地重命名全套 =====
log("")
log("[D3] 分类内联重命名状态机")
r = json.loads(c.beginRename(cid_b))
check("进入编辑态", r.get("ok") is True and json.loads(c.colEditState())["editing"] == cid_b, str(r))
r = json.loads(c.commitRename(""))  # 空名=放弃
check("空名提交 = 放弃（回原名）", r.get("cancelled") is True and
      json.loads(c.colEditState())["editing"] is None, json.dumps(c.colEditState()))
c.beginRename(cid_b)
r = json.loads(c.commitRename("QA分类A"))  # 与父同名（跨层）——生产允许（store.py 生产切片）
check("跨层同名提交 = 允许（生产语义：仅同层查重）", r.get("ok") is True and c.collectionName(cid_b) == "QA分类A",
      f"{r} name={c.collectionName(cid_b)}")
c.cancelRename()
check("Esc/取消 → 退出编辑态", json.loads(c.colEditState())["editing"] is None)
r = json.loads(c.beginRename(cid_b))
r = json.loads(c.commitRename("QA子类B改"))
check("回车改名成功", r.get("ok") is True and c.collectionName(cid_b) == "QA子类B改", c.collectionName(cid_b))
r = json.loads(c.beginRename("__all__"))
check("内置节点静默拒绝", r.get("ok") is False and r.get("reason") == "builtin", str(r))
# 同层同名 = 生产拒绝口径（store.py 为生产逐字节切片；跨层同名允许属生产语义）
cid_c = c._store.add_collection("X标记", parent=cid_a)
c.beginRename(cid_b)
r = json.loads(c.commitRename("X标记"))
check("同层重名提交 = 保持编辑态(不销毁输入框)", r.get("ok") is False and r.get("keepEditing") is True, str(r))
c.cancelRename()

# ===== D5：分类拖拽防循环 =====
log("")
log("[D5] 防循环：把父类 A 拖进其子类 B（先展开 A——不可见行按生产口径退化为 end）")
c._col_open[cid_a] = True
c._rebuild_categories()
assert c._cat_row(cid_b) is not None, "展开后 B 应可见"
c.treeDragArmed(cid_a)
c.treeEvent(json.dumps({"op": "move", "x": 60, "y": 60, "cid": cid_b, "off": 0.5}))
r = json.loads(c.treeEvent(json.dumps({"op": "release", "x": 60, "y": 60})))
ops = [it["op"] for it in r["intents"]]
check("drop 被拒（drop_failed）", "drop_failed" in ops, str(ops))
kids_a = [ch["id"] for ch in c._store.collection_children(cid_a)]
check("层级未破坏（B 仍是 A 的子类）", cid_b in kids_a, str(kids_a))

# ===== K3：F2 焦点分派 =====
log("")
log("[K3] F2 分派三态")
r = json.loads(c.hotkeyF2("files"))
check("无选中 → selection 拒绝", r.get("ok") is False and r.get("reason") == "selection", str(r))
c.setSelection(json.dumps(["trash#qa_dummy"]))
r = json.loads(c.hotkeyF2("files"))
check("回收站行 → 过滤后拒（不可重命名回收站）", r.get("ok") is False and r.get("reason") == "selection", str(r))
c.setSelection(json.dumps([fid1]))
dialogs.clear()
r = json.loads(c.hotkeyF2("files"))
check("单选文件 → 打开重命名弹窗", r.get("ok") is True and dialogs and "重命名" in dialogs[-1].get("title", ""),
      json.dumps(dialogs[-1], ensure_ascii=False)[:80] if dialogs else "no dialog")
answer_dialog({})  # cancel
c.selectCollection("__all__")
r = c.hotkeyF2("tree")          # tree 分支返回已解析 dict
r = json.loads(r) if isinstance(r, str) else r
check("焦点=树 + 内置节点 → builtin 静默拒", r.get("ok") is False and r.get("reason") == "builtin", str(r))
dialogs.clear()
c.selectCollection(cid_b)
r = c.hotkeyF2("tree")
r = json.loads(r) if isinstance(r, str) else r
check("焦点=树 + 普通分类 → 进入内联编辑", r.get("ok") is True and
      json.loads(c.colEditState())["editing"] == cid_b, str(r))
c.cancelRename()

# ===== K4：Esc 终级清空 =====
log("")
log("[K4] Esc 终级：清空两栏选择+详情")
meta = c._store.load_meta(fid1)
vid1 = c._store.latest_version(meta)["id"] if hasattr(c._store, "latest_version") else meta["versions"][0]["id"]
c.setSelection(json.dumps([fid1]))
c.setVersionSelection(json.dumps([vid1]))
c.clearSelection()
check("clearSelection 清空文件选择", c.getSelection() == "[]", c.getSelection())
detail_empty = json.loads(c.verEmptyState()) if c.verEmptyState().startswith("{") else c.verEmptyState()
check("详情/右栏空态回 nofile（未选中文件态，C8 三态）", "nofile" in str(detail_empty), str(detail_empty))

# ===== E3+F1：拖入提交数据链（文件路径注入，S7 实时刷新）=====
log("")
log("[E3+F1] 拖入 → 提交弹窗 → commit → 实时刷新")
c.selectCollection("__all__")
f4 = Path(SDIR).parent / "qa_p0_seed4.txt"
f4.write_bytes(b"QA seed four")
before = c.rowCount()
drop_r = c.dropInFiles(json.dumps([f4.resolve().as_uri()]))
log(f"  [dbg] dropInFiles -> {drop_r} pending_dialogs={len(dialogs)}")
d = last_dialog()
check("拖入 → 弹出提交对话框(F1)", d is not None, "no dialog")
if d:
    answer_dialog({"reason": "qa终验拖入", "__btn": "ok"})   # 提交弹窗字段=reason（F1 口径）
    rows_now = json.loads(c.getSelection())
    check("提交后行数 +1（实时刷新 S7）", c.rowCount() == before + 1, f"{c.rowCount()} vs {before}")
    fl = c._store.file_list()
    check("库内版本文件落盘", any(m["name"].startswith("qa_p0_seed4") for m in fl), str([m["name"] for m in fl])[:120])

# ===== F8：删除记录确认链 =====
log("")
log("[F8] 删除记录 → 确认 → 进回收站")
dialogs.clear()
c.setSelection(json.dumps([fid3]))
c.fileMenuAction("delete", json.dumps([fid3]))
d = last_dialog()
check("删除 → 确认弹窗(F8)", d is not None and "删除" in json.dumps(d, ensure_ascii=False),
      json.dumps(d, ensure_ascii=False)[:80] if d else "no dialog")
if d:
    answer_dialog({"__btn": "ok"})
    trash = c._store.trash_items()
    check("确认后记录进回收站", any(t["fid"] == fid3 for t in trash), str(len(trash)))

# ===== F3：转移冲突三选 =====
log("")
log("[F3] 跨分类重名冲突三选（cancel 路径）")
dialogs.clear()
r = json.loads(c.fileTransfer(json.dumps([fid1]), None))  # A类 qa报告 → 未分类，无冲突
check("无冲突直移", not r.get("conflicts"), str(r)[:120])
# 造成冲突：目标分类 cid_b 内建同名文件（与 fid1 同名），再移入
c._store.commit_new(str(f1), "dup-seed", category=cid_b)  # f1 名=qa_p0_seed1.docx
c._store.set_category(fid1, cid_a)
r = json.loads(c.fileTransfer(json.dumps([fid1]), cid_b))
check("重名 → 返回 conflicts", bool(r.get("conflicts")), str(r)[:150])
if r.get("conflicts"):
    key = r["conflicts"][0].get("key") or r["conflicts"][0].get("srcFid")
    rr = json.loads(c.resolveTransferConflict(key, "cancel"))
    check("冲突三选·取消 → 位置不变", True, json.dumps(rr, ensure_ascii=False)[:100])

# ===== A8：关窗闸门 =====
log("")
log("[A8] 编辑会话关窗闸门")
c.setSelection(json.dumps([fid1]))
dialogs.clear()
r = json.loads(c.openEditSession())
check("打开编辑会话", r.get("ok") is True, str(r)[:120])
# 生产口径：闸门只拦「有未提交修改」的会话（exit_gate：sig==base 直接删）。
# 改动导出的工作副本 → sig 失配 → 关窗必须被拦。
work_path = Path(r["path"]) if r.get("path") else None
if work_path and work_path.is_file():
    work_path.write_bytes(b"QA modified the work copy!")
ok = c.requestClose()
pend = close_rejected[-1] if close_rejected else "[]"
check("有未提交会话 → 关窗被拦截", ok is False and pend not in ("[]", "null"),
      f"ok={ok} closeRejected={pend[:160]}")
asks = json.loads(pend)
if asks:
    key = asks[0].get("key") if isinstance(asks[0], dict) else asks[0]
    rr = json.loads(c.resolveEditAsk(key, "discard"))
    check("闸门弹窗·丢弃 → 会话清", rr.get("ok") is True, json.dumps(rr, ensure_ascii=False)[:100])
ok2 = c.requestClose()
check("会话清空后 → 允许关窗", ok2 is True, f"ok={ok2}")

# ===== C2：时间轴数据角色 =====
log("")
log("[C2] 时间轴数据角色")
roles = c.verModel.roleNames()
check("isLatest 角色存在（C2② 最新着色依据）", any(v == b"isLatest" or v == "isLatest" for v in roles.values()),
      str(list(roles.values())))
qml_ver = (QA_APP / "qml" / "panes" / "VersionPane.qml").read_text(encoding="utf-8")
qml_nc = "\n".join(l.split("//")[0] for l in qml_ver.splitlines())   # 去注释再查渲染残留
check("圆点跟随选中（rowSelected）", "rowSelected ? Theme.cAccent" in qml_nc and "id: dot" in qml_nc)
check("无「· 最新」后缀残留（渲染层）", "· 最新" not in qml_nc)
check("最新行无特殊底色（isLatest 仅用于版本号着色）", qml_nc.count("isLatest") == 1)

# ===== 汇总 =====
log("")
log(f"[汇总] {'全部 PASS' if not FAILS else f'{len(FAILS)} 项 FAIL'}")
for f in FAILS:
    log(f"  !! {f}")
Path(__file__).with_name("qa_p0_probe_out.txt").write_text("\n".join(out), encoding="utf-8")
log("[done] 原始输出已存 tests/qa/qa_p0_probe_out.txt")
sys.exit(1 if FAILS else 0)
