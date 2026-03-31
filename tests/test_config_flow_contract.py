"""Regression checks for Home Assistant flow compatibility.

Purpose:
    Guard the most important Home Assistant config-flow contracts that recently
    broke the settings dialog on newer HA versions.
Input/Output:
    Parses `config_flow.py` and `strings.json` without importing Home Assistant.
Important invariants:
    The options flow must use the current `OptionsFlowWithReload` pattern and a
    dedicated `reconfigure` step must exist with matching translation strings.
How to debug:
    If this test fails, compare the AST expectations below with
    `custom_components/tesla_invoice_automatic/config_flow.py` and the matching
    keys in `strings.json`.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FLOW_PATH = ROOT / "custom_components" / "tesla_invoice_automatic" / "config_flow.py"
STRINGS_PATH = ROOT / "custom_components" / "tesla_invoice_automatic" / "strings.json"


class ConfigFlowContractTests(unittest.TestCase):
    """Protect HA flow structure against accidental regressions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(CONFIG_FLOW_PATH.read_text(encoding="utf-8"))
        cls.strings = json.loads(STRINGS_PATH.read_text(encoding="utf-8"))

    def test_options_flow_uses_reload_base_class(self) -> None:
        options_flow = self._get_class("TeslaInvoiceAutomaticOptionsFlow")

        base_names = [ast.unparse(base) for base in options_flow.bases]

        self.assertIn("config_entries.OptionsFlowWithReload", base_names)

    def test_async_get_options_flow_returns_handler_without_manual_entry_argument(self) -> None:
        config_flow = self._get_class("TeslaInvoiceAutomaticConfigFlow")
        method = self._get_method(config_flow, "async_get_options_flow")
        returns = [node for node in ast.walk(method) if isinstance(node, ast.Return)]

        self.assertEqual(len(returns), 1)
        return_value = returns[0].value
        self.assertIsInstance(return_value, ast.Call)
        self.assertEqual(ast.unparse(return_value.func), "TeslaInvoiceAutomaticOptionsFlow")
        self.assertEqual(len(return_value.args), 0)

    def test_reconfigure_step_exists(self) -> None:
        config_flow = self._get_class("TeslaInvoiceAutomaticConfigFlow")
        method_names = {
            node.name for node in config_flow.body if isinstance(node, ast.AsyncFunctionDef)
        }

        self.assertIn("async_step_reconfigure", method_names)

    def test_reconfigure_strings_exist(self) -> None:
        config_step = self.strings["config"]["step"]
        aborts = self.strings["config"]["abort"]

        self.assertIn("reconfigure", config_step)
        self.assertIn("reconfigure_successful", aborts)

    def _get_class(self, class_name: str) -> ast.ClassDef:
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return node
        self.fail(f"Klasse {class_name} nicht gefunden.")

    def _get_method(self, class_node: ast.ClassDef, method_name: str) -> ast.AST:
        for node in class_node.body:
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == method_name:
                return node
        self.fail(f"Methode {method_name} nicht gefunden.")


if __name__ == "__main__":
    unittest.main()
