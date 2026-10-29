import math

from app.services.supabase import _json_safe


def test_json_safe_replaces_nested_non_finite_numbers() -> None:
    payload = {
        "finite": 0.75,
        "nested": {
            "nan": float("nan"),
            "values": [float("inf"), float("-inf"), 2.5],
        },
    }

    sanitized = _json_safe(payload)

    assert sanitized == {
        "finite": 0.75,
        "nested": {"nan": None, "values": [None, None, 2.5]},
    }
    assert math.isfinite(sanitized["finite"])
