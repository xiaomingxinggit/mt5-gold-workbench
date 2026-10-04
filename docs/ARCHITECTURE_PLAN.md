# MT5 工作台桌面应用整理计划

> 此文档记录最初的 QWidget 工程整理基线。当前开发分支 `codex/qml-ui-redesign`
> 已将默认入口切换为 `ui/qml_app.py`，六页由 `ui/qml/` 渲染；只读状态桥接见
> `ui/qml_bridge.py`，确认后的写操作见 `ui/qml_trade_bridge.py`。旧 QWidget
> 文件仍在仓库中，但不再由默认入口加载。新界面仍需在真实 Windows 显示器上
> 验收字号、DPI、2K 布局和目标终端的响应速度。

## 目标与边界

把当前平铺在项目根目录的脚本整理为可安装、可测试、可维护的 Windows Python 桌面应用。保持 PySide6 6.11.2、`XAUUSDc` 单品种、USC 美分账户限制、日夜主题和现有五个页面。整理期间不改变仓位算法、订单确认规则或真实交易行为；自动测试只使用模拟 MT5。

目录归类和可安装包入口已建立；`build.ps1`、`requirements-build.txt` 与 `README-package.txt` 提供 Windows 便携 ZIP 的打包流程。目标机器上的启动、图标和持久化路径仍需在发行前验收。

## 整理前识别的问题

1. 根目录曾平铺业务、MT5 接口和 Qt 视图；主窗口混合窗口布局、连接轮询、账户门禁、仓位测算、订单预览与执行。目录归类已解决根目录堆积，但主窗口仍负责多种协调逻辑。
2. 1 秒定时器在 Qt 界面线程同步读取 MT5 和历史数据。终端响应慢时可能让窗口失去响应。
3. 多处直接导入全局 `MetaTrader5`；虽然部分函数支持注入模拟 API，界面仍直接调用终端，缺少统一的账户会话和调用入口。
4. 主窗口和主题模块分别决定状态文件位置。安装到只读目录时，设置和执行记录可能无法写入。
5. 已有离线测试覆盖主要计算与交易路径；仍需补足资源定位、后台刷新与完整确认链路的回归门槛。现在已有 `pyproject.toml` 和打包脚本，自动检查配置仍待完善。

## 目标结构

```text
MT5Test/
├─ pyproject.toml                 # 项目元数据、依赖、入口和检查配置
├─ gui.py                         # 临时兼容旧启动命令
├─ build.ps1                      # Windows 便携版打包脚本
├─ requirements-build.txt         # 打包依赖
├─ README-package.txt             # 发行包使用说明
├─ src/mt5_workbench/
│  ├─ __main__.py                 # python -m mt5_workbench
│  ├─ config.py                   # 单品种配置
│  ├─ domain/                     # 账户规则、风险模型、仓位计算
│  ├─ services/                   # 看板/订单分析、挂单发送与控制操作
│  ├─ infrastructure/             # MT5 行情适配；统一 gateway 后续实施
│  └─ ui/
│     ├─ main_window.py           # 导航、账户门禁与页面协调
│     ├─ pages/                   # 总览、交易概览、行情日志、下单管理、控制面板、实验功能
│     ├─ widgets/                 # 图表控件
│     ├─ dialogs/                 # 账户锁定弹窗
│     ├─ theme.py                 # 设计 token 与主题切换
│     └─ resources/icons/         # 日夜主题图标
├─ tests/                         # 领域、服务、界面分层测试
├─ docs/                          # 架构与界面规范
└─ scripts/                       # 只读 MT5 行情诊断工具
```

当前目录按职责划分，尚未表示所有模块内部都已彻底解耦。`mt5_watch.py` 是 `scripts/` 下的独立诊断工具，不进入桌面界面的依赖链。`gui.py` 暂保留兼容入口；标准入口为 `python -m mt5_workbench`。

## 分阶段实施

| 阶段 | 工作 | 验收 |
| --- | --- | --- |
| 0. 固定基线 | 记录源码状态、离线测试和五页视觉样本；列出订单执行记录的位置。 | 本地虚拟环境中测试全绿，确认没有真实 `order_send`。 |
| 1. 包化与入口 | 已建立 `pyproject.toml`、`src/mt5_workbench/`、包内导入与 `python -m mt5_workbench`，保留 `gui.py` 兼容入口。 | 旧入口和新入口均能打开五页；风险计算与现有测试结果不变。 |
| 2. 会话与存储 | 抽出统一 MT5 gateway、账户身份/USC 门禁、路径与交易 journal；让服务接收接口而不是直接依赖 Qt 控件。 | 账户切换、断线、非 USC 锁定、重复发送拦截均有模拟测试；旧 journal 仍可被识别。 |
| 3. 拆分 Qt 页面 | 五页、图表、账户锁定弹窗和主题/资源已移入 `ui/` 的独立目录；交易确认弹窗及部分编排仍在主窗口，后续继续拆分。 | 1200×800 到 2K 的两种主题、滚动和确认/取消在离屏与实屏检查中正常。 |
| 4. 后台读取 | 所有 MT5 调用进入单个串行 worker；用 Qt 信号把不可变快照传回界面，旧账户的迟到结果按会话编号丢弃。确认后仍在服务内重查账户、报价、计划和目标，再决定是否发送。 | 慢/断开的假终端不会卡住窗口；切号或取消后发送次数为 0。 |
| 5. 工程与发行 | 已有 `build.ps1` 制作 Windows 便携 ZIP；继续统一日志和启动异常处理，并核对资源打包、安装/便携模式和文档。 | 干净环境可安装并启动；两种主题图标、状态写入和交易记录在目标机器可用。 |

## 交易安全与状态目录

- `order_send()` 只允许从已确认的交易服务路径调用；预览、取消、看板刷新和自动测试不能调用真实发送。发送前继续检查 USC 币种、账户身份、报价、挂单重复、目标变化，以及适用操作的 `order_check()`。
- 保留逐笔执行 journal 与失败即停止的行为。普通日志不能替代 journal。
- 目前源码和冻结版分别把 `state/` 写在源码或 EXE 旁。整理路径时先集中到 `infrastructure/paths.py`，**先保持旧位置兼容**；若以后改用 Windows 应用数据目录，必须先迁移并验证 `state/executions/` 的旧记录，否则同一计划可能绕过重复发送拦截。
- 发行形态再确定默认状态路径：安装式应用建议使用用户应用数据目录；便携 ZIP 可显式启用程序旁目录。两种模式应读取同一账户的既有执行记录。
- MT5 Python 接口的跨线程行为不在此假定为安全；后台阶段先让单个 worker 串行拥有终端调用，界面线程只接收结果。

## 每阶段检查命令

以下命令均在 Windows 项目虚拟环境中执行；测试不得连接真实账户发单。

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

还需检查现有 `python -m mt5_workbench` 入口、可编辑安装和 `build.ps1` 产物。对真实 MT5 只做账户、行情和页面的只读连通检查；交易路径使用 FakeMT5 验证确认、取消、切号、发送异常和 journal 恢复。

## 参考规范

- [Python Packaging User Guide：`pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) 与 [src 布局](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [Qt for Python：QThread 与 worker 对象](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)
- [PyInstaller：资源文件与打包参数](https://pyinstaller.org/en/stable/usage.html)
