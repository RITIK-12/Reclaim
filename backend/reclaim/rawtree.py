"""Thin RawTree client: append-only inserts plus read-only ClickHouse SQL."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

import httpx

from .config import settings


def sql_str(value: Any) -> str:
    """Quote a value as a ClickHouse string literal."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def now_ms() -> int:
    return int(time.time() * 1000)


# RawTree is a shared cluster: we may only touch tables that carry our prefix.
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN|INTO|TABLE|DESCRIBE)\s+([`\"]?[A-Za-z_][\w.]*[`\"]?)", re.I)
_CTE_NAME = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.I)
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class RawTree:
    """Every table name passes through `t()` so all our tables share one prefix."""

    def __init__(self, url: str = settings.rawtree_url, key: str = settings.rawtree_key,
                 prefix: str = settings.table_prefix):
        self.prefix = prefix
        self._http = httpx.Client(base_url=url, timeout=60,
                                  headers={"Authorization": f"Bearer {key}"})

    def t(self, name: str) -> str:
        if not _SAFE_NAME.match(name):
            raise ValueError(f"bad table name {name!r}")
        return name if name.startswith(self.prefix) else f"{self.prefix}{name}"

    def check_scope(self, sql: str) -> None:
        """Refuse SQL that references any table outside our prefix (CTE names are fine)."""
        ctes = {n.lower() for n in _CTE_NAME.findall(sql)}
        for ref in _TABLE_REF.findall(sql):
            name = ref.strip('`"')
            if name.lower() not in ctes and not name.startswith(self.prefix):
                raise PermissionError(f"RawTree scope: {name!r} is outside {self.prefix}*")

    def insert(self, table: str, rows: dict | Iterable[dict], batch: int = 1000) -> int:
        rows = [rows] if isinstance(rows, dict) else list(rows)
        inserted = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            r = self._http.post(f"/v1/tables/{self.t(table)}", content=json.dumps(chunk, default=str),
                                headers={"Content-Type": "application/json"})
            r.raise_for_status()
            inserted += r.json().get("inserted", len(chunk))
        return inserted

    def query(self, sql: str) -> list[dict]:
        """Run SQL. Write `{tbl}` placeholders as `{t:name}`; they expand to prefixed names."""
        sql = self._expand(sql)
        self.check_scope(sql)
        r = self._http.post("/v1/query", json={"sql": sql, "format": "JSON"})
        if r.status_code >= 400:
            raise RuntimeError(f"RawTree {r.status_code}: {r.text[:500]}")
        return r.json().get("data", [])

    def one(self, sql: str) -> dict | None:
        rows = self.query(sql)
        return rows[0] if rows else None

    def tables(self) -> list[str]:
        r = self._http.get("/v1/tables")
        r.raise_for_status()
        return [t["name"] for t in r.json().get("tables", []) if t["name"].startswith(self.prefix)]

    def _expand(self, sql: str) -> str:
        # `{t:case_events}` -> `reclaim_case_events`
        out, i = [], 0
        while (j := sql.find("{t:", i)) != -1:
            k = sql.index("}", j)
            out.append(sql[i:j] + self.t(sql[j + 3:k]))
            i = k + 1
        out.append(sql[i:])
        return "".join(out)


db = RawTree()
