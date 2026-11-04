"""БД: карточка «В базу» (4.2), вкладка с поиском (4.3), архив (4.4); с 04.11.2026 — «База типов» и «Замечания»."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="type_db",
    title="БД",
    optional=["compare", "annotate_tools"],
    tab_order=20,
    factory="atlas.features.type_db.ui:TypeDbFeature",
)
