"""Сводка по детали в правой колонке экрана сравнения (5.1). «Проблемная деталь» — шаг 5.2."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="findings",
    title="Сводка по детали",
    optional=["compare", "type_db"],
    factory="atlas.features.findings.ui:FindingsFeature",
)
