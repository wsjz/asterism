"""Deterministic enrichment of collected items: no model, only rules."""
from .classify import classify, classify_item, item_facets

__all__ = ["classify", "classify_item", "item_facets"]
