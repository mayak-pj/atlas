"""Кнопка «Добавить папку…» в левой колонке экрана сравнения: временная замена импорту из письма (6.x)."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="add_folder",
    title="Добавить папку",
    optional=["compare"],
    tab_order=None,
    factory="atlas.features.add_folder.ui:AddFolderFeature",
)
