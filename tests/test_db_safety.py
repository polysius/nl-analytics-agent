"""Prove a write cannot succeed at each layer on its own. Needs the Postgres container."""

import dataclasses

import psycopg
import pytest

from nlagent.config import settings
from nlagent.db import QueryError, run_query
from nlagent.guard import UnsafeSQLError

pytestmark = pytest.mark.db


def test_layer1_guard_blocks_drop_before_the_database():
    with pytest.raises(UnsafeSQLError):
        run_query("DROP TABLE driver")


def test_layer2_role_has_no_write_privilege():
    # Bypass the guard and the read-only session flag: only the role's grants remain.
    with psycopg.connect(settings.database_url) as conn:
        conn.autocommit = True
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM driver")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE public.evil (id int)")


def test_layer3_read_only_session_blocks_writes_even_for_the_owner():
    with psycopg.connect(settings.admin_database_url, options="-c default_transaction_read_only=on") as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM driver WHERE false")


def test_row_cap_truncates_large_results():
    result = run_query("SELECT id FROM driver", row_cap=5)
    assert len(result.rows) == 5
    assert result.truncated


def test_small_results_are_not_marked_truncated():
    result = run_query("SELECT id FROM driver LIMIT 3", row_cap=5)
    assert len(result.rows) == 3
    assert not result.truncated


def test_statement_timeout_stops_slow_queries(monkeypatch):
    monkeypatch.setattr("nlagent.db.settings", dataclasses.replace(settings, statement_timeout_ms=50))
    with pytest.raises(QueryError, match="timeout"):
        # A cross join large enough to outlast 50 ms, without using a forbidden function.
        run_query("SELECT count(*) FROM race_data a, race_data b WHERE a.race_id < b.race_id")


def test_database_errors_are_returned_as_readable_messages():
    with pytest.raises(QueryError, match="does not exist"):
        run_query("SELECT not_a_column FROM driver")
