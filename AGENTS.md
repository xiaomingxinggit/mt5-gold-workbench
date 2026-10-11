# Branch workflow

- Perform all development, fixes, and commits on `dev`. Do not create additional development branches unless the user explicitly requests one.
- `main` is the stable release branch. Promote tested changes from `dev` to `main` for a release; do not develop directly on `main`.
- Build every release artifact from committed `main` code. If `dev` is ahead, validate and merge the intended changes into `main` before packaging; never publish a build taken directly from `dev` or an uncommitted checkout. CI may check out the release tag created from that `main` commit.
- Create version tags from `main`; the tag must match `mt5_workbench.__version__` (for example, `v0.2.0`).
- Keep the local working checkout on `dev` after publishing a release.
- Never commit `state/`, account records, screenshots containing account data, or generated build artifacts.

# 发布判断分工

- 用户指定专门负责发布判断的助手或会话，默认职责是评估当前项目是否需要发布；其他开发助手仍按各自任务工作。
- 判断时比较 `dev` 与最近正式发布版本，结合用户可见的功能、缺陷修复、交易安全、兼容性和发布验证证据，区分“有发布必要”与“已具备发布条件”。仅内部整理或文档变更通常不单独触发运行版发布。
- 结论使用“建议发布”“暂不需要发布”或“需要发布但尚未就绪”，说明依据、紧急程度及缺失的验证；未验证的项目不得写成通过。
- 发布判断本身不授权开发修复、修改版本、合并分支、创建标签或推送发布；用户另有明确指示时再执行。验证与发布要求见 [开发与发布指南](docs/DEVELOPMENT.md)。

# 工程上下文

本文件面向在本仓库工作的 AI 开发助手。面向用户的介绍在 `README.md`，完整操作说明在 `docs/USER_GUIDE.md`，贡献者的构建与发布说明在 `docs/DEVELOPMENT.md`。

- 项目是 Windows x64 本地桌面应用；Python 必须为 3.12 x64（`>=3.12,<3.13`）。
- 依赖版本以 `requirements.txt`、`requirements-build.txt` 为准，安装与运行均使用 `.venv/Scripts/python.exe`。
- 当前交易品种固定为 `XAUUSDc`，仅接受 `USC` 账户，按 `100 USC = 1 USD` 换算。不要在常规整理中放宽账户或品种限制。
- 默认入口是 `python -m mt5_workbench`，加载 `ui/qml_app.py` 和 `ui/qml/App.qml`；`gui.py` 保留为兼容入口。
- 当前使用 PySide6 Qt Quick/QML 与 FluentWinUI3；不要将新功能加到旧 QWidget 页面后误认为默认界面已更新，也不要引入 HTML/WebEngine 界面。

## 分层与修改位置

- `src/mt5_workbench/domain/`：账户规则、风险与仓位算法、日志模型；保持计算规则独立于界面。
- `services/`：看板、订单统计、指标、日志同步和交易执行；交易校验应位于服务路径，不只依赖按钮是否禁用。
- `infrastructure/`：MT5 行情适配、SQLite、数据迁移、系统设置。
- `ui/qml_bridge.py`：只读状态与后台读取；`ui/qml_trade_bridge.py`：默认界面的交易确认及日志写入入口。
- `ui/qml/`：九页导航、共用控件、主题及图表；界面修改遵循 `docs/UI_DESIGN.md`。
- `ui/main_window.py`、`ui/pages/`、`ui/widgets/`：保留的旧 QWidget 实现，非默认入口。
- `tests/`：离线测试；`scripts/mt5_watch.py`：独立的只读终端诊断。

`docs/ARCHITECTURE_PLAN.md` 记录历史基线与后续目标；不要把计划中的统一 gateway、全量串行 worker 等目标当作已实现的事实。修改前以当前源码核对调用链。

## 交易行为与数据口径

- 预览、取消、启动、页面刷新、主题切换与行情监测不得触发真实 `order_send()`。写操作只允许从明确确认后的交易服务路径执行。
- 预览与执行时都要重新检查 USC 账户、账户身份、交易权限、最新报价、价格与手数步进、保护价方向、目标变化、重复挂单，以及适用操作的 `order_check()`。
- 基础与高级下单都只发 BUY LIMIT / SELL LIMIT，必须有有效止损。修改字段、切换模式、账户或目标后旧确认应失效。
- 保留预算使用比例、手数约束与 `order_calc_profit()` 风险核验；不要因整理代码改变风险算法。估算不包含既有持仓、滑点、跳空、手续费、隔夜费与保证金限制。
- 保留 `state/executions/`、`state/controls/` 的逐笔执行记录与重复发送拦截。失败或结果不确定时停止剩余目标，不自动重试；普通日志不能替代执行记录。
- 批量止盈止损修改保留未填写的一侧，不把统一绝对价格套用于混合品种；推保本不得放宽已有更有利的止损。执行期间不得并发提交其他交易操作。
- 只读统计缺失、读取失败或历史不足时显示不可用，不以零替代。金额区分 USC 与 USD，价格幅度与券商 point 区分。
- 交易净现金流曲线排除出入金和未平仓浮盈亏，不命名为历史余额或权益曲线；BUY/SELL 成交方向不等同于当前持仓方向。
- 显示时区设置只改变显示；日志热力图与活跃天数按北京时间统计，其他按日统计保留现有口径。
- 后台结果需要核对当前账户与筛选条件，丢弃过期结果；不要假定 MT5 跨线程调用天然安全。

## 本地存储与隐私

- 状态路径统一通过 `config.state_directory()` 获取，默认 `%LOCALAPPDATA%/MT5Workbench/state/`；不要新增相对工作目录或 EXE 旁的写入路径。
- 测试使用 `MT5_WORKBENCH_DATA_DIR` 指定隔离根目录，其下仍使用 `state/`。普通启动可能迁移旧数据；隔离目录本身不表示禁用了迁移。
- 保留迁移前的原数据、SQLite WAL 数据、日志图片和旧执行记录。迁移失败应停止启动，不静默跳过。
- 配置、文本文件和新文档使用 UTF-8。测试使用虚构账户，不读取、复制或发布个人数据。
- 自动化交易测试使用模拟 MT5 接口和 `0.01` 手请求或持仓。未经用户明确授权，不进行真实发单、平仓、撤单或保护价修改；真实连通验证只读账户与行情。

## 验证方式

在项目根目录的 PowerShell 中执行离线检查：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QUICK_BACKEND = 'software'
$env:MT5_WORKBENCH_DATA_DIR = Join-Path $PWD 'build\test-data'
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m pip check
```

- 交易逻辑修改覆盖确认、取消、切号、目标变化、重复发送、执行异常与记录恢复；测试不得连接真实账户发送请求。
- QML、资源或入口修改使用 `python -m mt5_workbench --smoke-test build/source-smoke` 验证。该模式禁用 MT5 自动连接、轮询和旧数据迁移，检查退出码及 `result.json` 的 `ok`。
- 界面修改检查两种主题、1200 × 800、2K、滚动、非空表格和确认/取消交互；离屏测试不能代替真实显示器验收。
- 打包相关修改依照 `docs/DEVELOPMENT.md` 检查源码与冻结版启动及发布产物；检查结果如实报告，未运行的验证不得写成通过。
- 纯文档修改检查相对链接、命令、版本与功能描述，通常不需要运行全部应用测试。

## 文档维护

- `README.md` 面向首次访问者：产品价值、功能、下载、快速上手、必要边界与文档入口。保持简洁，不堆叠内部实现、AI 提示或发布操作日志。
- `docs/USER_GUIDE.md` 面向使用者：参数、页面操作、风险与统计口径、本地数据及升级。
- `docs/DEVELOPMENT.md` 面向贡献者：环境、结构、离线验证、构建与发布步骤。
- `AGENTS.md` 保存需要开发助手持续遵守的规则与验证要求；详细规范通过链接引用，不复制整份用户手册。
- 功能、默认参数、数据口径或使用步骤变更时同步相应文档；运行版相关变更同步 `README-package.txt`。
- 版本以 `src/mt5_workbench/__init__.py` 的 `__version__` 为单一来源。标签从 `main` 创建并与其匹配，发布完成后切回 `dev`；具体流程见开发指南。
- 不虚构 Star 数、使用人数、测试状态、许可证或收益承诺；项目首页只展示可以核对的内容。
