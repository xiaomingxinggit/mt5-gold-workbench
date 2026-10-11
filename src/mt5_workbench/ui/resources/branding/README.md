# 龙首应用标志

采用用户选定的第一版正面抽象龙首：保留额头纹饰、分叉龙角、卷曲龙须与三分龙髯。
初稿由内置图片生成工具制作，SVG 是根据已选定轮廓转换的真实路径，不内嵌位图。

| 文件 | 用途 |
| --- | --- |
| `dragon-gold.svg` | 古金色透明标志，适合深色界面 |
| `dragon-ink.svg` | 墨色透明标志，适合浅色界面与单色印刷 |
| `dragon-white.svg` | 白色透明标志，适合深色背景 |
| `app-icon.svg` | 金色龙首配圆角墨黑底的应用图标母版 |
| `app-icon.ico` | Windows EXE、快捷方式、窗口与任务栏图标 |
| `app-icon.png` | 256 像素应用图标 |

配色：古金 `#C6A363`，墨色 `#18252F`，图标底色 `#15181B`。
SVG 可直接编辑和任意缩放；PNG 使用透明通道，白色版应在深色背景上查看。

完整导出套装含上述四种 SVG、四种标志各 13 个尺寸的 PNG，以及一个多尺寸 ICO。
PNG 尺寸：16、20、24、32、40、48、64、96、128、192、256、512、1024。
ICO 内含 16 至 256 像素的 11 个尺寸、32 位颜色与透明通道。

默认入口在创建 QApplication 前设置固定的 Windows AppUserModelID `MT5Workbench.Desktop`，
源码与冻结版使用相同身份，避免任务栏把源码窗口归入 Python。应用和原生 QML 窗口都加载
`app-icon.ico`；修改启动身份或图标后需重新启动应用才能核对任务栏效果。

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\export_branding.py
```

导出文件位于 `build/branding/`。修改 SVG 后，在 `dev` 上追加 `--install-resources`
可更新应用使用的 ICO 与 PNG，确认后提交这些资源。正常构建只读取已提交资源。
`build.ps1` 会生成独立的 `dist/MT5Workbench-Logo.zip`，便于保存和复用整套素材。
