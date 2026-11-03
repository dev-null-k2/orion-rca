import sqlite3

import pytest

from orion.estate.builder import build_estate
from orion.harness import Budget, BudgetExceeded, Harness, ToolRefused
from orion.tools import guard_sql


@pytest.fixture(scope="module")
def h():
    return Harness(build_estate("upgrade-missing-login"))


@pytest.mark.parametrize("sql", [
    "DELETE FROM accounts", "UPDATE accounts SET status='X'", "SELECT 1; DROP TABLE accounts",
    "PRAGMA writable_schema=1", "ATTACH DATABASE 'x' AS y", "INSERT INTO orders VALUES (1)",
])
def test_sql_guard_refuses_writes(sql):
    with pytest.raises(ToolRefused):
        guard_sql(sql)


def test_sql_guard_allows_select_and_with():
    assert guard_sql("SELECT * FROM accounts -- note").startswith("SELECT")
    assert guard_sql("WITH x AS (SELECT 1) SELECT * FROM x;").startswith("WITH")


def test_database_is_read_only_even_past_the_guard(h):
    conn = h.estate.connect_readonly()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO accounts VALUES ('A','B','C','D')")


def test_code_read_cannot_escape_the_repos(h):
    with pytest.raises(ToolRefused):
        h.call("code_read", path="../../../etc/passwd")


def test_repeat_limit_and_budget():
    h = Harness(build_estate("sms-timeouts"), budget=Budget(max_tool_calls=3, max_same_call=1))
    h.call("ticket_read")
    with pytest.raises(ToolRefused):
        h.call("ticket_read")
    h.call("sql_schema")
    h.call("kb_search", query="sms")
    with pytest.raises(BudgetExceeded):
        h.call("logs_search", query="timeout")


def test_unknown_tool_is_refused(h):
    with pytest.raises(ToolRefused):
        h.call("rm_rf")
