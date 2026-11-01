"""База типов: карточка «В базу» (шаг 4.2); вкладка и поиск — шаг 4.3."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="type_db",
    title="База типов",
    optional=["compare", "annotate_tools"],
    factory="atlas.features.type_db.ui:TypeDbFeature",
)
