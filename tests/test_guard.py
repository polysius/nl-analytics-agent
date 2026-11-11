import pytest

from nlagent.guard import UnsafeSQLError, validate_select

ALLOWED = {"driver", "race", "constructor", "race_data"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT full_name FROM driver LIMIT 5",
        "WITH wins AS (SELECT driver_id FROM race_data) SELECT count(*) FROM wins",
        "SELECT d.full_name FROM driver d JOIN race_data r ON r.driver_id = d.id",
        "SELECT 1 UNION SELECT 2",
        "SELECT * FROM public.driver",
    ],
)
def test_read_only_queries_pass(sql):
    assert validate_select(sql, ALLOWED).sql


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE driver",
        "DELETE FROM driver",
        "UPDATE driver SET full_name = 'x'",
        "INSERT INTO driver (id) VALUES ('x')",
        "TRUNCATE driver",
        "CREATE TABLE evil (id int)",
        "ALTER TABLE driver ADD COLUMN x int",
        "GRANT ALL ON driver TO PUBLIC",
        "SELECT * INTO backup FROM driver",
        "SELECT 1; DROP TABLE driver",
        "WITH gone AS (DELETE FROM driver RETURNING *) SELECT * FROM gone",
        "COPY driver TO '/tmp/out'",
        "SET default_transaction_read_only = off",
    ],
)
def test_write_statements_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, ALLOWED)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM catalog.columns",
    ],
)
def test_tables_outside_the_allowed_set_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, ALLOWED)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(30)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
    ],
)
def test_dangerous_functions_are_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, ALLOWED)


def test_unparseable_sql_is_rejected():
    with pytest.raises(UnsafeSQLError):
        validate_select("SELEC FROM WHERE", ALLOWED)
