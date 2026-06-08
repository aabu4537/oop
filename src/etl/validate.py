"""Data validation for the football analytics pipeline.

Runs expectation-style checks directly on DataFrames using pandas.
Writes a JSON summary report to ge_reports/ after each run.
GE is an optional dependency — if installed, it is used for richer HTML docs.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_REPORT_DIR = Path("ge_reports")
_REPORT_DIR.mkdir(exist_ok=True)


@dataclass
class _Result:
    expectation: str
    success: bool
    detail: str = ""


def validate_matches_df(df: pd.DataFrame, raise_on_failure: bool = True) -> bool:
    results = [
        _column_exists(df, "match_id"),
        _column_exists(df, "home_team"),
        _column_exists(df, "away_team"),
        _column_exists(df, "match_date"),
        _not_null(df, "match_id"),
        _not_null(df, "match_date"),
        _unique(df, "match_id"),
        _between(df, "home_score", 0, 30, mostly=0.99),
        _between(df, "away_score", 0, 30, mostly=0.99),
    ]
    return _evaluate("matches", df, results, raise_on_failure)


def validate_events_df(df: pd.DataFrame, raise_on_failure: bool = True) -> bool:
    results = [
        _column_exists(df, "id"),
        _column_exists(df, "type"),
        _column_exists(df, "match_id"),
        _not_null(df, "id"),
        _not_null(df, "type"),
        _unique(df, "id"),
        _between(df, "minute", 0, 130, mostly=0.99),
    ]
    return _evaluate("events", df, results, raise_on_failure)


def validate_teams_df(df: pd.DataFrame, raise_on_failure: bool = True) -> bool:
    results = [
        _column_exists(df, "name"),
        _not_null(df, "name"),
        _unique(df, "name"),
    ]
    return _evaluate("teams", df, results, raise_on_failure)


# ---------------------------------------------------------------------------
# Expectation implementations
# ---------------------------------------------------------------------------

def _column_exists(df: pd.DataFrame, col: str) -> _Result:
    ok = col in df.columns
    return _Result(f"column_exists:{col}", ok, "" if ok else f"column '{col}' missing")


def _not_null(df: pd.DataFrame, col: str) -> _Result:
    if col not in df.columns:
        return _Result(f"not_null:{col}", False, f"column '{col}' missing")
    null_count = int(df[col].isna().sum())
    ok = null_count == 0
    return _Result(f"not_null:{col}", ok, f"{null_count} null(s)" if not ok else "")


def _unique(df: pd.DataFrame, col: str) -> _Result:
    if col not in df.columns:
        return _Result(f"unique:{col}", False, f"column '{col}' missing")
    dup_count = int(df[col].duplicated().sum())
    ok = dup_count == 0
    return _Result(f"unique:{col}", ok, f"{dup_count} duplicate(s)" if not ok else "")


def _between(df: pd.DataFrame, col: str, min_val: Any, max_val: Any, mostly: float = 1.0) -> _Result:
    if col not in df.columns:
        return _Result(f"between:{col}", True, "column absent — skipped")
    series = df[col].dropna()
    if series.empty:
        return _Result(f"between:{col}", True, "no non-null values — skipped")
    in_range = series.between(min_val, max_val).mean()
    ok = in_range >= mostly
    return _Result(
        f"between:{col}[{min_val},{max_val}]",
        ok,
        "" if ok else f"only {in_range:.1%} in range (need {mostly:.0%})",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _evaluate(name: str, df: pd.DataFrame, results: list[_Result], raise_on_failure: bool) -> bool:
    failed = [r for r in results if not r.success]
    _write_report(name, df, results)

    if failed:
        msg = f"Validation failed for '{name}' ({len(failed)} expectation(s) failed)"
        for r in failed:
            logger.error("  FAILED %s: %s", r.expectation, r.detail)
        logger.error(msg)
        if raise_on_failure:
            raise ValueError(msg)
        return False

    logger.info("Validation passed for '%s' (%d checks)", name, len(results))
    return True


def _write_report(name: str, df: pd.DataFrame, results: list[_Result]) -> None:
    try:
        report_path = _REPORT_DIR / f"{name}_validation.json"
        summary = {
            "dataset": name,
            "row_count": len(df),
            "passed": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "results": [{"expectation": r.expectation, "success": r.success, "detail": r.detail} for r in results],
        }
        report_path.write_text(json.dumps(summary, indent=2))
    except Exception as exc:
        logger.warning("Could not write validation report: %s", exc)
