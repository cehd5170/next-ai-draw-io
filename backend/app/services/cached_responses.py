"""
Cached diagram responses for common demo prompts.

Ported from lib/cached-responses.ts.  The cache avoids an LLM round-trip
for well-known first-message queries when the canvas is empty.

Each entry in ``CACHED_RESPONSES`` has:
    prompt       – substring (case-insensitive) to match against user text
    has_image    – whether the entry should match messages WITH an image
    response_xml – bare mxCell XML (no mxGraphModel wrapper) to return

``find_cached_response`` performs case-insensitive substring matching and
respects the ``has_image`` flag so that image-upload prompts are served
separately from plain-text ones.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached entries
# ---------------------------------------------------------------------------

CACHED_RESPONSES: list[dict] = [
    # ------------------------------------------------------------------
    # Transformer architecture — animated connector diagram
    # ------------------------------------------------------------------
    {
        "prompt": "animated connector",
        "has_image": False,
        "response_xml": (
            '<mxCell id="title" value="Transformer Architecture" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
            "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;fontStyle=1;"
            '" vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="20" width="250" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="input_embed" value="Input Embedding" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=11;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="480" width="120" height="40" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="pos_enc_left" value="Positional Encoding" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=11;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="420" width="120" height="40" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="encoder_box" value="ENCODER" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;'
            'verticalAlign=top;fontSize=12;fontStyle=1;" vertex="1" parent="1">\n'
            '  <mxGeometry x="60" y="180" width="160" height="220" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="mha_enc" value="Multi-Head&#xa;Attention" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="330" width="120" height="50" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="add_norm1_enc" value="Add &amp; Norm" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=10;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="280" width="120" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="ff_enc" value="Feed Forward" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=10;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="240" width="120" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="conn1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;'
            "orthogonalLoop=1;jettySize=auto;html=1;"
            'strokeWidth=2;strokeColor=#6c8ebf;flowAnimation=1;" '
            'edge="1" parent="1" source="input_embed" target="pos_enc_left">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="conn2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;'
            "orthogonalLoop=1;jettySize=auto;html=1;"
            'strokeWidth=2;strokeColor=#6c8ebf;flowAnimation=1;" '
            'edge="1" parent="1" source="pos_enc_left" target="mha_enc">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>"
        ),
    },
    # ------------------------------------------------------------------
    # Transformer architecture — alternate phrasing
    # ------------------------------------------------------------------
    {
        "prompt": "transformer",
        "has_image": False,
        "response_xml": (
            '<mxCell id="title" value="Transformer Architecture" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
            "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=20;fontStyle=1;"
            '" vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="20" width="250" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="encoder_box" value="ENCODER" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;'
            'verticalAlign=top;fontSize=12;fontStyle=1;" vertex="1" parent="1">\n'
            '  <mxGeometry x="60" y="180" width="160" height="220" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="decoder_box" value="DECODER" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;'
            'verticalAlign=top;fontSize=12;fontStyle=1;" vertex="1" parent="1">\n'
            '  <mxGeometry x="630" y="140" width="160" height="260" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="conn_cross" style="edgeStyle=orthogonalEdgeStyle;rounded=0;'
            "orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=1;exitY=0.5;exitDx=0;exitDy=0;"
            "entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
            'strokeWidth=3;strokeColor=#9673a6;flowAnimation=1;dashed=1;" '
            'edge="1" parent="1" source="encoder_box" target="decoder_box">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>"
        ),
    },
    # ------------------------------------------------------------------
    # Replicate diagram in AWS style (image required)
    # ------------------------------------------------------------------
    {
        "prompt": "Replicate this in aws style",
        "has_image": True,
        "response_xml": (
            '<mxCell id="vpc" value="VPC" '
            'style="points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],'
            "[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
            "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc;"
            "strokeColor=#8C4FFF;fillColor=#F4F0FA;verticalAlign=top;"
            "align=center;spacingTop=25;fontSize=14;fontColor=#AAB7B8;dashed=0;"
            '" vertex="1" parent="1">\n'
            '  <mxGeometry x="40" y="40" width="720" height="440" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="igw" value="Internet Gateway" '
            'style="outlineConnect=0;fontColor=#232F3E;gradientColor=none;'
            "strokeColor=none;fillColor=#8C4FFF;labelBackgroundColor=#ffffff;"
            "align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;"
            'shape=mxgraph.aws4.internet_gateway;" vertex="1" parent="1">\n'
            '  <mxGeometry x="360" y="60" width="60" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="subnet_pub" value="Public Subnet" '
            'style="points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],'
            "[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
            "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_public_subnet;"
            "strokeColor=#1A9C3E;fillColor=#E9F3E6;verticalAlign=top;"
            "align=center;spacingTop=25;fontSize=12;"
            '" vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="160" width="260" height="240" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="ec2" value="EC2 Instance" '
            'style="outlineConnect=0;fontColor=#232F3E;gradientColor=none;'
            "strokeColor=none;fillColor=#ED7100;labelBackgroundColor=#ffffff;"
            "align=center;html=1;fontSize=12;fontStyle=0;aspect=fixed;"
            'shape=mxgraph.aws4.instance;" vertex="1" parent="1">\n'
            '  <mxGeometry x="180" y="260" width="60" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e_igw_ec2" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="igw" target="ec2">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>"
        ),
    },
    # ------------------------------------------------------------------
    # Replicate this flowchart (image required)
    # ------------------------------------------------------------------
    {
        "prompt": "Replicate this flowchart.",
        "has_image": True,
        "response_xml": (
            '<mxCell id="start" value="Start" '
            'style="ellipse;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="40" width="120" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="process1" value="Process Step 1" '
            'style="rounded=1;whiteSpace=wrap;html=1;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="280" y="160" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="decision1" value="Decision?" '
            'style="rhombus;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="260" y="280" width="200" height="80" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="process2" value="Alternative Path" '
            'style="rounded=1;whiteSpace=wrap;html=1;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="520" y="280" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="end" value="End" '
            'style="ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="420" width="120" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="start" target="process1">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e2" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="process1" target="decision1">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e3" value="Yes" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="decision1" target="end">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e4" value="No" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="decision1" target="process2">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e5" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="process2" target="end">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>"
        ),
    },
    # ------------------------------------------------------------------
    # Summarise research paper as a diagram (image required)
    # ------------------------------------------------------------------
    {
        "prompt": "Summarize this paper as a diagram",
        "has_image": True,
        "response_xml": (
            '<mxCell id="title" value="Paper Summary" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;'
            "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=18;fontStyle=1;"
            '" vertex="1" parent="1">\n'
            '  <mxGeometry x="200" y="20" width="360" height="40" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="problem" value="Problem Statement" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=13;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="80" y="100" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="method" value="Proposed Method" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=13;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="100" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="results" value="Key Results" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=13;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="520" y="100" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="conclusion" value="Conclusion" '
            'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=13;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="300" y="220" width="160" height="60" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="problem" target="method">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e2" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="method" target="results">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="e3" style="edgeStyle=orthogonalEdgeStyle;" '
            'edge="1" parent="1" source="results" target="conclusion">\n'
            '  <mxGeometry relative="1" as="geometry"/>\n'
            "</mxCell>"
        ),
    },
    # ------------------------------------------------------------------
    # Draw a cat (no image)
    # ------------------------------------------------------------------
    {
        "prompt": "Draw a cat for me",
        "has_image": False,
        "response_xml": (
            '<mxCell id="body" value="" '
            'style="ellipse;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#E65100;strokeWidth=2;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="180" y="200" width="200" height="160" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="head" value="" '
            'style="ellipse;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#E65100;strokeWidth=2;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="210" y="100" width="140" height="120" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="ear_left" value="" '
            'style="triangle;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#E65100;strokeWidth=2;direction=north;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="215" y="70" width="40" height="50" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="ear_right" value="" '
            'style="triangle;whiteSpace=wrap;html=1;fillColor=#FFE0B2;strokeColor=#E65100;strokeWidth=2;direction=north;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="305" y="70" width="40" height="50" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="eye_left" value="●" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=18;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="235" y="130" width="30" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="eye_right" value="●" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=18;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="295" y="130" width="30" height="30" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="nose" value="&#9650;" '
            'style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=14;" '
            'vertex="1" parent="1">\n'
            '  <mxGeometry x="268" y="165" width="24" height="20" as="geometry"/>\n'
            "</mxCell>\n"
            '<mxCell id="mouth" value="" '
            'style="curved=1;endArrow=none;html=1;strokeColor=#E65100;strokeWidth=2;" '
            'edge="1" parent="1">\n'
            '  <mxGeometry relative="1" as="geometry">\n'
            '    <Array as="points">\n'
            '      <mxPoint x="265" y="192"/>\n'
            '      <mxPoint x="280" y="200"/>\n'
            '      <mxPoint x="295" y="192"/>\n'
            "    </Array>\n"
            "  </mxGeometry>\n"
            "</mxCell>"
        ),
    },
]


# ---------------------------------------------------------------------------
# Lookup helper
# ---------------------------------------------------------------------------


def find_cached_response(text: str, has_image: bool) -> str | None:
    """
    Return cached XML if *text* contains a known demo prompt substring.

    Matching is case-insensitive.  Both ``text`` and the stored entry must
    agree on the ``has_image`` flag.  Returns the ``response_xml`` string
    on a hit, or ``None`` on a miss.
    """
    if not text:
        return None

    text_lower = text.lower()

    for entry in CACHED_RESPONSES:
        if entry["has_image"] != has_image:
            continue
        if entry["prompt"].lower() in text_lower:
            logger.debug("Cache hit for prompt substring: %r", entry["prompt"])
            return entry["response_xml"]

    return None
