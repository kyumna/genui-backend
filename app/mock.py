"""Stand-in for the AI until the real provider is wired in."""

from app.schemas import UINode


def mock_ui(prompt: str) -> UINode:
    title = prompt if len(prompt) <= 60 else prompt[:57] + "..."
    return UINode.model_validate(
        {
            "type": "Stack",
            "props": {"gap": 5},
            "children": [
                {"type": "Heading", "props": {"text": title, "level": 2}},
                {
                    "type": "Text",
                    "props": {
                        "text": "Mock response from the FastAPI back end.",
                        "muted": True,
                    },
                },
                {
                    "type": "Grid",
                    "props": {"cols": 3, "gap": 3},
                    "children": [
                        {"type": "Stat", "props": {"label": "Best battery", "value": "Laptop B", "hint": "14 hours", "color": "green"}},
                        {"type": "Stat", "props": {"label": "Best value", "value": "Laptop A", "hint": "$899", "color": "blue"}},
                        {"type": "Stat", "props": {"label": "Most powerful", "value": "Laptop C", "hint": "32 GB RAM", "color": "purple"}},
                    ],
                },
                {
                    "type": "Tabs",
                    "props": {"tabs": ["Battery", "Specs"]},
                    "children": [
                        {
                            "type": "Chart",
                            "props": {
                                "kind": "bar",
                                "xKey": "name",
                                "yKeys": ["hours"],
                                "colors": ["orange"],
                                "data": [
                                    {"name": "Laptop A", "hours": 9},
                                    {"name": "Laptop B", "hours": 14},
                                    {"name": "Laptop C", "hours": 7},
                                ],
                            },
                        },
                        {
                            "type": "Table",
                            "props": {
                                "columns": ["Model", "RAM", "Price"],
                                "rows": [
                                    ["Laptop A", "16 GB", "$899"],
                                    ["Laptop B", "16 GB", "$1,199"],
                                    ["Laptop C", "32 GB", "$1,799"],
                                ],
                            },
                        },
                    ],
                },
                {
                    "type": "Card",
                    "props": {"title": "Your budget", "color": "amber"},
                    "children": [
                        {"type": "Slider", "props": {"label": "Max price ($)", "min": 500, "max": 2500, "step": 50, "value": 1200}}
                    ],
                },
            ],
        }
    )
