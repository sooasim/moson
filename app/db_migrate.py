"""기존 DB에 누락된 컬럼 추가 (create_all은 ALTER 미수행)."""
from sqlalchemy import inspect, text


def run_schema_patches(app, db) -> None:
    engine = db.engine
    is_pg = engine.dialect.name == "postgresql"

    def has_col(table: str, name: str) -> bool:
        try:
            insp = inspect(engine)
            return name in {c["name"] for c in insp.get_columns(table)}
        except Exception:
            return False

    def run(sqlite_sql: str, pg_sql: str) -> None:
        sql = pg_sql if is_pg else sqlite_sql
        with engine.begin() as conn:
            conn.execute(text(sql))

    patches = [
        (
            "reseller_applications",
            "recruiting_reseller_id",
            "ALTER TABLE reseller_applications ADD COLUMN recruiting_reseller_id INTEGER",
            "ALTER TABLE reseller_applications ADD COLUMN IF NOT EXISTS recruiting_reseller_id INTEGER",
        ),
        (
            "reseller_applications",
            "dealer_approved_at",
            "ALTER TABLE reseller_applications ADD COLUMN dealer_approved_at TIMESTAMP",
            "ALTER TABLE reseller_applications ADD COLUMN IF NOT EXISTS dealer_approved_at TIMESTAMP",
        ),
        (
            "reseller_applications",
            "dealer_dismissed_at",
            "ALTER TABLE reseller_applications ADD COLUMN dealer_dismissed_at TIMESTAMP",
            "ALTER TABLE reseller_applications ADD COLUMN IF NOT EXISTS dealer_dismissed_at TIMESTAMP",
        ),
        (
            "resellers",
            "recruited_by_reseller_id",
            "ALTER TABLE resellers ADD COLUMN recruited_by_reseller_id INTEGER",
            "ALTER TABLE resellers ADD COLUMN IF NOT EXISTS recruited_by_reseller_id INTEGER",
        ),
        (
            "consult_requests",
            "policy_row_id",
            "ALTER TABLE consult_requests ADD COLUMN policy_row_id INTEGER",
            "ALTER TABLE consult_requests ADD COLUMN IF NOT EXISTS policy_row_id INTEGER",
        ),
        (
            "consult_requests",
            "settlement_status",
            "ALTER TABLE consult_requests ADD COLUMN settlement_status VARCHAR(20) DEFAULT '미정산'",
            "ALTER TABLE consult_requests ADD COLUMN IF NOT EXISTS settlement_status VARCHAR(20) DEFAULT '미정산'",
        ),
        (
            "consult_requests",
            "settled_at",
            "ALTER TABLE consult_requests ADD COLUMN settled_at TIMESTAMP",
            "ALTER TABLE consult_requests ADD COLUMN IF NOT EXISTS settled_at TIMESTAMP",
        ),
    ]

    for table, col, sq, pq in patches:
        if not has_col(table, col):
            try:
                run(sq, pq)
            except Exception:
                app.logger.exception("schema patch skip %s.%s", table, col)

    if not is_pg:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE consult_requests SET settlement_status = '미정산' WHERE settlement_status IS NULL OR settlement_status = ''"
                    )
                )
        except Exception:
            pass
