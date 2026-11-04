from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from atlas.core.feature import Feature
from atlas.features.findings import logic

log = logging.getLogger("atlas.findings")

SLOT_RIGHT = "compare.right"
PANEL_KEY = "findings"
STOP_WAIT_S = 2.0  # сеть могла пропасть: дольше не держим закрытие программы
RELOAD_EVENTS = ("type.added", "type.archived", "type.restored", "type.deleted", "folder.done")
TITLE = "Сводка по детали"
TITLE_TYPES = "Типы"
TITLE_FINDINGS = "Замечания"
TEXT_NO_FOLDER = "Откройте папку — здесь появится сводка по детали"
TEXT_NO_TYPES = "В базе типов для этой детали ничего нет"
TEXT_NO_FINDINGS = "Замечаний раньше не было"
TEXT_NEVER_CHECKED = "Раньше эта деталь не проверялась"
TEXT_ARCHIVED = "в архиве"
TEXT_LOAD_FAILED = "Не удалось прочитать данные: сводка может быть устаревшей"
TEXT_PROBLEM = "Ранее были замечания — будьте внимательнее"
NOTICE_MS = 15000
PILL_DEFECT = "Дефект"
PILL_REMARK = "Замечание"


class _Signals(QObject):
    loaded = pyqtSignal(object, object)  # part_id, Summary или None, если база недоступна


def _label(text, role=None, wrap=True):
    label = QLabel(text)
    if role:
        label.setProperty("role", role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.NoTextInteraction)
    return label


def _pill(text, tone):
    pill = QLabel(text)
    pill.setProperty("role", "pill")
    pill.setProperty("tone", tone)
    return pill


class FindingsPanel(QFrame):
    """Правая колонка экрана сравнения. Только рисует готовую Summary."""

    def __init__(self, today=None, parent=None):
        super().__init__(parent)
        self.setProperty("role", "panel")
        self._today = today
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setProperty("role", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self.body = QWidget()
        self.body.setProperty("role", "plain")
        self.scroll.setWidget(self.body)
        self.column = QVBoxLayout(self.body)
        self.column.setContentsMargins(14, 14, 14, 14)
        self.column.setSpacing(8)
        self.column.addStretch(1)
        self.summary = None
        self.show_summary(None)

    def show_summary(self, summary, stale=False):
        self.summary = summary
        while self.column.count() > 1:
            item = self.column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater сработает позже, а рисуется старое сразу
                widget.setParent(None)
                widget.deleteLater()
        self._add(_label(TITLE, "caption"))
        if summary is None:
            self._add(_label(TEXT_NO_FOLDER, "muted"))
            return
        self._add(_label(summary.name, "heading"))
        if summary.problem is not None:
            self._add(self._alert(summary))
        if stale:
            self._add(_label(TEXT_LOAD_FAILED, "warn"))
        if summary.types is not None:
            self._separator()
            self._add(_label(TITLE_TYPES, "caption"))
            if not summary.types:
                self._add(_label(TEXT_NO_TYPES, "muted"))
            for line in summary.types:
                self._add(self._type_row(line))
        self._separator()
        self._add(_label(TITLE_FINDINGS, "caption"))
        if not summary.findings:
            self._add(_label(TEXT_NO_FINDINGS, "muted"))
        for line in summary.findings:
            self._add(self._finding_row(line))
        if summary.total > len(summary.findings):
            self._add(_label("Показано {} из {}".format(len(summary.findings), summary.total), "muted"))
        if summary.problem is None:  # у проблемной детали «последняя проверка» уже в плашке
            self._separator()
            self._add(_label(self.last_check_text(summary), "dim"))

    def last_check_text(self, summary):
        if summary.last_check is None:
            return TEXT_NEVER_CHECKED
        who = ", " + summary.last_check.author if summary.last_check.author else ""
        return "Последняя проверка: {}{}".format(logic.short_date(summary.last_check.when, self._today), who)

    def _add(self, widget):
        self.column.insertWidget(self.column.count() - 1, widget)

    def _separator(self):
        line = QFrame()
        line.setProperty("role", "hsep")
        self._add(line)

    def _alert(self, summary):
        """Красная плашка: что за дефекты и когда проверяли последний раз."""
        frame = QFrame()
        frame.setProperty("role", "alert")
        column = QVBoxLayout(frame)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(4)
        column.addWidget(_label(TEXT_PROBLEM, "alert-title"))
        column.addWidget(_label(logic.problem_text(summary.problem, self._today), "alert-text"))
        column.addWidget(_label(self.last_check_text(summary), "alert-text"))
        return frame

    def _type_row(self, line):
        row = QWidget()
        row.setProperty("role", "plain")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        tone = "muted" if line.archived or line.type_no <= 1 else ("type2" if line.type_no == 2 else "type3")
        layout.addWidget(_pill("Тип {}".format(line.type_no), tone), 0, Qt.AlignTop)
        text = _label(line.text, "muted" if line.archived else None)
        layout.addWidget(text, 1)
        note = TEXT_ARCHIVED if line.archived else "с " + logic.full_date(line.since)
        layout.addWidget(_label(note, "muted", wrap=False), 0, Qt.AlignTop)
        return row

    def _finding_row(self, line):
        row = QWidget()
        row.setProperty("role", "plain")
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        defect = line.mark == "defect"
        head.addWidget(_pill(PILL_DEFECT if defect else PILL_REMARK, "defect" if defect else "remark"))
        if line.sn:
            head.addWidget(_label(line.sn, "mono", wrap=False))
        head.addStretch(1)
        column.addLayout(head)
        column.addWidget(_label(logic.finding_title(line)))
        who = " · " + line.author if line.author else ""
        column.addWidget(_label(logic.short_date(line.when, self._today) + who, "muted"))
        return row


class FindingsFeature(Feature):
    """Панель в слоте compare.right и сервис «findings». Чужие данные берёт только через сервисы."""

    def on_start(self):
        self.part_id = None
        self.folder_id = None
        self._stopped = False
        self._thread = None
        self._again = False
        self._stale = False
        self._notify = False  # уведомление — один раз на открытие папки, а не на каждое обновление сводки
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.panel = FindingsPanel()
        bus = self.ctx.bus
        self._unsubscribe = [bus.subscribe("folder.opened", self._on_opened)]
        self._unsubscribe += [bus.subscribe(name, lambda _payload: self.reload()) for name in RELOAD_EVENTS]
        self.ctx.services.register("findings", self)
        if self.ctx.shell is not None:
            self.ctx.shell.add_panel(SLOT_RIGHT, self.panel, key=PANEL_KEY, order=10)

    def on_stop(self):
        self._stopped = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self.ctx.services.unregister("findings")
        if self._thread is not None:
            self._thread.join(STOP_WAIT_S)

    # --- сервис -----------------------------------------------------------------
    def summary(self, part_id, days=None, exclude_folder_id=None):
        """Сводка по детали → Summary или None, если детали нет. Из любого потока, кроме GUI (ходит в базу).

        days — считать дефекты и замечания, отмеченные за последние N дней (None — за всё время);
        exclude_folder_id — не считать папку, которую проверяют сейчас.
        """
        services = self.ctx.services
        parts, folders = services.get("parts"), services.get("folders")
        part = parts.get(part_id)
        if part is None:
            return None
        config = self.ctx.config
        ids = sorted({part.id} | {item.id for item in parts.find(part.name)})  # та же деталь — только точное название
        names = {user.id: user.name for user, _ in services.get("users").all()}
        marks = folders.problem_marks(ids, exclude_folder_id, logic.since_text(days))
        problem_days = logic.positive_int(config.get("findings.problem_days"), logic.DEFAULT_PROBLEM_DAYS)
        problem = logic.problem_of(
            marks, problem_days, logic.positive_int(config.get("findings.problem_min_marks"), logic.DEFAULT_PROBLEM_MIN)
        )
        limit = config.get("findings.list_limit", logic.DEFAULT_LIMIT)
        lines, total, defects, remarks = logic.build_findings(marks, names, limit)
        last = folders.last_done(ids)
        type_db = services.get_optional("type_db")
        types = None
        if type_db is not None:
            records = [record for item in ids for record in type_db.types_for_part(item, include_archived=True)]
            types = logic.build_types(records)
        return logic.Summary(
            part.id, part.name,
            types, lines, total, defects, remarks,
            logic.LastCheck(last.status_at, names.get(last.status_by, "")) if last is not None else None,
            problem,
        )

    # --- панель -----------------------------------------------------------------
    def _on_opened(self, payload):
        self.part_id = payload.get("part_id")
        self.folder_id = payload.get("folder_id")
        self._stale = False
        self._notify = True
        self.reload()

    def reload(self):
        if self._stopped or self.part_id is None:
            return
        if self._thread is not None:
            self._again = True
            return
        part_id, folder_id = self.part_id, self.folder_id
        self._thread = threading.Thread(target=self._work, args=(part_id, folder_id), daemon=True)
        self._thread.start()

    def _work(self, part_id, folder_id):
        try:
            summary = self.summary(part_id, None, folder_id)
        except Exception as exc:  # нет сети, база занята: остаётся прежняя сводка
            log.warning("Не удалось собрать сводку: %s", exc)
            summary = None
        self.signals.loaded.emit(part_id, summary)

    def _announce(self, summary):
        """Ранее были замечания: уведомление в строке состояния, один раз после открытия папки."""
        if not self._notify:
            return
        self._notify = False
        if summary.problem is not None and self.ctx.shell is not None:
            self.ctx.shell.show_message(logic.notice_text(summary.name, summary.problem), NOTICE_MS)

    def _on_loaded(self, part_id, summary):
        self._thread = None
        if self._stopped:
            return
        if part_id == self.part_id:
            if summary is not None:
                self._stale = False
                self.panel.show_summary(summary)
                self._announce(summary)
            else:
                self._stale = True
                if self.panel.summary is not None:
                    self.panel.show_summary(self.panel.summary, stale=True)
        if self._again or part_id != self.part_id:
            self._again = False
            self.reload()
