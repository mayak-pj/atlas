"""Разложить по папкам типов: фото с отметкой «Тип N» уходят в подпапку «Тип N», с журналом и отменой."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="sort_types",
    title="Раскладка по типам",
    optional=["compare"],
    factory="atlas.features.sort_types.ui:SortTypesFeature",
)
