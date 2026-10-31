# -*- coding: utf-8 -*-
"""M36 集成探针（源码级，offscreen）：四项反馈的运行时自验。

覆盖（对应 M36 施工单四项）：
  ① 星标 BUG：选中旧版本点头部星标 → 标/取消的是「选中版本」而非
     恒最新（含 latest 兜底口径不变）；
  ② 字号：分类区分组标签（功能实证，Direct Column 子项会孵化）+
     文件区表头（契约 + 源码事实——表头 Repeater 委托在 offscreen
     不孵化，M35 v3 #5 已实测的盲区，渲染层由真机截图兜底）；
  ③ 库信息卡删除：文本清零 + 列表高度公式归还 100px + 设置里
     「导出备份」入口仍在（调用真实槽位验证）；
  ④ Enter 确认：真实弹窗链路（controller.confirm/ask_text/
     open_commit_dialog/show_dialog → dialogRequested → Main.qml →
     DialogHost.openSpec）+ QTest.keyClick 真实按键：
       - danger 确认（主动作 accent=False，靠 key="ok" 兜底，
         不能按「最后一个按钮」视觉口径误判成取消）；
       - ask_text 单行输入（TextField 无 onAccepted，Enter 全新增）；
       - 提交弹窗豁免：reason 多行聚焦 Enter=换行，Ctrl+Enter 提交；
       - 孤儿三选一（open/drop/later 无主动作）Enter 不触发；
       - Esc 原有能力保留。
沙箱铁律同 M35：一次性库（DOCVER_STORE）；os.startfile 打桩；
真实库零接触。show_dialog 打桩仅用于捕获设置/导出 spec，随后即还原
真实方法（C4 必须走真实弹窗引擎）。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import re as _re


def theme_int(name: str, default: int = 0) -> int:
    """从 qml/Theme.qml 读 int 令牌实际值——避免探针把字号写死。

    历史坑：C2a 把 fsBody 写死成 13，1.1.30 把阶梯调到 14 后探针假 FAIL。
    """
    try:
        txt = (Path(__file__).resolve().parent.parent / "qml" / "Theme.qml").read_text(
            encoding="utf-8")
    except OSError:
        return default
    m = _re.search(r"readonly property int %s://s*(//d+)" % name, txt)
    return int(m.group(1)) if m else default

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))

STORE = tempfile.mkdtemp(prefix="m36_integ_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import (QQmlApplicationEngine,  # noqa: E402
                           QQmlExpression, QQmlEngine)
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import controller as ctrl_mod  # noqa: E402

STARTED = []
ctrl_mod.os.startfile = lambda p, *a, **k: STARTED.append(str(p))

app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Basic")
controller = ctrl_mod.AppController(STORE)
store = controller._store

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("controller", controller)
engine.rootContext().setContextProperty("filesModel", controller.model)
engine.rootContext().setContextProperty("categoriesModel", controller.catModel)
engine.rootContext().setContextProperty("verModel", controller.verModel)
engine.addImportPath(QA_APP.as_uri())
WARNS = []
engine.warnings.connect(lambda ws: WARNS.extend(w.toString() for w in ws))
engine.load(QUrl.fromLocalFile(str(QA_APP / "qml" / "Main.qml")))
assert engine.rootObjects(), "QML 加载失败"
win = engine.rootObjects()[0]
# 同 M35 v3 #1：主窗必须 show() 且给孵化时间，否则 ListView 行 /
# Repeater 委托在 offscreen 下不实例化，探针空对空。
win.resize(1440, 900)
win.show()
QTest.qWait(900)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


def walk(item):
    yield item
    for c in item.children():
        yield from walk(c)


def find_by_name(root, name):
    for it in walk(root):
        if it.property("objectName") == name:
            return it
    return None


def find_by_class(root, cls):
    """QML 组件实例的 metaObject 类名带 _QMLTYPE_nn 后缀，用前缀匹配。"""
    return [it for it in walk(root)
            if it.inherits("QQuickItem")
            and it.metaObject().className().startswith(cls)]


def pnum(item, name, default=0.0):
    """QQuickItem.property() 只收一个参数——取不到返回 default。"""
    v = item.property(name)
    return default if v is None else v


def pbool(item, name, default=True):
    v = item.property(name)
    return default if v is None else bool(v)


def jsval(v):
    if hasattr(v, "toVariant"):
        try:
            return v.toVariant()
        except Exception:
            return v
    return v


def eval_expr(obj, expr: str):
    """在 QML 对象上下文里求值任意绑定路径（m33_probe proven 姿势）。"""
    rv = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expr).evaluate()
    return rv[0] if isinstance(rv, tuple) else rv


def qml_click(item):
    """窗口级真点击（QTest.mouseClick proven 姿势，uiv_shots 同款）。"""
    if item is None:
        return False
    scene = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, scene.toPoint(), 10)
    QTest.qWait(150)
    return True


def qml_click_at(item, lx, ly):
    """点击 item 内的局部坐标点（避开行右侧操作热区用）。"""
    if item is None:
        return False
    scene = item.mapToScene(QPointF(lx, ly))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, scene.toPoint(), 10)
    QTest.qWait(150)
    return True


def star_state(fid):
    meta = store.load_meta(fid)
    return {v["id"]: bool(v.get("star")) for v in meta.get("versions", [])}


# ================= 造数：A 两版本（.txt 真文本）=================
tmp = Path(tempfile.mkdtemp(prefix="m36_src_"))
(srcA := tmp / "报表.txt").write_text("第一行AAA\n第二行\n", encoding="utf-8")
srcA2 = tmp / "报表_v2.txt"
srcA2.write_text("第一行BBB\n第二行改\n第三行新\n", encoding="utf-8")

v1 = store.commit_new(srcA, "首版", "M36探针")
fidA = v1.get("fid") or store.all_files()[0]["fid"]
v2 = store.commit_next_version(fidA, srcA2, "二版改动", "M36探针")
controller.reload_files()
QTest.qWait(300)
check("0 造数：A 两版本入库",
      len(store.all_files()) == 1 and v1["id"] != v2["id"],
      f"fidA={fidA} v1={v1['id']} v2={v2['id']}")

# ================= C1 ① 星标 BUG：点选哪个版本就标/取消哪个版本 =================
controller.setSelection(json.dumps([fidA]))
QTest.qWait(300)
vp = find_by_class(win, "VersionPane")
check("C1a VersionPane 实例可定位", len(vp) >= 1,
      [p.metaObject().className() for p in vp])
vp = vp[0]
eval_expr(vp, "refreshFromController()")
QTest.qWait(200)

vlist = find_by_name(vp, "verList")
check("C1b 版本列表 verList 可定位", vlist is not None)
rows = []
if vlist is not None:
    ci = vlist.property("contentItem")
    ci = ci[0] if isinstance(ci, tuple) else ci
    if ci is not None:
        # ⚠️ 实测坑：本构建 ci.children() 对 ListView 委托返回 0（QObject
        # 层看不到），必须走 QQuickItem.childItems()——childAt() 同路径可用
        # （M35 B4c 即用 childAt）。历史行高 78、最新卡高 96，按高定位。
        kids = ci.childItems() if hasattr(ci, "childItems") else ci.children()
        for ch in kids:
            if isinstance(ch, QQuickItem) \
                    and pnum(ch, "height") in (78.0, 96.0) \
                    and any(x.inherits("QQuickMouseArea") for x in walk(ch)):
                rows.append(ch)
check("C1c 版本行委托孵化（offscreen ListView）", len(rows) >= 2,
      [pnum(r, "height") for r in rows])

old_row = next((r for r in rows if abs(pnum(r, "height") - 78) < 0.6), None)
new_row = next((r for r in rows if abs(pnum(r, "height") - 96) < 0.6), None)
# 点行左侧文字区（x=60），避开右侧操作热区；事件落到行 rowMa 上
sel_ok = qml_click_at(old_row, 60, pnum(old_row, "height") / 2)
QTest.qWait(300)
sel_vids = jsval(vp.property("selectedVids"))
check("C1d 点击历史行 → 选中即旧版 v1",
      sel_ok and list(sel_vids) == [v1["id"]],
      f"selectedVids={sel_vids} 期望=[{v1['id']}]")

star_ma = find_by_name(vp, "verStarBtn")
check("C1e 文件头星标按钮可定位（objectName=verStarBtn）", star_ma is not None)
clicked1 = qml_click(star_ma)
QTest.qWait(300)
st = star_state(fidA)
check("C1f 选中旧版点头部星标 → 标的是选中版本 v1（BUG 修复实证）",
      clicked1 and st.get(v1["id"]) is True and st.get(v2["id"]) is False,
      st)

star_on = pbool(vp, "starOn", None)
star_glyph = ""
if star_ma is not None:
    for x in walk(star_ma.parent()):
        if x.metaObject().className().startswith("GlyphIcon"):
            star_glyph = x.property("name")
            break
check("C1g starOn/图标同步（star + 主色）",
      star_on is True and star_glyph == "star",
      f"starOn={star_on} glyph={star_glyph}")

clicked2 = qml_click(star_ma)
QTest.qWait(300)
st2 = star_state(fidA)
check("C1h 再点一次 → 取消选中版本 v1 的星标（toggle 闭环）",
      clicked2 and st2.get(v1["id"]) is False, st2)

# reset_rows 后 ListView 委托整体重建——缓存的行对象已失效，必须重取
# M37 起卡片跟选中走，「96 高=最新」启发式失效——改按 vNo 文本认行
def ver_rows():
    vlist = find_by_name(vp, "verList")
    if vlist is None:
        return []
    ci = vlist.property("contentItem")
    ci = ci[0] if isinstance(ci, tuple) else ci
    if ci is None:
        return []
    out = []
    kids = ci.childItems() if hasattr(ci, "childItems") else ci.children()
    for ch in kids:
        if not isinstance(ch, QQuickItem) \
                or pnum(ch, "height") not in (78.0, 96.0) \
                or not any(x.inherits("QQuickMouseArea") for x in walk(ch)):
            continue
        vno = None
        for t in walk(ch):
            if isinstance(t, QQuickItem) \
                    and t.metaObject().className() == "QQuickText" \
                    and t.property("text") in ("v1", "v2"):
                vno = t.property("text")
                break
        if vno:
            out.append((vno, ch))
    return out


new_row = next((r[1] for r in ver_rows() if r[0] == "v2"), None)
sel_latest = qml_click_at(new_row, 60, pnum(new_row, "height") / 2)
QTest.qWait(300)
sel_latest_vids = list(jsval(vp.property("selectedVids")))
clicked3 = qml_click(star_ma)
QTest.qWait(300)
st3 = star_state(fidA)
check("C1i 选中最新版点头部星标 → 标最新 v2（latest 兜底口径不变）",
      sel_latest and sel_latest_vids == [v2["id"]] and clicked3
      and st3.get(v2["id"]) is True and st3.get(v1["id"]) is False,
      f"sel={sel_latest_vids} star={st3}")
# M37 起点：点文件后控制器默认选中最新版本（selectedVids 恒非空），
# 「无选中回落」只剩显式清空一条路径——先 applyVids([]) 再验兜底
eval_expr(vp, "applyVids([])")
QTest.qWait(300)
cleared_vids = list(jsval(vp.property("selectedVids")))
check("C1j latest 兜底：starTargetVid 无选中时回落最新",
      cleared_vids == [] and eval_expr(vp, "starTargetVid()") == v2["id"],
      f"cleared={cleared_vids} target={eval_expr(vp, 'starTargetVid()')}")

# ================= C2 ② 字号 =================
cat = find_by_class(win, "CategoryTreePane")
check("C2 CategoryTreePane 实例可定位", len(cat) >= 1,
      [p.metaObject().className() for p in cat])
cat = cat[0]
gl_found = {}
for it in walk(cat):
    if it.inherits("QQuickItem") \
            and it.metaObject().className() == "QQuickText" \
            and pbool(it, "visible"):
        t = it.property("text")
        if t in ("分类", "项目分类"):
            gl_found[t] = eval_expr(it, "font.pointSize")
# M38 起第三轮放大：分组标签 11.5→13（fsBody，pt=9.75）；
# 本探针原断言 fsLabel(10.5)，随 M37/M38 批次演进为新口径
_FS_BODY = theme_int("fsBody", 14)
check("C2a 分组标签「分类/项目分类」字号等于 fsBody（功能实证）",
      set(gl_found) == {"分类", "项目分类"}
      and all(abs(ps - _FS_BODY * 0.75) < 0.01 for ps in gl_found.values()),
      {"实测": gl_found, "期望pt": _FS_BODY * 0.75})

# 表头：Repeater 委托 offscreen 不孵化（M35 v3 #5 实测盲区）——
# 渲染层由真机截图兜底；此处验两件事：colDefs 绑定存活 + 源码事实。
fp = find_by_class(win, "FileListPane")[0]
col_defs = jsval(fp.property("colDefs"))
check("C2b 文件区表头列定义绑定存活（契约层）",
      len(col_defs) >= 5 and col_defs[0].get("key") == "name",
      [(d.get("key"), d.get("title")) for d in col_defs])
src_flp = (QA_APP / "qml" / "panes" / "FileListPane.qml").read_text(
    encoding="utf-8")
# M37 起第二轮放大：表头 11.5→12.5（pt=9.375，字面量同版本卡 vNo）
check("C2c 表头字号绑定 = Theme.pt(12.5)（源码事实，渲染层真机兜底）",
      "font.pointSize: Theme.pt(12.5)" in src_flp
      and "M37" in src_flp)
hdr_texts = [it for it in find_by_class(fp, "QQuickText")
             if pbool(it, "visible")]
if any(it.property("text") == "文件名" for it in hdr_texts):
    ps = [eval_expr(it, "font.pointSize") for it in hdr_texts
          if it.property("text") == "文件名"]
    check("C2c+ 表头 Text 渲染层实证（Repeater 孵化成功）",
          all(abs(p - 12.5 * 0.75) < 0.01 for p in ps), ps)
else:
    print("  [info] 表头 Repeater 委托未孵化（offscreen 已知盲区，M35 "
          "同款）——契约层 + 源码事实已验，渲染层由真机截图兜底")

# ================= C3 ③ 库信息卡删除 =================
cat_texts = [it.property("text") for it in walk(cat)
             if it.inherits("QQuickItem")
             and it.metaObject().className() == "QQuickText"
             and pbool(it, "visible")]
check("C3a 库信息卡文本清零（「本地版本库」「导出备份 →」不可见）",
      "本地版本库" not in cat_texts and "导出备份 →" not in cat_texts,
      [t for t in cat_texts if t in ("本地版本库", "导出备份 →")])
cat_tree = find_by_name(cat, "catTree")
h_list = pnum(cat_tree, "height")
h_col = pnum(cat_tree.parent(), "height")
# 固定项 = 分组×2(80) + 导航×2(76) + 回收站(38) = 194，另有 16 呼吸位
# M94 曾去掉呼吸位，M95 已按用户要求回退 → 公式重新带 -16
check("C3b 分类树高度公式 = 列高 − 固定项 194 − 呼吸位 16",
      abs(h_list - (h_col - 40 * 2 - 38 * 2 - 38 - 16)) < 0.6,
      f"h={h_list} col={h_col} 期望={h_col - 210}")

# 导出备份入口仍在「设置」里（控制器层真实调用；show_dialog 打桩捕获）
SPECS = []
real_show = controller.show_dialog
controller.show_dialog = lambda spec, cb=None: SPECS.append(spec)
controller.open_settings()
btns = {b["key"] for g in SPECS[-1]["groups"] for i in g["items"]
        for b in i.get("buttons", [])}
check("C3c 设置组仍含「导出备份」按钮（export_backup）",
      "export_backup" in btns, sorted(btns))
controller.open_export_backup_dialog()
exp = SPECS[-1]
check("C3d 导出备份弹窗可开（ok/cancel，主动作 accent）",
      [(b["key"], b.get("accent")) for b in exp.get("buttons", [])]
      == [("ok", True), ("cancel", None)]
      and "导出" in exp.get("title", ""),
      exp.get("title"))
controller.show_dialog = real_show          # 还原真实弹窗引擎（C4 用）

# ================= C4 ④ Enter 确认 =================
host = win.findChild(object, "dialogHost")
check("C4a DialogHost 可定位", host is not None)

# C4-1：danger 确认——主动作 accent=False、按 spec 留在最左，
#       Enter 必须按 key="ok" 兜底命中「删除」，绝不能误判成取消。
cap1 = {}
controller.confirm("删除文件记录", "确定删除这条记录？",
                   ok_text="删除 1 条记录", danger=True,
                   on_result=lambda yes: cap1.update({"ok": yes}))
QTest.qWait(500)
vis1 = host.property("visible")
fb = jsval(host.property("footerBtns"))
check("C4b danger 确认弹窗真实打开 + footerBtns 契约",
      vis1 is True and [b.get("key") for b in fb] == ["ok", "cancel"]
      and fb[0].get("accent") in (False, None),
      f"visible={vis1} fb={fb}")
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(500)
check("C4c Enter → danger 主动作（key=ok 兜底，非取消）",
      cap1.get("ok") is True and host.property("visible") is False,
      f"cap={cap1} visible={host.property('visible')}")

# C4-2：ask_text——单行 TextField 无 onAccepted，Enter 全新增能力。
cap2 = {}
controller.ask_text("重命名文件", "新的文件名", initial="季度报表.txt",
                    on_result=lambda v: cap2.update({"v": v}))
QTest.qWait(500)
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(500)
check("C4d ask_text Enter → ok 且输入值回传",
      cap2.get("v") == "季度报表.txt" and host.property("visible") is False,
      cap2)

# C4-3：提交弹窗豁免——reason 多行聚焦 Enter=换行，Ctrl+Enter=提交。
controller.open_commit_dialog([])
QTest.qWait(500)
check("C4e 提交弹窗打开且 isCommit=true",
      host.property("visible") is True
      and bool(host.property("isCommit")) is True)
ri = host.property("reasonItem")
if ri is not None:
    eval_expr(host, "reasonItem.forceActiveFocus()")
QTest.qWait(150)
ri_focus = bool(host.property("reasonItem")
                and eval_expr(host, "reasonItem.activeFocus"))
before = eval_expr(host, "reasonItem.text")
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(350)
after = eval_expr(host, "reasonItem.text")
check("C4f reason 聚焦 Enter = 换行（豁免提交，条目不关闭）",
      ri_focus is True and host.property("visible") is True
      and "\n" in after and len(after) == len(before) + 1,
      f"focus={ri_focus} before={len(before)} after={len(after)}")
QTest.keyClick(win, Qt.Key_Return, Qt.ControlModifier)
QTest.qWait(500)
check("C4g Ctrl+Enter → 提交关闭弹窗（§4.6 快速保存保留）",
      host.property("visible") is False)

# C4-4：孤儿三选一（open/drop/later 无 accent 无 ok）→ Enter 不触发。
cap4 = {}
controller.show_dialog({
    "title": "发现未处理的工作副本",
    "message": "工作副本与库内文件不同步。\n\n·打开所在文件夹\n"
               "·删除工作副本\n·以后再说",
    "buttons": [{"label": "打开所在文件夹", "key": "open"},
                {"label": "删除工作副本", "key": "drop", "danger": True},
                {"label": "以后再说", "key": "later"}],
}, lambda v: cap4.update({"btn": v.get("__btn")}))
QTest.qWait(500)
QTest.keyClick(win, Qt.Key_Return)
QTest.qWait(400)
check("C4h 孤儿三选一无主动作 → Enter 不触发（不误伤）",
      host.property("visible") is True and cap4 == {},
      f"visible={host.property('visible')} cap={cap4}")
QTest.keyClick(win, Qt.Key_Escape)
QTest.qWait(400)
check("C4i Esc 仍可关闭（原有能力保留）",
      host.property("visible") is False)

# ================= C5 全程无 QML 运行时 Error 级警告 =================
err_warns = [w for w in WARNS if "TypeError" in w or "Error" in w
             or "is not a" in w or "Unable to assign" in w]
check("C5 全程 0 个 QML 运行时 Error 级警告", not err_warns,
      err_warns[:3])

# ================= 汇总 =================
print(f"\n===== M36 集成探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
for w in WARNS[:6]:
    print("[warn]", w[:130])
shutil.rmtree(STORE, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if FAIL else 0)
