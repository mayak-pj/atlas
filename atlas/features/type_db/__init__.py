"""База типов: карточка «В базу» (4.2), вкладка с поиском (4.3); архив — шаг 4.4."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="type_db",
    title="База типов",
    optional=["compare", "annotate_tools"],
    tab_order=20,
    factory="atlas.features.type_db.ui:TypeDbFeature",
)
