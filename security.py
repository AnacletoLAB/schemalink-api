import jwt
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from fastapi import HTTPException, Depends, status, Cookie
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

# Secret key for JWT
SECRET_KEY = os.getenv("SECRET_KEY") # The secret key used to sign JWT tokens.
ALGORITHM = "HS256" # Hashing algorithm for JWT
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Cbcrypt algoritmo configuration per l'hashing delle password.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# OAuth2 for the token authentication system
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Model for the Token
class Token(BaseModel):
    access_token: str   # The JWT access token
    token_type: str     # The token type, typically "bearer"

# Generates a JWT token
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Decodes the token and retrieves the user
def get_current_user(access_token: str = Cookie(None)):
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token not found in cookies"
        )
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    return username
