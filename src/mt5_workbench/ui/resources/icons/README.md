# MT5 图标规范

界面操作图标采用统一的 24 × 24 矢量网格、圆角端点与 1.8 单位主线宽。当前导航状态使用金色，其余操作图标使用主题文字色。图标文件自身透明，可以放在卡片、侧栏和按钮上。应用不使用独立 LOGO。

## 资源

- `{name}-{theme}-{size}.png`：Qt `QIcon` 可直接加载的透明 PNG；`theme` 为 `dark` 或 `light`，`size` 为 16、20、24、32。
- `svg/{theme}/{name}.svg`：同一套图形的矢量源文件。导航选中状态另有 `{name}-active`。

图标名：`dashboard`、`orders`、`journal`、`allocation`、`controls`、`refresh`、`sun`、`moon`、`fullscreen`、`exit-fullscreen`、`send`、`copy`、`calculate`、`close`、`remove`、`connection`、`warning`、`check`、`info`、`calendar`、`chart-line`、`candles`、`bar-chart`、`status`、`confirm`、`cancel`。

PySide6 示例：

```python
icon = QIcon(str(icon_dir / f"orders-{theme_name}-20.png"))
button.setIcon(icon)
```

重新生成（使用项目虚拟环境）：

```powershell
.\.venv\Scripts\python.exe -m pip install Pillow
.\.venv\Scripts\python.exe src\mt5_workbench\ui\resources\icons\generate.py
```

主题颜色跟随 `mt5_workbench.ui.theme`。若更改主题中的文字色、金色或卡片色，请同步修改 `generate.py` 的 `PALETTES` 并重新生成。

图标作为 `mt5_workbench.ui` 的包数据纳入项目元数据。制作 Windows 运行版时需要核对深浅主题图标都已包含。
