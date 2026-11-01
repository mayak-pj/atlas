"""Инструменты разметки на фото: ножницы, обводка, подпись, отмена и повтор (шаг 4.1)."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="annotate_tools",
    title="Разметка фото",
    optional=["compare"],
    factory="atlas.features.annotate_tools.ui:AnnotateToolsFeature",
)
