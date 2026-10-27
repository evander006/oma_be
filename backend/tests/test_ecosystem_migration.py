"""Migration regression: 0001_initial uses the current SQLAlchemy models."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_fresh_database_upgrades_to_ecosystem_head(tmp_path: Path) -> None:
    db_path = tmp_path / "oma_migration_regression.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    env = {**os.environ, "DATABASE_URL": database_url, "AI_PROVIDER": "mock"}
    command = [sys.executable, "-m", "alembic", "upgrade", "head"]

    result = subprocess.run(
        command, cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "contractor_profiles", "work_orders", "home_equipment",
        "home_history_events", "journey_templates", "journey_step_progress",
    }.issubset(set(inspector.get_table_names()))
    assert "tenure" in {c["name"] for c in inspector.get_columns("properties")}
    assert {"wall_material", "floor_material", "ceiling_material"}.issubset(
        {c["name"] for c in inspector.get_columns("rooms")}
    )
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0002_digital_home_ecosystem"
    engine.dispose()

    again = subprocess.run(
        command, cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )
    assert again.returncode == 0, f"{again.stdout}\n{again.stderr}"
