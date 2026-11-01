"""Сравнение: раскладки 1–4 фото, эталон, листание одного окна, «мигалка»."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="compare",
    title="Сравнение",
    tab_order=5,
    factory="atlas.features.compare.ui:CompareFeature",
)
