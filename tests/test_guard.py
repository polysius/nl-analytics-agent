import pytest

from nlagent.guard import UnsafeSQLError, validate_select

ALLOWED = {"driver", "race", "constructor", "race_data"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT full_name FROM driver LIMIT 5",
        "WITH wins AS (SELECT driver_id FROM race_data) SELECT count(*) FROM wins",
        "WITH a AS (SELECT driver_id FROM race_data), b AS (SELECT * FROM a) SELECT * FROM b",
        "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT * FROM r",
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
        "WITH pg_tables AS (SELECT 1) SELECT * FROM pg_catalog.pg_tables",
        "WITH columns AS (SELECT 1) SELECT * FROM catalog.columns",
        "WITH pg_roles AS (SELECT * FROM pg_roles) SELECT * FROM pg_roles",
        "WITH a AS (SELECT * FROM pg_roles), pg_roles AS (SELECT 1) SELECT * FROM a",
        "WITH a AS (SELECT * FROM pg_settings), pg_settings AS (SELECT 1) SELECT * FROM a",
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


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT left(database_to_xml(true, false, '')::text, 200)",
        "SELECT table_to_xml('catalog.columns', true, false, '')",
        "SELECT schema_to_xml('catalog', true, false, '')",
        "SELECT query_to_xml_and_xmlschema('select pg_sleep(1)', true, false, '')",
        "SELECT * FROM driver, LATERAL pg_stat_get_activity(NULL) a LIMIT 1",
        "SELECT pg_notify('x', 'y')",
        "SELECT version()",
        'WITH "PG_ROLES" AS (SELECT 1) SELECT rolname FROM pg_roles',
        "SELECT 1 FROM driver FOR UPDATE",
        "SELECT * FROM generate_series(1, 3)",
    ],
)
def test_holes_found_in_review_are_closed(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, ALLOWED)


def test_common_functions_still_work():
    sql = ("SELECT count(*), round(avg(x), 2), coalesce(max(x), 0), date_trunc('year', now()) "
           "FROM (SELECT 1 AS x) t")
    assert validate_select(sql, ALLOWED).sql


@pytest.mark.parametrize(
    "text",
    [
        "Does the `constructor` table have a `name` column?",
        "SELECT * FROM race WHERE name = 'unterminated",
        "I cannot answer that question.",
    ],
)
def test_prose_and_broken_quoting_are_rejected_not_crashed(text):
    with pytest.raises(UnsafeSQLError):
        validate_select(text, ALLOWED)
