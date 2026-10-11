# 开发与发布指南

[返回项目首页](../README.md) · [使用指南](USER_GUIDE.md) · [AI 工程约定](../AGENTS.md)

本指南面向贡献者和维护者。开发、修复与提交统一在 `dev`；`main` 保存稳定发布代码。

## 准备环境

使用 Windows x64 与 Python 3.12 x64。在仓库根目录的 PowerShell 中执行：

```powershell
git switch dev
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip check
```

运行依赖由 `requirements.txt` 固定版本，`pyproject.toml` 读取依赖与 `mt5_workbench.__version__`。
默认入口为 `python -m mt5_workbench`，`gui.py` 保留为兼容入口。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `src/mt5_workbench/domain/` | USC 账户规则、仓位计算、日志数据模型 |
| `src/mt5_workbench/services/` | 看板、交易统计、日志持仓同步、下单与账户控制 |
| `src/mt5_workbench/infrastructure/` | MT5 行情适配、本地 SQLite、应用数据迁移与设置 |
| `src/mt5_workbench/ui/qml/` | 九个页面、共用控件、主题及图表 |
| `src/mt5_workbench/ui/qml_bridge.py` | 只读状态、后台读取与 QML 同步 |
| `src/mt5_workbench/ui/qml_trade_bridge.py` | 交易预览、确认执行与日志写入入口 |
| `src/mt5_workbench/ui/qml_app.py` | Qt Quick 应用入口及离线启动验证 |
| `src/mt5_workbench/ui/pages/`、`ui/main_window.py` | 旧 QWidget 实现，作为兼容与回归参考 |
| `tests/` | 模拟 MT5 的离线测试 |
| `scripts/mt5_watch.py` | 只读命令行行情诊断 |

修改界面前阅读[界面设计规范](UI_DESIGN.md)。[架构整理记录](ARCHITECTURE_PLAN.md)保留演进计划，不应将其中的目标方案当作当前已完成的实现。

## 隔离本地数据

默认数据位于 `%LOCALAPPDATA%\MT5Workbench\state\`。开发与测试使用独立根目录：

```powershell
$env:MT5_WORKBENCH_DATA_DIR = Join-Path $PWD 'build\dev-data'
```

应用会在该根目录下使用 `state/`，路径由 `config.state_directory()` 统一提供。
普通启动有旧 `state/` 的迁移行为；隔离路径不能单独视为禁用迁移。自动启动验证使用下述 `--smoke-test`，该模式禁用旧数据迁移和 MT5 自动连接。

不得提交个人数据、含账户信息的截图和生成的构建产物。离线测试使用虚构账户及模拟交易接口；真实 MT5 连通检查只读取账户和行情。

## 验证修改

运行项目现有离线测试，与发布工作流保持一致：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QUICK_BACKEND = 'software'
$env:MT5_WORKBENCH_DATA_DIR = Join-Path $PWD 'build\test-data'
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m pip check
```

验证默认入口、QML 加载和资源路径：

```powershell
.\.venv\Scripts\python.exe -m mt5_workbench --smoke-test build\source-smoke
Get-Content -Raw build\source-smoke\result.json
```

该模式不连接 MT5、不启动交易轮询，使用隔离目录生成 `settings.png` 和 `result.json`；检查退出码与 `ok` 字段。
界面修改还需在真实 Windows 显示器上检查两种主题、1200 × 800、2K、滚动与确认弹窗。离屏加载成功不能替代显示器上的布局验收。

只读行情诊断需已安装并登录的 MT5 客户端：

```powershell
.\.venv\Scripts\python.exe .\scripts\mt5_watch.py --samples 5
```

## 构建 Windows 运行版

先准备上述虚拟环境，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

脚本安装运行与构建依赖，生成：

- `dist/MT5Workbench.exe`：包含 Python、MetaTrader5、NumPy 与 PySide6 运行库的单文件 EXE。
- `dist/MT5Workbench-Windows-x64.zip`：EXE 与 `README-package.txt`。
- `dist/SHA256SUMS.txt`：EXE 与 ZIP 的 SHA-256 校验值。

目标电脑仍需安装并登录 MetaTrader 5 客户端。更新面向运行版用户的说明时同步修改根目录的 `README-package.txt`。

可在 PowerShell 中验证冻结版的离线启动：

```powershell
$smokeProcess = Start-Process -FilePath .\dist\MT5Workbench.exe -ArgumentList @('--smoke-test', 'build/frozen-smoke') -WindowStyle Hidden -Wait -PassThru
if ($smokeProcess.ExitCode -ne 0) { throw 'Frozen application smoke test failed' }
Get-Content -Raw build\frozen-smoke\result.json
```

## 发布版本

发布时将测试通过的 `dev` 合并到 `main`，从 `main` 创建版本标签，完成后本地回到 `dev`。不创建额外开发分支。

1. 在 `dev` 修改 `src/mt5_workbench/__init__.py` 的 `__version__`，同步 `README-package.txt` 的版本及相关使用说明，完成测试并提交。
2. 将已测试的 `dev` 合并到 `main`，核对准备发布的代码与版本。
3. 从 `main` 创建与应用版本完全相同的 `v主版本.次版本.修订版本` 标签，再推送分支与标签。
4. 查看 GitHub Actions 的离线测试、构建和冻结版启动结果，核对正式 Release 的附件。
5. 切回 `dev` 继续开发。

例如，**仅在应用版本已改为 `0.2.2` 且测试通过时**执行：

```powershell
git switch main
git merge dev
git tag v0.2.2
git push origin main dev
git push origin v0.2.2
git switch dev
```

[发布工作流](../.github/workflows/release.yml)使用 Windows x64 / Python 3.12，核对标签与应用版本，运行离线测试、打包及冻结版 QML 启动验证；全部成功后发布 EXE、ZIP 与校验文件。
工作流使用内置 `GITHUB_TOKEN` 和 `contents: write`，不需要新增 Secrets；仓库 Actions 或组织策略需允许该工作流发布。手动触发只生成构建产物，不创建 Release。

## 版本检测的约定

`services/app_updates.py` 中的 `REPOSITORY` 指向 `xiaomingxinggit/mt5-gold-workbench`，通过公开 GitHub Releases API 检查正式版本。
草稿、预发布和普通提交不触发更新提示；EXE 未上传完成时会提示等待打包。下载通过默认浏览器进行，不自动覆盖本地文件。
更换仓库时需同步修改该常量、README 中的仓库链接及徽章，并重新打包。

## 提交与反馈

提交前查看 diff，确认修改范围、验证结果与文档一致，且没有加入 `state/`、账户记录或构建产物。
报告问题时提供版本、环境、复现步骤、预期与实际表现；账户信息与错误日志需要脱敏。
