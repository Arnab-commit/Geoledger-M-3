"""GeoLedger — Main FastAPI application."""

import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.logging_config import setup_logging

# Set up logging
setup_logging("DEBUG" if settings.DEBUG else "INFO")
logger = logging.getLogger("geoldger.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("=" * 60)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  {settings.APP_DESCRIPTION}")
    logger.info("=" * 60)

    # Create directories
    for dir_path in [settings.UPLOAD_DIR, settings.ORIGINAL_DIR, settings.PROCESSED_DIR, "data", "logs", "reports"]:
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Demo accounts remain enabled for local SQLite; production PostgreSQL
    # requires an explicit opt-in to avoid adding demo identities to live data.
    if settings.should_seed_demo_data:
        _create_default_users()

    yield

    logger.info("GeoLedger shutting down")


def _create_default_users():
    """Create default governance users and jurisdictions if not present."""
    from backend.database import SessionLocal
    from backend.models.user import User, RoleEnum, Jurisdiction, UserJurisdiction
    from backend.api.auth import hash_password

    db = SessionLocal()
    try:
        # Seed core jurisdictions if none exist
        j_n24p = db.query(Jurisdiction).filter(Jurisdiction.code == "WB_N24P_BARASAT").first()
        if not j_n24p:
            j_n24p = Jurisdiction(
                code="WB_N24P_BARASAT",
                name="Barasat Tehsil, North 24 Parganas",
                state="West Bengal",
                district="North 24 Parganas",
                tehsil="Barasat",
            )
            db.add(j_n24p)

        j_s24p = db.query(Jurisdiction).filter(Jurisdiction.code == "WB_S24P_BARUIPUR").first()
        if not j_s24p:
            j_s24p = Jurisdiction(
                code="WB_S24P_BARUIPUR",
                name="Baruipur Tehsil, South 24 Parganas",
                state="West Bengal",
                district="South 24 Parganas",
                tehsil="Baruipur",
            )
            db.add(j_s24p)

        db.commit()

        # Seed core roles / test accounts
        seed_users = [
            ("admin", "admin@geoldger.local", "admin123", "System Administrator", RoleEnum.ADMIN, "GLOBAL", None),
            ("verifier", "verifier@geoldger.local", "verifier123", "Revenue Officer (Demo)", RoleEnum.REVENUE_OFFICER, "SCOPED", j_n24p.id),
            ("viewer", "viewer@geoldger.local", "viewer123", "Public Record Observer", RoleEnum.CITIZEN, "SELF", None),
            ("citizen_rahul", "rahul@geoldger.local", "citizen123", "Rahul Sharma (Citizen)", RoleEnum.CITIZEN, "SELF", None),
            ("officer_north", "officer.north@revenue.gov.in", "officer123", "Revenue Officer North 24P", RoleEnum.REVENUE_OFFICER, "SCOPED", j_n24p.id),
            ("officer_south", "officer.south@revenue.gov.in", "officer123", "Revenue Officer South 24P", RoleEnum.REVENUE_OFFICER, "SCOPED", j_s24p.id),
            ("auditor_system", "auditor@geoldger.local", "auditor123", "Statutory Land Auditor", RoleEnum.AUDITOR, "GLOBAL", None),
        ]

        for username, email, pwd, full_name, role, scope, jur_id in seed_users:
            existing = db.query(User).filter(User.username == username).first()
            if not existing:
                u = User(
                    username=username,
                    email=email,
                    hashed_password=hash_password(pwd),
                    full_name=full_name,
                    role=role,
                    jurisdiction_scope=scope,
                    is_active="true",
                )
                db.add(u)
                db.flush()
                if jur_id:
                    uj = UserJurisdiction(user_id=u.id, jurisdiction_id=jur_id, is_primary="true")
                    db.add(uj)
            else:
                # Ensure existing verifier has jurisdiction assigned
                if jur_id and not existing.jurisdictions:
                    uj = UserJurisdiction(user_id=existing.id, jurisdiction_id=jur_id, is_primary="true")
                    db.add(uj)

        db.commit()
        logger.info("Governance users and jurisdictions initialized successfully")
    except Exception as e:
        logger.error(f"Error creating default users: {e}")
        db.rollback()
    finally:
        db.close()


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
    )


# Register API routers
from backend.api.health import router as health_router
from backend.api.auth import router as auth_router
from backend.api.admin import router as admin_router
from backend.api.upload import router as upload_router
from backend.api.process import router as process_router
from backend.api.parcels import router as parcels_router
from backend.api.reconciliation import router as reconciliation_router
from backend.api.gis import router as gis_router
from backend.api.verification import router as verification_router
from backend.api.audit import router as audit_router

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(upload_router)
app.include_router(process_router)
app.include_router(parcels_router)
app.include_router(reconciliation_router)
app.include_router(gis_router)
app.include_router(verification_router)
app.include_router(audit_router)

# Serve frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
