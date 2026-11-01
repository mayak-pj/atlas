"""Кто сейчас работает и над какой папкой."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="presence",
    title="Кто онлайн",
    optional=["login"],
    factory="atlas.features.presence.ui:PresenceFeature",
)
