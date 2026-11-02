"""Правила проверки (7.1): список с фильтрами, создание с фото, «прочитано» на пользователя, правила к детали."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="rules",
    title="Правила",
    optional=["compare"],
    tab_order=40,
    factory="atlas.features.rules.ui:RulesFeature",
)
