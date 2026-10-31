"""Тестовая функция: показывает, что работают вкладка, сервис и миграция."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="hello",
    title="Привет",
    tab_order=10,
    factory="atlas.features.hello.ui:HelloFeature",
)
