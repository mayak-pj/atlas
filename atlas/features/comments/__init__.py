"""Комментарии (7.2): временные сообщения коллегам с фото, адресат, привязка к детали, «ошибка ранее»."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="comments",
    title="Комментарии",
    optional=["compare"],
    tab_order=50,
    factory="atlas.features.comments.ui:CommentsFeature",
)
