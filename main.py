import yaml
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from linkml.generators.pydanticgen import PydanticGenerator
from linkml.linter.linter import Linter
from linkml.linter.formatters import JsonFormatter
from linkml_runtime.linkml_model.meta import SchemaDefinition
from openai import OpenAI, OpenAIError, APIError, RateLimitError
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Annotated
from database import SessionLocal, engine
from sqlalchemy.orm import Session
from sqlalchemy import text
from dotenv import load_dotenv
from datetime import date, datetime, timedelta, time
from security import hash_password, verify_password, create_access_token, get_current_user, Token
from gmail_service import send_email
from typing import List
import models
import os
import tempfile
import logging
import asyncio
from email_listener import listen_notifications
from typing import Optional
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from ontologies.ontologies import router as ontologies_router, refresh_all as refresh_ontologies, refresh_state, background_refresh
from ontologies.cache import is_empty
from expire_subscriptions_job import expire_subscriptions_job
import chromadb
import re
import openai
import json
import Levenshtein
from registry_utils import load_json_file, save_json_file, is_admin, save_custom_ontologies, load_and_modify_custom_ontologies, update_cache_with_custom_ontology
from ontologies.service import load_custom_ontologies
#from linkml_translator_aldyiar import translate_linkml_oo
from linkml_translator import translate_linkml_oo
from export_algorithm import convert_internal_representation_to_yaml, dump_yaml_schema

local_tz = pytz.timezone("Europe/Rome")

load_dotenv(override=True)

admin_email = os.getenv("ADMIN_EMAIL")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI(
    docs_url="/api/docs/", redoc_url="/api/redoc/", openapi_url="/api/openapi.json"
)

# models.Base.metadata.create_all(bind=engine) # Create tables in the database

# Defining Pydantic Models for Data Validation

class UserBase(BaseModel):
    username: str
    email: str
    password: str
    firstName: str
    lastName: str
    birthDate: date
    status: str

class UsernameRequest(BaseModel):
    username: str

class UpdateUserStatusRequest(BaseModel):
    username: str
    newStatus: str

class OperationRequest(BaseModel):
    username: str
    operation: str

class UserResponse(BaseModel):
    username: str
    email: str
    firstName: str
    lastName: str
    birthDate: date
    status: str

    class Config:
        orm_mode = True

class UserLogin(BaseModel):
    username: str
    password: str

class UserSubscribesPolicyBase(BaseModel):
    username: str
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    requestDate: datetime
    status: str
    policyName: str

    class Config:
        orm_mode = True

class UserSubscribesPolicyRequest(BaseModel):
    username: str
    policyName: str

class UserMadeOperationInput(BaseModel):
    username: str
    operationName: str

class UserUpdateRequest(BaseModel):
    username: str
    email: Optional[str] = Field(default=None)
    firstName: Optional[str] = Field(default=None)
    lastName: Optional[str] = Field(default=None)
    birthDate: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None)

class ContributeRequest(BaseModel):
    username: str
    diagramName: str
    graphJson: str

class EnumCreateRequest(BaseModel):
    name: str
    permissible_values: List[str]

class EnumUpdateRequest(BaseModel):
    permissible_values: List[str]

class RegexCreateRequest(BaseModel):
    name: str
    expression: str

class RegexUpdateRequest(BaseModel):
    expression: str

class CustomOntologyCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    namespace: str = ""
    annotator: str = ""
    properties: List[str] = []
    terms: List[str] = []

class CustomOntologyUpdateRequest(BaseModel):
    name: str
    description: str = ""
    namespace: str = ""
    annotator: str = ""
    properties: List[str] = []
    terms: List[str] = []

class LinkMLOOTranslateRequest(BaseModel):
    yaml_content: str = Field(..., description="Object-Oriented LinkML YAML schema content")
    return_visual: bool = Field(default=True, description="If True, return visual representation; if False, return internal representation")

class JSONExportRequest(BaseModel):
    graph_json: Dict[str, Any] = Field(..., description="Internal representation JSON graph with nodes, relationships, and metadata")


# Database Connection Function
def get_db ():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Mount ontologies router under /api
app.include_router(ontologies_router, prefix="/api")


# Register a User
@app.post("/api/auth/register/")
async def register_user(user: UserBase, db: db_dependency):
    existing_user = db.query(models.User).filter(models.User.username == user.username).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username already exists."
        )

    existing_email = db.query(models.User).filter(models.User.email == user.email).first()

    if existing_email:
        if existing_email.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email already exists and is pending approval."
            )
        elif existing_email.status == "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="email already exists."
            )
        elif existing_email.status == "blocked":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="email already exists and is blocked."
            )

    
    hashed_pw = hash_password(user.password)

    db_user = models.User(
        username=user.username,
        email=user.email,
        password=hashed_pw,
        firstName=user.firstName,
        lastName=user.lastName,
        birthDate=user.birthDate,
        status="pending"
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    subject = "New user awaiting approval"
    body = (
        f"A new user has just registered on SchemaLink and is awaiting approval:\n\n"
        f"Username: {user.username}\n"
        f"Email: {user.email}"
        f"\n\nSchemaLink Notification System"
    )

    logging.info(f"Sending email to notify admin of new registration: {user.email}")

    send_email(to_email=admin_email, subject=subject, message=body)
    
    return {
        "username": db_user.username,
        "email": db_user.email,
        "firstName": db_user.firstName,
        "lastName": db_user.lastName,
        "status": db_user.status
    }


# Login a User and return JWT Token
@app.post("/api/auth/login/")
async def login_user(user: UserLogin, db: db_dependency):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user account not found."
        )
    if not verify_password(user.password, db_user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect password."
        )
    if db_user.status=='pending':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user account not yet approved."
        )
    if db_user.status == "blocked":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user account is blocked."
        )
    if db_user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user account is disabled."
        )
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(data={"sub": db_user.username}, expires_delta=access_token_expires)

    response_data = {
        "message": "Login successful",
        "access_token": access_token,
        "user": {
            "username": db_user.username,
            "email": db_user.email,
            "firstName": db_user.firstName,
            "lastName": db_user.lastName,
            "birthDate": db_user.birthDate.isoformat() if db_user.birthDate else None,
            "status": db_user.status
        }
    }

    response = JSONResponse(content=response_data)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,  # Not accessible by JavaScript (prevents XSS)
        secure=False,  # ONLY in development, set to True in production
        samesite="Lax",  # Prevents CSRF, but allows use across subdomains
        max_age=1800,  # Expiration time (30 min)
    )

    return response   


# Logout a User
@app.post("/api/auth/logout/")
async def logout_user():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token")
    return response


# Delete user account
@app.post("/api/auth/delete-account/")
async def delete_account(db: db_dependency, current_user: str = Depends(get_current_user)):
    db_user = db.query(models.User).filter(models.User.username == current_user).first()
    
    db_user.status = "disabled"
    db.commit()
    db.refresh(db_user)

    subscriptions = db.query(models.UserSubscribesPolicy).filter(
        models.UserSubscribesPolicy.username == db_user.username,
        models.UserSubscribesPolicy.status.in_(["active", "pending"])
    ).all()

    for sub in subscriptions:
        if sub.status == "active":
            sub.status = "expired"
            sub.endDate = datetime.now(local_tz)
        elif sub.status == "pending":
            sub.status = "expired"

    db.commit()

    admin_subject = f"Account deletion notice: {db_user.username}"
    admin_body = (
        f"The following user has deleted his account from SchemaLink:\n\n"
        f"Username: {db_user.username}\n"
        f"Email: {db_user.email}\n\n"
        f"SchemaLink Notification System"
    )
    send_email(to_email=admin_email, subject=admin_subject, message=admin_body)

    return JSONResponse(content={"message": "Account successfully deleted."})

# Get all users
@app.post("/api/get-users/", response_model=List[UserResponse])
async def get_users(db: db_dependency):
    db_users = db.query(models.User).all()

    return db_users


# Update user status
@app.post("/api/update-status/")
async def update_user_status( status_update: UpdateUserStatusRequest, db: db_dependency):
    user = db.query(models.User).filter(models.User.username == status_update.username).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Business rule validation on the backend side
    valid_transitions = {
        "pending": ["active", "disabled"],
        "active": ["disabled", "blocked"],
        "blocked": ["active"]
    }

    current_status = user.status
    new_status = status_update.newStatus

    if current_status not in valid_transitions or new_status not in valid_transitions[current_status]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status change from {current_status} to {new_status}"
        )

    user.status = new_status
    db.commit()
    db.refresh(user)

    return {
        "message": f"Status of {user.username} updated from {current_status} to {new_status}",
        "user": {
            "username": user.username,
            "status": user.status
        }
    }


# Get all user subscriptions to policies
@app.post("/api/get-user-subscriptions/", response_model=List[UserSubscribesPolicyBase])
async def get_user_subscriptions(db: db_dependency):
    db_subscriptions = db.query(models.UserSubscribesPolicy).all()

    return db_subscriptions
    

# Update user policy status
@app.post("/api/update-subscription-status/")
async def update_subscription_status( status_subscription_update: UpdateUserStatusRequest, db: db_dependency):
    policySubscription = db.query(models.UserSubscribesPolicy).filter(
        models.UserSubscribesPolicy.username == status_subscription_update.username,
        models.UserSubscribesPolicy.status == "pending" 
    ).first()

    if not policySubscription:
        raise HTTPException(
            status_code=404,
            detail="Policy subscription not found"
        )

    # Business rule validation on the backend side
    valid_transitions = {
        "pending": ["active", "rejected"],
    }

    current_status = policySubscription.status
    new_status = status_subscription_update.newStatus

    if current_status not in valid_transitions or new_status not in valid_transitions[current_status]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status change from {current_status} to {new_status}"
        )

    policySubscription.status = new_status

    if new_status == "active":
        now = datetime.now(local_tz)

        existing_active = db.query(models.UserSubscribesPolicy).filter(
            models.UserSubscribesPolicy.username == policySubscription.username,
            models.UserSubscribesPolicy.status == "active",
            models.UserSubscribesPolicy.startDate <= now,
            models.UserSubscribesPolicy.endDate >= now
        ).first()

        residual_operations = 0

        if existing_active and policySubscription.policyName != "platinum":
            used_operations = db.query(models.UserMadeOperation).filter(
                models.UserMadeOperation.username == existing_active.username,
                models.UserMadeOperation.date >= existing_active.startDate,
                models.UserMadeOperation.date <= existing_active.endDate
            ).count()

            total_allowed = existing_active.numOperations or 0
            residual_operations = max(total_allowed - used_operations, 0)
        
        if existing_active:
            existing_active.status = "expired"
            existing_active.endDate = now

        policySubscription.startDate = now

        if policySubscription.policyName == "silver":
            duration_days = 3
            maxAccess = 50
        elif policySubscription.policyName == "gold":
            duration_days = 7
            maxAccess = 100
        elif policySubscription.policyName == "platinum":
            duration_days = 7
            maxAccess = None
        else:
            raise HTTPException(status_code=400, detail="Invalid policy name")
            
        if policySubscription.policyName != "platinum":
            policySubscription.numOperations = maxAccess + residual_operations
        else:
            policySubscription.numOperations = None
            
        policySubscription.endDate = now + timedelta(days=duration_days)

    db.commit()
    db.refresh(policySubscription)

    return {
        "message": f"Status of policy of {policySubscription.username} to {policySubscription.policyName} updated from {current_status} to {new_status}",
        "subscription": {
            "username": policySubscription.username,
            "policyName": policySubscription.policyName,
            "status": policySubscription.status,
            "startDate": policySubscription.startDate,
            "endDate": policySubscription.endDate
        }
    }


# User is authorized to perform operation
@app.post("/api/canPerformOperation/")
async def check_user_operation(request_data: OperationRequest, db: db_dependency):
    username = request_data.username
    operation = request_data.operation

    #print("Username received:", username)
    #print("Operation received:", operation)

    # Username null
    if not username:
        return JSONResponse(content={"allowed": False, "reason": "You must register to request intelligent operations."})
    
    # Admin user
    if username == "schemalink":
        return JSONResponse(content={"allowed": True})

    now = datetime.now(local_tz)

    # Active policy
    policy_subscription = db.execute(
        text ("""
        SELECT startDate, policyName
        FROM UserSubscribesPolicy
        WHERE username = :username
        AND startDate <= :now
        AND endDate >= :now
        AND status = 'active'
        ORDER BY startDate DESC
        LIMIT 1
        """),
        {"username": username, "now": now}
    ).fetchone()

    if not policy_subscription:
        return JSONResponse(content={"allowed": False, "reason": "No active subscription policy."})

    start_date = policy_subscription[0]
    policy_name = policy_subscription[1]

    if policy_name == "platinum":
        return JSONResponse(content={"allowed": True, "policy": policy_name})

    max_access = db.execute(
        text("""
            SELECT numOperations
            FROM UserSubscribesPolicy
            WHERE username = :username
            AND startDate <= :now
            AND endDate >= :now
            AND status = 'active'
        """),
        {"username": username, "now": now}
    ).scalar()

    # Operations performed by the user
    user_ops_count = db.execute(
        text("""SELECT COUNT(*)
        FROM UserMadeOperation
        WHERE username = :username
        AND date >= :start_date
        """),
        {"username": username, "start_date": start_date}
    ).scalar()

    if user_ops_count >= max_access:
        return JSONResponse(content={"allowed": False, "reason": "You reached the maximum number of intelligent requests for your policy."}) 

    return JSONResponse(content={"allowed": True, "policy": policy_name})


# User made operation
@app.post("/api/user-operation/")
async def log_user_operation(operation: UserMadeOperationInput, db: db_dependency):
    try:
        now = datetime.now(local_tz)

        db_operation = models.UserMadeOperation(
            username=operation.username,
            operationName=operation.operationName,
            date=now
        )

        db.add(db_operation)
        db.commit()
        db.refresh(db_operation)

        threshold_reached = False
        policy = None
        subscription = None

        if (operation.username != "schemalink"):

            subscription = db.query(models.UserSubscribesPolicy).filter(
                models.UserSubscribesPolicy.username == operation.username,
                models.UserSubscribesPolicy.status == 'active'
            ).order_by(models.UserSubscribesPolicy.startDate.desc()).first()

            if subscription:
                policy = db.query(models.Policy).filter_by(name=subscription.policyName).first()

                if policy:
                    op_count = db.query(models.UserMadeOperation).filter(
                        models.UserMadeOperation.username == operation.username,
                        models.UserMadeOperation.date >= subscription.startDate,
                        models.UserMadeOperation.date <= now
                    ).count()

                    threshold_reached = False

                    if (policy.name != "platinum"):
                        threshold = policy.threshold if policy.threshold is not None else 0
                        if op_count == (subscription.numOperations - threshold):
                            threshold_reached = True
                            user = db.query(models.User).filter_by(username=operation.username).first()
                            if user:
                                subject = f"You have {policy.threshold} operations remaining on your '{policy.name}' plan"
                                body = (
                                    f"Hi {user.username},\n\n"
                                    f"You have {policy.threshold} intelligent requests remaining"
                                    f"under your current '{policy.name}' subscription plan.\n\n"
                                    f"Once you reach the limit of {subscription.numOperations} intelligent requests, your subscription will expire "
                                    f"and you will no longer be able to use intelligent requests.\n\n"
                                    f"To continue uninterrupted, consider upgrading or renewing your plan.\n\n"
                                    f"Thank you for using SchemaLink!\n"
                                    f"\nBest regards,\n"
                                    f"The SchemaLink Team"
                                )
                                send_email(to_email=user.email, subject=subject, message=body)

                        if op_count >= subscription.numOperations:
                            subscription.status = 'expired'
                            subscription.endDate = now
                            db.commit()

        return {
            "message": "Operation logged successfully.",
            "thresholdReached": threshold_reached,
            "data": {
                "username": db_operation.username,
                "operationName": db_operation.operationName,
                "date": db_operation.date,
                "policyName": policy.name if policy else None,
                "policyThreshold": policy.threshold if policy else None,
                "policyMaxAccess": subscription.numOperations if subscription else None
            }
        }
    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# User subscribes to a policy
@app.post("/api/subscribe-policy/")
async def subscribe_policy( data: UserSubscribesPolicyRequest, db: db_dependency):
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(local_tz)

    pending_policy = db.execute(
        text("""
        SELECT policyName FROM UserSubscribesPolicy
        WHERE username = :username
        AND status = 'pending'
        """),
        {"username": data.username}
    ).fetchone()

    if pending_policy:
        raise HTTPException(
            status_code=400,
            detail="User already has a pending policy request."
        )

    active_policy = db.execute(
        text ("""
        SELECT policyName AS "policyName", requestDate AS "requestDate"
        FROM UserSubscribesPolicy
        WHERE username = :username
        AND startDate <= :now
        AND endDate >= :now
        AND status = 'active'
        """),
        {"username": data.username, "now": now}
    ).mappings().fetchone()

    current_policy = active_policy["policyName"].lower() if active_policy else None
    request_date = active_policy["requestDate"] if active_policy else None

    requested = data.policyName.lower()
    allowed_transitions = {
        None: ["trial", "silver", "gold", "platinum"],     # No policy
        "trial": ["silver", "gold", "platinum"],
        "silver": ["gold", "platinum"],
        "gold": ["platinum"],
        "platinum": []
    }

    if requested not in allowed_transitions[current_policy]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot subscribe to '{requested}' while having '{current_policy or 'no'}' policy active."
        )

    new_subscription = models.UserSubscribesPolicy(
        username=data.username,
        policyName=data.policyName,
        requestDate = now,
        startDate=None,
        endDate=None,
        status='pending'
    )

    db.add(new_subscription)
    db.commit()
    db.refresh(new_subscription)

    subject = " Policy Subscription Request Pending Approva"
    body = (
        f"The user **{data.username}** has requested to subscribe to the **{data.policyName}** policy."
        f"\n\nSchemaLink Notification System"
    )

    logging.info(f"Sending email to notify policy request")

    send_email(to_email=admin_email, subject=subject, message=body)

    return {
        "message": "Policy subscription request created successfully.",
        "data": {
            "username": new_subscription.username,
            "policyName": new_subscription.policyName,
            "requestDate": new_subscription.requestDate
        }
    }


# Get user subscription details
@app.post("/api/get-user-subscription-details/")
async def get_user_subscription_details(request: UsernameRequest, db: db_dependency):
    username = request.username 
    
    user = db.query(models.User).filter(models.User.username == username).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    subscription = db.query(models.UserSubscribesPolicy).filter(
        models.UserSubscribesPolicy.username == username,
        models.UserSubscribesPolicy.status == 'active'
    ).order_by(models.UserSubscribesPolicy.requestDate.desc()).first()

    if not subscription:
        return {
            "hasSubscription": False
        }

    policy = db.query(models.Policy).filter(models.Policy.name == subscription.policyName).first()

    operations_done = db.query(models.UserMadeOperation).filter(
        models.UserMadeOperation.username == username,
        models.UserMadeOperation.date >= subscription.startDate,
        models.UserMadeOperation.date <= subscription.endDate
    ).count()

    now = datetime.now(local_tz)
    subscription_end = subscription.endDate.astimezone(local_tz)
    delta = subscription_end - now
    hours_remaining = delta.seconds // 3600 + delta.days * 24
    minutes_remaining = (delta.seconds % 3600) // 60

    remaining_time_str = f"{int(hours_remaining)}:{int(minutes_remaining):02d}"

    return {
        "hasSubscription": True,
        "policyName": policy.name,
        "operationsDone": operations_done,
        "maxAccess": subscription.numOperations,
        "hoursRemaining": remaining_time_str,
    }


# Get user subscription active or pending
@app.post("/api/get-user-subscription/")
async def get_user_subscription(request: UsernameRequest, db: db_dependency):
    username = request.username 
    
    user = db.query(models.User).filter(models.User.username == username).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    
    active_sub = db.query(models.UserSubscribesPolicy).filter(
        models.UserSubscribesPolicy.username == username,
        models.UserSubscribesPolicy.status == "active"
    ).order_by(models.UserSubscribesPolicy.requestDate.desc()).first()

    pending_sub = db.query(models.UserSubscribesPolicy).filter(
        models.UserSubscribesPolicy.username == username,
        models.UserSubscribesPolicy.status == "pending"
    ).order_by(models.UserSubscribesPolicy.requestDate.desc()).first()
    
    return {
        "activePolicyName": active_sub.policyName if active_sub else None,
        "pendingPolicyName": pending_sub.policyName if pending_sub else None
    }


# Update a user
@app.patch("/api/update-user/")
async def update_user(user_update: UserUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_update.username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user_update.firstName:
        user.firstName = user_update.firstName
    if user_update.lastName:
        user.lastName = user_update.lastName
    if user_update.email:
        existing_email = db.query(models.User).filter(models.User.email == user_update.email).first()
        if existing_email:
            if existing_email.status == "pending":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="email already exists and is pending approval."
                )
            elif existing_email.status == "active":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="email already exists."
                )
            elif existing_email.status == "blocked":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="email already exists and is blocked."
                )
        user.email = user_update.email
    if user_update.birthDate:
        try:
            user.birthDate = datetime.strptime(user_update.birthDate, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid birthDate format. Use YYYY-MM-DD."
            )
    if user_update.password:
        user.password = hash_password(user_update.password)
    db.commit()
    db.refresh(user)
    return {
        "username": user.username,
        "email": user.email,
        "firstName": user.firstName,
        "lastName": user.lastName,
        "birthDate": user.birthDate.isoformat() if user.birthDate else None,
        "status": user.status
    }


# Contribute on AI store
@app.post("/api/contribute/")
async def contribute_on_ai_store(request: ContributeRequest, db: db_dependency):
    username = request.username
    user = db.query(models.User).filter(models.User.username == username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode='w', encoding='utf-8') as temp_file:
        temp_file.write(request.graphJson)
        temp_file_path = temp_file.name

    subject = "New contribution received"
    body =  (
        f"The gold/platinum user {user.username} ({user.email}) "
        f"proposes the schema '{request.diagramName}' to be included into the AI store. "
        f"See attached file for the SchemaLink JSON internal representation."
        f"\n\nSchemaLink Notification System"
    )
    
    send_email(to_email=admin_email, subject=subject, message=body, attachment=temp_file_path)

    subject = "Thanks for contributing to the AI store"
    body = (
        f"Hi {user.username},\n\n"
        f"Thank you for contributing to the AI store! "
        f"Your schema '{request.diagramName}' has been received and is under review.\n"
        f"\nBest regards,\n"
        f"The SchemaLink Team"
    )
    to_email = user.email

    send_email(to_email=to_email, subject=subject, message=body)

    os.remove(temp_file_path)

    return JSONResponse(content={"message": "Contribution received successfully"}, status_code=200)


# All subscription
@app.post("/api/dashboard-subscriptions/")
async def dashboard_subscriptions(db: db_dependency):
    try:
        result = db.execute (
            text ("""
                SELECT policyName, COUNT(*) as count
                FROM UserSubscribesPolicy
                WHERE status = 'active'
                GROUP BY policyName
            """)
        )

        data = result.fetchall()
        response = {policy: count for policy, count in data}

        return response

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# Most active users
@app.get("/api/most-active-users/")
async def most_active_users(db: db_dependency):
    try:
        query = text("""
            SELECT username, COUNT(*) AS operations_count
            FROM UserMadeOperation
            GROUP BY username
            ORDER BY operations_count DESC
            LIMIT 10
        """)

        result = db.execute(query)
        data = result.fetchall()

        response = [{"username": row.username, "operations_count": row.operations_count} for row in data]
        return response

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# Operations by policy category
@app.get("/api/operations-by-policy-category")
async def operations_by_policy_category(db=Depends(get_db)):
    try:
        query = text("""
            SELECT
                usp.policyName AS policy,
                c.name AS category,
                COUNT(*) AS count
            FROM UserSubscribesPolicy usp
            JOIN UserMadeOperation umo ON umo.username = usp.username
            JOIN OperationIsCategory oic ON oic.operationName = umo.operationName
            JOIN Category c ON c.name = oic.categoryName
            GROUP BY usp.policyName, c.name
            ORDER BY usp.policyName, c.name
        """)

        result = db.execute(query)
        rows = result.fetchall()

        data = {}
        for row in rows:
            policy = row.policy
            category = row.category
            count = row.count

            if policy not in data:
                data[policy] = {}
            data[policy][category] = count

        return data

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# User growth by policy
@app.get("/api/user-growth-by-policy")
async def user_growth_by_policy(db=Depends(get_db)):
    try:
        query = text("""
            SELECT 
                DATE_TRUNC('month', startDate) AS month,
                policyName,
                COUNT(DISTINCT username) AS active_users
            FROM UserSubscribesPolicy
            WHERE status = 'active'
            GROUP BY month, policyName
            ORDER BY month, policyName
        """)

        result = db.execute(query)
        rows = result.fetchall()

        data = {}
        for row in rows:
            month_str = row.month.strftime('%Y-%m')
            policy = row.policyname
            active_users = row.active_users

            if month_str not in data:
                data[month_str] = {"month": month_str, "trial": 0, "silver": 0, "gold": 0, "platinum": 0}
            data[month_str][policy] = active_users

        sorted_data = [data[month] for month in sorted(data.keys())]

        return sorted_data

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


# Average latency by policy
@app.get("/api/average-latency-by-policy")
async def average_latency_by_policy(db=Depends(get_db)):
    try:
        query = text("""
            WITH UserRequests AS (
              SELECT
                umo.username,
                umo.date,
                usp.policyName
              FROM UserMadeOperation umo
              JOIN UserSubscribesPolicy usp ON umo.username = usp.username
                AND umo.date >= usp.startDate
                AND (usp.endDate IS NULL OR umo.date <= usp.endDate)
                AND usp.status = 'active'
            ),
            RankedRequests AS (
              SELECT
                username,
                policyName,
                date,
                LEAD(date) OVER (PARTITION BY username ORDER BY date) AS next_date
              FROM UserRequests
            ),
            Differences AS (
              SELECT
                policyName,
                EXTRACT(EPOCH FROM (next_date - date)) AS latency_seconds
              FROM RankedRequests
              WHERE next_date IS NOT NULL
            )
            SELECT
              policyName,
              AVG(latency_seconds) AS avg_latency_seconds
            FROM Differences
            GROUP BY policyName
            ORDER BY policyName
        """)

        result = db.execute(query)
        rows = result.fetchall()

        data = { "trial": 0, "silver": 0, "gold": 0, "platinum": 0 }
        for row in rows:
            policy = row.policyname
            avg_latency = float(row.avg_latency_seconds)
            data[policy] = avg_latency

        return data

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"message": "Internal server error"})


scheduler = BackgroundScheduler()


def nightly_refresh_job():
    """Nightly ontology refresh job that runs at midnight."""
    import logging
    logger = logging.getLogger("uvicorn.nightly")
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        async def check_and_start():
            if not await refresh_state.is_in_progress():
                logger.info("🌙 Nightly ontologies refresh triggered")
                async with refresh_state._lock:
                    refresh_state.in_progress = True
                    refresh_state.last_started = datetime.now()
                await background_refresh()
            else:
                logger.warning("⚠️ Nightly refresh skipped - already in progress")
        
        asyncio.run_coroutine_threadsafe(check_and_start(), loop)
    else:
        logger.info("🌙 Nightly ontologies refresh triggered (sync mode)")
        asyncio.run(refresh_ontologies(force=False))


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(listen_notifications())
    
    cache_empty = await is_empty()
    
    if cache_empty:
        print("🆕 First start detected - populating ontologies cache (this will take 1-2 minutes)")
        try:
            await refresh_ontologies(blocking=True)
        except Exception as e:
            print(f"❌ Failed to populate cache on first start: {e}")
    else:
        print("✅ Ontologies cache loaded from disk - API ready")
        if not await refresh_state.is_in_progress():
            print("   ↳ Starting background refresh to update cache...")
            async with refresh_state._lock:
                refresh_state.in_progress = True
                refresh_state.last_started = datetime.now()
            asyncio.create_task(background_refresh())

    scheduler.add_job(expire_subscriptions_job, CronTrigger(minute='*/5'))
    scheduler.add_job(nightly_refresh_job, CronTrigger(hour=0, minute=0))
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()


@app.post(
    "/api/gen-pydantic/",
    openapi_extra={
        "requestBody": {
            "content": {"application/x-yaml"},
            "required": True,
        },
    },
)
async def gen_pydantic(request: Request):
    raw_body = await request.body()
    try:
        data = yaml.safe_load(raw_body)
    except yaml.YAMLError:
        raise HTTPException(status_code=422, detail="Invalid YAML")

    try:
        schema = SchemaDefinition(**data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    generator = PydanticGenerator(schema=schema)
    pydantic_model = generator.serialize()

    with open("pydantic_model.py", "w") as f:
        f.write(pydantic_model)

    return FileResponse(
        "pydantic_model.py",
        media_type="application/octet-stream",
        filename="pydantic_model.py",
    )


@app.post(
    "/api/validate-linkml/",
    openapi_extra={
        "requestBody": {
            "content": {"application/x-yaml"},
            "required": True,
        },
    },
)

async def validate_linkml(request: Request):
    raw_body = await request.body()
    try:
        data = yaml.safe_load(raw_body)
    except yaml.YAMLError:
        raise HTTPException(status_code=422, detail="Invalid YAML")

    '''
    with open("schema.yaml", "w") as f:
        f.write(yaml.dump(data))

    problems = Linter.validate_schema("schema.yaml")

    with open("report.json", "w") as f:
        formatter = JsonFormatter(f)
        formatter.start_report()
        for problem in problems:
            formatter.handle_problem(problem)
        formatter.end_report()

        return FileResponse(
            "report.json", media_type="application/json", filename="report.json"
        )
    '''

def get_embedding(text):
    response = openai.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


# it extracts and returns all the informations related to the column named as the value of "column" from the class named as the value of "class_name" from the received schema. The block extracted includes all the "column" releated informations (e.g. if "column" value is "description", the returned block will contain the string of the description of the class, if the class exists)
def extract_class_block_from_schema_UPDATED(schema, class_name, column):
    if class_name is None:
        block = schema
    else:
        pattern = r"(^\s*{}:.*?)(?=\n^\s*[A-Z][a-zA-Z0-9_]*:|\Z)".format(re.escape(class_name))
        match = re.search(pattern, schema, flags=re.DOTALL | re.MULTILINE)
        if match:
            block = match.group(1).lstrip('\n').rstrip('\n')
        else:
            return None     # if the class named as the value of "class_name" does not exist, returns None
    
    if column is None:
        return block
    else:
        pattern = rf'^([ \t]*){column}:[ \t]*(.*?)(?=\n^\1\S.*?:|\Z|\n^\1\S+:\s*$)'
        match_column = re.search(pattern, block, flags=re.DOTALL | re.MULTILINE)
        if match_column:
            return match_column.group(2).lstrip('\n').rstrip('\n')        # group(2) is returned (so group(0) is NOT) because group(0) includes also the column name, which is not required
        else:
            return None     # if the column named as the value of "column" does not exist, returns None


# it replaces the informations of the column named as the value of "column" from the received schema with the value of "new_column_block" 
def replace_class_in_schema(schema, class_name, column, new_column_block):
    if class_name is None:
        class_block = schema
    else:
        class_pattern = rf"(^\s*{re.escape(class_name)}:\n(.*?))(?=\n^\s*[A-Z][a-zA-Z0-9_]*:|\Z)"
        class_match = re.search(class_pattern, schema, flags=re.DOTALL | re.MULTILINE)
        if not class_match:
            return schema
        class_block = class_match.group(1)

    if column == None:
        updated_schema = schema.replace(class_block, new_column_block)
        return updated_schema
    
    pattern = rf'''
        ^(?P<indent>[ \t]*){re.escape(column)}:[ \t]*(?P<inline>[^\n]*)    # inline after column:
        (?P<block>(?:\n(?!\s*$)(?:(?P=indent)[ \t]+.+))+)?                 # indented block (optional)
    '''
    match = re.search(pattern, class_block, re.MULTILINE | re.VERBOSE)
    if not match:
        return schema
    
    if match.group(2) and match.group(2) != ">-":
        to_replace = match.group(2)
    elif match.group(3):
        to_replace = match.group(3)
        to_replace = re.sub(r'^>-\n?', '', to_replace)
        to_replace = re.sub(r'^\n+', '', to_replace)        # this removes possible empty lines at the start
    
    updated_class_block = class_block.replace(to_replace, new_column_block)
    
    updated_schema = schema.replace(class_block, updated_class_block)
    
    return updated_schema


@app.post("/api/openai/generate/")
async def generate(request: Request):

    import yaml as pyyaml # Don't know why, but if I don't do this, it considers the "yaml" as a variable here...

    raw_body = await request.body()
    body = json.loads(raw_body)

    received_prompt_text = body.get("prompt")
    operation = body.get("operation")

    selected_classes = body.get("classes_names")
    classes = [item["caption"] for item in selected_classes if "caption" in item]

    associations = body.get("associations_names")

    current_schema = body.get("full_schema")

    use_response_format_description = False
    use_response_format_ontology_subschema = False
    use_response_format_examples_subschema = False
    use_response_format_names_subschema = False
    match operation:
        case "AddClassAssociatedToClass": # return new classes+relationships --> yaml code
            collection_name = "only_classes"
            instructions = "You are an expert in LinkML schemas. Output only valid YAML LinkML, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "AnnotateClassOntology" | "AnnotateClassExample":
            # return a list of ontologies separated by commas --> list
            # return a list of examples separated by commas --> list
            collection_name = "only_classes"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list whose elements are separated by commas, no explanations. Use CONTEXT to improve the output but not include it in the output."
        case "AnnotateClassDescription": # return a description --> sentence
            collection_name = "only_classes"
            instructions = "You are an expert in LinkML schemas. Output only the description, no explanations. Use CONTEXT to improve the output but not include it in the output."
        case "FixClassName": # return a class name --> word
            collection_name = "only_classes"
            instructions = "You are an expert in LinkML schemas. Output only a name, just one word, no explanations. Use CONTEXT to improve the output but not include it in the output."
        case "AddAttributesToRelationship" | "AddClassesSimilarToEntities" | "FixClassAttributesName" | "FixClassAttributesType" | "AddAssociationsSimilarToEntities" : 
            # return updated relationship --> yaml code
            # return new classes --> yaml code
            # return updated class --> yaml code
            # return updated class --> yaml code
            # return new relationship --> yaml code
            collection_name = "classes_and_relationships"
            instructions = "You are an expert in LinkML schemas. Output only valid YAML LinkML, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "FixClassDescription" | "AnnotateRelationshipDescription" | "FixRelationshipDescription":
            # return description --> sentence
            # return description --> sentence
            collection_name = "classes_and_relationships"
            instructions = "You are an expert in LinkML schemas. Output only the description, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "FixRelationshipName":
            # return a relationship name --> sentence
            collection_name = "classes_and_relationships"
            instructions = "You are an expert in LinkML schemas. Output only a single word or few words for renaming a predicate, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "AnnotateRelationshipOntology" | "AnnotateRelationshipExample":
            # return a list of ontologies separated by commas --> list
            # return a list of examples separated by commas --> list
            collection_name = "classes_and_relationships"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list whose elements are separated by commas, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "AnnotateSubschemaDescription":
            # return list of pair className/relationshipName <-> description --> JSON schema
            collection_name = "classes_and_relationships"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list of updates. Use CONTEXT to improve the output."   
            use_response_format_description = True
        case "AddClassSimilarToClass" | "ReifyClass" | "FixRelationshipCardinality" | "AddAttributesToClass" | "AddParentClass" | "AddChildClass" | "FixRelationshipAttributesName" |  "FixRelationshipAttributesType" | "FixSubschemaCardinalities" | "FixClassAttributesDescription" | "AddAttributesDescription" | "AddRelationshipAttributesDescription":
            # return new class --> yaml code
            # return new class+relationship+updated oldclass --> yaml code
            # return updated relationship --> yaml code
            # return updated class --> yaml code
            # return updated class --> yaml code
            # return updated class --> yaml code
            # return updated relationship --> yaml code
            # return updated relationship --> yaml code
            # return updated cardinalities --> yaml code
            # return updated attributes description --> sentence
            # return updated attributes description --> sentence
            # return updated attributes description --> sentence
            collection_name = "full_schemas"
            if operation in ['FixSubschemaCardinalities']: # Refactor this case
                instructions = "You are an expert in LinkML schemas. Output only valid YAML LinkML, no explanations. Use CONTEXT to improve the output but not include it in the output. IMPORTANT RULE: Note that minimum_cardinality MUST be strictly less than maximum_cardinality i.e. minimum_cardinality and maximum_cardinality CANNOT be equal e.g. minimum_cardinality=1 and maximum_cardinality=1 is NOT valid, instead minimum_cardinality=0 and maximum_cardinality=1 is valid."
            else:
                instructions = "You are an expert in LinkML schemas. Output only valid YAML LinkML, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "FixClassExample" | "FixClassOntology" | "FixRelationshipOntology" | "FixRelationshipExample":
            # return list of examples --> list
            # return list of ontologies --> list
            # return list of ontologies --> list
            # return list of examples --> list
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list whose elements are separated by commas, no explanations. Use CONTEXT to improve the output but not include it in the output."   
        case "AnnotateSubschemaOntology" | "FixSubschemaOntology":
            # return a list of ontologies separated by commas --> JSON
            # return a list of ontologies separated by commas --> JSON
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list of ontologies. Use CONTEXT to improve the output."   
            use_response_format_ontology_subschema = True
        case "FixClassesAndAssociationsDescription":
            # return list of pair className/relationshipName <-> description --> JSON schema
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list of descriptions. Use CONTEXT to improve the output."   
            use_response_format_description = True
        case "FixClassesAndAssociationsName":
            # return updated class and relationship --> JSON
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only a list of classes and predicate names. Use CONTEXT to improve the output."   
            use_response_format_names_subschema = True
        case "AnnotateSubschemaExample" | "FixSubschemaExample":
            # return list of examples --> JSON
            # return list of examples --> JSON
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas and biomedical ontologies. Output only lists of examples. Use CONTEXT to improve the output."   
            use_response_format_examples_subschema = True
        case _:
            operation = "Generate"
            # return yaml code for an entire schema
            collection_name = "full_schemas"
            instructions = "You are an expert in LinkML schemas. Output only valid YAML LinkML schemas, no explanations. Use CONTEXT to improve the output but not include it in the output. Answer as fast as possible."

    client = await chromadb.AsyncHttpClient(host='localhost', port=8001)

    try:
        collection = await client.get_collection(collection_name)
    except Exception as e:
        return Response(content="Error retrieving collection", status_code=500)

    if operation != "Generate":
        try:
            # Load the current schema as YAML
            current_schema_yaml = pyyaml.safe_load(current_schema)

            # Extract the initial part of the schema
            intro_schema_keys = ['id', 'title', 'description']  
            intro_schema_parts = {k: current_schema_yaml.get(k) for k in intro_schema_keys if k in current_schema_yaml}
    
            classes_section = current_schema_yaml.get('classes', {})     # this extracts only classes names from classes_section
            original_schema_classes_names = list(classes_section.keys())
    
        except pyyaml.YAMLError as e:
            return JSONResponse(status_code=500, content={"error": "YAML parsing error", "details": str(e)})

    query_embedding = get_embedding(received_prompt_text)

    results = await collection.query(query_embeddings=[query_embedding], n_results=10, include=["metadatas", "distances", "documents"])

    similar_schemas = results["ids"][0]
    
    if similar_schemas:
        received_prompt_text += "\nCONTEXT:\n"
        if collection_name == "full_schemas":
            for meta in results["metadatas"][0][:10]:
                received_prompt_text += f"\n{meta.get('content')}\n\n"
        else:
            for i in range(10):
                received_prompt_text += results['documents'][0][i] + "\n\n"

    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

    try:

        params = {
            "model": "gpt-4o-mini",
            "temperature": 0,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": received_prompt_text}
            ]
        }
        if use_response_format_description:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pairs_list",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pairs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "class_or_relationship_name": {"type": "string"},
                                        "description": {"type": "string"}
                                    },
                                    "required": ["class_or_relationship_name", "description"]
                                }
                            }
                        },
                        "required": ["pairs"]
                    }
                }
            }
        if use_response_format_ontology_subschema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pairs_list",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pairs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "class_or_relationship_name": {"type": "string"},
                                        "ontologies": {"type": "string"}
                                    },
                                    "required": ["class_or_relationship_name", "ontologies"]
                                }
                            }
                        },
                        "required": ["pairs"]
                    }
                }
            }
        if use_response_format_names_subschema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pairs_list",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pairs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "class_or_predicate_old_name": {"type": "string"},
                                        "class_or_predicate_new_name": {"type": "string"}
                                    },
                                    "required": ["class_or_predicate_old_name", "class_or_predicate_new_name"]
                                }
                            }
                        },
                        "required": ["pairs"]
                    }
                }
            }
        if use_response_format_examples_subschema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pairs_list",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pairs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "class_or_relationship_name": {
                                            "type": "string",
                                            "description": "Only the class or relationship name, without examples"
                                        },
                                        "examples": {
                                            "type": "string",
                                            "description": "One or more usage examples, must not repeat the class_or_relationship_name"
                                        }
                                    },
                                    "required": ["class_or_relationship_name", "examples"]
                                }
                            }
                        },
                        "required": ["pairs"]
                    }
                }
            }
        response = openai_client.chat.completions.create(**params)

        #print("Prompt:\n", prompt)
        new_schema_yaml = response.choices[0].message.content

        new_schema_yaml = re.sub(r"^```yaml\s*", "", new_schema_yaml).split("\nCONTEXT")[0] # it removes the ```yaml at the beginning of the output, if present, and anything that is after the word "\nCONTEXT" (included)
        new_schema_yaml = new_schema_yaml.strip('`').strip()
        new_schema_yaml = new_schema_yaml.replace("mixins: {}", "mixins: []")   # it replaces "mixins: {}" with "mixins: []" because the first one is not valid in LinkML
        new_schema_yaml = re.sub(r'\n\s*\n$', '\n', new_schema_yaml)        # it removes possible empty lines at the end
        new_schema_yaml = re.sub(
            r'prompt\.examples:\s*\'\'', 
            'prompt.examples: |\n      # no examples provided', 
            new_schema_yaml
        )
        if operation == "Generate":
            return Response(content=new_schema_yaml)
    except RateLimitError as e:
        subject = "SchemaLink Error: OpenAI rate or fund limit exceeded"
        body = (
            f"An OpenAI request failed due to a rate or funding limit being exceeded.\n\n"
            f"Details: {str(e)}\n\nSchemaLink Notification System"
        )
        send_email(to_email=admin_email, subject=subject, message=body)

        return JSONResponse(status_code=429, content={"error": "Quota exceeded or rate limited", "details": str(e)})

    except APIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI API error", "details": str(e)})

    except OpenAIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI error", "details": str(e)})
    
    try:
        match operation:
            case "AddClassSimilarToClass" | "AddClassesSimilarToEntities":
                # Parse the new schema YAML
                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                # Ensure 'classes' section exists
                if new_schema_data.get('classes', {}) == {}:
                    new_schema_classes = new_schema_data # in this case, the entire schema is only classes
                else: 
                    new_schema_classes = new_schema_data.get('classes', {}) 
                new_schema_classes_names = list(new_schema_classes.keys())

                # Identify the truly new classes
                new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

                updated_final_schema_data = pyyaml.safe_load(current_schema)
                if 'classes' not in updated_final_schema_data:
                    updated_final_schema_data['classes'] = {}

                # Add new classes if they are not Triple or RelationshipType
                for class_name in new_classes:
                    class_block = new_schema_classes[class_name]
                    is_a_value = class_block.get('is_a')
                    if is_a_value not in ("Triple", "RelationshipType", "CompoundExpression"):
                        updated_final_schema_data['classes'][class_name] = class_block

                # Convert back to YAML string
                updated_final_schema = pyyaml.dump(updated_final_schema_data, sort_keys=False)

            case "AddClassAssociatedToClass":
                # Parse the new schema YAML
                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                # Ensure 'classes' section exists
                if new_schema_data.get('classes', {}) == {}:
                    new_schema_classes = new_schema_data  # in this case, the entire schema is only classes
                else:
                    new_schema_classes = new_schema_data.get('classes', {}) 
                new_schema_classes_names = list(new_schema_classes.keys())

                # Identify the truly new classes
                new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

                # Start from current schema
                updated_final_schema_data = pyyaml.safe_load(current_schema)
                if 'classes' not in updated_final_schema_data:
                    updated_final_schema_data['classes'] = {}

                # Add each new class
                for name in new_classes:
                    class_block_dict = new_schema_classes[name]
                    updated_final_schema_data['classes'][name] = class_block_dict

                # Convert back to YAML string
                updated_final_schema = pyyaml.dump(updated_final_schema_data, sort_keys=False)
            
            # PROBLEMA: errore nell'istruzione new_schema_data = pyyaml.safe_load(new_schema_yaml)
            # L’alternativa é farsi ritornare solamente le classi padri e aggiungere il nome della classe padre nell’is_a della figlia se una sola
            # Ed aggiungere eventuali altre nel mixins se più di una

            # Esempio 

            # Test:
            #     is_a: Test2
            #     mixins:
            #     - Test3
            case "AddParentClass":
                # Parse the new schema YAML
                #print("\nNew schema YAML:", new_schema_yaml)
                try:
                    new_schema_data = pyyaml.safe_load(new_schema_yaml)
                    #print("\nNew schema data:", new_schema_data)
                except Exception as e:
                    #print("Error loading YAML:", str(e))
                    return

                # new_schema_data = pyyaml.safe_load(new_schema_yaml)
                # print("\nNew schema data:", new_schema_data)

                # Ensure 'classes' section exists
                if new_schema_data.get('classes', {}) == {}:
                    new_schema_classes = new_schema_data  # in this case, the entire schema is only classes
                else:
                    new_schema_classes = new_schema_data.get('classes', {}) 
                #print("\nNew schema classes:", new_schema_classes)
                # new_schema_classes_names = list(new_schema_classes.keys())

                # List of class names in the new schema
                new_schema_classes_names = list(new_schema_classes.keys())

                # Child class to update
                child_class = classes[0]

                # Get the new parent class ('is_a') from the new schema
                new_is_a_value = new_schema_classes.get(child_class, {}).get("is_a")

                # Identify truly new classes compared to the original schema
                new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)
                #print("New classes:", new_classes)

                # Start from current schema
                updated_final_schema_data = pyyaml.safe_load(current_schema)

                # Ensure child class exists in current schema
                if child_class not in updated_final_schema_data['classes']:
                    updated_final_schema_data['classes'][child_class] = {}

                # Update the 'is_a' of the child class and add the parent class if needed
                for parent_name in new_classes:
                    # print("\nparent_name =", parent_name)
                    if parent_name != "NamedEntity" and parent_name == new_is_a_value:
                        # Set the child class parent
                        updated_final_schema_data['classes'][child_class]['is_a'] = parent_name
                        #print("Set", child_class, "'is_a' to", parent_name)
                        # Add parent class to schema if missing
                        if parent_name not in updated_final_schema_data['classes']:
                            updated_final_schema_data['classes'][parent_name] = new_schema_classes[parent_name]

                        break  # Apply only the first matching parent

                # Convert the updated schema back to YAML
                updated_final_schema = pyyaml.dump(updated_final_schema_data, sort_keys=False)
                #print("Updated final schema:\n", updated_final_schema)

            case "AddChildClass":
                # Parse the new schema YAML
                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                # Ensure 'classes' section exists
                if 'classes' in new_schema_data and isinstance(new_schema_data['classes'], dict):
                    new_schema_classes = new_schema_data['classes']
                else:
                    new_schema_classes = new_schema_data

                # List of class names in the new schema
                new_schema_classes_names = list(new_schema_classes.keys())

                # Parent class to update
                parent_class = classes[0]

                # Identify truly new classes compared to the original schema
                new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

                # Start from current schema
                updated_final_schema_data = pyyaml.safe_load(current_schema)

                # Iterate through the new classes to find children of the target parent class
                for child_name in new_classes:
                    class_block = new_schema_classes.get(child_name, {})
                    class_block_is_a_value = class_block.get("is_a")

                    if class_block_is_a_value == parent_class:
                        # Add the new child class under the parent
                        updated_final_schema_data['classes'][child_name] = class_block
                        break  # Add only the first matching child

                # Convert the updated schema back to YAML
                updated_final_schema = pyyaml.dump(updated_final_schema_data, sort_keys=False)    

            case "AddAttributesToClass":
                # Parse current and new schema
                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                # Ensure 'classes' section exists
                if new_schema_data.get("classes", {}) == {}:
                    new_classes_data = new_schema_data 
                else:
                    new_classes_data = new_schema_data.get("classes", {})

                # Class target
                target_class = classes[0]

                old_class_block = current_schema_yaml.get("classes", {}).get(target_class, {})
                old_attributes = old_class_block.get("attributes", {})

                new_class_block = new_classes_data.get(target_class, {})
                new_attributes = new_class_block.get("attributes", {})

                merged_attributes = old_attributes.copy()
                merged_attributes.update(new_attributes)

                # Aggiorna la classe con la fusione
                merged_class_block = old_class_block.copy()
                merged_class_block.update(new_class_block)
                merged_class_block["attributes"] = merged_attributes

                current_schema_yaml["classes"][target_class] = merged_class_block

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AddAttributesDescription":
                #print(new_schema_yaml)
                # Load new schema classes
                new_schema_data = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data.get("classes", {}) == {}:
                    new_classes_data = new_schema_data
                else:
                    new_classes_data = new_schema_data.get("classes", {})

                # Target class
                target_class = classes[0]

                # Old and new class blocks
                old_class_block = current_schema_yaml.get("classes", {}).get(target_class, {}) or {}
                old_attributes = old_class_block.get("attributes", {}) or {}

                new_class_block = new_classes_data.get(target_class, {}) or {}
                new_attributes = new_class_block.get("attributes", {}) or {}

                merged_attributes = {}
                all_attr_names = set(old_attributes.keys()) | set(new_attributes.keys())

                for attr_name in sorted(all_attr_names):
                    old_attr = old_attributes.get(attr_name, {}) or {}
                    new_attr = new_attributes.get(attr_name, {}) or {}

                    merged_attr = old_attr.copy()

                    # Merge non-description fields
                    for k, v in new_attr.items():
                        if k != "description":
                            merged_attr[k] = v

                    # Merge descriptions with similarity check
                    old_desc = old_attr.get("description").strip()
                    new_desc = new_attr.get("description").strip()

                    if new_desc:
                        if not old_desc:
                            merged_attr["description"] = new_desc
                        else:
                            sim = Levenshtein.ratio(old_desc, new_desc)
                            #print(
                            #    f"Comparing descriptions for attribute '{attr_name}':\n"
                            #    f"Old: {old_desc}\nNew: {new_desc}\nSimilarity: {sim}"
                            #)
                            if sim <= 0.75:
                                # Remove trailing punctuation from old_desc
                                old_trim = old_desc.rstrip(".,;:!?")
                                # Remove any leading punctuation or spaces from new_desc
                                new_trim = new_desc.lstrip(" ,.;:!?")
                                # Avoid duplicating the common initial part (ignoring punctuation differences)
                                if new_trim.lower().startswith(old_trim.lower()):
                                    combined = new_trim
                                else:
                                    # Use a comma as connector if old_desc ended with punctuation, otherwise use a space
                                    connector = ", " if old_desc and old_desc[-1] in ".,;:!?" else " "
                                    combined = (old_trim + connector + new_trim).strip()
                                merged_attr["description"] = combined
                            else:
                                merged_attr["description"] = old_desc
                    else:
                        if old_desc:
                            merged_attr["description"] = old_desc

                    merged_attributes[attr_name] = merged_attr

                # Merge class-level data
                merged_class_block = old_class_block.copy()
                merged_class_block.update(new_class_block)
                merged_class_block["attributes"] = merged_attributes

                # Update schema
                if "classes" not in current_schema_yaml or current_schema_yaml["classes"] is None:
                    current_schema_yaml["classes"] = {}
                current_schema_yaml["classes"][target_class] = merged_class_block

                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AnnotateClassDescription":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                # Ensure 'classes' sections
                old_classes = current_schema_data.get("classes", {})
                # Class to update
                target_class = classes[0]
                # Get old class description
                old_class_description = old_classes.get(target_class, {}).get("description", "").strip()

                # Parse new description (strip to remove leading/trailing whitespace/newlines)
                new_class_description = new_schema_yaml.strip()

                # Compute similarity with Levenshtein
                if new_class_description:  # update only if new is non-empty
                    similarity = Levenshtein.ratio(old_class_description, new_class_description)
                    if similarity <= 0.2:  # overwrite if different enough     
                            current_schema_data["classes"][target_class]["description"] = new_class_description

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "AnnotateClassOntology":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                old_classes = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old values
                old_class_data = old_classes.get(target_class, {})
                old_annotators = old_class_data.get("annotations", {}).get("annotators", "")
                if isinstance(old_annotators, str):
                    old_annotators_list = sorted(list(set(old_annotators.split(", "))))
                else:
                    old_annotators_list = []

                # Parse new ontology block (strip to clean input)
                new_annotators_list = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Update only if there are new values
                if new_annotators_list:
                    # Merge old and new values as a set
                    merged_annotators = sorted(set(old_annotators_list) | set(new_annotators_list))

                    # Ensure the class and annotations structure exists
                    if "annotations" not in current_schema_data["classes"][target_class]:
                        current_schema_data["classes"][target_class]["annotations"] = {}

                    # Store as string separated by commas
                    current_schema_data["classes"][target_class]["annotations"]["annotators"] = ", ".join(merged_annotators)

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "AnnotateClassExample":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                old_classes = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old values
                old_class_data = old_classes.get(target_class, {})
                old_prompt_examples = old_class_data.get("annotations", {}).get("prompt.examples", "")
                if isinstance(old_prompt_examples, str):
                    old_prompt_examples_list = sorted(list(set(old_prompt_examples.split(", "))))
                else:
                    old_prompt_examples_list = []

                # Parse new ontology block (strip to clean input)
                new_prompt_examples_list = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Update only if there are new values
                if new_prompt_examples_list:
                    # Merge old and new values as a set
                    merged_prompt_examples = sorted(set(old_prompt_examples_list) | set(new_prompt_examples_list))

                    # Ensure the class and annotations structure exists
                    if "annotations" not in current_schema_data["classes"][target_class]:
                        current_schema_data["classes"][target_class]["annotations"] = {}

                    # Store as string separated by commas
                    current_schema_data["classes"][target_class]["annotations"]["prompt.examples"] = ", ".join(merged_prompt_examples)

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassExample":
                # Load current schema as YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old annotations block (if any)
                old_class_data = classes_data.get(target_class, {})
                old_annotations = old_class_data.get("annotations", {})

                # Parse new prompt example (strip whitespace)
                new_prompt_example = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Overwrite old prompt.examples if new exists
                if new_prompt_example:
                    if "annotations" not in old_class_data or old_class_data["annotations"] is None:
                        old_class_data["annotations"] = {}

                    old_class_data["annotations"]["prompt.examples"] = ", ".join(new_prompt_example)
                    classes_data[target_class] = old_class_data

                # Update schema data
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassOntology":
                # Load current schema as YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old annotations block (if any)
                old_class_data = classes_data.get(target_class, {})
                old_annotations = old_class_data.get("annotations", {})

                # Parse new prompt example (strip whitespace)
                new_annotators = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Overwrite old prompt.examples if new exists
                if new_annotators:
                    if "annotations" not in old_class_data or old_class_data["annotations"] is None:
                        old_class_data["annotations"] = {}

                    old_class_data["annotations"]["annotators"] = ", ".join(new_annotators)
                    classes_data[target_class] = old_class_data

                # Update schema data
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassName":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Only update if the new class name is short enough
                if len(new_schema_yaml) < 50:  # avoid very long names
                    # Parse new class name and remove whitespace
                    new_class_name = "".join(new_schema_yaml.strip().split())

                    if new_class_name and target_class in classes_data:
                        # Rename the class key
                        classes_data[new_class_name] = classes_data.pop(target_class)

                        # Update any 'range' references inside attributes
                        for cls_data in classes_data.values():
                            attributes = cls_data.get("attributes", {})
                            for attr_name, attr_data in attributes.items():
                                if attr_data.get("range") == target_class:
                                    attr_data["range"] = new_class_name
                            attributes = cls_data.get("slot_usage", {})
                            for attr_name, attr_data in attributes.items():
                                if attr_data.get("range") == target_class:
                                    attr_data["range"] = new_class_name
                # Update the schema
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassDescription":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                new_class_description = new_schema_yaml

                classes_data[target_class]["description"] = new_class_description
                
                # Update the schema
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)
                
            case "FixClassAttributesName":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get current class attributes
                old_attributes = classes_data.get(target_class, {}).get("attributes", {})

                new_schema_yaml = pyyaml.safe_load(new_schema_yaml)
                # Get new schema attributes for this class
                if new_schema_yaml.get('classes', {}) == {}:
                    new_schema_classes = new_schema_yaml.get(target_class, {})  # entire schema is only this class
                else:
                    new_schema_classes = new_schema_yaml.get('classes', {}).get(target_class, {})
                new_attributes = new_schema_classes.get("attributes", {})

                if old_attributes and new_attributes:
                    # Map old attribute names to descriptions
                    old_desc_map = {attr_name: attr_data.get("description", "").strip()
                                    for attr_name, attr_data in old_attributes.items()}

                    # Map new attribute names to descriptions
                    new_desc_map = {attr_name: attr_data.get("description", "").strip()
                                    for attr_name, attr_data in new_attributes.items()}

                    # For each old attribute, find the closest matching new attribute
                    for old_key, old_desc in old_desc_map.items():
                        min_score = float('inf')
                        best_match_key = None

                        for new_key, new_desc in new_desc_map.items():
                            # Levenshtein distance on descriptions
                            distance_desc = Levenshtein.distance(old_desc, new_desc)
                            # Levenshtein distance on attribute name vs class name (weighted)
                            distance_name = Levenshtein.distance(new_key.lower(), target_class.lower()) * 0.3
                            # Combine score
                            score = distance_desc + distance_name

                            if score < min_score:
                                min_score = score
                                best_match_key = new_key

                        if best_match_key and best_match_key != old_key:
                            # Rename the attribute
                            old_attributes[best_match_key] = old_attributes.pop(old_key)

                    # Update the class attributes
                    classes_data[target_class]["attributes"] = old_attributes

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassAttributesDescription":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old attributes
                old_attributes = classes_data.get(target_class, {}).get("attributes", {})

                # Load new schema YAML as dict
                new_schema_data_parsed = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data_parsed.get('classes', {}) == {}:
                    new_class_data = new_schema_data_parsed.get(target_class, {})
                else:
                    new_class_data = new_schema_data_parsed.get('classes', {}).get(target_class, {})

                new_attributes = new_class_data.get("attributes", {})

                # Update descriptions using exact attribute name match (the LLM is prompted to avoid changing attribute names here)
                for attr_name, attr_data in new_attributes.items():
                    new_desc = attr_data.get("description", "").strip()
                    if attr_name in old_attributes:
                        old_attributes[attr_name]["description"] = new_desc

                # Assign updated attributes back to class
                classes_data[target_class]["attributes"] = old_attributes

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixClassAttributesType":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old attributes
                old_attributes = classes_data.get(target_class, {}).get("attributes", {})

                # Load new schema YAML as dict
                new_schema_data_parsed = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data_parsed.get('classes', {}) == {}:
                    new_class_data = new_schema_data_parsed.get(target_class, {})
                else:
                    new_class_data = new_schema_data_parsed.get('classes', {}).get(target_class, {})

                new_attributes = new_class_data.get("attributes", {})

                # Update descriptions using exact attribute name match (the LLM is prompted to avoid changing attribute names here)
                for attr_name, attr_data in new_attributes.items():
                    new_range = attr_data.get("range", "").strip()
                    new_multivalued = attr_data.get("multivalued", False)
                    
                    if attr_name in old_attributes:
                        old_attributes[attr_name]["range"] = new_range
                        old_attributes[attr_name]["multivalued"] = bool(new_multivalued)

                # Assign updated attributes back to class
                classes_data[target_class]["attributes"] = old_attributes

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)
                
            case "ReifyClass":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = classes[0]

                # Get old attributes
                old_attributes = classes_data.get(target_class, {}).get("attributes", {})

                # Load new schema as dict
                new_schema_data_parsed = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data_parsed.get('classes', {}) == {}:
                    new_classes_data = {}  # fallback if entire schema is a single class
                else:
                    new_classes_data = new_schema_data_parsed.get('classes', {})

                # Identify new classes
                new_classes_set = set(new_classes_data.keys()) - set(original_schema_classes_names) | {target_class}

                # Add queued parent classes if available in new_classes_data
                for new_class_name in list(new_classes_set):
                    classes_data[new_class_name] = new_classes_data[new_class_name]

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "AddAttributesToRelationship":
                # Parse current and new schema
                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                # Ensure 'classes' section exists
                if new_schema_data.get("classes", {}) == {}:
                    new_classes_data = new_schema_data 
                else:
                    new_classes_data = new_schema_data.get("classes", {})
                
                # Class target
                target_class = associations[0] + "Relationship"

                old_class_block = current_schema_yaml.get("classes", {}).get(target_class, {})
                old_attributes = old_class_block.get("slot_usage", {})
                old_subject = old_attributes.get("subject")
                old_object = old_attributes.get("object")
                old_predicate = old_attributes.get("predicate")

                new_class_block = new_classes_data.get(target_class, {})
                new_attributes = new_class_block.get("slot_usage", {})

                merged_attributes = old_attributes.copy()
                merged_attributes.update(new_attributes)
                merged_attributes['subject'] = old_subject
                merged_attributes['object'] = old_object
                merged_attributes['predicate'] = old_predicate

                # Aggiorna la classe con la fusione
                merged_class_block = old_class_block.copy()
                merged_class_block.update(new_class_block)
                merged_class_block["slot_usage"] = merged_attributes

                current_schema_yaml["classes"][target_class] = merged_class_block

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AddRelationshipAttributesDescription":
                # Load new schema classes
                new_schema_data = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data.get("classes", {}) == {}:
                    new_classes_data = new_schema_data
                else:
                    new_classes_data = new_schema_data.get("classes", {})

                # Target class
                target_class = associations[0] + "Relationship"

                # Old and new class blocks
                old_class_block = current_schema_yaml.get("classes", {}).get(target_class, {}) or {}
                old_attributes = old_class_block.get("slot_usage", {}) or {}
                old_subject = old_attributes.get("subject")
                old_object = old_attributes.get("object")
                old_predicate = old_attributes.get("predicate")

                new_class_block = new_classes_data.get(target_class, {}) or {}
                new_attributes = new_class_block.get("slot_usage", {}) or {}

                merged_attributes = {}
                all_attr_names = set(old_attributes.keys()) | set(new_attributes.keys())

                merged_attributes['subject'] = old_subject
                merged_attributes['object'] = old_object
                merged_attributes['predicate'] = old_predicate

                for attr_name in sorted(all_attr_names):
                    if attr_name != "subject" and attr_name != "object" and attr_name != "predicate":
                        old_attr = old_attributes.get(attr_name, {}) or {}
                        new_attr = new_attributes.get(attr_name, {}) or {}

                        merged_attr = old_attr.copy()

                        # Merge descriptions with similarity check
                        old_desc = old_attr.get("description").strip()
                        new_desc = new_attr.get("description").strip()

                        if new_desc:
                            if not old_desc:
                                merged_attr["description"] = new_desc
                            else:
                                sim = Levenshtein.ratio(old_desc, new_desc)
                                if sim <= 0.75:
                                    # Remove trailing punctuation from old_desc
                                    old_trim = old_desc.rstrip(".,;:!?")
                                    # Remove any leading punctuation or spaces from new_desc
                                    new_trim = new_desc.lstrip(" ,.;:!?")
                                    # Avoid duplicating the common initial part (ignoring punctuation differences)
                                    if new_trim.lower().startswith(old_trim.lower()):
                                        combined = new_trim
                                    else:
                                        # Use a comma as connector if old_desc ended with punctuation, otherwise use a space
                                        connector = ", " if old_desc and old_desc[-1] in ".,;:!?" else " "
                                        combined = (old_trim + connector + new_trim).strip()
                                    merged_attr["description"] = combined
                                else:
                                    merged_attr["description"] = old_desc
                        else:
                            if old_desc:
                                merged_attr["description"] = old_desc

                        merged_attributes[attr_name] = merged_attr

                # Merge class-level data
                merged_class_block = old_class_block.copy()
                merged_class_block.update(new_class_block)
                merged_class_block["slot_usage"] = merged_attributes

                # Update schema
                if "classes" not in current_schema_yaml or current_schema_yaml["classes"] is None:
                    current_schema_yaml["classes"] = {}
                current_schema_yaml["classes"][target_class] = merged_class_block

                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AnnotateRelationshipOntology":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                old_classes = current_schema_data.get("classes", {})
                target_class = associations[0] + "Predicate"

                # Get old values
                old_class_data = old_classes.get(target_class, {})
                old_annotators = old_class_data.get("annotations", {}).get("annotators", "")
                if isinstance(old_annotators, str):
                    old_annotators_list = sorted(list(set(old_annotators.split(", "))))
                else:
                    old_annotators_list = []

                # Parse new ontology block (strip to clean input)
                new_annotators_list = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Update only if there are new values
                if new_annotators_list:
                    # Merge old and new values as a set
                    merged_annotators = sorted(set(old_annotators_list) | set(new_annotators_list))

                    # Ensure the class and annotations structure exists
                    if "annotations" not in current_schema_data["classes"][target_class]:
                        current_schema_data["classes"][target_class]["annotations"] = {}

                    # Store as string separated by commas
                    current_schema_data["classes"][target_class]["annotations"]["annotators"] = ", ".join(merged_annotators)

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)
                
            case "AnnotateRelationshipExample":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                old_classes = current_schema_data.get("classes", {})
                target_class = associations[0] + "Relationship"

                # Get old values
                old_class_data = old_classes.get(target_class, {})
                old_prompt_examples = old_class_data.get("annotations", {}).get("prompt.examples", "")
                if isinstance(old_prompt_examples, str):
                    old_prompt_examples_list = sorted(list(set(old_prompt_examples.split(", "))))
                else:
                    old_prompt_examples_list = []

                # Parse new ontology block (strip to clean input)
                new_prompt_examples_list = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Update only if there are new values
                if new_prompt_examples_list:
                    # Merge old and new values as a set
                    merged_prompt_examples = sorted(set(old_prompt_examples_list) | set(new_prompt_examples_list))
                    # Remove empty examples
                    merged_prompt_examples = [example for example in merged_prompt_examples if example.strip()]

                    # Ensure the class and annotations structure exists
                    if "annotations" not in current_schema_data["classes"][target_class]:
                        current_schema_data["classes"][target_class]["annotations"] = {}

                    # Store as string separated by commas
                    current_schema_data["classes"][target_class]["annotations"]["prompt.examples"] = ", ".join(merged_prompt_examples)

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)
                
            case "AnnotateRelationshipDescription":
                # Parse current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                # Ensure 'classes' sections
                old_classes = current_schema_data.get("classes", {})
                # Class to update
                target_class = associations[0] + "Relationship"
                # Get old class description
                old_class_description = old_classes.get(target_class, {}).get("description", "").strip()

                # Parse new description (strip to remove leading/trailing whitespace/newlines)
                new_class_description = new_schema_yaml.strip()

                # Compute similarity with Levenshtein
                if new_class_description:  # update only if new is non-empty
                    similarity = Levenshtein.ratio(old_class_description, new_class_description)
                    if similarity <= 0.5:  # overwrite if different enough     
                        current_schema_data["classes"][target_class]["description"] = new_class_description
                
                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipName":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Predicate"

                # Only update if the new class name is short enough
                if len(new_schema_yaml) < 50:  # avoid very long names
                    # Parse new class name and remove whitespace
                    new_relationship_name = "".join(new_schema_yaml)

                    if new_relationship_name and target_class in classes_data:
                        # Update "pattern" to the new association name
                        classes_data[target_class]["attributes"]["id"]["pattern"] = new_relationship_name
                        
                # Update the schema
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipDescription":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Relationship"

                new_schema_data = pyyaml.safe_load(new_schema_yaml)

                new_class_description = new_schema_data[target_class]["description"]

                classes_data[target_class]["description"] = new_class_description
                
                # Update the schema
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipAttributesName":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Relationship"

                # Get current class attributes
                old_attributes = classes_data.get(target_class, {}).get("slot_usage", {})

                new_schema_yaml = pyyaml.safe_load(new_schema_yaml)
                # Get new schema attributes for this class
                if new_schema_yaml.get('classes', {}) == {}:
                    new_schema_classes = new_schema_yaml.get(target_class, {})  # entire schema is only this class
                else:
                    new_schema_classes = new_schema_yaml.get('classes', {}).get(target_class, {})
                new_attributes = new_schema_classes.get("slot_usage", {})

                if old_attributes and new_attributes:
                    # Map old attribute names to descriptions
                    old_desc_map = {
                        attr_name: attr_data.get("description", "").strip()
                        for attr_name, attr_data in old_attributes.items()
                        if attr_name not in ["subject", "object", "predicate"]
                    }

                    # Map new attribute names to descriptions
                    new_desc_map = {
                        attr_name: attr_data.get("description", "").strip()
                        for attr_name, attr_data in new_attributes.items()
                        if attr_name not in ["subject", "object", "predicate"]
                    }

                    # For each old attribute, find the closest matching new attribute
                    for old_key, old_desc in old_desc_map.items():
                        min_score = float('inf')
                        best_match_key = None

                        for new_key, new_desc in new_desc_map.items():
                            # Levenshtein distance on descriptions
                            distance_desc = Levenshtein.distance(old_desc, new_desc)
                            # Levenshtein distance on attribute name vs class name (weighted)
                            distance_name = Levenshtein.distance(new_key.lower(), target_class.lower()) * 0.3
                            # Combine score
                            score = distance_desc + distance_name

                            if score < min_score:
                                min_score = score
                                best_match_key = new_key

                        if best_match_key and best_match_key != old_key:
                            # Rename the attribute
                            old_attributes[best_match_key] = old_attributes.pop(old_key)

                    # Update the class attributes
                    classes_data[target_class]["slot_usage"] = old_attributes

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipAttributesType":
                # Load current schema
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Relationship"

                # Get old attributes
                old_attributes = classes_data.get(target_class, {}).get("slot_usage", {})

                # Load new schema YAML as dict
                new_schema_data_parsed = pyyaml.safe_load(new_schema_yaml)
                if new_schema_data_parsed.get('classes', {}) == {}:
                    new_class_data = new_schema_data_parsed.get(target_class, {})
                else:
                    new_class_data = new_schema_data_parsed.get('classes', {}).get(target_class, {})

                new_attributes = new_class_data.get("slot_usage", {})

                # Update descriptions using exact attribute name match (the LLM is prompted to avoid changing attribute names here)
                for attr_name, attr_data in new_attributes.items():
                    new_range = attr_data.get("range", "").strip()
                    new_multivalued = attr_data.get("multivalued", False)
                    
                    if attr_name in old_attributes and attr_name != "subject" and attr_name != "object" and attr_name != "predicate":
                        old_attributes[attr_name]["range"] = new_range
                        old_attributes[attr_name]["multivalued"] = bool(new_multivalued)

                # Assign updated attributes back to class
                classes_data[target_class]["slot_usage"] = old_attributes

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipOntology":
                # Load current schema as YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Predicate"

                # Get old annotations block (if any)
                old_class_data = classes_data.get(target_class, {})
                old_annotations = old_class_data.get("annotations", {})

                # Parse new prompt example (strip whitespace)
                new_annotators = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Overwrite old prompt.examples if new exists
                if new_annotators:
                    if "annotations" not in old_class_data or old_class_data["annotations"] is None:
                        old_class_data["annotations"] = {}

                    old_class_data["annotations"]["annotators"] = ", ".join(new_annotators)
                    classes_data[target_class] = old_class_data

                # Update schema data
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixRelationshipExample":
                # Load current schema as YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                target_class = associations[0] + "Relationship"

                # Get old annotations block (if any)
                old_class_data = classes_data.get(target_class, {})
                old_annotations = old_class_data.get("annotations", {})

                # Parse new prompt example (strip whitespace)
                new_prompt_example = sorted(list(set(new_schema_yaml.strip().split(", ")))) if new_schema_yaml.strip() else []

                # Overwrite old prompt.examples if new exists
                if new_prompt_example:
                    if "annotations" not in old_class_data or old_class_data["annotations"] is None:
                        old_class_data["annotations"] = {}

                    old_class_data["annotations"]["prompt.examples"] = ", ".join(new_prompt_example)
                    classes_data[target_class] = old_class_data

                # Update schema data
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)
                
            case "FixRelationshipCardinality":
                # Load current schema as YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                # Parse the new schema YAML
                new_schema_data = pyyaml.safe_load(new_schema_yaml)
                #print("New schema from LLM:", new_schema_data)
                # Ensure 'classes' section exists
                if new_schema_data.get('classes', {}) == {}:
                    new_classes = new_schema_data  # in this case, the entire schema is only classes
                else:
                    new_classes = new_schema_data.get('classes', {})
                new_classes_names = list(new_classes.keys())

                rel_class_name = associations[0] + "Relationship"
                #print(f"Processing relationship class: {rel_class_name}")

                # If relationship class not found, return unchanged schema
                if rel_class_name not in original_schema_classes_names or rel_class_name not in new_classes_names:
                    return Response(content=current_schema_yaml)

                # Check is_a type
                class_is_a_value = classes_data[rel_class_name].get("is_a")
                new_class_is_a_value = new_classes[rel_class_name].get("is_a")
                if class_is_a_value != "Triple" or new_class_is_a_value != "Triple":
                    return Response(content=current_schema_yaml)

                # Access slot_usage
                slot_usage = classes_data[rel_class_name].get("slot_usage", {})
                new_slot_usage = new_classes[rel_class_name].get("slot_usage", {})

                # Cardinality synchronization for 'subject' and 'object'
                for slot_name in ["subject", "object"]:
                    if slot_name in slot_usage and slot_name in new_slot_usage:
                        old_slot = slot_usage[slot_name]
                        new_slot = new_slot_usage[slot_name]
                        if (new_slot.get("minimum_cardinality") and new_slot.get("maximum_cardinality") and new_slot.get("minimum_cardinality") < new_slot.get("maximum_cardinality")):
                            if isinstance(old_slot, dict) and isinstance(new_slot, dict):
                                for bound in ["minimum_cardinality", "maximum_cardinality"]:
                                    # print(f"\nSyncing {bound} for slot '{slot_name}'")
                                    old_val = old_slot.get(bound)
                                    new_val = new_slot.get(bound)
                                    if new_val is not None and old_val != new_val:
                                        # print(f"\nUpdating {bound} for slot '{slot_name}' from {old_val} to {new_val}")
                                        old_slot[bound] = new_val
                                    elif old_val is not None and new_val is None:
                                        # print(f"\nRemoving {bound} for slot '{slot_name}' as it's not present in new schema")
                                        old_slot.pop(bound, None)

                # Update schema
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "AddAssociationsSimilarToEntities":
                # print("\ncurrent_schema_yaml =", current_schema_yaml)
                # Parse the new schema YAML
                new_schema_data = pyyaml.safe_load(new_schema_yaml)
                # print("\nnew_schema_data =", new_schema_data)

                # Ensure 'classes' section exists
                if new_schema_data.get("classes", {}) == {}:
                    new_classes = new_schema_data  # in this case, the entire schema is only classes
                else:
                    new_classes = new_schema_data.get("classes", {})
                if "relationships" in new_classes:
                    relationship_classes = new_classes["relationships"]
                else:
                    relationship_classes = new_classes
                # print("\nrelationship_classes =", relationship_classes)

                new_classes_names = list(relationship_classes.keys())

                # Compute newly generated classes
                new_class_names = set(new_classes_names) - set(original_schema_classes_names)
                # print("\nNew classes identified:", new_class_names)

                # this variabile contains the relationships that have been already added to the schema
                relationships_already_added = set()

                # Work on the current schema YAML and add only association-like classes (Triple / RelationshipType)
                for name in new_class_names:
                    if name not in relationships_already_added:
                        # print("\nConsidering new class:", name)
                        class_block = relationship_classes[name]
                        # print("\nClass block:", class_block)
                        is_a_value = class_block.get("is_a")
                        if is_a_value in ("Triple", "RelationshipType"):
                            if "slot_usage" in class_block:
                                section = "slot_usage"
                            elif "attributes" in class_block:
                                section = "attributes"
                            subject_range = class_block.get(section, {}).get("subject", {}).get("range", "")
                            object_range = class_block.get(section, {}).get("object", {}).get("range", "")

                            # Use a copy of the original name to extract the pattern value
                            cleaned_name = name

                            # Remove the suffix 'Predicate' if present
                            if cleaned_name.endswith("Predicate"):
                                cleaned_name = cleaned_name[:-len("Predicate")]
                            # Remove the suffix 'Relationship' if present
                            if cleaned_name.endswith("Relationship"):
                                cleaned_name = cleaned_name[:-len("Relationship")]
                            # Remove the subject_range prefix if present
                            if cleaned_name.startswith(subject_range):
                                cleaned_name = cleaned_name[len(subject_range):]
                            # Remove the object_range suffix if present
                            if cleaned_name.endswith(object_range):
                                cleaned_name = cleaned_name[:-len(object_range)]

                            # print("\nCleaned name:", cleaned_name)

                            # Create the RelationshipType block for the 'name' association
                            rel_type_class_block = {
                                "is_a": "RelationshipType",
                                "attributes": {
                                    "id": {
                                        "pattern": cleaned_name
                                    }
                                }
                            }
                            # Create the name of the Predicate class
                            new_name = subject_range + cleaned_name + object_range + "Predicate"
                            current_schema_yaml["classes"][new_name] = rel_type_class_block

                            # Create the Triple block only if subject, object and predicate are present (otherwise the association can't be added because its subject and object are not known --> this is not a problem for the already added "Predicate" block because it will be deleted as soon as the schema is uploaded if no related Triple block is present)
                            if "subject" in class_block[section] and "object" in class_block[section] and "predicate" in class_block[section]:
                                triple_class_block = {
                                    "is_a": "Triple",
                                    "slot_usage": {
                                        "subject": class_block[section]["subject"],
                                        "object":class_block[section]["object"],
                                        "predicate":class_block[section]["predicate"]
                                    }
                                }
                                new_name = subject_range + cleaned_name + object_range + "Relationship"
                                current_schema_yaml["classes"][new_name] = triple_class_block

                                relationships_already_added.add(new_name)

                # Dump back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)
                #print("\nupdated_final_schema =", updated_final_schema)

            case "AnnotateSubschemaDescription":
                #print(new_schema_yaml)
                associations = [name + "Relationship" for name in associations]
                # Iterate over provided pairs, new_schema_yaml is a JSON here compliant with the JSON schema prompt
                for item in json.loads(new_schema_yaml).get("pairs", []):
                    element = item["class_or_relationship_name"]
                    if element in associations or element in classes:
                        new_desc = item["description"].strip()
                        #print(f"Processing element: {element} with new description: {new_desc}")

                        # Get old block (if exists)
                        old_class_block = current_schema_yaml.get("classes", {}).get(element, {})
                        #print("Old class block:", old_class_block)
                        old_desc = old_class_block.get("description", "").strip() if old_class_block else ""
                        #print("Old description:", old_desc)

                        similarity = 1
                        if old_desc and new_desc:
                            similarity = Levenshtein.ratio(old_desc, new_desc)
                        elif not old_desc and new_desc:
                            similarity = 0
                        if similarity <= 0.9:
                            if not old_desc and new_desc:
                                description = new_desc
                            elif old_desc and not new_desc:
                                description = old_desc
                            elif old_desc and new_desc:
                                description = old_desc + ". " + new_desc
                            else:
                                description = ""

                            if description and element in current_schema_yaml["classes"]:
                                #print(f"Updating description for {element}: {description}")
                                current_schema_yaml["classes"][element]["description"] = description

                # Dump back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AnnotateSubschemaExample":
                #print(new_schema_yaml)
                associations = [name + "Relationship" for name in associations]
                # Iterate over classes
                for element in json.loads(new_schema_yaml).get("pairs", []):
                    if element["class_or_relationship_name"] in associations or element in classes:
                        #print(f"\nProcessing class: {element["class_or_relationship_name"]}")
                        old_class_block = current_schema_yaml.get("classes", {}).get(element["class_or_relationship_name"], {})
                        #print("Old class block:", old_class_block)
                        old_examples = old_class_block.get("annotations", {}).get("prompt.examples", "").strip()
                        #print("\nOld examples:", old_examples)
                        # Find new examples from new_schema_yaml
                        new_examples = element["examples"].strip()  
                        #print("New examples:", new_examples)

                        if new_examples:
                            old_list = [ex.strip() for ex in old_examples.split(", ")] if old_examples else []
                            new_list = [ex.strip() for ex in new_examples.split(", ")]
                            combined_list = old_list[:]
                            #print("Old examples list:", old_list)
                            #print("New examples list:", new_list)
                            for ex in new_list:
                                if ex not in combined_list:
                                    combined_list.append(ex)

                            combined_str = ", ".join(combined_list)
                            current_schema_yaml["classes"][element["class_or_relationship_name"]]["annotations"]["prompt.examples"] = combined_str
                
                # Dump back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "AnnotateSubschemaOntology":
                associations = [name + "Relationship" for name in associations]
                # Iterate over classes
                for element in json.loads(new_schema_yaml).get("pairs", []):
                    is_association = False
                    element_name = element["class_or_relationship_name"]
                    if element_name in associations:
                        element_name = element_name.replace("Relationship", "Predicate")
                        is_association = True
                    if is_association or element_name in classes:
                        old_class_block = current_schema_yaml.get("classes", {}).get(element_name, {})
                        old_annotators = old_class_block.get("annotations", {}).get("annotators", "").strip()
                        # Find new examples from new_schema_yaml
                        new_annotators = element["ontologies"].strip()  

                        if new_annotators:
                            old_list = [ont.strip() for ont in old_annotators.split(", ")] if old_annotators else []
                            new_list = [ont.strip() for ont in new_annotators.split(", ")]
                            combined_list = old_list[:]
                            for ont in new_list:
                                if ont not in combined_list:
                                    combined_list.append(ont)

                            combined_str = ", ".join(combined_list)
                            current_schema_yaml["classes"][element_name]["annotations"]["annotators"] = combined_str
                
                # Dump back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "FixClassesAndAssociationsName":
                # Load pairs from the JSON response of the model
                pairs_data = json.loads(new_schema_yaml)  # Here new_schema_yaml actually contains the JSON pairs according to the json_schema in the prompt
                pairs = pairs_data.get("pairs", [])
                #print("Pairs to process:", pairs)

                # Work on a copy of the classes dict
                classes_data = current_schema_yaml.get("classes", {})

                # Prepare associations list with Predicate suffix
                associations_with_suffix = [name + "Predicate" for name in associations]

                # Apply renaming based on pairs
                for mapping in pairs:
                    old_name = mapping.get("class_or_predicate_old_name")
                    new_name = mapping.get("class_or_predicate_new_name", "").strip()

                    # --- Case 1: old_name is a class ---
                    if old_name in classes:
                        # Normalize new_name (remove spaces)
                        new_name_clean = re.sub(r'\s+', '', new_name.title())
                        #print(f"Renaming class {old_name} to {new_name_clean}")

                        # Rename the class: move the block under new_name
                        classes_data[new_name_clean] = classes_data.pop(old_name)

                        # Update any 'range' references that previously pointed to old_name
                        for cls_data in classes_data.values():
                            attributes = cls_data.get("attributes", {})
                            for attr_name, attr_data in attributes.items():
                                if attr_data.get("range") == old_name:
                                    attr_data["range"] = new_name_clean

                            attributes = cls_data.get("slot_usage", {})
                            for attr_name, attr_data in attributes.items():
                                if attr_data.get("range") == old_name:
                                    attr_data["range"] = new_name_clean

                    # --- Case 2: old_name is a Predicate (association) ---
                    elif old_name in associations_with_suffix:
                        #print(f"Renaming predicate {old_name} to {new_name}")
                        # Fix predicate attributes: ensure id.pattern and id.label reflect the new name
                        attributes = classes_data.get(old_name, {}).get("attributes", {})
                        #print(f"Old attributes for {old_name}:", attributes)
                        if "id" not in attributes:
                            attributes["id"] = {}
                        #print(f"Updating id pattern for {old_name} to {new_name}")
                        attributes["id"]["pattern"] = new_name
                        #print(f"Updated attributes for {old_name}:", attributes)
                        classes_data[old_name]["attributes"] = attributes

                # Assign updated classes back to schema
                current_schema_yaml["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "FixClassesAndAssociationsDescription":
                # Work on a copy of the classes dict
                classes_data = current_schema_yaml.get("classes", {})
                associations = [name + "Relationship" for name in associations]

                # Load pairs from JSON response of the model
                pairs_data = json.loads(new_schema_yaml)  # new_schema_yaml contains the JSON pairs according to json_schema
                pairs = pairs_data.get("pairs", [])
                #print("Pairs to process:", pairs)

                # Apply description updates based on pairs
                for mapping in pairs:
                    name = mapping.get("class_or_relationship_name")
                    new_description = mapping.get("description", "").strip()

                    # --- Case 1: name is a class ---
                    if name in classes:
                        #print(f"Updating description of class {name}")
                        classes_data[name]["description"] = new_description

                    # --- Case 2: name is a relationship ---
                    elif name in associations:
                        #print(f"Updating description of relationship {name}")
                        classes_data[name]["description"] = new_description

                # Assign updated classes back to schema
                current_schema_yaml["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "FixSubschemaCardinalities":
                # Parse current schema classes
                classes_data = current_schema_yaml.get("classes", {})
                # Parse new schema classes
                #print("New schema YAML:", new_schema_yaml)
                new_schema_data = pyyaml.safe_load(new_schema_yaml)
                # Ensure 'classes' section exists
                if new_schema_data.get("classes", {}) == {}:
                    new_classes_data = new_schema_data  # in this case, the entire schema is only classes
                else:
                    new_classes_data = new_schema_data.get("classes", {})
                associations = [name + "Relationship" for name in associations]
                # Filter new classes to only those matching the associations
                new_classes_names = set(new_classes_data.keys()).intersection(associations)
                #print("New relationship classes to process:", new_classes_names)

                for rel_class_name in new_classes_names:
                    #print(f"Processing relationship class: {rel_class_name}")

                    old_class = classes_data[rel_class_name]
                    new_class = new_classes_data[rel_class_name]

                    # Only process if both are Triple
                    if old_class.get("is_a") != "Triple" and new_class.get("is_a") != "Triple":
                        continue

                    old_slot_usage = old_class.get("slot_usage", {})
                    new_slot_usage = new_class.get("slot_usage", {})

                    for slot_name in ["subject", "object"]:
                        #print(f"  Processing slot: {slot_name}")
                        if slot_name in old_slot_usage and slot_name in new_slot_usage:
                            old_slot = old_slot_usage[slot_name]
                            new_slot = new_slot_usage[slot_name]
                            #print(f"    Old slot '{slot_name}':", old_slot)
                            #print(f"    New slot '{slot_name}':", new_slot)

                            if isinstance(old_slot, dict) and isinstance(new_slot, dict):
                                # Sync minimum_cardinality
                                if "minimum_cardinality" in new_slot:
                                    old_slot["minimum_cardinality"] = new_slot["minimum_cardinality"]
                                elif "minimum_cardinality" in old_slot and "minimum_cardinality" not in new_slot:
                                    old_slot.pop("minimum_cardinality", None)

                                # Sync maximum_cardinality
                                if "maximum_cardinality" in new_slot:
                                    old_slot["maximum_cardinality"] = new_slot["maximum_cardinality"]
                                elif "maximum_cardinality" in old_slot and "maximum_cardinality" not in new_slot:
                                    old_slot.pop("maximum_cardinality", None)

                    # Assign back updated slot_usage
                    old_class["slot_usage"] = old_slot_usage
                    classes_data[rel_class_name] = old_class

                # Assign back updated classes to schema
                current_schema_yaml["classes"] = classes_data
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)

            case "FixSubschemaExample":
                # Parse current schema YAML
                current_schema_data = pyyaml.safe_load(current_schema)
                classes_data = current_schema_data.get("classes", {})
                associations = [name + "Relationship" for name in associations]
                #print("Classes to process:", classes)
                #print("Associations to process:", associations)

                # Load new examples from JSON
                new_pairs_data = json.loads(new_schema_yaml)  # contains {"pairs": [{"class_or_relationship_name": ..., "examples": ...}, ...]}
                pairs = new_pairs_data.get("pairs", [])

                # Update classes examples
                for mapping in pairs:
                    #print("Processing mapping:", mapping)
                    name = mapping.get("class_or_relationship_name")
                    examples_raw = mapping.get("examples", "").strip()

                    if not examples_raw:
                        continue

                    # Normalize the examples string
                    examples = ", ".join(sorted(set(examples_raw.split(", "))))

                    # Determine if it's a class or a relationship
                    if name in classes or name in associations:
                        #print(f"Updating examples for {name}: {examples}")
                        target_class = classes_data[name]

                        # Ensure annotations exist
                        if "annotations" not in target_class or target_class["annotations"] is None:
                            target_class["annotations"] = {}

                        # Overwrite prompt.examples
                        target_class["annotations"]["prompt.examples"] = examples

                # Assign back updated classes
                current_schema_data["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_data, sort_keys=False)

            case "FixSubschemaOntology":
                # Parse current schema YAML
                classes_data = current_schema_yaml.get("classes", {})
                associations_with_suffix = [name + "Predicate" for name in associations]

                # Load new ontology mappings from JSON
                new_pairs_data = json.loads(new_schema_yaml)  # {"pairs": [{"class_or_relationship_name": ..., "ontologies": ...}, ...]}
                pairs = new_pairs_data.get("pairs", [])

                for mapping in pairs:
                    #print("Processing mapping:", mapping)
                    name = mapping.get("class_or_relationship_name")
                    ontologies_raw = mapping.get("ontologies", "").strip()

                    if not ontologies_raw:
                        continue

                    # Normalize ontologies list
                    ontologies_list = sorted(set([o.strip() for o in ontologies_raw.split(", ") if o.strip()]))

                    if name in classes or name in associations_with_suffix:
                        target_class = classes_data[name]
                        #print(f"Updating ontologies for {name}: {ontologies_list}")
                        if "annotations" not in target_class or target_class["annotations"] is None:
                            target_class["annotations"] = {}
                        #print(f"Updating annotators for {name}: {ontologies_list}")
                        #print(f"Old annotators:", target_class["annotations"].get("annotators"))
                        target_class["annotations"]["annotators"] = ", ".join(ontologies_list)
                        #print(f"New annotators:", target_class["annotations"].get("annotators"))

                current_schema_yaml["classes"] = classes_data

                # Convert back to YAML
                updated_final_schema = pyyaml.dump(current_schema_yaml, sort_keys=False)


        # the following code is a fix to ensure that 'prompt.examples' is always defined as a YAML multiline block, even when there are no examples, by adding a default text to prevent errors.
        updated_final_schema = re.sub(
            r'prompt\.examples:\s*\'\'', 
            'prompt.examples: |\n      # no examples provided', 
            updated_final_schema
        )

    except pyyaml.YAMLError as e:
        return JSONResponse(status_code=500, content={"error": "YAML error", "details": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Internal server error", "details": str(e)})

    #print("\n\n\nUpdated schema:\n", updated_final_schema)

    return Response(content=updated_final_schema)


@app.post("/api/openai/ask/")
async def ask(request: Request):
    if not (OPENAI_API_KEY):
        return Response(status_code=500, content="OpenAI API key not set")

    raw_body = await request.body()
    client = OpenAI(api_key=OPENAI_API_KEY)
    try: 
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": raw_body.decode("utf-8"),
                },
            ],
        )
        response_text = completion.choices[0].message.content.replace("```yaml\n", "").replace("```", "")
        #print("Response text:", response_text)
        return Response(content=response_text)

    except RateLimitError as e:
        subject = "SchemaLink Error: OpenAI rate or fund limit exceeded"
        body = (
            f"An OpenAI request failed due to a rate or funding limit being exceeded.\n\n"
            f"\n\nSchemaLink Notification System")
        send_email(to_email=admin_email, subject=subject, message=body)

        # include 'insufficient_quota'
        return JSONResponse(status_code=429, content={"error": "Quota exceeded or rate limited", "details": str(e)})

    except APIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI API error", "details": str(e)})
    except OpenAIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI error", "details": str(e)})


# ============================================================================
# Enum Registry Endpoints
# ============================================================================

@app.get("/api/enum-registry")
async def get_enum_registry():
    """GET /api/enum-registry - Get all enums"""
    registry = load_json_file('enumRegistry.json')
    return JSONResponse(content=registry)


@app.post("/api/enum-registry")
async def create_enum(request: EnumCreateRequest, current_user: str = Depends(get_current_user)):
    """POST /api/enum-registry - Create new enum (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    enum_name = request.name
    permissible_values = request.permissible_values
    
    if not enum_name or not permissible_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing name or permissible_values"
        )
    
    registry = load_json_file('enumRegistry.json')
    
    # Check if enum already exists
    if enum_name in registry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enum already exists"
        )
    
    # Only allow creating simple enums (with permissible_values)
    registry[enum_name] = {
        'permissible_values': permissible_values
    }
    
    save_json_file('enumRegistry.json', registry)
    return JSONResponse(content=registry[enum_name], status_code=200)


@app.put("/api/enum-registry/{enum_name:path}")
async def update_enum(enum_name: str, request: EnumUpdateRequest, current_user: str = Depends(get_current_user)):
    """PUT /api/enum-registry/{enum_name} - Update enum (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    registry = load_json_file('enumRegistry.json')
    
    if enum_name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enum not found"
        )
    
    # Only allow updating simple enums (not complex ones with reachable_from)
    if 'reachable_from' in registry[enum_name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot edit complex enums with ontology mappings"
        )
    
    permissible_values = request.permissible_values
    
    if not permissible_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing permissible_values"
        )
    
    registry[enum_name] = {
        'permissible_values': permissible_values
    }
    
    save_json_file('enumRegistry.json', registry)
    return JSONResponse(content=registry[enum_name], status_code=200)


@app.delete("/api/enum-registry/{enum_name:path}")
async def delete_enum(enum_name: str, current_user: str = Depends(get_current_user)):
    """DELETE /api/enum-registry/{enum_name} - Delete enum (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    registry = load_json_file('enumRegistry.json')
    
    if enum_name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enum not found"
        )
    
    # Only allow deleting simple enums (not complex ones with reachable_from)
    if 'reachable_from' in registry[enum_name]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete complex enums with ontology mappings"
        )
    
    del registry[enum_name]
    save_json_file('enumRegistry.json', registry)
    return JSONResponse(content={"message": "Enum deleted successfully"}, status_code=200)


# ============================================================================
# Regex Registry Endpoints
# ============================================================================

@app.get("/api/regex-registry")
async def get_regex_registry():
    """GET /api/regex-registry - Get all regexes"""
    registry = load_json_file('regexRegistry.json')
    return JSONResponse(content=registry)


@app.post("/api/regex-registry")
async def create_regex(request: RegexCreateRequest, current_user: str = Depends(get_current_user)):
    """POST /api/regex-registry - Create new regex (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    regex_name = request.name
    expression = request.expression
    
    if not regex_name or not expression:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing name or expression"
        )
    
    # Validate regex
    try:
        re.compile(expression)
    except re.error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regex expression: {str(e)}"
        )
    
    registry = load_json_file('regexRegistry.json')
    
    # Check if regex already exists
    if regex_name in registry:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Regex already exists"
        )
    
    registry[regex_name] = {
        'name': regex_name,
        'expression': expression
    }
    
    save_json_file('regexRegistry.json', registry)
    return JSONResponse(content=registry[regex_name], status_code=200)


@app.put("/api/regex-registry/{regex_name:path}")
async def update_regex(regex_name: str, request: RegexUpdateRequest, current_user: str = Depends(get_current_user)):
    """PUT /api/regex-registry/{regex_name} - Update regex (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    registry = load_json_file('regexRegistry.json')
    
    if regex_name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regex not found"
        )
    
    expression = request.expression
    
    if not expression:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing expression"
        )
    
    # Validate regex
    try:
        re.compile(expression)
    except re.error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regex expression: {str(e)}"
        )
    
    registry[regex_name] = {
        'name': regex_name,
        'expression': expression
    }
    
    save_json_file('regexRegistry.json', registry)
    return JSONResponse(content=registry[regex_name], status_code=200)


@app.delete("/api/regex-registry/{regex_name:path}")
async def delete_regex(regex_name: str, current_user: str = Depends(get_current_user)):
    """DELETE /api/regex-registry/{regex_name} - Delete regex (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    registry = load_json_file('regexRegistry.json')
    
    if regex_name not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regex not found"
        )
    
    del registry[regex_name]
    save_json_file('regexRegistry.json', registry)
    return JSONResponse(content={"message": "Regex deleted successfully"}, status_code=200)


# ============================================================================
# Custom Ontologies Registry Endpoints
# ============================================================================

@app.get("/api/custom-ontologies")
async def get_custom_ontologies(current_user: str = Depends(get_current_user)):
    """GET /api/custom-ontologies - Get all custom ontologies (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    ontologies = load_custom_ontologies()  # This is a sync function from service.py
    return JSONResponse(content={"ontologies": ontologies})


@app.post("/api/custom-ontologies")
async def create_custom_ontology(request: CustomOntologyCreateRequest, current_user: str = Depends(get_current_user)):
    """POST /api/custom-ontologies - Create new custom ontology (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    ontology_id = request.id.strip() if request.id else ""
    if not ontology_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing id"
        )
    
    # Validate properties and terms are lists of strings
    if not isinstance(request.properties, list) or not all(isinstance(p, str) for p in request.properties):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="properties must be a list of strings"
        )
    if not isinstance(request.terms, list) or not all(isinstance(t, str) for t in request.terms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="terms must be a list of strings"
        )
    
    # Use atomic load-modify-save to prevent race conditions
    def add_ontology(ontologies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Check if ontology already exists (case-insensitive check)
        for o in ontologies:
            if o.get("id", "").lower() == ontology_id.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Custom ontology with this id already exists"
                )
        
        # Create new ontology entry
        new_ontology = {
            "id": ontology_id,
            "name": request.name.strip() if request.name else "",
            "description": request.description.strip() if request.description else "",
            "namespace": request.namespace.strip() if request.namespace else "",
            "annotator": request.annotator.strip() if request.annotator else "",
            "properties": request.properties or [],
            "terms": request.terms or []
        }
        
        ontologies.append(new_ontology)
        return ontologies
    
    ontologies = await load_and_modify_custom_ontologies(add_ontology)
    new_ontology = next((o for o in ontologies if o.get("id", "").lower() == ontology_id.lower()), None)
    
    # Update cache immediately so the new ontology is available
    if new_ontology:
        await update_cache_with_custom_ontology(new_ontology, operation="upsert")
    
    return JSONResponse(content=new_ontology, status_code=200)


@app.put("/api/custom-ontologies/{ontology_id:path}")
async def update_custom_ontology(ontology_id: str, request: CustomOntologyUpdateRequest, current_user: str = Depends(get_current_user)):
    """PUT /api/custom-ontologies/{ontology_id} - Update custom ontology (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    # Validate properties and terms are lists of strings
    if not isinstance(request.properties, list) or not all(isinstance(p, str) for p in request.properties):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="properties must be a list of strings"
        )
    if not isinstance(request.terms, list) or not all(isinstance(t, str) for t in request.terms):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="terms must be a list of strings"
        )
    
    # Use atomic load-modify-save to prevent race conditions
    def update_ontology(ontologies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Find ontology by id (case-insensitive)
        ontology_index = None
        for i, o in enumerate(ontologies):
            if o.get("id", "").lower() == ontology_id.lower():
                ontology_index = i
                break
        
        if ontology_index is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Custom ontology not found"
            )
        
        # Update ontology
        ontologies[ontology_index].update({
            "name": request.name.strip() if request.name else "",
            "description": request.description.strip() if request.description else "",
            "namespace": request.namespace.strip() if request.namespace else "",
            "annotator": request.annotator.strip() if request.annotator else "",
            "properties": request.properties or [],
            "terms": request.terms or []
        })
        
        return ontologies
    
    ontologies = await load_and_modify_custom_ontologies(update_ontology)
    updated_ontology = next((o for o in ontologies if o.get("id", "").lower() == ontology_id.lower()), None)
    
    # Update cache immediately so the updated ontology is available
    if updated_ontology:
        await update_cache_with_custom_ontology(updated_ontology, operation="upsert")
    
    return JSONResponse(content=updated_ontology, status_code=200)


@app.delete("/api/custom-ontologies/{ontology_id:path}")
async def delete_custom_ontology(ontology_id: str, current_user: str = Depends(get_current_user)):
    """DELETE /api/custom-ontologies/{ontology_id} - Delete custom ontology (admin only)"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized"
        )
    
    # Use atomic load-modify-save to prevent race conditions
    deleted_ontology_id = None
    
    def delete_ontology(ontologies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        nonlocal deleted_ontology_id
        # Find ontology by id (case-insensitive)
        ontology_index = None
        for i, o in enumerate(ontologies):
            if o.get("id", "").lower() == ontology_id.lower():
                ontology_index = i
                break
        
        if ontology_index is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Custom ontology not found"
            )
        
        deleted_ontology = ontologies.pop(ontology_index)
        deleted_ontology_id = deleted_ontology.get("id")
        return ontologies
    
    await load_and_modify_custom_ontologies(delete_ontology)
    
    # Update cache immediately to remove the deleted ontology
    if deleted_ontology_id:
        deleted_ontology = {"id": deleted_ontology_id}
        await update_cache_with_custom_ontology(deleted_ontology, operation="delete")
    
    return JSONResponse(content={"message": "Custom ontology deleted successfully", "id": deleted_ontology_id}, status_code=200)


# ============================================================================
# LinkML Translation Endpoint
# ============================================================================

@app.post("/api/linkml/oo/translate/")
async def translate_linkml_oo_schema(request: LinkMLOOTranslateRequest):
    """
    POST /api/linkml/oo/translate/ - Translate Object-Oriented LinkML YAML schema to visual representation JSON
    
    This endpoint takes an Object-Oriented LinkML YAML schema and converts it into a visual representation
    format with nodes and relationships suitable for diagram visualization.
    
    This translator specifically handles OO LinkML patterns where classes have attributes that reference
    other classes. For other LinkML patterns, use appropriate endpoints.
    
    Args:
        request: LinkMLOOTranslateRequest containing:
            - yaml_content: Object-Oriented LinkML YAML schema as string
            - return_visual: If True (default), return visual representation; if False, return internal representation
    
    Returns:
        JSONResponse containing the transformed representation with nodes and relationships
    """
    try:
        # Validate YAML content
        if not request.yaml_content or not request.yaml_content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="YAML content cannot be empty"
            )
        
        # Translate OO LinkML to visual representation
        result = translate_linkml_oo(request.yaml_content, return_visual=request.return_visual)
        print("Translation result:", result)
        return JSONResponse(content=result, status_code=200)
    
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YAML format: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OO LinkML schema: {str(e)}"
        )
    except Exception as e:
        logging.error(f"Error translating OO LinkML schema: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# JSON to YAML Export Endpoint
# ============================================================================

@app.post("/api/export/json-to-yaml/")
async def export_json_to_yaml(request: JSONExportRequest):
    """
    POST /api/export/json-to-yaml/ - Convert internal representation JSON to LinkML YAML schema
    
    This endpoint takes an internal representation JSON graph (with nodes, relationships, and metadata)
    and converts it into a LinkML YAML schema using the export algorithm.
    
    Args:
        request: JSONExportRequest containing:
            - graph_json: Internal representation JSON graph with nodes, relationships, and metadata
    
    Returns:
        JSONResponse containing the YAML schema as a string
    """
    try:
        # Validate required fields
        if "nodes" not in request.graph_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Graph JSON must contain 'nodes' field"
            )
        if "relationships" not in request.graph_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Graph JSON must contain 'relationships' field"
            )
        
        # Convert JSON to YAML using the export algorithm (clean implementation)
        yaml_schema = convert_internal_representation_to_yaml(request.graph_json)
        
        # Convert YAML schema dict to YAML string
        yaml_string = dump_yaml_schema(yaml_schema)
        
        return JSONResponse(
            content={"yaml_content": yaml_string, "yaml_schema": yaml_schema},
            status_code=200
        )
    
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field in graph JSON: {str(e)}"
        )
    except Exception as e:
        logging.error(f"Error converting JSON to YAML: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )