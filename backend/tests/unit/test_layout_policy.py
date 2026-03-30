import sys
from types import SimpleNamespace

from app.tools.graphviz_layout import apply_graphviz_layout
from app.tools.layout_policy import apply_display_diagram_layout_defaults


class _FakeDigraph:
    def __init__(self, name: str | None = None, engine: str | None = None):
        self.name = name
        self.engine = engine

    def attr(self, **kwargs):
        return None

    def node(self, *args, **kwargs):
        return None

    def edge(self, *args, **kwargs):
        return None

    def subgraph(self, graph):
        return None

    def pipe(self, format: str = "plain") -> bytes:
        assert format == "plain"
        return (
            "graph 1 5 3\n"
            "node 2 1 2 1.67 0.83 A solid box black lightgrey\n"
            "node 3 4 2 1.67 0.83 B solid box black lightgrey\n"
            "stop\n"
        ).encode("utf-8")


class TestLayoutPolicy:
    def test_positioned_vertices_default_to_no_auto_layout(self):
        xml = """
<mxCell id="2" value="A" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="120" height="60" as="geometry"/>
</mxCell>
<mxCell id="3" value="B" vertex="1" parent="1">
  <mxGeometry x="240" y="40" width="120" height="60" as="geometry"/>
</mxCell>
"""
        result = apply_display_diagram_layout_defaults("display_diagram", {"xml": xml})
        assert result["layout"] == "none"

    def test_unpositioned_vertices_keep_hierarchical_default(self):
        xml = """
<mxCell id="2" value="A" vertex="1" parent="1">
  <mxGeometry width="120" height="60" as="geometry"/>
</mxCell>
<mxCell id="3" value="B" vertex="1" parent="1">
  <mxGeometry width="120" height="60" as="geometry"/>
</mxCell>
"""
        result = apply_display_diagram_layout_defaults("display_diagram", {"xml": xml})
        assert result["layout"] == "mxHierarchicalLayout"

    def test_explicit_layout_is_preserved(self):
        xml = """
<mxCell id="2" value="A" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="120" height="60" as="geometry"/>
</mxCell>
<mxCell id="3" value="B" vertex="1" parent="1">
  <mxGeometry x="240" y="40" width="120" height="60" as="geometry"/>
</mxCell>
"""
        result = apply_display_diagram_layout_defaults(
            "display_diagram",
            {"xml": xml, "layout": "mxCircleLayout"},
        )
        assert result["layout"] == "mxCircleLayout"


class TestGraphvizLayout:
    def test_auto_layout_rebuilds_edge_connection_points(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules,
            "graphviz",
            SimpleNamespace(Digraph=_FakeDigraph),
        )

        xml = """
<mxGraphModel>
  <root>
    <mxCell id="0" />
    <mxCell id="1" parent="0" />
    <mxCell id="2" value="A" vertex="1" parent="1">
      <mxGeometry width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="3" value="B" vertex="1" parent="1">
      <mxGeometry width="120" height="60" as="geometry"/>
    </mxCell>
    <mxCell
      id="4"
      style="curved=1;endArrow=classic;exitX=0;exitY=0;entryX=1;entryY=1;"
      edge="1"
      parent="1"
      source="2"
      target="3"
    >
      <mxGeometry as="geometry">
        <Array as="points">
          <mxPoint x="10" y="10"/>
        </Array>
      </mxGeometry>
    </mxCell>
  </root>
</mxGraphModel>
"""

        result = apply_graphviz_layout(xml, engine="dot")

        assert "edgeStyle=orthogonalEdgeStyle" in result
        assert "exitX=1" in result
        assert "exitY=0.5" in result
        assert "entryX=0" in result
        assert "entryY=0.5" in result
        assert "curved=1" not in result
        assert "<Array as=\"points\">" not in result
