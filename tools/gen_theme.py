# -*- coding: utf-8 -*-
"""Theme.qml 生成器 —— V3 令牌表（规格书 §2）→ qml/Theme.qml。

M29 变更（产品要求：严格按 UI 规格书 V3）：
  · 旧口径是「从生产 .pyw 的 _THEME_LIGHT/_THEME_DARK 逐字节取 42 令牌」；
    V3 是全新设计体系（一个蓝 #4E6BFF + 中性灰阶 + 双主题成对），
    生产字典里没有这些值，故生成器改为**持有 V3 令牌表**（本文件即唯一真源）。
  · 旧 42 个令牌名全部保留（值按 V3 语义重映射），保证既有 QML 不改名也能编译；
    新增 cText2/cText3/cGlass*/cChipBg/cSelPill/cType* 等 V3 语义令牌。
  · 每个令牌浅/深成对定义（规格 §2.3 硬要求），tests/theme_probe.py 逐值断言。

⚠️ 只改本生成器，不要手改 qml/Theme.qml（产物头注释已写明）。
"""

from __future__ import annotations

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "qml" / "Theme.qml"

# (令牌名, 浅色, 深色)
# 顺序 = 产物内顺序；旧名在前（兼容既有 QML），V3 新名在后。
TOKENS: list[tuple[str, str, str]] = [
    # ---- 底 / 面板 / 玻璃（§2.2 §2.3 §2.7）----
    # 浅色窗口底 #E7EDFC 必须比面板深，卡片才浮得起来；深色不用纯黑。
    ("C_BG", "#D8E3FA", "#0A0E1A"),
    ("C_PANEL", "#FFFFFF", "#13FFFFFF"),          # 列表：纯白 / 白 7.5%
    ("C_PANEL_SIDE", "#F0FFFFFF", "#0DFFFFFF"),   # 侧栏：白 94% / 白 5%
    ("C_PANEL_INSP", "#CCFFFFFF", "#0FFFFFFF"),   # 检查器：白 80% / 白 6%
    ("C_TOOLBAR", "#8CFFFFFF", "#0FFFFFFF"),      # 顶栏玻璃：白 74% / 白 6%
    ("C_GLASS_BORDER", "#F2FFFFFF", "#1FFFFFFF"),  # 1px 白 95% / 白 12%
    ("C_SIDEBAR", "#F0FFFFFF", "#0DFFFFFF"),      # 旧名 → 侧栏玻璃
    ("C_BORDER", "#EDF0F6", "#14FFFFFF"),         # 分隔线：浅 #EDF0F6 / 深 白 8%
    ("C_HAIRLINE", "#D6DFF2", "#1FFFFFFF"),       # 栏间发丝线
    ("C_VSEP", "#D6DFF2", "#1FFFFFFF"),           # 旧名（列竖线）→ 发丝线
    ("C_HEADER_BG", "#00FFFFFF", "#00FFFFFF"),     # V3 表头无底色
    ("C_HEADER_HOVER", "#F6F9FF", "#0AFFFFFF"),   # 旧名 → hover 行底
    ("DETAIL_BG", "#FBFCFE", "#0AFFFFFF"),
    ("C_INSP_BG", "#FBFCFE", "#0AFFFFFF"),

    # ---- 文本（§2.2 §2.3；M35 验收 A4：深色弱色提亮）----
    ("C_TEXT", "#0F1A33", "#E9EEFA"),
    ("C_TEXT_2", "#2A3752", "#C6D0E2"),
    ("C_TEXT_3", "#3A4763", "#A9BDFF"),           # 深色 300 = 正文次级
    ("C_TEXT_DIM", "#66738C", "#7E8BA6"),
    ("C_TEXT_WEAK", "#6E7B94", "#8C99B4"),         # M35：#6E7C97→#8C99B4（≥3:1）
    ("C_TEXT_MUTE", "#8A96AC", "#55627A"),
    ("C_TEXT_TYPE", "#475467", "#8C99B4"),         # M35：文件类型列（11px 大写）
    ("C_TEXT_HEADER", "#66738C", "#98A6C4"),       # M35：表头专用（弱色 ≥3:1）

    # ---- 蓝阶（§2.1）----
    ("C_ACCENT", "#4E6BFF", "#A9BDFF"),           # 600 / 深色用 300
    ("C_ACCENT_2", "#6C8CFF", "#6C8CFF"),         # 400：渐变起点
    ("C_ACCENT_3", "#A9BDFF", "#A9BDFF"),         # 300
    ("C_ACCENT_HOVER", "#3D5AE0", "#7C99FF"),     # 700
    ("C_ACCENT_DOWN", "#3D5AE0", "#4E6BFF"),
    ("C_ACCENT_TEXT", "#FFFFFF", "#FFFFFF"),
    ("C_ACCENT_BG", "#EBF0FF", "#334E6BFF"),      # 100 / 深色 20% 蓝
    ("C_SELECT_BG", "#EBF0FF", "#334E6BFF"),      # 旧名 → 选中底
    ("C_SEL_PILL", "#EBF0FF", "#334E6BFF"),
    ("C_SEL_BAR", "#4E6BFF", "#6C8CFF"),
    ("C_FOCUS", "#4E6BFF", "#7C99FF"),
    ("C_IRIS", "#7A5CFF", "#7A5CFF"),
    ("C_AQUA", "#22D3EE", "#22D3EE"),
    # M35 验收 2.1：主按钮渐变专用（深色 #7C99FF→#4E6BFF，浅色不变）
    ("C_PRIMARY_A", "#4E68F0", "#4E68F0"),
    ("C_PRIMARY_B", "#4560E8", "#4560E8"),

    # ---- 语义色 ----
    ("C_DANGER", "#E5484D", "#FF7A7E"),
    ("C_DANGER_SOFT", "#FCE8E9", "#3A1F26"),
    ("C_DANGER_HOVER", "#FBE3E4", "#46262D"),
    ("C_DANGER_DOWN", "#F8D6D8", "#522B33"),
    ("C_SUCCESS", "#0E9F6E", "#3DDC97"),
    ("C_SUCCESS_BG", "#E6F7F0", "#12332A"),
    # M35 验收 4.2：diff 琥珀=改动（红=删 / 琥珀=改 / 绿=增，三色固定）
    ("C_CHANGE", "#B45309", "#FFA05C"),
    ("C_CHANGE_BG", "#FFF2E8", "#3A2618"),
    ("C_INS", "#067647", "#47CD89"),               # 新增行文字/描边
    ("C_INS_BG", "#ECFDF3", "#0D3325"),            # 新增行底色
    ("C_STAR", "#F5A524", "#F5A524"),
    ("C_HIT_BG", "#FFF2B3", "#4D4520"),
    # M35 验收 2.2：弹窗遮罩（浅 rgba(11,18,36,.20) / 深 rgba(0,0,0,.40)）
    ("C_SCRIM", "#330B1224", "#66000000"),
    # M35 验收 2.2：深色弹窗底 #141A2B→#1A2233（与设置弹窗统一）
    ("C_DIALOG_BG", "#FFFFFF", "#1A2233"),
    ("C_TIP_BG", "#0F1A33", "#E9EEFA"),           # toast：成功=深色底
    ("C_TIP_FG", "#FFFFFF", "#0A0E1A"),

    # ---- 控件底（§4.6 §4.7 §6）----
    ("C_INPUT_BG", "#CCFFFFFF", "#F5101626"),     # 深色输入框给实底（96%）
    ("C_INPUT_BORDER", "#DCE3EF", "#1AFFFFFF"),
    ("C_BTN_BG", "#CCFFFFFF", "#14FFFFFF"),
    ("C_BTN_HOVER", "#F4F6FA", "#1FFFFFFF"),
    ("C_BTN_PRESS", "#EDF0F6", "#29FFFFFF"),
    ("C_DISABLED_BG", "#F7F8F9", "#1A2132"),
    ("C_DISABLED_FG", "#8A9099", "#5F6A77"),
    ("C_CHIP_BG", "#F2F5FD", "#14FFFFFF"),
    ("C_CHIP_BG_SEL", "#FFFFFF", "#33FFFFFF"),
    ("C_ROW_HOVER", "#F6F9FF", "#0AFFFFFF"),
    ("C_SEARCH_BG", "#9EFFFFFF", "#0DFFFFFF"),   # 顶栏搜索：白 62% / 白 5%

    # ---- 滚动条（§4.7：轨道透明、滑块 6px）----
    ("C_SCROLL_THUMB", "#C9D3E6", "#3A4763"),
    ("C_SCROLL_THUMB_HOVER", "#9FB0CE", "#55627A"),
    ("C_SCROLL_TRACK", "#00FFFFFF", "#00FFFFFF"),

    # ---- 菜单（§4.8）----
    ("C_MENU_BG", "#FFFFFF", "#F5171E30"),
    ("C_MENU_BORDER", "#EDF0F6", "#1FFFFFFF"),
    ("C_MENU_FG", "#0F1A33", "#E9EEFA"),
    ("C_MENU_HOVER", "#EBF0FF", "#334E6BFF"),
    ("C_MENU_DANGER", "#E5484D", "#FF7A7E"),
    ("C_MENU_DIS", "#B3BCCB", "#55627A"),
    ("C_MENU_ACCEL", "#8492AC", "#8C99B4"),       # M35：深色随弱色提亮
    ("C_MENU_CURRENT", "#4E6BFF", "#A9BDFF"),

    # ---- 文件类型编码（§2.4：图标底色 / 图形色）----
    ("C_TYPE_DOCX_BG", "#EEF3FF", "#1D2A55"),
    ("C_TYPE_DOCX_FG", "#4E6BFF", "#8FA6FF"),
    ("C_TYPE_XLSX_BG", "#EAF7F1", "#12332A"),
    ("C_TYPE_XLSX_FG", "#0E9F6E", "#3DDC97"),
    ("C_TYPE_PPTX_BG", "#FFF2E8", "#3A2618"),
    ("C_TYPE_PPTX_FG", "#F97316", "#FFA05C"),
    ("C_TYPE_PDF_BG", "#FCE8E9", "#3A1F26"),
    ("C_TYPE_PDF_FG", "#E5484D", "#FF7A7E"),
    ("C_TYPE_TXT_BG", "#EFF2F7", "#232A38"),
    ("C_TYPE_TXT_FG", "#8892A6", "#A9B6CE"),
    ("C_TYPE_IMG_BG", "#F0E9FD", "#2A1F45"),
    ("C_TYPE_IMG_FG", "#8B5CF6", "#C0A6FF"),

    # ---- M93：浮层 / 卡片 / 气泡（收口散落的 dark 三元组）----
    # 这些值原本以 `Theme.mode === "dark" ? A : B` 硬编码在 8 个 QML 里，共 26 处。
    # 改主题时要逐个记得改，漏一处就是「某个弹层在暗色下还是白块」——而且浅色下
    # 完全看不出来。现在统一由本表签发，QML 只写 Theme.cXxx。
    ("C_FLOAT_BG", "#FFFFFF", "#1A2233"),              # 浮层底：下拉/弹窗/列显隐卡
    ("C_FLOAT_BORDER", "#EDF0F6", "#1FFFFFFF"),        # 浮层边框
    ("C_NAV_SEL_BG", "#FFFFFF", "#2E3A55"),            # 分类树选中卡底
    ("C_NAV_SEL_BORDER", "#F2F5FD", "#1FFFFFFF"),      # 分类树选中卡边框
    ("C_SUBTLE_BG", "#F7F9FE", "#0DFFFFFF"),           # 凹底块：设置分组/预览/版本区
    ("C_EMPTY_BG", "#FBFCFE", "#08FFFFFF"),            # 空态盒子底
    ("C_CARD_SEL_BG", "#F5FFFFFF", "#14FFFFFF"),       # 版本卡悬停/选中底
    ("C_CARD_SEL_BORDER", "#144E6BFF", "#334E6BFF"),   # 版本卡选中边框
    ("C_NODE_BG", "#FFFFFF", "#101626"),               # 时间线节点填充（须盖住竖线）
    # 气泡：暗色原为 #0F1A33，比面板 #1C202B 还暗（1.04:1），浮层方向反了。
    # 改为 #333B50：对面板 1.46:1，与文字 #E9EEFA 对比 9.5:1。
    ("C_BUBBLE_BG", "#FFFFFF", "#333B50"),             # 悬停气泡底
    ("C_BUBBLE_BORDER", "#EDF0F6", "#24FFFFFF"),       # 悬停气泡边框
]

# 排版 / 尺度 / 动效（非颜色，手工维护；改这里即改全站）
# M40：随包字体的族名改为独有的 PJM Sans SC / PJM Num（tools/rename_fonts_pjm.py），
# 避免与系统安装的 Noto Sans SC 同名合并导致部分字形错位（部分企业环境机器实测乱码）。
EXTRA_PROPS = '''
    // ================= M29 · V3 排版令牌（规格 §2.5）=================
    readonly property string fontFamily: "PJM Sans SC"
    readonly property string numFamily: "PJM Num"
    readonly property string fallbackFamily: "Microsoft YaHei UI"

    readonly property int fsPage: 20        // 页面标题 20/SemiBold
    readonly property int fsDialog: 18      // 弹窗标题 18/SemiBold
    readonly property int fsSection: 16     // 区块标题 16/SemiBold
    readonly property int fsBody: 14        // 正文 / 行 14
    // M100：元信息 12 → 13。用户反馈「文件区文字、右栏标题区偏小」。
    // 查下来块标题本身是 16/DemiBold 并不小，真正小的是**列表里的数据列**
    // 和右栏副标题——它们都吃这一档。12px 配 48px 行高，留白太多显空。
    // 主流做法（Windows 资源管理器、VS Code 资源管理器）是**同列表内各列
    // 同字号**，主次靠颜色/字重区分，而不是靠缩字号；所以这里只把这一档
    // 抬到 13（仍比文件名 14 小一档，保留层次），不整体拉平到 14。
    readonly property real fsMeta: 13     // 元信息（小数必须是 real）
    readonly property real fsLabel: 11    // 表头 / 标签 10.5，字距 +0.5
    readonly property real fsNano: 10      // 微型 10

    // 旧名保留（既有 QML 不改名即可编译），按 V3 语义对齐
    readonly property int fsBase: 13
    readonly property real fsSm: 12
    readonly property real fsXs: 11
    readonly property real fsMicro: 10
    readonly property int fsTitle: 20

    readonly property real lsLabel: 0.5     // 表头字距

    // ================= M29 · V3 尺度（规格 §2.6）=================
    readonly property int sp4: 4
    readonly property int sp8: 8
    readonly property int sp12: 12
    readonly property int sp16: 16
    readonly property int sp20: 20
    readonly property int sp24: 24
    readonly property int sp28: 28
    readonly property int sp32: 32
    readonly property int sp48: 48
    // 半档：2 与 6 是紧凑行内间隙的真实需求（6px 出现过 14 次）
    readonly property int sp2: 2
    readonly property int sp6: 6

    readonly property int rPanel: 12
    readonly property int rTopBar: 11            // M35：顶栏收窄 60→48，圆角 18→14
    readonly property int rCard: 10
    readonly property int rBtn: 9
    readonly property int rBtnPrimary: 8        // M35：主按钮圆角 10（§4.1 定稿）
    readonly property int rInput: 9
    readonly property int rChip: 7
    readonly property int rBadge: 7
    readonly property int rMenu: 10

    // ================= M29 · 玻璃 / 极光（规格 §2.7）=================
    // QML 没有 backdrop-filter：半透明面板 + 背后柔边径向光斑近似。
    // 极光只允许出现在顶栏背后（横向光带）与右栏背后（竖向冷光），
    // 列表背后不放颜色；透明度上限浅 0.42/0.30/0.20、深 0.30/0.22/0.14。
    readonly property real auroraA: mode === "dark" ? 0.30 : 0.42
    readonly property real auroraB: mode === "dark" ? 0.22 : 0.30
    readonly property real auroraC: mode === "dark" ? 0.14 : 0.20

    // ================= M29 · 动效（规格 §1.5）=================
    readonly property int durHover: 140
    readonly property int durPane: 220

    // ===== M81：动效令牌 =====
    // 依据 Material 对桌面端的明确建议：过渡 150–200ms（比移动端更快），
    // 进入用减速曲线、退场用加速且更短。之前全项目只有两个裸数字、
    // 没有任何缓动曲线 → 所有 Behavior 走默认 Linear，看着"机械"。
    readonly property int durFast: 110        // 悬停/按下/退场
    readonly property int durBase: 160        // 菜单、弹窗进场；列表让位
    readonly property int durLarge: 220       // 面板级位移
    // cubic-bezier 控制点（QML Easing.Bezier 接受四元数组）
    readonly property var easeStandard: [0.4, 0.0, 0.2, 1.0]   // 起止都在屏内
    readonly property var easeDecel: [0.0, 0.0, 0.2, 1.0]      // 进场：全速到静止
    readonly property var easeAccel: [0.4, 0.0, 1.0, 1.0]      // 退场：静止到全速
'''


def camel(name: str) -> str:
    parts = name.lower().split("_")
    head = parts[0]
    if head == "c":
        head = "c"
    if head == "detail":
        head = "detail"
    return head + "".join(p.capitalize() for p in parts[1:])


def main() -> int:
    seen = set()
    for k, _l, _d in TOKENS:
        assert k not in seen, f"重复令牌 {k}"
        seen.add(k)

    def block(idx: int, indent: str = "            ") -> str:
        return "\n".join(f"{indent}{t[0]}: \"{t[idx]}\"," for t in TOKENS)

    props = "\n".join(
        f"    readonly property color {camel(k)}: tokens.{k}" for k, *_ in TOKENS)

    qml = f"""pragma Singleton
import QtQuick

// 主题令牌单例 —— V3 设计体系（项目文件管家 UI 规格书 V3 §2）。
// ⚠️ 机械生成物：只改 tools/gen_theme.py，不要手改本文件。
// 生成口径：每个令牌浅/深成对定义；旧 42 令牌名保留（值按 V3 语义重映射），
// 新增 cText2/cText3/cGlass*/cChipBg/cSelPill/cType* 等语义令牌。
// 机制：切 mode → tokens 换表 → 全界面重绑定（无闪、无重建）。
QtObject {{
    property string mode: "light"   // "light" | "dark"

    // JS 对象字面量必须包一层圆括号（QML binding 的 {{ 有分组歧义）
    readonly property var _light: ({{
{block(1)}
    }})

    readonly property var _dark: ({{
{block(2)}
    }})

    readonly property var tokens: mode === "dark" ? _dark : _light

    // 语义色访问器（QML 侧统一用这些名字；共 {len(TOKENS)} 个 × 2 模式）
{props}
{EXTRA_PROPS}
    function switchMode(m) {{
        if (m === "light" || m === "dark") mode = m
    }}

    // QML 的 font.pixelSize 是 int（QFont::pixelSize），规格里的 11.5/10.5/9.5
    // 这类小数字号只能用 pointSize（real）。96dpi 逻辑坐标下 1px = 0.75pt。
    function pt(px) {{
        return px * 0.75
    }}

    function toggleMode() {{
        mode = mode === "dark" ? "light" : "dark"
    }}
}}
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(qml, encoding="utf-8")
    n = len(TOKENS)
    print(f"[theme] OK -> {OUT}  ({n} 令牌 × 2 模式 = {n * 2} 值, "
          f"访问器 {n} 个)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
