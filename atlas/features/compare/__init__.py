"""Сравнение: раскладки 1–4 фото, эталон, листание одного окна, «мигалка»."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="compare",
    title="Сравнение",
    optional=["defect_kinds"],  # общий список видов замечаний; без неё — data/defect_kinds.json
    tab_order=5,
    factory="atlas.features.compare.ui:CompareFeature",
)
