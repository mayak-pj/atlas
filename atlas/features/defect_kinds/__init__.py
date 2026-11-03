"""Виды замечаний (03.11.2026): общий список в базе, правится в программе — добавить, исправить, удалить."""
from atlas.core.feature import FeatureSpec

FEATURE = FeatureSpec(
    id="defect_kinds",
    title="Виды замечаний",
    factory="atlas.features.defect_kinds.ui:DefectKindsFeature",
)
