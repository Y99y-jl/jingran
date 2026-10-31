pragma Singleton
import QtQuick

// 主题令牌单例 —— V3 设计体系（项目文件管家 UI 规格书 V3 §2）。
// ⚠️ 机械生成物：只改 tools/gen_theme.py，不要手改本文件。
// 生成口径：每个令牌浅/深成对定义；旧 42 令牌名保留（值按 V3 语义重映射），
// 新增 cText2/cText3/cGlass*/cChipBg/cSelPill/cType* 等语义令牌。
// 机制：切 mode → tokens 换表 → 全界面重绑定（无闪、无重建）。
QtObject {
    property string mode: "light"   // "light" | "dark"

    // JS 对象字面量必须包一层圆括号（QML binding 的 { 有分组歧义）
    readonly property var _light: ({
            C_BG: "#D8E3FA",
            C_PANEL: "#FFFFFF",
            C_PANEL_SIDE: "#F0FFFFFF",
            C_PANEL_INSP: "#CCFFFFFF",
            C_TOOLBAR: "#8CFFFFFF",
            C_GLASS_BORDER: "#F2FFFFFF",
            C_SIDEBAR: "#F0FFFFFF",
            C_BORDER: "#EDF0F6",
            C_HAIRLINE: "#D6DFF2",
            C_VSEP: "#D6DFF2",
            C_HEADER_BG: "#00FFFFFF",
            C_HEADER_HOVER: "#F6F9FF",
            DETAIL_BG: "#FBFCFE",
            C_INSP_BG: "#FBFCFE",
            C_TEXT: "#0F1A33",
            C_TEXT_2: "#2A3752",
            C_TEXT_3: "#3A4763",
            C_TEXT_DIM: "#66738C",
            C_TEXT_WEAK: "#6E7B94",
            C_TEXT_MUTE: "#8A96AC",
            C_TEXT_TYPE: "#475467",
            C_TEXT_HEADER: "#66738C",
            C_ACCENT: "#4E6BFF",
            C_ACCENT_2: "#6C8CFF",
            C_ACCENT_3: "#A9BDFF",
            C_ACCENT_HOVER: "#3D5AE0",
            C_ACCENT_DOWN: "#3D5AE0",
            C_ACCENT_TEXT: "#FFFFFF",
            C_ACCENT_BG: "#EBF0FF",
            C_SELECT_BG: "#EBF0FF",
            C_SEL_PILL: "#EBF0FF",
            C_SEL_BAR: "#4E6BFF",
            C_FOCUS: "#4E6BFF",
            C_IRIS: "#7A5CFF",
            C_AQUA: "#22D3EE",
            C_PRIMARY_A: "#4E68F0",
            C_PRIMARY_B: "#4560E8",
            C_DANGER: "#E5484D",
            C_DANGER_SOFT: "#FCE8E9",
            C_DANGER_HOVER: "#FBE3E4",
            C_DANGER_DOWN: "#F8D6D8",
            C_SUCCESS: "#0E9F6E",
            C_SUCCESS_BG: "#E6F7F0",
            C_CHANGE: "#B45309",
            C_CHANGE_BG: "#FFF2E8",
            C_INS: "#067647",
            C_INS_BG: "#ECFDF3",
            C_STAR: "#F5A524",
            C_HIT_BG: "#FFF2B3",
            C_SCRIM: "#330B1224",
            C_DIALOG_BG: "#FFFFFF",
            C_TIP_BG: "#0F1A33",
            C_TIP_FG: "#FFFFFF",
            C_INPUT_BG: "#CCFFFFFF",
            C_INPUT_BORDER: "#DCE3EF",
            C_BTN_BG: "#CCFFFFFF",
            C_BTN_HOVER: "#F4F6FA",
            C_BTN_PRESS: "#EDF0F6",
            C_DISABLED_BG: "#F7F8F9",
            C_DISABLED_FG: "#8A9099",
            C_CHIP_BG: "#F2F5FD",
            C_CHIP_BG_SEL: "#FFFFFF",
            C_ROW_HOVER: "#F6F9FF",
            C_SEARCH_BG: "#9EFFFFFF",
            C_SCROLL_THUMB: "#C9D3E6",
            C_SCROLL_THUMB_HOVER: "#9FB0CE",
            C_SCROLL_TRACK: "#00FFFFFF",
            C_MENU_BG: "#FFFFFF",
            C_MENU_BORDER: "#EDF0F6",
            C_MENU_FG: "#0F1A33",
            C_MENU_HOVER: "#EBF0FF",
            C_MENU_DANGER: "#E5484D",
            C_MENU_DIS: "#B3BCCB",
            C_MENU_ACCEL: "#8492AC",
            C_MENU_CURRENT: "#4E6BFF",
            C_TYPE_DOCX_BG: "#EEF3FF",
            C_TYPE_DOCX_FG: "#4E6BFF",
            C_TYPE_XLSX_BG: "#EAF7F1",
            C_TYPE_XLSX_FG: "#0E9F6E",
            C_TYPE_PPTX_BG: "#FFF2E8",
            C_TYPE_PPTX_FG: "#F97316",
            C_TYPE_PDF_BG: "#FCE8E9",
            C_TYPE_PDF_FG: "#E5484D",
            C_TYPE_TXT_BG: "#EFF2F7",
            C_TYPE_TXT_FG: "#8892A6",
            C_TYPE_IMG_BG: "#F0E9FD",
            C_TYPE_IMG_FG: "#8B5CF6",
            C_FLOAT_BG: "#FFFFFF",
            C_FLOAT_BORDER: "#EDF0F6",
            C_NAV_SEL_BG: "#FFFFFF",
            C_NAV_SEL_BORDER: "#F2F5FD",
            C_SUBTLE_BG: "#F7F9FE",
            C_EMPTY_BG: "#FBFCFE",
            C_CARD_SEL_BG: "#F5FFFFFF",
            C_CARD_SEL_BORDER: "#144E6BFF",
            C_NODE_BG: "#FFFFFF",
            C_BUBBLE_BG: "#FFFFFF",
            C_BUBBLE_BORDER: "#EDF0F6",
    })

    readonly property var _dark: ({
            C_BG: "#0A0E1A",
            C_PANEL: "#13FFFFFF",
            C_PANEL_SIDE: "#0DFFFFFF",
            C_PANEL_INSP: "#0FFFFFFF",
            C_TOOLBAR: "#0FFFFFFF",
            C_GLASS_BORDER: "#1FFFFFFF",
            C_SIDEBAR: "#0DFFFFFF",
            C_BORDER: "#14FFFFFF",
            C_HAIRLINE: "#1FFFFFFF",
            C_VSEP: "#1FFFFFFF",
            C_HEADER_BG: "#00FFFFFF",
            C_HEADER_HOVER: "#0AFFFFFF",
            DETAIL_BG: "#0AFFFFFF",
            C_INSP_BG: "#0AFFFFFF",
            C_TEXT: "#E9EEFA",
            C_TEXT_2: "#C6D0E2",
            C_TEXT_3: "#A9BDFF",
            C_TEXT_DIM: "#7E8BA6",
            C_TEXT_WEAK: "#8C99B4",
            C_TEXT_MUTE: "#55627A",
            C_TEXT_TYPE: "#8C99B4",
            C_TEXT_HEADER: "#98A6C4",
            C_ACCENT: "#A9BDFF",
            C_ACCENT_2: "#6C8CFF",
            C_ACCENT_3: "#A9BDFF",
            C_ACCENT_HOVER: "#7C99FF",
            C_ACCENT_DOWN: "#4E6BFF",
            C_ACCENT_TEXT: "#FFFFFF",
            C_ACCENT_BG: "#334E6BFF",
            C_SELECT_BG: "#334E6BFF",
            C_SEL_PILL: "#334E6BFF",
            C_SEL_BAR: "#6C8CFF",
            C_FOCUS: "#7C99FF",
            C_IRIS: "#7A5CFF",
            C_AQUA: "#22D3EE",
            C_PRIMARY_A: "#4E68F0",
            C_PRIMARY_B: "#4560E8",
            C_DANGER: "#FF7A7E",
            C_DANGER_SOFT: "#3A1F26",
            C_DANGER_HOVER: "#46262D",
            C_DANGER_DOWN: "#522B33",
            C_SUCCESS: "#3DDC97",
            C_SUCCESS_BG: "#12332A",
            C_CHANGE: "#FFA05C",
            C_CHANGE_BG: "#3A2618",
            C_INS: "#47CD89",
            C_INS_BG: "#0D3325",
            C_STAR: "#F5A524",
            C_HIT_BG: "#4D4520",
            C_SCRIM: "#66000000",
            C_DIALOG_BG: "#1A2233",
            C_TIP_BG: "#E9EEFA",
            C_TIP_FG: "#0A0E1A",
            C_INPUT_BG: "#F5101626",
            C_INPUT_BORDER: "#1AFFFFFF",
            C_BTN_BG: "#14FFFFFF",
            C_BTN_HOVER: "#1FFFFFFF",
            C_BTN_PRESS: "#29FFFFFF",
            C_DISABLED_BG: "#1A2132",
            C_DISABLED_FG: "#5F6A77",
            C_CHIP_BG: "#14FFFFFF",
            C_CHIP_BG_SEL: "#33FFFFFF",
            C_ROW_HOVER: "#0AFFFFFF",
            C_SEARCH_BG: "#0DFFFFFF",
            C_SCROLL_THUMB: "#3A4763",
            C_SCROLL_THUMB_HOVER: "#55627A",
            C_SCROLL_TRACK: "#00FFFFFF",
            C_MENU_BG: "#F5171E30",
            C_MENU_BORDER: "#1FFFFFFF",
            C_MENU_FG: "#E9EEFA",
            C_MENU_HOVER: "#334E6BFF",
            C_MENU_DANGER: "#FF7A7E",
            C_MENU_DIS: "#55627A",
            C_MENU_ACCEL: "#8C99B4",
            C_MENU_CURRENT: "#A9BDFF",
            C_TYPE_DOCX_BG: "#1D2A55",
            C_TYPE_DOCX_FG: "#8FA6FF",
            C_TYPE_XLSX_BG: "#12332A",
            C_TYPE_XLSX_FG: "#3DDC97",
            C_TYPE_PPTX_BG: "#3A2618",
            C_TYPE_PPTX_FG: "#FFA05C",
            C_TYPE_PDF_BG: "#3A1F26",
            C_TYPE_PDF_FG: "#FF7A7E",
            C_TYPE_TXT_BG: "#232A38",
            C_TYPE_TXT_FG: "#A9B6CE",
            C_TYPE_IMG_BG: "#2A1F45",
            C_TYPE_IMG_FG: "#C0A6FF",
            C_FLOAT_BG: "#1A2233",
            C_FLOAT_BORDER: "#1FFFFFFF",
            C_NAV_SEL_BG: "#2E3A55",
            C_NAV_SEL_BORDER: "#1FFFFFFF",
            C_SUBTLE_BG: "#0DFFFFFF",
            C_EMPTY_BG: "#08FFFFFF",
            C_CARD_SEL_BG: "#14FFFFFF",
            C_CARD_SEL_BORDER: "#334E6BFF",
            C_NODE_BG: "#101626",
            C_BUBBLE_BG: "#333B50",
            C_BUBBLE_BORDER: "#24FFFFFF",
    })

    readonly property var tokens: mode === "dark" ? _dark : _light

    // 语义色访问器（QML 侧统一用这些名字；共 98 个 × 2 模式）
    readonly property color cBg: tokens.C_BG
    readonly property color cPanel: tokens.C_PANEL
    readonly property color cPanelSide: tokens.C_PANEL_SIDE
    readonly property color cPanelInsp: tokens.C_PANEL_INSP
    readonly property color cToolbar: tokens.C_TOOLBAR
    readonly property color cGlassBorder: tokens.C_GLASS_BORDER
    readonly property color cSidebar: tokens.C_SIDEBAR
    readonly property color cBorder: tokens.C_BORDER
    readonly property color cHairline: tokens.C_HAIRLINE
    readonly property color cVsep: tokens.C_VSEP
    readonly property color cHeaderBg: tokens.C_HEADER_BG
    readonly property color cHeaderHover: tokens.C_HEADER_HOVER
    readonly property color detailBg: tokens.DETAIL_BG
    readonly property color cInspBg: tokens.C_INSP_BG
    readonly property color cText: tokens.C_TEXT
    readonly property color cText2: tokens.C_TEXT_2
    readonly property color cText3: tokens.C_TEXT_3
    readonly property color cTextDim: tokens.C_TEXT_DIM
    readonly property color cTextWeak: tokens.C_TEXT_WEAK
    readonly property color cTextMute: tokens.C_TEXT_MUTE
    readonly property color cTextType: tokens.C_TEXT_TYPE
    readonly property color cTextHeader: tokens.C_TEXT_HEADER
    readonly property color cAccent: tokens.C_ACCENT
    readonly property color cAccent2: tokens.C_ACCENT_2
    readonly property color cAccent3: tokens.C_ACCENT_3
    readonly property color cAccentHover: tokens.C_ACCENT_HOVER
    readonly property color cAccentDown: tokens.C_ACCENT_DOWN
    readonly property color cAccentText: tokens.C_ACCENT_TEXT
    readonly property color cAccentBg: tokens.C_ACCENT_BG
    readonly property color cSelectBg: tokens.C_SELECT_BG
    readonly property color cSelPill: tokens.C_SEL_PILL
    readonly property color cSelBar: tokens.C_SEL_BAR
    readonly property color cFocus: tokens.C_FOCUS
    readonly property color cIris: tokens.C_IRIS
    readonly property color cAqua: tokens.C_AQUA
    readonly property color cPrimaryA: tokens.C_PRIMARY_A
    readonly property color cPrimaryB: tokens.C_PRIMARY_B
    readonly property color cDanger: tokens.C_DANGER
    readonly property color cDangerSoft: tokens.C_DANGER_SOFT
    readonly property color cDangerHover: tokens.C_DANGER_HOVER
    readonly property color cDangerDown: tokens.C_DANGER_DOWN
    readonly property color cSuccess: tokens.C_SUCCESS
    readonly property color cSuccessBg: tokens.C_SUCCESS_BG
    readonly property color cChange: tokens.C_CHANGE
    readonly property color cChangeBg: tokens.C_CHANGE_BG
    readonly property color cIns: tokens.C_INS
    readonly property color cInsBg: tokens.C_INS_BG
    readonly property color cStar: tokens.C_STAR
    readonly property color cHitBg: tokens.C_HIT_BG
    readonly property color cScrim: tokens.C_SCRIM
    readonly property color cDialogBg: tokens.C_DIALOG_BG
    readonly property color cTipBg: tokens.C_TIP_BG
    readonly property color cTipFg: tokens.C_TIP_FG
    readonly property color cInputBg: tokens.C_INPUT_BG
    readonly property color cInputBorder: tokens.C_INPUT_BORDER
    readonly property color cBtnBg: tokens.C_BTN_BG
    readonly property color cBtnHover: tokens.C_BTN_HOVER
    readonly property color cBtnPress: tokens.C_BTN_PRESS
    readonly property color cDisabledBg: tokens.C_DISABLED_BG
    readonly property color cDisabledFg: tokens.C_DISABLED_FG
    readonly property color cChipBg: tokens.C_CHIP_BG
    readonly property color cChipBgSel: tokens.C_CHIP_BG_SEL
    readonly property color cRowHover: tokens.C_ROW_HOVER
    readonly property color cSearchBg: tokens.C_SEARCH_BG
    readonly property color cScrollThumb: tokens.C_SCROLL_THUMB
    readonly property color cScrollThumbHover: tokens.C_SCROLL_THUMB_HOVER
    readonly property color cScrollTrack: tokens.C_SCROLL_TRACK
    readonly property color cMenuBg: tokens.C_MENU_BG
    readonly property color cMenuBorder: tokens.C_MENU_BORDER
    readonly property color cMenuFg: tokens.C_MENU_FG
    readonly property color cMenuHover: tokens.C_MENU_HOVER
    readonly property color cMenuDanger: tokens.C_MENU_DANGER
    readonly property color cMenuDis: tokens.C_MENU_DIS
    readonly property color cMenuAccel: tokens.C_MENU_ACCEL
    readonly property color cMenuCurrent: tokens.C_MENU_CURRENT
    readonly property color cTypeDocxBg: tokens.C_TYPE_DOCX_BG
    readonly property color cTypeDocxFg: tokens.C_TYPE_DOCX_FG
    readonly property color cTypeXlsxBg: tokens.C_TYPE_XLSX_BG
    readonly property color cTypeXlsxFg: tokens.C_TYPE_XLSX_FG
    readonly property color cTypePptxBg: tokens.C_TYPE_PPTX_BG
    readonly property color cTypePptxFg: tokens.C_TYPE_PPTX_FG
    readonly property color cTypePdfBg: tokens.C_TYPE_PDF_BG
    readonly property color cTypePdfFg: tokens.C_TYPE_PDF_FG
    readonly property color cTypeTxtBg: tokens.C_TYPE_TXT_BG
    readonly property color cTypeTxtFg: tokens.C_TYPE_TXT_FG
    readonly property color cTypeImgBg: tokens.C_TYPE_IMG_BG
    readonly property color cTypeImgFg: tokens.C_TYPE_IMG_FG
    readonly property color cFloatBg: tokens.C_FLOAT_BG
    readonly property color cFloatBorder: tokens.C_FLOAT_BORDER
    readonly property color cNavSelBg: tokens.C_NAV_SEL_BG
    readonly property color cNavSelBorder: tokens.C_NAV_SEL_BORDER
    readonly property color cSubtleBg: tokens.C_SUBTLE_BG
    readonly property color cEmptyBg: tokens.C_EMPTY_BG
    readonly property color cCardSelBg: tokens.C_CARD_SEL_BG
    readonly property color cCardSelBorder: tokens.C_CARD_SEL_BORDER
    readonly property color cNodeBg: tokens.C_NODE_BG
    readonly property color cBubbleBg: tokens.C_BUBBLE_BG
    readonly property color cBubbleBorder: tokens.C_BUBBLE_BORDER

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

    function switchMode(m) {
        if (m === "light" || m === "dark") mode = m
    }

    // QML 的 font.pixelSize 是 int（QFont::pixelSize），规格里的 11.5/10.5/9.5
    // 这类小数字号只能用 pointSize（real）。96dpi 逻辑坐标下 1px = 0.75pt。
    function pt(px) {
        return px * 0.75
    }

    function toggleMode() {
        mode = mode === "dark" ? "light" : "dark"
    }
}
