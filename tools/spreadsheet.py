"""Spreadsheet tools: load CSV/Excel, profile, describe, groupby."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def load_table(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    suffix = p.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(p)
    if suffix in {".tsv"}:
        return pd.read_csv(p, sep="\t")
    # csv with encoding / sep fallbacks
    try:
        return pd.read_csv(p)
    except Exception:
        try:
            return pd.read_csv(p, sep=";", encoding="utf-8-sig")
        except Exception:
            return pd.read_csv(p, encoding="latin-1")


def _is_numeric_dtype(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s)


def describe_table(df: pd.DataFrame) -> dict:
    profile = []
    numeric_desc: dict[str, Any] = {}
    for col in df.columns:
        series = df[col]
        non_null = int(series.notna().sum())
        try:
            nunique = int(series.nunique(dropna=True))
        except TypeError:
            nunique = -1
        profile.append({
            "column": str(col),
            "dtype": str(series.dtype),
            "non_null": non_null,
            "nunique": nunique,
            "sample": series.dropna().astype(str).head(3).tolist(),
        })
        if _is_numeric_dtype(series):
            desc = series.describe()
            numeric_desc[str(col)] = {
                "count": _safe(desc.get("count")),
                "mean": _safe(desc.get("mean")),
                "std": _safe(desc.get("std")),
                "min": _safe(desc.get("min")),
                "25%": _safe(desc.get("25%")),
                "50%": _safe(desc.get("50%")),
                "75%": _safe(desc.get("75%")),
                "max": _safe(desc.get("max")),
            }
    return {"profile": profile, "numeric_describe": numeric_desc}


def _safe(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:  # noqa: BLE001
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:  # noqa: BLE001
            return str(v)
    return v


def group_by_table(
    df: pd.DataFrame,
    group_by: str,
    agg_col: str | None = None,
    agg_func: str = "sum",
) -> dict:
    func = (agg_func or "sum").lower()
    if func not in {"sum", "mean", "count", "min", "max", "median"}:
        func = "sum"

    # pick numeric column if not specified
    target = agg_col
    if target is None:
        nums = [c for c in df.columns if c != group_by and _is_numeric_dtype(df[c])]
        target = nums[0] if nums else None

    if target is None or func == "count":
        series = df.groupby(group_by, dropna=False).size().reset_index(name="value")
        series.columns = [group_by, "value"]
        values = [
            {"key": _safe(row[group_by]), "value": _safe(row["value"])}
            for _, row in series.iterrows()
        ]
        return {
            "group_by": str(group_by),
            "agg_col": "(count)",
            "agg_func": "count",
            "values": values,
        }

    grouped = df.groupby(group_by, dropna=False)[target]
    if func == "sum":
        result = grouped.sum()
    elif func == "mean":
        result = grouped.mean()
    elif func == "min":
        result = grouped.min()
    elif func == "max":
        result = grouped.max()
    elif func == "median":
        result = grouped.median()
    else:
        result = grouped.sum()

    result = result.reset_index()
    result.columns = [group_by, "value"]
    result = result.sort_values("value", ascending=False)
    values = [
        {"key": _safe(row[group_by]), "value": _safe(row["value"])}
        for _, row in result.iterrows()
    ]
    return {
        "group_by": str(group_by),
        "agg_col": str(target),
        "agg_func": func,
        "values": values,
    }


def preview_table(df: pd.DataFrame, head: int = 5) -> list[dict]:
    sample = df.head(head)
    records = sample.astype(object).where(sample.notna(), None).to_dict(orient="records")
    # stringify non-json types
    out = []
    for rec in records:
        out.append({str(k): _safe(v) for k, v in rec.items()})
    return out
