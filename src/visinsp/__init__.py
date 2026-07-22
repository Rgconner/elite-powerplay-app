"""
Visual Inspector — camera-based manufacturing defect detection.

Public package surface. Sub-modules are not imported eagerly to keep the
package importable in very small environments (the Pi Zero 2 W with only
the inspection engine, for example).
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "Visual Inspector Project"
__email__ = "noreply@example.com"

__all__ = ["__version__", "__author__", "__email__"]
