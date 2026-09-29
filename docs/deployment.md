# Free cloud demo deployment

This setup serves the FastAPI app, its frontend, OCR, and GIS from a free
Render web service. Supabase Free provides PostgreSQL/PostGIS. The deployment
starts with an empty cloud database; it does not copy the local database or
uploaded documents.

## Important free-tier behavior

- Render free web services sleep after 15 minutes without traffic and can take
  about a minute to wake. Their filesystem is temporary, so uploaded documents
  and generated OCR artifacts are lost after a restart, redeploy, or sleep.
- Supabase Free includes 500 MB of database storage and 1 GB of file storage.
  Free projects can pause after seven days of low activity.
- This is suitable for a public prototype/demo, not production or sensitive
  land-record data. Do not upload real personal or government records.

## Setup

1. Create a Supabase Free project and enable the `postgis` extension from
   **Database → Extensions**. Keep the database password private.
2. In Supabase **Connect**, use the Session Pooler connection string for an
   external IPv4-hosted service. The connection URL must use the
   `postgresql+psycopg://` scheme; URL-encode reserved characters in the
   password if needed.
3. In Render, choose **New → Blueprint**, connect this repository, and select
   the root `render.yaml`. Keep the web service plan set to `free`.
4. When prompted, enter the Supabase connection string as `DATABASE_URL`.
   Render generates `SECRET_KEY`; do not set it to a value from `.env` or
   commit it to GitHub.
5. Deploy. The container runs `alembic upgrade head` before starting Uvicorn.
   Wait for the Render health check at `/api/health` to pass, then open the
   generated `https://*.onrender.com` URL on other devices.

The Supabase database is separate from the local PostgreSQL instance. No local
database, `.env`, upload, log, or report files are included in the container.
