"""Отчёт (8.2): Excel по templates/excel_columns.json и письмо-ответ по templates/mail_reply.html (Outlook, не отправлять)."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="report",
    title="Отчёт",
    optional=["draft", "compare"],
    factory="atlas.features.report.ui:ReportFeature",
)
