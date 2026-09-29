# GeoLedger Database Operations

## Database architecture

FastAPI uses SQLAlchemy 2.x. Local/demo installations continue to use SQLite;
PostgreSQL is selected with `DATABASE_URL` for production. PostgreSQL stores
parcel shapes in a PostGIS `geometry(GEOMETRY, 4326)` column with a GiST index.
The original GeoJSON text remains in `gis_geometries.geojson` so current API
responses and map clients stay compatible. PostgreSQL pool size, overflow and
timeout are configurable with `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` and
`DB_POOL_TIMEOUT_SECONDS`.

Set secrets in an uncommitted `.env` file or a secret manager. Use a URL of the
form `postgresql+psycopg://<user>:<password>@<host>:<port>/<database>`; URL
reserved characters in credentials must be percent-encoded. Do not put real
credentials in source control, command-line examples or logs.

Install dependencies with `python -m pip install -r requirements.txt`. The
PostgreSQL driver is Psycopg 3, and spatial mapping uses GeoAlchemy2. The
PostgreSQL database must be reachable and the configured role must be allowed
to create the PostGIS extension during the first migration (or an administrator
must enable PostGIS first).

### This workspace's local PostgreSQL setup

This Windows workspace has a user-owned PostgreSQL 18.6 runtime with PostGIS
3.6.2 in the ignored `.runtime/` directory. It listens only on `127.0.0.1:5432`;
no Windows service or firewall rule is needed. The app connection is stored in
the ignored, user-readable `.env`; the local PostgreSQL administrator
credentials are in `.runtime/credentials.json`. Do not commit either file.

`run.ps1` starts this local database when its runtime files exist, then starts
the API. Other workspaces without `.runtime/` continue to use their configured
database (SQLite by default). The original SQLite database and a consistent
pre-migration backup remain in `data/`; document and upload files remain in
their existing directories.

## Schema migrations

PostgreSQL schema changes are versioned with Alembic. Before starting the app
against a new PostgreSQL database, set `DATABASE_URL` and run:

```powershell
python -m alembic upgrade head
```

The app validates PostGIS, the managed tables and the Alembic version at
startup. It does not silently create or alter production PostgreSQL tables.
SQLite retains its existing additive startup initialization for local/demo
use.

## Import an existing SQLite database

Use a separate, empty PostgreSQL database. Back up the SQLite database first;
because it may be using WAL, make the backup with SQLite's backup API rather
than copying only the `.db` file while the application is running. For example:

```powershell
python -c "import sqlite3; source=sqlite3.connect('data/geoldger.db'); backup=sqlite3.connect('data/geoldger.pre-postgres-backup.db'); source.backup(backup); backup.close(); source.close()"
```

Stop application writes while taking the final backup and importing. Configure
`DATABASE_URL` to point to the empty PostgreSQL database, then inspect the
source without changing either database:

```powershell
python scripts/migrate_sqlite_to_postgres.py --source data/geoldger.pre-postgres-backup.db --dry-run
```

After reviewing counts and any reported legacy references, run the import:

```powershell
python scripts/migrate_sqlite_to_postgres.py --source data/geoldger.pre-postgres-backup.db
```

The importer opens the SQLite source read-only, refuses to overwrite populated
PostgreSQL tables, preserves record IDs and database values, derives PostGIS
geometry from the existing EPSG:4326 GeoJSON without reprojection, and copies
rows inside one PostgreSQL transaction. Counts and content fingerprints are
checked for every table; document hashes, declared foreign keys, and geometry
SRIDs are checked before commit. A failed row import or check rolls back the
data copy. PostgreSQL schema setup itself is tracked by Alembic and the source
SQLite database is never modified by the import.

Keep document-file storage available at the paths recorded in the migrated
database. The import moves relational metadata only, not PDFs/images, OCR files,
or uploads; the app's existing file-storage mechanism remains authoritative.
Only switch the production deployment to PostgreSQL after the importer reports
successful verification and the file-storage paths are available. Keep the
SQLite backup until the application has been checked against PostgreSQL.

The current SQLite data has two `verification_cases.discrepancy_id` values
without matching discrepancy rows. This legacy relationship is not declared as
a database foreign key in the existing model. The importer reports and
preserves those references rather than silently dropping records or adding a
constraint that would make the import fail.

## Spatial query API

`POST /api/gis/spatial/query` supports `intersects`, `overlaps`, `contains`,
`within`, `touches` (neighboring/touching parcels) and `nearby` (distance in
meters). The endpoint applies the existing parcel visibility scoping and is
available only with PostgreSQL/PostGIS. SQLite keeps all existing GIS API
behavior and returns `501` for this additive PostGIS-only endpoint.

Example request:

```json
{
  "geometry": {"type": "Point", "coordinates": [87.0, 23.0]},
  "operation": "nearby",
  "distance_meters": 250
}
```

Public registration/demo seeding is not run for PostgreSQL by default. Existing
SQLite demo users and their credentials are not reset by this database change.
Set `SEED_DEMO_DATA=true` only for an intentionally disposable local/demo
database.
