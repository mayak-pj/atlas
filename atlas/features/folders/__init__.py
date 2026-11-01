"""Панель истории копирования в левой колонке экрана сравнения."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="folders",
    title="Папки",
    optional=["compare", "presence"],
    factory="atlas.features.folders.ui:FoldersFeature",
)
