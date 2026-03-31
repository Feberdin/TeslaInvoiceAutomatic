"""Helpers for loading pure integration modules without Home Assistant.

Purpose:
    Unit tests in this repository focus on pure helper modules such as
    `models.py` and `emailer.py`. Importing the package normally would execute
    Home Assistant setup code from `__init__.py`, which pulls in optional
    runtime dependencies not needed for these tests.
Input/Output:
    Exposes `load_integration_module(name)` which returns one loaded module.
Important invariants:
    Only use this helper for pure modules that do not require Home Assistant to
    be instantiated.
How to debug:
    If an import fails, check whether the requested module depends on
    Home Assistant-specific imports and should therefore be tested differently.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "custom_components" / "tesla_invoice_automatic"
PACKAGE_NAME = "custom_components.tesla_invoice_automatic"


def load_integration_module(module_name: str):
    """Load one integration module without importing package `__init__.py`."""

    if "custom_components" not in sys.modules:
        package = types.ModuleType("custom_components")
        package.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = package

    if PACKAGE_NAME not in sys.modules:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(PACKAGE_ROOT)]
        sys.modules[PACKAGE_NAME] = package

    full_name = f"{PACKAGE_NAME}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    spec = importlib.util.spec_from_file_location(
        full_name,
        PACKAGE_ROOT / f"{module_name}.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Module {module_name} konnte nicht geladen werden.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
