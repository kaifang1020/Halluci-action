"""Compatibility wrapper for the expanded task registry.

The canonical task definitions live in ``research.tasks``.  Keep this module
only for older notebooks or scripts that still import ``tasks_added``.
"""

from research.tasks import *  # noqa: F401,F403
