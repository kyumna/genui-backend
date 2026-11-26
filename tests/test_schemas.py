from app.schemas import UINode, validate_ui


def clean(node: dict) -> dict:
    return validate_ui(UINode.model_validate(node)).props


def test_palette_and_hex_colors_are_kept_and_normalised():
    assert clean({"type": "Card", "props": {"color": "Red"}})["color"] == "red"
    assert clean({"type": "Stat", "props": {"label": "a", "value": "1", "color": "#AABBCC"}})[
        "color"
    ] == "#aabbcc"


def test_invalid_colors_are_dropped_not_rejected():
    for bad in ["light blue", "#12", "#gggggg", "url(javascript:x)", "red; x: y", 5, None]:
        props = clean({"type": "Card", "props": {"color": bad}})
        assert "color" not in props


def test_card_variant_defaults_to_soft():
    assert clean({"type": "Card", "props": {"variant": "filled"}})["variant"] == "soft"
    assert clean({"type": "Card", "props": {"variant": "solid"}})["variant"] == "solid"


def test_chart_colors_are_filtered_and_capped():
    props = clean(
        {
            "type": "Chart",
            "props": {
                "kind": "bar",
                "xKey": "x",
                "yKeys": ["y"],
                "data": [{"x": "a", "y": 1}],
                "colors": ["blue", "nope", "#ff0000", "green", "teal", "pink"],
            },
        }
    )
    assert props["colors"] == ["blue", "#ff0000", "green", "teal"]
