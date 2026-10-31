"""Вход по фамилии, без пароля. Диалог при старте, тег пользователя в слоте shell.user."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="login",
    title="Вход",
    tab_order=None,
    factory="atlas.features.login.ui:LoginFeature",
)
