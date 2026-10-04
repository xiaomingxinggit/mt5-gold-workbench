"""LIMIT order planning page with a centered entry range."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from mt5_workbench.domain.position_optimizer import Optimization
from mt5_workbench.ui.components import button, card, fill_table, icon, label, make_table
from mt5_workbench.ui.widgets.charts import AllocationChart

MODES = {
    "加权分配 · 自定义风险比例": "weighted",
    "等风险 · 每档承担相同风险": "equal_risk",
    "覆盖区间 · 尽量增大总手数": "max_lots_ladder",
    "单点开仓 · 总手数最大": "max_lots_single",
}


class OptimizerPage(QWidget):
    calculate_requested = Signal()
    preview_requested = Signal()
    copy_requested = Signal()
    inputs_changed = Signal()

    def __init__(self, palette: dict[str, str], theme: str):
        super().__init__()
        self.palette = palette
        self.theme = theme
        self._compact = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 32)
        outer.setSpacing(18)
        outer.addWidget(label("下单管理（限价单）", kind="pageTitle"))
        outer.addWidget(label("用目标价与误差度生成入场区间，分档测算后只发送 LIMIT 挂单。",
                              kind="muted"))
        columns = QGridLayout()
        columns.setHorizontalSpacing(16)
        columns.setVerticalSpacing(16)
        self.columns = columns
        outer.addLayout(columns)

        form = card()
        self.form_card = form
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(20, 20, 20, 22)
        form_layout.setSpacing(14)
        form_layout.addWidget(label("配置参数", kind="sectionTitle"))
        form_layout.addWidget(label("填写预算、目标价、误差度和止损；止盈可选。", kind="muted"))
        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(15)
        self.inputs: dict[str, QLineEdit] = {}
        specs = (
            ("budget", "风险预算 · USD", "", 0, 0),
            ("usage", "预算使用比例 · %", "95", 0, 1),
            ("center", "目标入场价", "", 1, 0),
            ("tolerance", "误差度 · ±价格", "", 1, 1),
            ("stop", "统一止损价", "", 2, 0),
            ("take_profit", "统一止盈价 · 可选", "", 2, 1),
            ("levels", "开仓档数 · 2～12", "3", 3, 0),
            ("weights", "每档风险权重", "1,2,3", 3, 1),
        )
        for key, caption, default, row, column in specs:
            group = QVBoxLayout()
            group.setSpacing(7)
            group.addWidget(label(caption, kind="muted"))
            entry = QLineEdit(default)
            entry.setMinimumHeight(40)
            entry.textChanged.connect(self.inputs_changed)
            self.inputs[key] = entry
            group.addWidget(entry)
            fields.addLayout(group, row, column)
        form_layout.addLayout(fields)
        self.range_hint = label("示例：4220 ± 1 → 4219～4221；按档数等距生成价格。",
                                kind="muted", wrap=True)
        form_layout.addWidget(self.range_hint)
        self.inputs["center"].textChanged.connect(self._update_range_hint)
        self.inputs["tolerance"].textChanged.connect(self._update_range_hint)
        form_layout.addWidget(label("分配方式", kind="muted"))
        self.mode = QComboBox()
        for title, value in MODES.items():
            self.mode.addItem(title, value)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form_layout.addWidget(self.mode)
        form_layout.addWidget(label("权重 1,2,3 表示三个档位分别承担 1:2:3 的预算。",
                                    kind="muted", wrap=True))
        self.calculate_button = button("计算 LIMIT 挂单", theme, "calculate", "primary")
        self.calculate_button.clicked.connect(self.calculate_requested)
        self.calculate_button.setMinimumHeight(42)
        form_layout.addWidget(self.calculate_button)
        columns.addWidget(form, 0, 0, alignment=Qt.AlignmentFlag.AlignTop)

        result = card()
        self.result_card = result
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(20, 20, 20, 22)
        result_layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(label("测算结果", kind="sectionTitle"))
        header.addStretch()
        self.copy_button = button("复制配置", theme, "copy")
        self.copy_button.clicked.connect(self.copy_requested)
        self.copy_button.setEnabled(False)
        header.addWidget(self.copy_button)
        self.send_button = button("预览并发送 LIMIT", theme, "send", "primary")
        self.send_button.clicked.connect(self.preview_requested)
        self.send_button.setEnabled(False)
        header.addWidget(self.send_button)
        result_layout.addLayout(header)
        self.info = label("填写参数并计算；发送前会再次核对账户与报价。", kind="muted", wrap=True)
        result_layout.addWidget(self.info)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.lot = self._mini_metric(metrics, "总手数")
        self.risk = self._mini_metric(metrics, "预计止损风险")
        self.unused = self._mini_metric(metrics, "原预算剩余")
        result_layout.addLayout(metrics)
        result_layout.addWidget(label("建议挂单", kind="sectionTitle"))
        self.suggestion_table = make_table(("档位", "建议类型", "入场价", "手数",
                                            "止损距离", "风险 USD"), 220)
        result_layout.addWidget(self.suggestion_table)
        result_layout.addWidget(label("每档风险分配", kind="sectionTitle"))
        self.allocation = AllocationChart(palette)
        self.allocation.setMinimumHeight(164)
        result_layout.addWidget(self.allocation)
        self.comparison = label("计算后显示各分配方式的总手数。", kind="muted", wrap=True)
        comparison_box = QFrame()
        comparison_box.setObjectName("softCard")
        comparison_layout = QVBoxLayout(comparison_box)
        comparison_layout.setContentsMargins(16, 13, 16, 13)
        comparison_layout.addWidget(self.comparison)
        self.warning = label("测算不包含滑点、跳空、手续费和保证金限制。",
                             kind="warning", wrap=True)
        result_layout.addWidget(comparison_box)
        result_layout.addWidget(self.warning)
        columns.addWidget(result, 0, 1)
        columns.setColumnStretch(0, 0)
        columns.setColumnStretch(1, 1)
        outer.addStretch()
        self._mode_changed()
        self._reflow()

    def _mini_metric(self, row: QHBoxLayout, caption: str) -> QLabel:
        box = QFrame()
        box.setObjectName("softCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 13, 16, 15)
        layout.setSpacing(6)
        layout.addWidget(label(caption, kind="muted"))
        value = label("—", kind="metricValue")
        layout.addWidget(value)
        row.addWidget(box, 1)
        return value

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """Keep the form and result legible in a 1200 px window."""
        compact = self.width() < 1220
        if compact == self._compact:
            return
        self._compact = compact
        self.columns.removeWidget(self.form_card)
        self.columns.removeWidget(self.result_card)
        if compact:
            self.form_card.setMaximumWidth(16777215)
            self.columns.addWidget(self.form_card, 0, 0)
            self.columns.addWidget(self.result_card, 1, 0)
            self.columns.setColumnStretch(0, 1)
            self.columns.setColumnStretch(1, 0)
        else:
            self.form_card.setMaximumWidth(480)
            self.columns.addWidget(self.form_card, 0, 0, alignment=Qt.AlignmentFlag.AlignTop)
            self.columns.addWidget(self.result_card, 0, 1)
            self.columns.setColumnStretch(0, 0)
            self.columns.setColumnStretch(1, 1)

    def _mode_changed(self) -> None:
        self.inputs["weights"].setEnabled(self.mode.currentData() == "weighted")
        self.inputs_changed.emit()

    def _centered_range(self) -> tuple[Decimal, Decimal]:
        try:
            center = Decimal(self.inputs["center"].text().strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("目标入场价需要填写数字") from exc
        try:
            tolerance = Decimal(self.inputs["tolerance"].text().strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("误差度需要填写数字") from exc
        if not center.is_finite() or center <= 0:
            raise ValueError("目标入场价必须大于 0")
        if not tolerance.is_finite() or tolerance <= 0:
            raise ValueError("误差度必须大于 0")
        low, high = center - tolerance, center + tolerance
        if low <= 0:
            raise ValueError("误差度过大，区间起点必须大于 0")
        return low, high

    def _update_range_hint(self, _text: str = "") -> None:
        try:
            low, high = self._centered_range()
        except ValueError:
            self.range_hint.setText("示例：4220 ± 1 → 4219～4221；按档数等距生成价格。")
            return
        self.range_hint.setText(f"自动生成入场区间：{low:g}～{high:g}；按档数等距生成价格。")

    def read_inputs(self):
        low, high = self._centered_range()
        try:
            levels = int(self.inputs["levels"].text().strip())
        except ValueError as exc:
            raise ValueError("档数必须是 2～12 的整数") from exc
        mode = str(self.mode.currentData())
        weights = None
        if mode == "weighted":
            try:
                weights = tuple(Decimal(piece.strip()) for piece in
                                self.inputs["weights"].text().split(","))
            except InvalidOperation as exc:
                raise ValueError("权重格式示例：1,2,3") from exc
        return (low, high,
                self.inputs["stop"].text().strip(),
                self.inputs["take_profit"].text().strip(),
                self.inputs["budget"].text().strip(),
                self.inputs["usage"].text().strip(), levels, mode, weights)

    def set_result(self, result: Optimization, suggested_types: tuple[str, ...],
                   comparison: str, warning: str, stop: str,
                   *, can_preview: bool = True) -> None:
        range_text = (f"入场区间 {result.range_low}～{result.range_high} · "
                      if result.range_low is not None and result.range_high is not None
                      else "")
        self.info.setText(
            f"{result.side} LIMIT · {range_text}{len(result.entries)} 档 · "
            f"原预算 {result.budget_usd:.2f} × {result.budget_usage_percent:g}% "
            f"= 风险上限 {result.risk_cap_usd:.2f} USD · 统一止损 {stop} · "
            f"统一止盈 {result.take_profit if result.take_profit is not None else '未设置'}")
        self.lot.setText(f"{result.total_volume} lot")
        self.risk.setText(f"{result.total_risk_usd:.2f} USD")
        self.unused.setText(f"{result.unused_usd:.2f} USD")
        fill_table(self.suggestion_table, (
            (index, suggested_types[index - 1], item.price, item.volume,
             item.stop_distance, f"{item.risk_usd:.2f}")
            for index, item in enumerate(result.entries, 1)))
        self.allocation.set_data(result.entries, result.budget_usd)
        self.comparison.setText(comparison)
        self.warning.setText(warning)
        self.copy_button.setEnabled(True)
        self.send_button.setEnabled(can_preview)

    def clear(self, message: str = "参数已修改，请重新计算配置。") -> None:
        self.info.setText(message)
        self.lot.setText("—")
        self.risk.setText("—")
        self.unused.setText("—")
        fill_table(self.suggestion_table, ())
        self.allocation.set_data((), 0)
        self.comparison.setText("计算后显示各分配方式的总手数。")
        self.warning.setText("测算不包含滑点、跳空、手续费和保证金限制。")
        self.copy_button.setEnabled(False)
        self.send_button.setEnabled(False)

    def set_palette(self, palette: dict[str, str], theme: str) -> None:
        self.palette = palette
        self.theme = theme
        self.allocation.set_palette(palette)
        for item, name in ((self.calculate_button, "calculate"),
                           (self.copy_button, "copy"), (self.send_button, "send")):
            item.setIcon(icon(name, theme))
