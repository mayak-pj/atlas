"""Диалог входа — по design/mockup/Main.dc.html."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from atlas.features.login import logic
from atlas.shared.widgets import FlowLayout, LogoMark, NameTag

SLOT_SUMMARY = "login.summary"  # «С вашего последнего входа» — кладут другие функции
SLOT_ASIDE = "login.aside"  # «Сейчас в работе», последние папки


def _panel(role="panel"):
    frame = QFrame()
    frame.setProperty("role", role)
    return frame


class LoginDialog(QDialog):
    def __init__(self, repo, colors, shell=None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.colors = colors
        self.shell = shell
        self.selected = None  # User
        self._tags = []
        self._users = {}
        self._last_logins = {}
        self.setWindowTitle("Atlas — вход")
        self.setModal(True)
        self.resize(1080, 560)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(24)
        outer.addWidget(self._build_main(), 3)
        self.aside = self._build_aside()
        outer.addWidget(self.aside, 1)
        self.add_button = self._make_add_button()
        self._reload()

    # --- сборка ---------------------------------------------------------------
    def _build_main(self):
        panel = _panel()
        column = QVBoxLayout(panel)
        column.setContentsMargins(40, 40, 40, 40)
        column.setSpacing(28)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(LogoMark(44))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("ATLAS")
        title.setProperty("role", "title")
        subtitle = QLabel("Сверка фото деталей на однотипность и дефекты")
        subtitle.setProperty("role", "dim")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        column.addLayout(head)

        caption = QLabel("КТО ВЫ? ВЫБЕРИТЕ ФАМИЛИЮ — БЕЗ ПАРОЛЯ")
        caption.setProperty("role", "caption")
        column.addWidget(caption)
        self.tags_host = QWidget()
        self.tags_host.setProperty("role", "plain")
        self.tags_layout = FlowLayout(self.tags_host, spacing=10)
        column.addWidget(self.tags_host)
        self.empty_hint = QLabel("Список пуст. Нажмите «+ Добавить себя».")
        self.empty_hint.setProperty("role", "muted")
        column.addWidget(self.empty_hint)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.go_button = QPushButton()
        self.go_button.setProperty("role", "primary")
        self.go_button.setDefault(True)
        self.go_button.setCursor(Qt.PointingHandCursor)
        self.go_button.clicked.connect(self._accept)
        self.last_label = QLabel()
        self.last_label.setProperty("role", "muted")
        row.addWidget(self.go_button)
        row.addWidget(self.last_label)
        row.addStretch(1)
        column.addLayout(row)

        self.summary_host = _panel("panel-alt")
        self.summary_layout = QVBoxLayout(self.summary_host)
        self.summary_layout.setContentsMargins(18, 18, 18, 18)
        self.summary_layout.setSpacing(10)
        column.addWidget(self.summary_host)
        column.addStretch(1)
        return panel

    def _build_aside(self):
        panel = _panel()
        self.aside_layout = QVBoxLayout(panel)
        self.aside_layout.setContentsMargins(24, 24, 24, 24)
        self.aside_layout.setSpacing(16)
        return panel

    def _make_add_button(self):
        button = QPushButton("+ Добавить себя")
        button.setProperty("role", "dashed")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(self._add_self)
        return button

    # --- слоты ----------------------------------------------------------------
    def attach_slots(self):
        if self.shell is None:
            self.summary_host.hide()
            self.aside.hide()
            return
        self.shell.register_slot(SLOT_SUMMARY, self.summary_layout)
        self.shell.register_slot(SLOT_ASIDE, self.aside_layout)
        self.summary_host.setVisible(bool(self.shell.slots.panels(SLOT_SUMMARY)))
        self.aside.setVisible(bool(self.shell.slots.panels(SLOT_ASIDE)))

    def detach_slots(self):
        if self.shell is None:
            return
        for name in (SLOT_SUMMARY, SLOT_ASIDE):
            self.shell.slots.unregister_slot(name)
            self.shell.slots.clear_slot(name)  # панели живут в диалоге и вместе с ним удаляются

    # --- данные ---------------------------------------------------------------
    def _reload(self, select_name=None):
        while self._tags:
            tag = self._tags.pop()
            self.tags_layout.removeWidget(tag)
            tag.deleteLater()
        self.tags_layout.removeWidget(self.add_button)
        rows = self.repo.all()
        self._last_logins = {user.id: last for user, last in rows}
        self._users = {user.id: user for user, _ in rows}
        for user, _ in rows:
            tag = NameTag(user.name, user.color)
            tag.setParent(self.tags_host)
            tag.clicked.connect(lambda checked=False, uid=user.id: self._select(uid))
            self.tags_layout.addWidget(tag)
            self._tags.append(tag)
        self.add_button.setParent(self.tags_host)
        self.tags_layout.addWidget(self.add_button)
        self.tags_host.updateGeometry()
        self.empty_hint.setVisible(not rows)
        target = None
        if select_name:
            target = next((u for u, _ in rows if u.name == select_name), None)
        if target is None and rows:
            logged = [(last, user) for user, last in rows if last]
            target = max(logged, key=lambda pair: pair[0])[1] if logged else rows[0][0]
        self._select(target.id if target else None)

    def _select(self, user_id):
        self.selected = self._users.get(user_id)
        for tag in self._tags:
            tag.setChecked(self.selected is not None and tag.name == self.selected.name)
        if self.selected is None:
            self.go_button.setText("Войти")
            self.go_button.setEnabled(False)
            self.last_label.setText("")
            return
        self.go_button.setEnabled(True)
        self.go_button.setText("Войти как {}".format(self.selected.name))
        self.last_label.setText("Последний вход: " + logic.describe_last_login(self._last_logins.get(user_id)))

    def _add_self(self):
        existing = [user.name for user in self._users.values()]
        text, ok = QInputDialog.getText(self, "Новый пользователь", "Ваша фамилия:")
        if not ok:
            return
        try:
            name = logic.validate_name(text, existing)
        except logic.NameInvalid as exc:
            QMessageBox.warning(self, "Atlas", str(exc))
            return
        user = self.repo.add(name, self.colors)
        self._reload(select_name=user.name)

    def _accept(self):
        if self.selected is not None:
            self.accept()
