# 井然（Jingran）

> 每个文件，井然有序。

井然是一个**本地文件版本与分类管理**工具：把散落的文件收进分类、每次修改留下一个版本、随时回溯，全部数据存在你自己的电脑上。

![Windows](https://img.shields.io/badge/platform-Windows%2010%2B%20x64-0078D4)
![License](https://img.shields.io/badge/license-MIT-green)

## 它能做什么

- **拖入即收纳**：把文件或文件夹拖进窗口，按分类归档；拖到某个文件行上可直接为它续一个版本
- **多版本时间轴**：每个文件保留完整版本历史，随时对比、回滚、另存
- **分类树**：一级分类 / 子分类自由组织，拖拽移动、批量整理
- **星标与搜索**：常用文件置顶，关键字即时过滤
- **回收站**：删除进回收站可还原，也可彻底清除
- **拖出分享**：把任意版本拖到微信 / 资源管理器 / SVN，即得到一份真实文件
- **完全本地**：不联网、不上传、无遥测，版本库就在 `%LOCALAPPDATA%\井然\store`

## 下载与安装

- **安装版**：到 [Releases](../../releases) 下载 `井然_安装程序_x.y.z.exe`，双击按提示安装。
  - 装到当前用户目录，**不需要管理员权限**；
  - 卸载只删程序，**不会删你的版本库**。

系统要求：Windows 10 1809 及以上（x64）。

## 从源码构建

```bash
# 依赖
python -m pip install "PySide6==6.12.*" pyinstaller

# 打包（onedir，输出到 build_qml/dist_mXX/井然；XX 随版本递增）
pyinstaller build_pjm_qml.spec --distpath build_qml/dist_mXX --workpath build_qml_work_mXX --noconfirm

# 做安装包（需先安装 Inno Setup 6）
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/jingran.iss
```

发版还有一个容易踩的坑：Inno 遇到被占用/被杀软扫描锁定的文件会**静默跳过**，
安装仍报成功，结果是版本号变了、界面还是旧的。仓库里带了两个校验脚本：

```bash
python tools/wait_install.py <安装包.exe> <dist_mXX/井然/井然.exe>   # 等安装真正完成
python tools/verify_install.py <dist_mXX/井然>                      # 逐文件哈希比对
```

开发运行：`python main.py`。开发态默认用项目内的 `.devstore` 作沙箱库，不会触碰
`%LOCALAPPDATA%\井然\store`（启动时有断言拦截，防止误开真实库）；如需指定其他沙箱，
设置环境变量 `DOCVER_STORE`。

## 数据与隐私

- 版本库默认位于 `%LOCALAPPDATA%\井然\store`，可通过「设置 → 更改版本库位置」迁移；
- 程序**不发起任何网络请求**，无账号、无云同步、无统计上报；
- 提交时只做**字节级复制**，不打开、不解析、不索引文件内容
  （唯一例外：你主动点「文本对比」时，才会按白名单读取那两个版本）。

## 测试

一条命令跑完核心回归集（13 个用例 / 约 90 秒），全部是离屏运行、不碰真实库：

```bash
set QT_QPA_PLATFORM=offscreen
python tests/run_all.py
```

覆盖集成、交互、回收站、行内操作、设置/托盘、拖拽、弹窗、暗色主题、页脚、
分栏拖拽、弹窗尺寸与 UI 冒烟。新增行为时优先在对应探针里补断言——
尤其是「有上限的断言要配一条下限」，只有上界的检查漏掉过真事故。

## 字体

随包字体为 Noto Sans SC 与 Inter（均为 SIL Open Font License 1.1），
为避免与系统安装的同名字体冲突，本项目将其**改名为** `PJM Sans SC` / `PJM Num`
（仅修改 name 表，字形与度量未变），详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

[MIT](LICENSE)
