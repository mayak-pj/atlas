"""Дашборд (9.1): показатели за неделю / месяц / год, детали с замечаниями, виды замечаний, детали без проблем."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="dashboard",
    title="Дашборд",
    optional=["type_db"],
    tab_order=60,
    factory="atlas.features.dashboard.ui:DashboardFeature",
)
