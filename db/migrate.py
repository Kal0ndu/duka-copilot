"""Database migration runner for Duka.

Usage:
    python db/migrate.py --latest    # Run all pending migrations
    python db/migrate.py --rollback  # Rollback last migration (future)
    python db/migrate.py --status    # Show migration status
"""
import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import Config


class MigrationRunner:
    """Run SQL migrations from db/migrations/ directory."""

    def __init__(self, db_path=None):
        # Default to the same database the app actually reads (Config.DB_PATH),
        # not a throwaway file in the current working directory.
        self.db_path = db_path or Config.DB_PATH
        self.migrations_dir = Path(__file__).parent / "migrations"
        self.schema_path = Path(__file__).parent / "schema.sql"

    def load_base_schema_if_needed(self):
        """Load db/schema.sql if the target database has no tables yet.

        Incremental files under db/migrations/ assume the base schema
        (business, app_user, transaction_ledger, ...) already exists —
        this bootstraps a brand-new database file the same way
        data/generate_synthetic.py does, so --latest works from scratch.
        """
        db_file = Path(self.db_path)
        is_empty = not db_file.exists() or db_file.stat().st_size == 0
        if not is_empty:
            with sqlite3.connect(self.db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                is_empty = count == 0

        if not is_empty:
            return

        db_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"📦 {self.db_path} has no tables yet — loading base schema.sql...")
        with open(self.schema_path, "r") as f:
            sql_script = f.read()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(sql_script)
            conn.commit()
        print("✅ Base schema loaded.")

    def init_schema_tracking(self):
        """Create schema_migration table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migration (
                    version INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                )
            """)
            conn.commit()
    
    def get_applied_migrations(self):
        """Return list of applied migration versions."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT version FROM schema_migration ORDER BY version")
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []
    
    def get_pending_migrations(self):
        """Return list of migration files that haven't been applied."""
        if not self.migrations_dir.exists():
            return []
        
        applied = set(self.get_applied_migrations())
        migration_files = sorted(self.migrations_dir.glob("*.sql"))
        pending = []
        
        for f in migration_files:
            # Extract version from filename (e.g., "001_auth_and_kyc_schema.sql" → 1)
            try:
                version = int(f.name.split("_")[0])
                if version not in applied:
                    pending.append((version, f.name, f))
            except (ValueError, IndexError):
                print(f"⚠️  Warning: Skipping migration with invalid name: {f.name}")
        
        return pending
    
    def run_migration(self, version, filename, filepath):
        """Execute a single migration file."""
        print(f"⏳ Applying migration {version}: {filename}...", end=" ")
        
        try:
            with open(filepath, "r") as f:
                sql_script = f.read()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(sql_script)
                
                # Record migration
                conn.execute(
                    "INSERT INTO schema_migration (version, description) VALUES (?, ?)",
                    (version, filename)
                )
                conn.commit()
            
            print("✅ Done")
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
    
    def run_pending(self):
        """Run all pending migrations."""
        self.load_base_schema_if_needed()
        self.init_schema_tracking()
        pending = self.get_pending_migrations()
        
        if not pending:
            print("✅ All migrations applied. Database is up to date.")
            return True
        
        print(f"📦 Found {len(pending)} pending migration(s):\n")
        for version, filename, _ in pending:
            print(f"  {version}. {filename}")
        print()
        
        success_count = 0
        for version, filename, filepath in pending:
            if self.run_migration(version, filename, filepath):
                success_count += 1
            else:
                print(f"❌ Migration {version} ({filename}) failed. Stopping.")
                return False
        
        print(f"\n✅ Successfully applied {success_count}/{len(pending)} migration(s)")
        return True
    
    def status(self):
        """Show migration status."""
        self.init_schema_tracking()
        applied = self.get_applied_migrations()
        pending = self.get_pending_migrations()
        
        print("📊 Migration Status")
        print("=" * 60)
        
        if applied:
            print("\n✅ Applied Migrations:")
            for version in applied:
                print(f"   {version}")
        else:
            print("\n❌ No migrations applied yet")
        
        if pending:
            print(f"\n⏳ Pending Migrations ({len(pending)}):")
            for version, filename, _ in pending:
                print(f"   {version}. {filename}")
        else:
            print("\n✅ No pending migrations")
        
        print("\n" + "=" * 60)


def main():
    runner = MigrationRunner()
    
    if len(sys.argv) < 2 or sys.argv[1] == "--latest":
        runner.run_pending()
    elif sys.argv[1] == "--status":
        runner.status()
    elif sys.argv[1] == "--rollback":
        print("❌ Rollback not yet implemented")
    else:
        print("Usage: python db/migrate.py [--latest|--status|--rollback]")


if __name__ == "__main__":
    main()
