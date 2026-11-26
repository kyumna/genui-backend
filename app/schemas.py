"""UI contract shared with the front end (mirrors src/components/gen/schema.ts).

Every node the AI returns is checked against these models before it is sent
to the browser or saved. Unknown component types and bad props are rejected.
"""

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

MAX_DEPTH = 6
MAX_NODES = 150

Cell = Union[str, int, float]

# Styling the AI may use: a named palette color or a #rrggbb hex value.
# Anything else is dropped (not rejected), so a creative model cannot fail a request
# by writing "light blue". Only these safe values ever reach the browser.
PALETTE = {"red", "orange", "amber", "green", "teal", "blue", "purple", "pink", "gray"}
_HEX = re.compile(r"^#[0-9a-f]{6}$")


def _clean_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in PALETTE or _HEX.match(v) else None


def _clean_colors(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned = [c for c in (_clean_color(v) for v in value) if c]
    return cleaned[:4] or None


def _clean_variant(value: Any) -> str:
    return value if value in ("soft", "solid") else "soft"


Color = Annotated[str | None, BeforeValidator(_clean_color)]
Colors = Annotated[list[str] | None, BeforeValidator(_clean_colors)]
Variant = Annotated[Literal["soft", "solid"], BeforeValidator(_clean_variant)]


class Props(BaseModel):
    # Extra keys the model invents are dropped instead of failing the request.
    model_config = ConfigDict(extra="ignore")


class StackProps(Props):
    gap: float = Field(4, ge=0, le=12)


class GridProps(Props):
    cols: int = Field(2, ge=1, le=4)
    gap: float = Field(4, ge=0, le=12)


class CardProps(Props):
    title: str | None = None
    color: Color = None
    variant: Variant = "soft"


class HeadingProps(Props):
    text: str
    level: Literal[1, 2, 3] = 2
    color: Color = None


class TextProps(Props):
    text: str
    muted: bool = False
    color: Color = None


class StatProps(Props):
    label: str
    value: str
    hint: str | None = None
    color: Color = None


class TableProps(Props):
    columns: list[str] = Field(min_length=1)
    rows: list[list[Cell]]


class ChartProps(Props):
    kind: Literal["bar", "line"]
    data: list[dict[str, Cell]] = Field(min_length=1)
    xKey: str
    yKeys: list[str] = Field(min_length=1, max_length=4)
    colors: Colors = None


class SliderProps(Props):
    label: str
    min: float
    max: float
    step: float = Field(1, gt=0)
    value: float
    color: Color = None


class TabsProps(Props):
    tabs: list[str] = Field(min_length=1, max_length=6)


PROP_MODELS: dict[str, type[Props]] = {
    "Stack": StackProps,
    "Grid": GridProps,
    "Card": CardProps,
    "Heading": HeadingProps,
    "Text": TextProps,
    "Stat": StatProps,
    "Table": TableProps,
    "Chart": ChartProps,
    "Slider": SliderProps,
    "Tabs": TabsProps,
}


class UINode(BaseModel):
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list["UINode"] = Field(default_factory=list)


def _count(node: UINode) -> int:
    return 1 + sum(_count(c) for c in node.children)


def _validate(node: UINode, depth: int) -> UINode:
    if depth > MAX_DEPTH:
        raise ValueError(f"UI is nested deeper than {MAX_DEPTH} levels")
    model = PROP_MODELS.get(node.type)
    if model is None:
        raise ValueError(f"Unknown component type: {node.type!r}")
    props = model.model_validate(node.props).model_dump(exclude_none=True)
    children = [_validate(c, depth + 1) for c in node.children]
    return UINode(type=node.type, props=props, children=children)


def validate_ui(node: UINode) -> UINode:
    """Return a cleaned copy of the tree, or raise ValueError / ValidationError."""
    if _count(node) > MAX_NODES:
        raise ValueError(f"UI has more than {MAX_NODES} components")
    return _validate(node, 0)
