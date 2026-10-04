"""Modal account-currency gate for USC-only calculations."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from mt5_workbench.ui.components import button, label


class AccountLockDialog(QDialog):
    def __init__(self, owner: "MainWindow", account):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("账户不受支持 · 工作台已锁定")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(610, 310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label("仅支持 USC 美分账户", kind="pageTitle"))
        self.details = label()
        layout.addWidget(self.details)
        layout.addWidget(label(
            "本工作台按 100 USC = 1 USD 计算。当前账户不能使用看板、仓位测算或交易操作。",
            kind="muted", wrap=True))
        self.note = label("请在 MT5 客户端切换账户后重新检查。", kind="warning", wrap=True)
        layout.addWidget(self.note)
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        self.exit_button = button("退出工作台", owner.theme)
        self.exit_button.clicked.connect(owner.close)
        actions.addWidget(self.exit_button)
        self.recheck_button = button("重新检查账户", owner.theme, "refresh", "primary")
        self.recheck_button.clicked.connect(owner.connect)
        actions.addWidget(self.recheck_button)
        layout.addLayout(actions)
        self.update_account(account)
        self.rejected.connect(self._exit_on_reject)

    def _exit_on_reject(self) -> None:
        if not self.owner._closing and self.owner.account_lock is self:
            self.owner.close()

    def update_account(self, account) -> None:
        currency = str(getattr(account, "currency", "") or "未知")
        login = getattr(account, "login", "未知")
        server = getattr(account, "server", "未知")
        self.details.setText(f"当前账户：{login} · {server} · 币种 {currency}")
        self.note.setText("请在 MT5 客户端切换账户后重新检查。")
