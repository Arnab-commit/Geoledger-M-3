"""Authentication API endpoints."""

import logging
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer

from backend.database import get_db
from backend.config import settings
from backend.models.user import User, RoleEnum
from backend.schemas.auth import UserCreate, UserLogin, UserResponse, TokenResponse

logger = logging.getLogger("geoldger.auth")
router = APIRouter(prefix="/api/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a unique salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        parts = hashed_password.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_key = parts[3]
        key = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        )
        return secrets.compare_digest(key.hex(), expected_key)
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: extract current user from JWT token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not _is_user_active(user):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def _is_user_active(user: User) -> bool:
    """Interpret the legacy string-backed active flag consistently."""
    value = getattr(user, "is_active", False)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "active")
    return bool(value)


def get_optional_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Dependency: extract user if token provided, otherwise None."""
    if token is None:
        return None
    try:
        return get_current_user(token=token, db=db)
    except HTTPException:
        return None


def require_role(*roles: RoleEnum):
    """Dependency factory: require specific roles."""
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' not authorized for this action",
            )
        return current_user
    return role_checker


@router.post("/register", response_model=UserResponse, status_code=201)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    existing = db.query(User).filter(
        (func.lower(User.username) == user_data.username.lower()) |
        (func.lower(User.email) == user_data.email.lower())
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    # Public self-registration must never grant administrative or officer roles.
    requested_role = (user_data.role or RoleEnum.CITIZEN.value).strip().lower()
    if requested_role not in (RoleEnum.CITIZEN.value, RoleEnum.VIEWER.value):
        raise HTTPException(status_code=403, detail="Public registration is limited to citizen accounts")
    role = RoleEnum.CITIZEN

    user = User(
        # Store newly registered usernames in their login-comparison form.
        # The database's unique constraint is case-sensitive on supported
        # backends, so canonical storage also prevents case-only duplicates
        # from racing past the case-insensitive pre-check.
        username=user_data.username.strip().lower(),
        email=user_data.email.strip().lower(),
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
        role=role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Username or email already registered")
    db.refresh(user)
    logger.info(f"User registered: {user.username} ({user.role})")
    return user


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, request: Request, db: Session = Depends(get_db)):
    """Authenticate and return JWT token."""
    identifier = credentials.username.strip().lower()
    user = db.query(User).filter(
        (func.lower(User.username) == identifier) |
        (func.lower(User.email) == identifier)
    ).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        from backend.security.authorization import log_security_event
        log_security_event(
            db=db, user=user, action="LOGIN_FAILED", resource_type="user",
            resource_id=user.id if user else None, result="DENIED",
            reason="Invalid credentials", ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not _is_user_active(user):
        from backend.security.authorization import log_security_event
        log_security_event(
            db=db, user=user, action="LOGIN_BLOCKED_INACTIVE", resource_type="user",
            resource_id=user.id, result="DENIED", reason="Account is inactive",
            ip_address=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    from backend.security.authorization import log_security_event
    log_security_event(
        db=db, user=user, action="LOGIN_SUCCESS", resource_type="user",
        resource_id=user.id, details="User authenticated successfully",
        ip_address=request.client.host if request.client else None,
    )

    token = create_access_token(data={"sub": user.id, "role": user.role.value})
    logger.info(f"User logged in: {user.username}")
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Get current user profile."""
    return current_user
