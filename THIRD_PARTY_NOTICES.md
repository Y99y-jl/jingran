# 第三方组件与许可声明

本项目在运行时与分发物中包含以下第三方组件。分发（含安装包）时请保留本文件。

## Qt / PySide6

- 组件：Qt 6.12（Core、Gui、Qml、Quick、QuickControls2 等）与 PySide6 6.12
- 许可：**LGPL v3**（Qt 与 PySide6 均以 LGPLv3 提供）
- 使用方式：本程序以**动态链接**方式使用 Qt 库（`_internal/PySide6/*.dll`），
  未修改 Qt 源码；使用者可自行替换这些 DLL 为兼容版本。
- 许可全文：https://www.gnu.org/licenses/lgpl-3.0.html
- 项目主页：https://www.qt.io/ 、https://pypi.org/project/PySide6/

## 字体：PJM Sans SC（源自 Noto Sans SC）

- 上游：Noto Sans SC（Google / Adobe），版本 2.004-H2
- 许可：**SIL Open Font License 1.1**（OFL-1.1）
- 本项目修改：仅修改字体 name 表（家族名改为 `PJM Sans SC`、唯一 ID 与
  PostScript 名同步），**未改动字形、字宽与度量**。改名为遵守 OFL 关于
  修改版不得冒充原字体的要求，并避免与用户系统中安装的同名 Noto 字体冲突。
- 许可全文：https://openfontlicense.org/open-font-license-official-text/

## 字体：PJM Num（源自 Inter）

- 上游：Inter（Rasmus Andersson），版本 4.001
- 许可：**SIL Open Font License 1.1**（OFL-1.1）
- 本项目修改：同上——仅改家族名（`PJM Num`），字形、字宽与度量未改动。
- 许可全文：https://openfontlicense.org/open-font-license-official-text/

## 图标与视觉资源

- `resources/icons/*`、`resources/logo_v3.png`、`resources/app_icon.ico`：
  本项目自制资源，随本项目以 MIT 许可分发。
- UI 内的矢量图标由项目内 `GlyphIcon` 组件以 QML 绘制，无第三方图标库依赖。

## Python 运行时

- 组件：CPython 3.13（随 PyInstaller 打包分发）
- 许可：PSF License Agreement
- https://docs.python.org/3/license.html

## 打包工具（不随分发物提供）

- PyInstaller（GPL with exception）、Inno Setup（修改版 BSD）——仅用于构建，
  其许可不影响本项目的 MIT 授权。
- fontTools（MIT）——仅用于 `tools/rename_fonts_pjm.py` 调整字体 name 表，
  不进入分发物。

## 名称

本项目的名称「井然」为常用汉语词汇，本项目未申请商标。若你计划将本项目
或其衍生作品用于商业产品，请自行核查目标市场的商标情况（软件相关类别
通常为第 9 类与第 42 类）。
