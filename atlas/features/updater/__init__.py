"""Обновление (10.1): при старте сверяет свою версию с release/version.txt и предлагает перейти на действующую."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="updater",
    title="Обновление",
    factory="atlas.features.updater.ui:UpdaterFeature",
)
