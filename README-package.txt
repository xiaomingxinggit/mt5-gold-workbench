MT5 黄金交易工作台（Windows x64）

1. 将压缩包完整解压到一个可写入的文件夹，不要直接在压缩包内运行。
2. 先启动并登录 MetaTrader 5 客户端。
3. 双击 MT5Workbench.exe 启动。本包已包含 Python、MetaTrader5 Python 包、NumPy 和图形界面所需运行库，无需再安装 Python 包。

如果电脑上有多个 MT5 客户端，可在 PowerShell 中运行：
  .\MT5Workbench.exe --terminal "C:\Program Files\MetaTrader 5\terminal64.exe"

侧栏“系统配置”可查看实时系统时间，设置全局显示时区（默认北京时间 UTC+8）、报价／持仓／订单刷新间隔和界面主题，并查看 UTF-8 编码、运行环境及本地数据路径。未连接 MT5 时仍可使用。时区设置仅调整工作台显示；日志热力图与活跃天数仍按北京时间计算。

程序旁的整个 state 文件夹包含交易执行记录（executions、controls）、行情日志帖子与图片（journal）、界面主题、刷新间隔及系统时区设置。升级或移动程序时请完整保留 state 文件夹，以免丢失日志和设置，或失去同一配置的重复发送拦截记录。

程序不会自动下单。发单、平仓或撤单均需在界面中预览并确认。实际交易还要求 MT5 客户端允许算法交易。
