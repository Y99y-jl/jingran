# -*- coding: utf-8 -*-
"""M91 暗色模式回归：像素级验证 + 令牌一致性 + 资源完整性。

为什么需要这个探针
------------------
暗色模式一直是「开发时手动切一眼看看」，没有任何自动化覆盖。这类"看着
没问题"的代码有个隐蔽退化路径：谁给某个面板补一行硬编码 `color: "#FFFFFF"`，
浅色下完全看不出问题（本来就是白的），暗色下才变成白块——而这正是最容易
在改动里漏掉的地方。本探针不读代码猜，而是**真渲染 → 逐像素扫**，
能抓到这类回归。

覆盖
----
 D1 暗色主界面无过亮区块（24px 网格平均亮度）
 D2 三栏面板底色确为深色
 D3 暗色正文对比度 ≥ 4.5:1（WCAG AA）
 D4 主按钮白字对比度 ≥ 4.5:1
 D5 设置弹窗在暗色下不是白块
 D6 暗色/浅色令牌键集完全一致（缺键会静默变透明）
 D7 6 组图标的 dark 资源齐全（缺文件 → Image 加载失败 → 空白按钮）
 D8 主题落库到 ui.theme，且新实例能读回
 D9 切回浅色完全还原，无深色残留

运行：<venv>/python.exe tests/m91_dark_probe.py
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m91_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl                                  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402

import controller as cm                                          # noqa: E402

cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
for _ttf in sorted((QA / "resources" / "fonts").glob("*.ttf")):
    QFontDatabase.addApplicationFont(str(_ttf))
QQuickStyle.setStyle("Basic")

PASS, FAIL = [], []
ART = QA / "tests" / "artifacts"
ART.mkdir(parents=True, exist_ok=True)


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)
    return bool(ok)


# ---------------- 颜色工具 ----------------
def _ch(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def lum_rgb(r, g, b):
    return 0.2126 * _ch(r) + 0.7152 * _ch(g) + 0.0722 * _ch(b)


def parse_argb(hx):
    """'#AARRGGBB' / '#RRGGBB' → (r, g, b, a)"""
    hx = hx.lstrip("#")
    if len(hx) == 8:
        return (int(hx[2:4], 16), int(hx[4:6], 16), int(hx[6:8], 16),
                int(hx[0:2], 16) / 255.0)
    return (int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16), 1.0)


def over(fg, bg):
    """把带 alpha 的 fg 合成到不透明 bg 上（都是 (r,g,b,a)）"""
    a = fg[3]
    return tuple(int(round(fg[i] * a + bg[i] * (1 - a))) for i in range(3)) + (1.0,)


def lin(rgb):
    return lum_rgb(rgb[0], rgb[1], rgb[2])


def contrast(fg, bg):
    """fg/bg 为 (r,g,b,a)，先在 bg 上合成再算"""
    f = over(fg, bg) if fg[3] < 1.0 else fg
    l1, l2 = lin(f), lin(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---------------- 解析 Theme.qml 令牌表 ----------------
THEME = (QA / "qml" / "Theme.qml").read_text(encoding="utf-8").replace("\r\n", "\n")


def token_block(which):
    """取 _light / _dark 两块字典里的 键→色值。"""
    m = re.search(r"readonly property var " + which + r": \(\{", THEME)
    if not m:
        raise RuntimeError("找不到 %s 令牌块" % which)
    end = re.search(r"\n\s*\}\)", THEME[m.end():]).start() + m.end()
    body = THEME[m.end():end]
    return dict(re.findall(r'(\w+):\s*"(#[0-9A-Fa-f]{6,8})"', body))


LIGHT, DARK = token_block("_light"), token_block("_dark")

# ---------------- 造数据 ----------------
c = cm.AppController(STORE)
st = c._store
a_id = st.add_collection("项目分类")
b_id = st.add_collection("合同")
tmp = Path(tempfile.mkdtemp(prefix="m91_src_"))
names = ["季度经营汇报.docx", "供应商合同_Q3.pdf", "成本测算表.xlsx",
         "需求说明.md", "会议纪要.txt", "预算草案.xlsx", "验收单.pdf"]
for i, n in enumerate(names):
    f = tmp / n
    f.write_text("v0-%d" % i, encoding="utf-8")
    st.commit_new(f, "首次提交", category=a_id if i % 2 == 0 else b_id)
meta0 = st.find_in_category(a_id, names[0])
f0 = tmp / names[0]
for k in range(2):
    f0.write_text("v%d-body" % (k + 1), encoding="utf-8")
    st.commit_next_version(meta0["fid"], f0, "第%d次修订" % (k + 2))
c.reload_files()
c.selectCollection("__all__")
QTest.qWait(150)

# ---------------- 起界面 ----------------
engine = QQmlApplicationEngine()
for k, val in (("controller", c), ("filesModel", c.model),
               ("categoriesModel", c.catModel), ("verModel", c.verModel)):
    engine.rootContext().setContextProperty(k, val)
engine.addImportPath(QA.as_uri())
engine.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
win.resize(1296, 817)
win.show()
QTest.qWait(800)
rows = c.model.rows
c.setSelection(json.dumps([rows[0]["fid"]]))
QTest.qWait(400)


def snap(tag):
    p = ART / ("m91_%s.png" % tag)
    win.grabWindow().save(str(p))
    return p


def dominant(px, x0, y0, x1, y1):
    """区域内出现最多的颜色（用于取"面板底色"，避开文字）"""
    cnt = {}
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            v = px.pixel(x, y)
            key = (v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF)
            cnt[key] = cnt.get(key, 0) + 1
    return max(cnt.items(), key=lambda kv: kv[1])[0] + (1.0,)


def bright_blocks(img, thresh=0.55, grid=24):
    """扫描过亮区块：返回 [(avg, x, y)]，相邻块合并后按亮度降序。"""
    W, H = img.width(), img.height()
    out = []
    for by in range(0, H - grid + 1, grid):
        for bx in range(0, W - grid + 1, grid):
            tot, n = 0.0, 0
            for y in range(by, by + grid, 4):
                for x in range(bx, bx + grid, 4):
                    v = img.pixel(x, y)
                    tot += lum_rgb(v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF)
                    n += 1
            avg = tot / n
            if avg > thresh:
                out.append((avg, bx, by))
    return sorted(out, reverse=True)


# ================= D6 令牌一致性（先做，纯静态，最快）=================
miss = sorted(set(LIGHT) - set(DARK))
extra = sorted(set(DARK) - set(LIGHT))
check("D6 暗色令牌与浅色键集完全一致", not miss and not extra,
      "暗色缺 %s / 多余 %s" % (miss, extra))

# ================= D7 图标资源 =================
ICONS = QA / "resources" / "icons"
used = set(re.findall(r'iconUrl\("(\w+)"', (QA / "qml" / "Main.qml").read_text(encoding="utf-8")))
lack = []
for nm in sorted(used):
    for px in (22, 28, 33, 44):
        for mode in ("light", "dark"):
            if not (ICONS / f"{nm}_{mode}_{px}.png").is_file():
                lack.append(f"{nm}_{mode}_{px}.png")
check("D7 %d 组图标的 dark/light 四档全部就位" % len(used), not lack, lack[:8])

# ================= 切暗色 =================
c.setThemeMode("dark")
QTest.qWait(700)
p_dark = snap("1_dark")
img = QImage(str(p_dark)).convertToFormat(QImage.Format_RGB32)
px = img

blocks = bright_blocks(img)
check("D1 暗色主界面无过亮区块（白块漏适配）", not blocks,
      "最亮 %s" % (blocks[:3],))

p_panel = dominant(px, 600, 480, 700, 530)
p_side = dominant(px, 280, 560, 340, 600)
p_insp = dominant(px, 1000, 600, 1040, 650)
worst = max(lin(p_panel), lin(p_side), lin(p_insp))
check("D2 三栏面板确为深色（相对亮度 < 0.10）", worst < 0.10,
      "panel=%.3f side=%.3f insp=%.3f"
      % (lin(p_panel), lin(p_side), lin(p_insp)))

# 正文对比度：用暗色令牌 cText 压在实测面板色上（比取样更稳，不受抗锯齿影响）
txt = parse_argb(DARK.get("C_TEXT", "#FFFFFF"))
cr_body = contrast(txt, p_panel)
check("D3 暗色正文对比度 ≥ 4.5:1", cr_body >= 4.5, f"{cr_body}:1 on {p_panel[:3]}")

# 主按钮：C_PRIMARY_A/B 渐变，白字取较差的一端
pa = parse_argb(DARK.get("C_PRIMARY_A", "#FFFFFF"))
pb = parse_argb(DARK.get("C_PRIMARY_B", "#FFFFFF"))
white = (255, 255, 255, 1.0)
cr_btn = min(contrast(white, pa), contrast(white, pb))
check("D4 暗色主按钮白字对比度 ≥ 4.5:1", cr_btn >= 4.5,
      f"{cr_btn}:1 (A={cr_body and DARK.get('C_PRIMARY_A')} B={DARK.get('C_PRIMARY_B')})")

# ================= D5 设置弹窗 =================
c.open_settings()
QTest.qWait(650)
p_dlg = snap("2_dark_dialog")
dimg = QImage(str(p_dlg)).convertToFormat(QImage.Format_RGB32)
dpx = dimg
# 弹窗居中：取中心一块区域的主色（与面板底色区分开）
dlg_bg = dominant(dpx, 560, 300, 740, 380)
check("D5 设置弹窗在暗色下为深色（相对亮度 < 0.22）", lin(dlg_bg) < 0.22,
      "dialog=#%02X%02X%02X L=%.3f" % (dlg_bg[0], dlg_bg[1], dlg_bg[2], lin(dlg_bg)))
c.dialogResult(json.dumps({"rid": "x", "values": {"__btn": "cancel"}}))
QTest.qWait(300)

# ================= D8 主题落库 =================
ui = st.config.get("ui", {}) or {}
check("D8 主题写入 ui.theme", ui.get("theme") == "dark", ui.get("theme"))
c2 = cm.AppController(STORE)
check("D8b 新实例读回暗色", c2.themeMode() == "dark", c2.themeMode())

# ================= D9 切回浅色 =================
c.setThemeMode("light")
QTest.qWait(800)
p_light = snap("3_light_after")
limg = QImage(str(p_light)).convertToFormat(QImage.Format_RGB32)
lpanel = dominant(limg, 600, 480, 700, 530)
check("D9 切回浅色后中栏回到浅色（相对亮度 > 0.60）", lin(lpanel) > 0.60,
      "panel=#%02X%02X%02X L=%.3f" % (lpanel[0], lpanel[1], lpanel[2], lin(lpanel)))
lblocks = [b for b in bright_blocks(limg, thresh=0.55) if b[2] > 400]
check("D9b 浅色下恢复原有明度分布（底部空白区仍亮）", bool(lblocks),
      "底部亮块 %d 个" % len(lblocks))

# ================= 暗色选中态 / 次级文字 =================
# 选中行的辨识依据是左侧 3px 强调条（非文本控件 → 3:1），而不是底色本身：
# 底色只是"氛围"，浅色下是 1.12:1、暗色 1.26:1，本来就都低于 1.4。
bar = parse_argb(DARK.get("C_SEL_BAR", "#FFFFFF"))
cr_bar = contrast(bar, p_panel)
check("D10 暗色选中行左侧强调条可辨（≥ 3:1）", cr_bar >= 3.0, f"{cr_bar}:1")
sel = parse_argb(DARK.get("C_SELECT_BG", "#00000000"))
cr_sel = contrast(sel, p_panel)
check("D10b 暗色选中底色不弱于浅色水准（≥ 1.15:1）", cr_sel >= 1.15, f"{cr_sel}:1")
hdr = contrast(parse_argb(DARK.get("C_TEXT_HEADER", "#888888")), p_panel)
check("D11 暗色表头文字 ≥ 4.5:1", hdr >= 4.5, f"{hdr}:1")
dim = contrast(parse_argb(DARK.get("C_TEXT_DIM", "#888888")), p_panel)
check("D12 暗色次级文字 ≥ 4.5:1", dim >= 4.5, f"{dim}:1")
typefg = contrast(parse_argb(DARK.get("C_TYPE_DOCX_FG", "#888888")),
                  parse_argb(DARK.get("C_TYPE_DOCX_BG", "#000000")))
check("D13 暗色类型徽标文字可读（≥ 4.5:1）", typefg >= 4.5, f"{typefg}:1")

# ================= D14 颜色双写清零（M93 收口）=================
# 只允许 Main.qml 里两处非颜色用法（图标路径 dark/light、光带 opacity）。
hits = []
for f in sorted((QA / "qml").rglob("*.qml")):
    for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if 'Theme.mode === "dark"' in ln and '"#' in ln:
            hits.append("%s:%d" % (f.name, i))
check("D14 主题色不再有 dark 三元组硬编码（M93 已全部收口）", not hits, hits)

# ================= D15 气泡浮层方向 =================
# 暗色下浮层必须比它浮在之上的面板更亮；原 #0F1A33 比面板 #1C202B 还暗，
# 1.04:1 只靠描边撑，方向反了。
bub = parse_argb(DARK.get("C_BUBBLE_BG", "#000000"))
cr_bub = contrast(bub, p_panel)
check("D15 暗色气泡比面板亮（≥1.4:1）", cr_bub >= 1.4, f"{cr_bub}:1")

print(f"\n===== M91 暗色回归：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
if FAIL:
    print("失败项：" + "、".join(FAIL))
print("截图：%s" % ART)
sys.exit(1 if FAIL else 0)
