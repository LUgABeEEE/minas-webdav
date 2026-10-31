"""Smoke tests for the MCP server surface.

The MCP server lives behind the optional ``[mcp]`` extra, so this module is
skipped when that dependency is absent (the plain CLI/CI install does not pull
it in). When it *is* installed, the test pins the tool catalogue: an accidental
rename or a dropped ``@mcp.tool`` decorator must not go unnoticed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import unittest

HAS_MCP = importlib.util.find_spec("mcp") is not None

EXPECTED_TOOLS = {
    "nas_ls",
    "nas_stat",
    "nas_tree",
    "nas_find",
    "nas_du",
    "nas_df",
    "nas_cat",
    "nas_get",
    "nas_put",
    "nas_mkdir",
    "nas_mv",
    "nas_cp",
    "nas_rm",
    "nas_probe",
}


@unittest.skipUnless(HAS_MCP, "optional 'mcp' extra is not installed")
class TestToolCatalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from minas_webdav.mcp_server import mcp

        cls.tools = asyncio.run(mcp.list_tools())

    def test_exactly_the_expected_tools(self):
        names = {tool.name for tool in self.tools}
        self.assertEqual(names, EXPECTED_TOOLS)

    def test_every_tool_has_a_description(self):
        for tool in self.tools:
            with self.subTest(tool=tool.name):
                self.assertTrue((tool.description or "").strip(),
                                f"{tool.name} has no description")
                schema = getattr(tool, "input_schema", None)
                self.assertTrue(schema, f"{tool.name} has no input schema")

    def test_destructive_tool_takes_confirm(self):
        schema = None
        for tool in self.tools:
            if tool.name == "nas_rm":
                schema = getattr(tool, "input_schema", None)
        self.assertIsNotNone(schema)
        self.assertIn("recursive", schema.get("properties", {}))
        self.assertIn("confirm", schema.get("properties", {}))


if __name__ == "__main__":
    unittest.main()
