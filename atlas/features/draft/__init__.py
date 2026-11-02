"""Черновик (8.1): свободные заметки с автосохранением, автосписок найденного из отметок, ручные строки."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="draft",
    title="Черновик",
    optional=["compare"],
    tab_order=70,
    factory="atlas.features.draft.ui:DraftFeature",
)
