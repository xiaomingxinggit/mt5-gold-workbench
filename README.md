<div align="center">

# MT5 黄金交易工作台

**把黄金行情、风险测算、交易执行与复盘，放在同一个桌面。**

面向 `XAUUSDc` · USC 美分账户的 Windows 本地交易工作台

[![Release](https://img.shields.io/github/v/release/xiaomingxinggit/mt5-gold-workbench?label=Release)](https://github.com/xiaomingxinggit/mt5-gold-workbench/releases/latest)
![Windows x64](https://img.shields.io/badge/Windows-x64-0078D4?logo=windows)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Qt Quick](https://img.shields.io/badge/UI-Qt%20Quick-41CD52?logo=qt&logoColor=white)

[下载运行版](https://github.com/xiaomingxinggit/mt5-gold-workbench/releases/latest) · [快速开始](#快速开始) · [使用指南](docs/USER_GUIDE.md) · [反馈问题](https://github.com/xiaomingxinggit/mt5-gold-workbench/issues)

</div>

---

MT5 黄金交易工作台连接本机已登录的 MetaTrader 5，把报价、持仓、挂单、交易记录和行情日志集中到一个界面。你可以先观察行情，按止损和风险预算测算分档手数，再预览确认挂单，最后把交易想法与持仓结果留在日志里。

应用采用 Python、PySide6 与 Qt Quick/QML，提供日间和夜间主题。账户与交易数据通过本机 MT5 客户端读取，日志和设置保存在本地。

> **使用前确认：** 当前仅支持 Windows x64、`USC` 美分账户和 `XAUUSDc`，按 **100 USC = 1 USD** 换算。交易操作会提交到当前登录账户，均需先预览再确认；行情监测不会自动下单。

## 能做什么

| 你要做的事 | 工作台提供的能力 |
| --- | --- |
| 快速了解账户与行情 | 黄金 Bid/Ask、点差、M5 K 线、净值与保证金、近 30 日已实现净损益 |
| 回看成交表现 | 持仓与挂单、历史订单与成交、交易净现金流和按日回撤 |
| 按风险安排入场 | 基础限价下单；按预算、区间和统一止损测算分档手数，支持四种分配模式 |
| 管理已有交易 | 平仓、撤单、推保本、批量设置止盈止损，逐项预览并确认 |
| 留下交易思路 | 文字、图片、截图粘贴、持仓关联、回复与年度记录热力图 |
| 观察波动与均线 | 多周期 ATR、平均日真实波幅、M1 EMA 7/14/30/60 与均线聚拢候选 |
| 调整使用习惯 | 显示时区、独立刷新间隔、深浅主题、全屏及版本检查 |

九个页面覆盖上述工作流程；“实验功能”目前为预留页面。各功能的操作步骤与统计口径见[使用指南](docs/USER_GUIDE.md)。

## 快速开始

### 下载运行版

1. 打开 [Releases](https://github.com/xiaomingxinggit/mt5-gold-workbench/releases/latest)，下载 `MT5Workbench.exe` 或 `MT5Workbench-Windows-x64.zip`。
2. 启动 MetaTrader 5 客户端，登录 USC 账户，确认可以读取 `XAUUSDc` 报价。
3. 双击 EXE；如果下载的是 ZIP，请先解压。运行版已包含 Python 和界面依赖。
4. 在“总览看板”核对账户与连接状态，再进入需要的页面。

涉及发单等交易操作时，还需在 MT5 客户端允许算法交易。详细说明见[首次使用](docs/USER_GUIDE.md#下载与首次使用)。

### 从源码运行

准备 **Windows x64 + Python 3.12 x64 + 已安装的 MetaTrader 5 客户端**，在 PowerShell 中执行：

```powershell
git clone https://github.com/xiaomingxinggit/mt5-gold-workbench.git
cd mt5-gold-workbench
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m mt5_workbench
```

有多个 MT5 客户端时，指定要连接的终端：

```powershell
.\.venv\Scripts\python.exe -m mt5_workbench --terminal "C:\Program Files\MetaTrader 5\terminal64.exe"
```

安装与启动均使用同一虚拟环境中的 Python。默认品种固定为 `XAUUSDc`；非 USC 账户会锁定行情和交易功能，切回 USC 账户后点击顶部“重新连接”。

## 一次典型的使用流程

1. **观察**：在总览、指标参考和行情监测中查看报价与波动。
2. **测算**：进入高级下单，填写风险预算、目标价、误差度与统一止损，选择分配方式。
3. **确认**：核对预览中的账户、每档价格、手数、保护价和估算风险，确认后发送 LIMIT 挂单。
4. **管理**：在交易概览查看结果，需要调整时进入控制面板预览操作。
5. **复盘**：在行情日志记录思路、贴上截图并关联持仓。

基础下单可直接指定价格与手数，止损必填，止盈可选。高级模式的[参数与示例](docs/USER_GUIDE.md#高级下单)帮助你理解预算比例和分档权重。

## 理解风险与数据

- **风险测算**估计的是所有档位成交后、在指定止损价退出时的亏损；滑点、跳空、手续费、隔夜费和保证金限制未计入，已有持仓风险也不在本次预算内。
- **交易净现金流曲线**汇总已发生的成交资金分项，排除出入金和未平仓浮盈亏；它不是历史余额或权益曲线。
- **ATR 与 EMA 聚拢**用于描述行情波动和均线距离，不能据此推断收益或反转概率。
- **执行失败或状态不确定**时会停止后续请求，不自动重试；请到 MT5 核对实际结果。

完整的金额单位、统计范围及确认规则见[使用指南](docs/USER_GUIDE.md)。

## 本地数据与升级

日志、图片、设置和交易执行记录默认保存在：

```text
%LOCALAPPDATA%\MT5Workbench\state\
```

“系统配置 → 连接与本地数据”可查看实际路径并打开目录。备份时关闭工作台，复制整个目录；移动或替换 EXE 后仍使用同一份数据。

“系统配置 → 版本与更新”支持检查正式 Release 并通过浏览器下载新版。下载后关闭工作台，再替换 EXE。旧版数据迁移说明见[升级与备份](docs/USER_GUIDE.md#升级与备份本地数据)。

## 文档与参与

| 文档 | 适合什么时候阅读 |
| --- | --- |
| [使用指南](docs/USER_GUIDE.md) | 连接终端、使用各页面、理解风险与统计口径 |
| [行情日志详解](docs/JOURNAL.md) | 记录、图片、回复与持仓结果同步 |
| [开发与发布指南](docs/DEVELOPMENT.md) | 准备开发环境、离线验证、构建与发布 |
| [界面设计规范](docs/UI_DESIGN.md) | 修改 QML 页面、主题、布局与交互 |
| [架构整理记录](docs/ARCHITECTURE_PLAN.md) | 了解工程演进及后续整理方向 |
| [AGENTS.md](AGENTS.md) | AI 开发助手的工程约定与修改边界 |

欢迎通过 [Issues](https://github.com/xiaomingxinggit/mt5-gold-workbench/issues) 报告问题或提出建议，通过 [Pull Requests](https://github.com/xiaomingxinggit/mt5-gold-workbench/pulls) 参与改进。开发前请阅读[开发指南](docs/DEVELOPMENT.md)，所有开发修改在 `dev` 分支进行。

反馈时请附上版本、复现步骤和已脱敏的错误信息。请勿上传真实账户号、交易记录、本地数据库或含账户数据的截图。
