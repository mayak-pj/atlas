"""Шаблон функции: скопировать в atlas/features/<id>/ и заменить _template на <id>. Не загружается."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="_template",
    title="Шаблон",
    requires=[],
    optional=[],
    tab_order=None,  # число — есть вкладка
    factory="atlas.features._template.ui:TemplateFeature",
)
