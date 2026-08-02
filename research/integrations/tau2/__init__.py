"""Tau2 to Halluci-Action trajectory integration."""

from .adapter import adapt_tau2_run
from .contract import CanonicalTrajectory

__all__ = ["CanonicalTrajectory", "adapt_tau2_run"]

