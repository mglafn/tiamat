"""
test/test_constants_parity.py
-----------------------------
Ensures frontend TypeScript fee constants stay strictly synchronized with
src/config.py and guards key config invariants before refactoring.
"""

import re
from pathlib import Path

from src.config import BASE_DIR, EVAL_CONFIG, FEATURE_COLS, FEE_CONFIG, MODEL_CONFIG


def _parse_ts_fee_constants(ts_path: Path) -> dict[str, float]:
    content = ts_path.read_text(encoding="utf-8")
    content = re.sub(r"//.*?$", "", content, flags=re.MULTILINE)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    match = re.search(
        r"export\s+const\s+FEE_CONSTANTS\s*=\s*\{(.*?)\}\s*as\s+const",
        content,
        re.DOTALL,
    )
    assert match is not None, f"Could not locate FEE_CONSTANTS in {ts_path}"

    parsed: dict[str, float] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = float(value.strip())
    return parsed


def test_fee_config_matches_typescript_constants():
    ts_constants = _parse_ts_fee_constants(BASE_DIR / "lib" / "constants.ts")
    assert set(ts_constants.keys()) == set(FEE_CONFIG.keys())
    for key, py_val in FEE_CONFIG.items():
        assert ts_constants[key] == py_val, f"Drift on {key}: TS={ts_constants[key]} vs PY={py_val}"


def test_feature_cols_and_embargo_invariants():
    assert len(FEATURE_COLS) == len(set(FEATURE_COLS)), "Duplicate entries in FEATURE_COLS"
    assert MODEL_CONFIG["EMBARGO_DAYS"] == EVAL_CONFIG["PURGE_HORIZON_DAYS"]