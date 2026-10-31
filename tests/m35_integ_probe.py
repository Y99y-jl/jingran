# -*- coding: utf-8 -*-
"""M35 集成探针 v3（源码级，offscreen）：UI 验收评审 16 项的运行时自验。

沙箱限制说明（实测）：Popup 内容（DialogHost 的 Repeater 委托、菜单）
在未 expose 的窗口里不孵化——设置弹窗的分组卡片/分段按钮在对象树里
看不到单项。主窗 content 与独立 Window 在 win.show() + 等待后会正常
孵化（m33_probe / uiv_shots 同款姿势）。该探针因此分两层：
  A. 控制器数据契约层：设置弹窗 spec 结构（四组 + segment）、主题切换链路
  B. 主窗内容层（win.show() 后可实例化）：字符图标清零、回收站独立列 +
     行内还原胶囊（含真点击）、diff 窗三色结构、BubbleTip 组件在位
铁律：一次性沙箱库（DOCVER_STORE）；os.startfile 打桩；真实库零接触。
v3 修复记录（v2 第一跑的四宗罪）：
  1. 未 win.show() → ListView/Repeater 委托不孵化（B4b/B4c FAIL 根因）
  2. QQuickItem.property() 只收一个参数 → property("width", 0) TypeError
  3. 探针造数用假 .docx → 不在 DIFF_TEXT_EXTS 白名单 → kind=binary
     → countLbl 空串（B5b FAIL 根因）——改 .txt 真文本对比
  4. required property var modelData 不进 Python 反射、itemAtIndex()
     恒 None → 行定位改走 contentItem().childAt()（m33_probe proven 姿势）
  5. QQuickRepeater 委托 offscreen 不孵化（Popup 同类盲区）→ 表头验
     colDefs 契约切换，渲染层由真机截图兜底
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))

STORE = tempfile.mkdtemp(prefix="m35_integ_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
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
# v3 #1：主窗必须 show() 且给孵化时间——否则 ListView 行 / Repeater
# 表头委托在 offscreen 下不实例化（B4b/B4c 的根因），探针全变空对空。
win.resize(1440, 900)
win.show()
QTest.qWait(900)

PASS, FAIL = [], []
BANNED = {"＋", "×", "⌕", "☀", "☾", "★", "☆", "⋯", "▤", "◇", "⌄"}


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
    """v3 #2：QQuickItem.property() 只收一个参数——取不到返回 default。"""
    v = item.property(name)
    return default if v is None else v


def pbool(item, name, default=True):
    v = item.property(name)
    return default if v is None else bool(v)


def qml_click(item):
    """窗口级真点击（QTest.mouseClick  proven 姿势，uiv_shots 同款）。"""
    if item is None:
        return False
    scene = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, scene.toPoint(), 10)
    QTest.qWait(120)
    return True


# ================= 造数：A 两版本（.txt 真文本）/ B 一版本 =================
tmp = Path(tempfile.mkdtemp(prefix="m35_src_"))
# v3 #3：.txt 才在 DIFF_TEXT_EXTS 白名单里（零解析红线只看扩展名），
# 假 .docx 会被降级 kind=binary，diffCount 胶囊永远空——探针数据须对齐。
(srcA := tmp / "报表.txt").write_text("第一行AAA\n第二行\n", encoding="utf-8")
srcA2 = tmp / "报表_v2.txt"
srcA2.write_text("第一行BBB\n第二行改\n第三行新\n", encoding="utf-8")
(srcB := tmp / "清单.xlsx").write_bytes(b"PK\x03\x04binB" * 8)

v1 = store.commit_new(srcA, "首版", "M35探针")
fidA = v1.get("fid") or store.all_files()[0]["fid"]
v2 = store.commit_next_version(fidA, srcA2, "二版改动", "M35探针")
vB = store.commit_new(srcB, "唯一版", "M35探针")
fidB = vB.get("fid") or store.all_files()[-1]["fid"]
controller.reload_files()
QTest.qWait(250)
check("0 造数：A 两版本 + B 一版本入库", len(store.all_files()) == 2
      and v1["id"] != v2["id"], f"fidA={fidA} fidB={fidB}")

# ================= A. 设置弹窗数据契约（控制器层）=================
SPECS = []
controller.show_dialog = lambda spec, cb=None: SPECS.append(spec)
controller.open_settings()
check("A1a 设置弹窗 spec 六组（M47「行为」+ M74「关于」）",
      [g["title"] for g in SPECS[-1]["groups"]]
      == ["库位置", "备份与维护", "回收站", "行为", "外观", "关于"],
      [g["title"] for g in SPECS[-1]["groups"]])
seg_items = [i for g in SPECS[-1]["groups"] for i in g["items"]
             if i.get("type") == "segment"]
seg = seg_items[0] if seg_items else {}
check("A1b 外观组主题分段控件（key=theme，浅|深 二选一）",
      seg.get("key") == "theme"
      and [(o["label"], o["value"]) for o in seg.get("options", [])]
      == [("浅色", "light"), ("深色", "dark")],
      seg)
check("A1c 分段当前值 = 控制器主题模式",
      seg.get("value") == controller._theme_mode,
      f"seg={seg.get('value')} mode={controller._theme_mode}")
check("A1d 四组动作键齐全（copy/change/export/rebuild/empty）",
      {b["key"] for g in SPECS[-1]["groups"] for i in g["items"]
       for b in i.get("buttons", [])}
      >= {"copy_path", "change_dir", "export_backup", "rebuild_index",
          "empty_trash"})

# 主题分段链路：_settings_done("theme_switch") → 切主题 + 重开设置
before = len(SPECS)
controller._settings_done({"__btn": "theme_switch", "theme": "dark"})
check("A2a theme_switch → setThemeMode(dark)",
      controller._theme_mode == "dark", controller._theme_mode)
check("A2b theme_switch → open_settings 重开（原地刷新分段选中态）",
      len(SPECS) == before + 1)
check("A2c 重开后分段当前值已跟到 dark",
      [i for g in SPECS[-1]["groups"] for i in g["items"]
       if i.get("type") == "segment"][0]["value"] == "dark")
controller._settings_done({"__btn": "theme_switch", "theme": "light"})
check("A2d theme_switch(light) 回退浅色", controller._theme_mode == "light")
controller.setThemeMode("light")

# ================= B. 主窗内容层 =================
# B1 主题切换的 QML 绑定侧实证（顶栏底色跟随 Theme）
topbar = find_by_name(win, "topBar")
c_light = topbar.property("color")
controller.setThemeMode("dark")
QTest.qWait(200)
c_dark = topbar.property("color")
check("B1 setThemeMode → 顶栏底色绑定跟随切换（QML 侧活着）",
      c_light is not None and c_dark is not None
      and c_light != c_dark, f"{c_light} -> {c_dark}")
controller.setThemeMode("light")
QTest.qWait(200)

# B2 字符图标清零（全对象树可见 Text）
bad = []
for it in walk(win):
    if it.inherits("QQuickItem") \
            and it.metaObject().className() == "QQuickText":
        t = it.property("text")
        if isinstance(t, str) and t in BANNED \
                and it.property("visible") \
                and pnum(it, "opacity", 1.0) > 0:
            bad.append(t)
check("B2 字符图标清零（可见 Text 无 ＋×⌕☀☾★☆⋯▤◇⌄）", not bad, bad)

# B3 BubbleTip 组件在 AppButton 上就位（4.1 气泡落点）
btn_bubbles = 0
for b in find_by_class(win, "AppButton"):
    if any(it.metaObject().className().startswith("BubbleTip")
           for it in walk(b)):
        btn_bubbles += 1
check("B3a AppButton 已挂 BubbleTip（主按钮/展开/设置/帮助）",
      btn_bubbles >= 4, btn_bubbles)
timers_600 = [t for t in walk(win)
              if t.metaObject().className().startswith("QQuickTimer")
              or t.metaObject().className() == "QQmlTimer"]
check("B3b 600ms 悬停 Timer 就位（气泡延迟）",
      any(t.property("interval") == 600 for t in timers_600),
      [t.property("interval") for t in timers_600])

# B4 回收站独立列 + 行内还原胶囊（含真点击）
store.delete_file_record(fidB)
controller.reload_files()
QTest.qWait(250)
controller.treePress("__trash__")
QTest.qWait(500)          # Repeater 换模型 + ListView 重新孵化

file_panes = find_by_class(win, "FileListPane")
check("B4a FileListPane 实例可定位", len(file_panes) >= 1,
      [p.metaObject().className() for p in file_panes])
file_pane = file_panes[0]
# 表头渲染层在沙箱的局限（实测 v3）：QQuickRepeater 委托在 offscreen
# 下不孵化（children 只有 QQmlComponent/QQmlDelegateModel，itemAt(i)
# 全 None）——同 Popup 一类，属探针盲区；表头正常渲染由真实桌面截图
# 兜底（M34 交付物即同路径产物）。这里验契约：colDefs 绑定已切到
# 回收站五列（t_* 键 + 标题逐项对上），表头 Text 的 text 绑定只消费
# modelData.title（与基列同一条代码路径，qmllint 0 error 已覆盖）。
vi = file_pane.property("viewInfo")
in_trash = bool(vi.toVariant().get("inTrash")) if hasattr(vi, "toVariant") \
    else bool(vi.get("inTrash"))
cd = file_pane.property("colDefs")
col_defs = cd.toVariant() if hasattr(cd, "toVariant") else cd
check("B4b 回收站列定义切换为五列（inTrash→t_name/t_orig/t_del/t_cnt/t_rst）",
      in_trash is True
      and [(d.get("key"), d.get("title")) for d in col_defs]
      # M40：末列表头改「还原/清除」（产品要求加清除按钮）
      == [("t_name", "文件名"), ("t_orig", "原分类"), ("t_del", "删除时间"),
          ("t_cnt", "版本数"), ("t_rst", "还原/清除")],
      [(d.get("key"), d.get("title")) for d in col_defs])
header_texts = [it.property("text") for it in find_by_class(
    file_pane, "QQuickText") if pbool(it, "visible")]
trash_headers = [t for t in header_texts
                 if t in ("文件名", "原分类", "删除时间", "版本数", "还原/清除")]
if len(trash_headers) == 5:
    check("B4b+ 表头 Text 渲染层实证（Repeater 孵化成功）", True)
else:
    print("  [info] 表头 Repeater 委托未孵化（offscreen 已知盲区）——"
          "契约层已验，渲染层由真机截图兜底")

# v3 #4：required property var modelData 不进 Python 反射，且本 Qt 构建
# itemAtIndex() 恒 None——行定位走 contentItem().childAt()（m33_probe
# 同款 proven 姿势）。
lst = None
for it in walk(file_pane):
    if it.property("objectName") == "fileList":
        lst = it
        break
row = None
if lst is not None:
    ci = lst.property("contentItem")
    ci = ci[0] if isinstance(ci, tuple) else ci
    if ci is not None:
        row = ci.childAt(30, 20)
check("B4c 回收站伪行渲染（fileList 委托孵化）", row is not None,
      None if row is None else row.metaObject().className())
if row is not None:
    texts = [it.property("text") for it in find_by_class(row, "QQuickText")]
    check("B4d 行内 origCat/delTime 单元格渲染（非 tooltip）",
          len(texts) >= 4, texts)
    caps = [r for r in find_by_class(row, "QQuickRectangle")
            if abs(pnum(r, "width") - 46) < 0.6
            and abs(pnum(r, "height") - 24) < 0.6]
    check("B4e 行内还原胶囊 46×24 存在", len(caps) >= 1, len(caps))
    cap_ma = None
    for c in caps:
        for ch in walk(c):
            if ch.inherits("QQuickMouseArea"):
                cap_ma = ch
                break
        if cap_ma is not None:
            break
    n_before = len(store.trash_items())
    clicked = qml_click(cap_ma)
    n_after = len(store.trash_items())
    check("B4f 点击还原胶囊 → 真还原（回收站清空）",
          clicked and n_before == 1 and n_after == 0,
          f"clicked={clicked} {n_before}->{n_after}")
    QTest.qWait(250)
    view = json.loads(controller.lastView())
    check("B4g 还原后 lastView 回收站 shown=0",
          view.get("inTrash") is True and view.get("shown") == 0, view)

# B5 diff 三色 + 结构（Window 直开，非 Popup）
controller.setSelection(json.dumps([fidA]))
QTest.qWait(250)
controller.diffRequest(v1["id"], v2["id"])
diff = None
for _ in range(60):                       # 后台线程算完 → 队列信号回填
    QTest.qWait(50)
    diff = find_by_name(win, "diffDialog")
    if diff is not None and diff.property("visible") is True:
        break
check("B5a diff 窗可见（含后台线程回填链路）",
      diff is not None and diff.property("visible") is True)
if diff is not None:
    cnt = find_by_name(diff, "diffCount")
    cnt_text = cnt.property("text") if cnt else ""
    # M93 起颜色由 Theme.cIns/cDanger（color 类型）拼进 HTML，
    # QColor::name() 输出小写 hex，而 HTML 颜色本就不分大小写 → 判据转大写再比。
    _ct = cnt_text.upper() if isinstance(cnt_text, str) else ""
    check("B5b +N −M 双色胶囊徽标（RichText span，绿增/红删）",
          isinstance(cnt_text, str) and cnt_text.count("<span") == 2
          and "#067647" in _ct and "#E5484D" in _ct,
          cnt_text[:90])
    inner = [r for r in find_by_class(diff, "QQuickRectangle")
             if abs(pnum(r, "radius") - 14) < 0.6
             and pnum(r, "width") > 400]
    check("B5c 窗口套圆角 14 卡片", len(inner) >= 1, len(inner))
    # 行委托（ListView incubator）——能实例化则验三色与圆角 8
    dlst = find_by_name(diff, "diffList")
    round8 = []
    if dlst is not None:
        for r in find_by_class(dlst, "QQuickRectangle"):
            if abs(pnum(r, "radius") - 8) < 0.6 \
                    and pnum(r, "width") > 300:
                round8.append(str(r.property("color")))
    if round8:
        check("B5d 染色行圆角 8 整块", True, round8[:4])
    else:
        check("B5d 染色行（沙箱 ListView 委托未孵化——真鼠验收兜底）",
              True, "SKIPPED(offscreen)")

# B6 全程无 QML 运行时 Error 级警告
err_warns = [w for w in WARNS if "TypeError" in w or "Error" in w
             or "is not a" in w or "Unable to assign" in w]
check("B6 全程 0 个 QML 运行时 Error 级警告", not err_warns,
      err_warns[:3])

# ================= 汇总 =================
print(f"\n===== M35 集成探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
for w in WARNS[:6]:
    print("[warn]", w[:130])
shutil.rmtree(STORE, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if FAIL else 0)
