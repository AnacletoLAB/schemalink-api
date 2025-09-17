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
from typing import List, Annotated
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
from expire_subscriptions_job import expire_subscriptions_job
import chromadb
import re
import openai
import json
import Levenshtein

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
    allow_origins=["helix.biodata.di.unimi.it", "schemalink.biodata.di.unimi.it", "schemalink.anacleto.di.unimi.it", "http://localhost:8000","http://localhost:4200",],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


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

# Start the listener during the app's startup in FastAPI and set up the scheduler
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(listen_notifications()) # Start the listener in parallel

    scheduler.add_job(
        expire_subscriptions_job,
        CronTrigger(minute='*/5')
    )

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


def get_embedding(text):
    """Ottiene l'embedding usando OpenAI text-embedding-3-small"""
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
    raw_body = await request.body()
    body = json.loads(raw_body)

    received_prompt_text = body.get("prompt")
    operation = body.get("operation")

    selected_classes = body.get("classes_names")
    classes = [item["caption"] for item in selected_classes if "caption" in item]

    associations = body.get("associations_names")

    match operation:
        case "AddClassAssociatedToClass" | "AnnotateClassOntology" | "AnnotateClassExample" | "AnnotateClassDescription" | "FixClassName":
            collection_name = "only_classes"
        case "AddAttributesToRelationship" | "AddClassesSimilarToEntities" | "FixClassDescription" | "FixClassAttributesName" | "FixClassAttributesType" | "AnnotateRelationshipOntology" | "AnnotateRelationshipExample" | "AnnotateRelationshipDescription" | "FixRelationshipName" | "AddAssociationsSimilarToEntities" | "AnnotateSubschemaDescription":
            collection_name = "classes_and_relationships"
        case "AddClassSimilarToClass" | "ReifyClass" | "ExplainClass" | "ExplainEntities" | "FixClassOntology" | "FixRelationshipCardinality" | "AddAttributesToClass" | "AddAttributesDescription" | "AddParentClass" | "AddChildClass" | "FixClassAttributesDescription" | "FixClassExample" | "AddRelationshipAttributesDescription" | "FixRelationshipAttributesName" | "FixRelationshipAttributesType" | "FixRelationshipOntology" | "FixRelationshipExample" | "ExplainRelationship" | "AnnotateSubschemaOntology" | "AnnotateSubschemaExample" | "FixClassesAndAssociationsName" | "FixSubschemaOntology" | "FixSubschemaExample" | "FixSubschemaCardinalities" | "FixClassesAndAssociationsDescription":
            collection_name = "full_schemas"
        case _:
            operation = "Generate"
            collection_name = "full_schemas"

    client = await chromadb.AsyncHttpClient(host='localhost', port=8001)

    try:
        collection = await client.get_collection(collection_name)
    except Exception as e:
        return Response(content="Error retrieving collection", status_code=500)

    if operation == "Generate":
        query_embedding = get_embedding(received_prompt_text)
    else:
        match = re.search(r"id:\s*(https?://\S+)", received_prompt_text)
        if match:
            schema_id = match.group(1)
        else:
            return Response(content="ID not found in raw_body.", status_code=400)
        
        intro_schema_match = re.search(r"(id:.*?\nclasses:)", received_prompt_text, re.DOTALL)
        if intro_schema_match:
            intro_schema = intro_schema_match.group(1).strip()      # this extracts the initial part from the given LinkML schema. This part includes the schema id, title, description and other informations that do not have to be modified
        else:
            return None
    
        start_index = received_prompt_text.find("id:")
        if start_index != -1:
            prompt_text_substring = received_prompt_text[start_index:]
        schemas_classes_match = re.search(r'classes:\s*(.*?)\n(?:\w+:|$)', prompt_text_substring, re.DOTALL)
        if schemas_classes_match:
            classes_section = schemas_classes_match.group(1).strip()    # this extracts the classes section from the given LinkML schema
            classes_section = '  ' + classes_section.lstrip()
            original_schema_classes_names = re.findall(r'^\s*([A-Z][A-Za-z0-9_]+):', classes_section, re.MULTILINE)       # this extracts only classes names from classes_section
        
        prompt_text_modified = received_prompt_text.replace("\n", " ")    # this removes possible empty lines at the beginning of the string in received_prompt_text
        match_intro = re.match(r"^(.*?\.)\s", prompt_text_modified + " ")
        if match_intro:
            intro = match_intro.group(1).strip()
        else:
            intro = received_prompt_text.split("\n")[0].strip()
        
        query_embedding = get_embedding(intro + "SCHEMA:" + schema_id)
    

    results = await collection.query(query_embeddings=[query_embedding], n_results=10, include=["metadatas", "distances", "documents"])

    similar_schemas = results["ids"][0]
    
    prompt = f"{received_prompt_text}"
    if similar_schemas:
        prompt += "\nCONTEXT:\n"
        if collection_name == "full_schemas":
            for meta in results["metadatas"][0][:10]:
                prompt += f"\n{meta.get('content')}\n\n"
        else:
            for i in range(10):
                prompt += results['documents'][0][i] + "\n\n"

    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=3000,
            messages=[
                {"role": "system", "content": "You are an expert in LinkML schemas. Output only valid YAML LinkML schema, no explanations. Use CONTEXT to improve the output but not include it in the output. Answer as fast as possible."},
                {"role": "user", "content": prompt}
            ],
        )

        print("Prompt:\n", prompt)
        new_schema_yaml = response.choices[0].message.content
        print("Generated schema:\n", new_schema_yaml)

        new_schema_yaml = re.sub(r"^```yaml\s*", "", new_schema_yaml).split("\nCONTEXT")[0] # it removes the ```yaml at the beginning of the output, if present, and anything that is after the word "\nCONTEXT" (included)
        new_schema_yaml = new_schema_yaml.strip('`').strip()
        new_schema_yaml = new_schema_yaml.replace("mixins: {}", "mixins: []")   # it replaces "mixins: {}" with "mixins: []" because the first one is not valid in LinkML
        new_schema_yaml = re.sub(r'\n\s*\n$', '\n', new_schema_yaml)        # it removes possible empty lines at the end
        if operation == "Generate":
            new_schema_yaml = re.sub(
                r'prompt\.examples:\s*\'\'', 
                'prompt.examples: |\n      # no examples provided', 
                new_schema_yaml
            )

            return Response(content=new_schema_yaml)
    except RateLimitError as e:
        subject = "SchemaLink Error: OpenAI rate or fund limit exceeded"
        body = (
            f"An OpenAI request failed due to a rate or funding limit being exceeded.\n\n"
            f"Details: {str(e)}\n\nSchemaLink Notification System"
        )
        send_email(to_email=admin_email, subject=subject, message=body)

        # include 'insufficient_quota'
        return JSONResponse(status_code=429, content={"error": "Quota exceeded or rate limited", "details": str(e)})

    except APIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI API error", "details": str(e)})

    except OpenAIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI error", "details": str(e)})
    
    new_schemas_classes_match = re.search(r'^classes:\s*((?:\s{2,}.*\n)+)', new_schema_yaml, re.MULTILINE)
    if new_schemas_classes_match:
        new_schema_classes_section = new_schemas_classes_match.group(1)         # this extracts the classes section from the NEW LinkML schema
        new_schema_classes_names = re.findall(r'^\s*([A-Z][A-Za-z0-9_]+):', new_schema_classes_section, re.MULTILINE)       # this extracts only classes names from classes_section
    
    match operation:
        case "AddClassSimilarToClass" | "AddClassesSimilarToEntities":
            # it finds out which are the new classes by comparing elements of original_schema_classes_names and new_schema_classes_names
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            # it repeats the following action for each new produced class: if the class is not a "Triple" or "RelationshipType", it adds it to classes_section
            for name in new_classes:
                class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, None)

                is_a_value = extract_class_block_from_schema_UPDATED(class_block, None, "is_a")
                if is_a_value != "Triple" and is_a_value != "RelationshipType":
                    classes_section += "\n\n" + class_block
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddClassAssociatedToClass":
            # it finds out which are the new classes by comparing elements of original_schema_classes_names and new_schema_classes_names
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            # it repeats the following action for each new produced class: it adds the class to classes_section, whatever its is_a value is
            for name in new_classes:
                class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, None)
                classes_section += "\n\n" + class_block
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddParentClass":
            new_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "is_a")

            # it finds out which are the new classes by comparing elements of original_schema_classes_names and new_schema_classes_names
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            for name in new_classes:
                if name != "NamedEntity" and name == new_is_a_value:
                    classes_section = replace_class_in_schema(classes_section, classes[0], "is_a", name)
                    class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, None)
                    classes_section += "\n\n" + class_block
                    break
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddChildClass":
            # it finds out which are the new classes by comparing elements of original_schema_classes_names and new_schema_classes_names
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            # it repeats the following action for each new produced class: it adds the class to classes_section ONLY IF its is_a value is equal to the name of the class that the "Add child class" operation is called on
            for name in new_classes:
                class_block_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, "is_a")
                if class_block_is_a_value == classes[0]:
                    class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, None)
                    classes_section += "\n\n" + class_block
                    break
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddAttributesToClass":
            # it extracts the attributes of the class that the "AddAttributesToClass" operation is called on from the original schema. The original attributes are needed so that they can be compared to the ones of the same class from the new produced schema in order compare them and avoid to duplicate them.
            old_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")
            pattern = r'^[ \t]*([a-zA-Z_][\w\-]*):\n(?=(?:[ \t]{2,}))'
            attributes_names = re.findall(pattern, old_attributes_block, flags=re.MULTILINE)
            
            # it extracts the attributes of the class that the "Add attributes to class" operation is called on from the new produced schema
            new_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "attributes")
            pattern = r'^[ ]{6}([a-zA-Z_][\w\-]*):\n(?=[ ]{8})'
            attributes_names_new_schema = re.findall(pattern, new_attributes_block, flags=re.MULTILINE)
            
            # it adds to the class "attributes" column ONLY new attributes in attributes_names_new_schema
            new_attributes = set(attributes_names_new_schema) - set(attributes_names)
            old_attributes_block += '\n'
            for attribute in sorted(new_attributes):
                pattern = rf'^[ ]{{6}}{attribute}:\n(.*?)(?=^[ ]{{6}}[a-zA-Z_][\w\-]*:|\Z)'     # it extracts all the informations related to this actribute
                match = re.search(pattern, new_attributes_block, flags=re.DOTALL | re.MULTILINE)
                if match:
                    new_attribute = f"      {attribute}:\n" + match.group(1)
                    old_attributes_block += new_attribute + "\n"
            
            classes_section = replace_class_in_schema(classes_section, classes[0], "attributes", old_attributes_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddAttributesDescription":
            old_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")
            
            new_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "attributes")
            
            new_descriptions = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}description:\s*(.*)',
                new_attributes_block,
                flags=re.MULTILINE
            ))

            updated_attributes_block = old_attributes_block
            for attr, new_desc in new_descriptions.items():
                match = re.search(
                    rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}description:\s*)(.*)',
                    updated_attributes_block,
                    flags=re.MULTILINE
                )
                if match:
                    old_desc = match.group(2).strip()
                    similarity = Levenshtein.ratio(old_desc, new_desc)
                    
                    if similarity <= 0.5:           # it checks if old_desc and new_desc are different at least of 50%
                        combined_desc = f"{old_desc} {new_desc.strip('.')}".strip()
                    else:
                        combined_desc = old_desc
                    
                    # it replace the old description with the new updated one
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}description:\s*).+',
                        rf'\1{combined_desc}',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )

            classes_section = replace_class_in_schema(classes_section, classes[0], "attributes", updated_attributes_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "AnnotateClassDescription":
            old_class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None)
            
            pattern_extract = r'^\s{4}description:\s*\|?\s*(.*?)(?=(^\s{4}[a-zA-Z]+:|^\s*$))'
            match = re.search(pattern_extract, old_class_block, re.DOTALL | re.MULTILINE)
            if match:
                old_class_description = match.group(1).strip()
                if old_class_description and old_class_description.strip() != "''":
                    old_class_description = re.sub(r'>-\s*|\s+', ' ', old_class_description).strip()
                    old_class_description = re.sub(r'^>\s', '', old_class_description)
                    old_class_description = re.sub(r'[.,;!?]+$', '', old_class_description.strip())
            else:
                old_class_description = ''
            
            new_class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], None)
            pattern_extract = r'^\s{4}description:\s*\|?\s*(.*?)(?=(^\s{4}[a-zA-Z]+:|^\s*$))'
            match = re.search(pattern_extract, new_class_block, re.DOTALL | re.MULTILINE)
            if match:
                new_class_description = match.group(1).strip()
                if new_class_description and new_class_description.strip() != "''":
                    new_class_description = re.sub(r'>-\s*|\s+', ' ', new_class_description).strip()
                    new_class_description = re.sub(r'^>\s', '', new_class_description)
                    new_class_description = re.sub(r'[.,;!?]+$', '', new_class_description.strip())         # it removes the punctuation at the end
                    new_class_description = new_class_description.replace(old_class_description, "")
                    new_class_description = re.sub(r'^[\s.,;!?-]+', '', new_class_description)              # it removes the punctuation at the beginning and also blank characters and initial empty lines
            else:
                new_class_description = "''"
            
            similarity = Levenshtein.ratio(old_class_description, new_class_description)

            if similarity <= 0.2:           # it checks if old_class_description and new_class_description are different at least of 80%
                if not old_class_description:
                    description = new_class_description
                    old_class_block += "\n" + "    description: " + description
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], None, old_class_block)
                else:
                    if old_class_description.strip() == "''":
                        description = new_class_description
                    elif new_class_description == "''":
                        description = old_class_description
                    elif old_class_description.startswith(">-"):
                        description = old_class_description + ". " + new_class_description.strip()
                    else:
                        description = ">-\n      " + old_class_description + ". " + new_class_description.strip()
                    
                    old_class_block = replace_class_in_schema(old_class_block, None, "description", description)
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], None, old_class_block)
            else:
                updated_classes_section = classes_section
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AnnotateClassOntology":
            old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "id_prefixes")
            old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "annotations")
            
            old_annotators_values = extract_class_block_from_schema_UPDATED(old_annotations_block, None, "annotators")
            if old_annotators_values is not None:
                old_annotators_values = old_annotators_values.lstrip('\n').rstrip('\n')
                old_annotators_values = ', '.join(line.strip('- ').strip() for line in old_annotators_values.splitlines() if line.strip())
                old_annotators_list = old_annotators_values.split(", ")
                old_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in old_annotators_list]
            else:
                old_list_id_prefixes = []

            new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "annotations")

            new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
            if new_annotators_values is not None:
                new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                new_annotators_list = new_annotators_values.split(", ")
                new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
            else:
                new_list_id_prefixes = []

            id_prefixes_difference = list(set(new_list_id_prefixes) - set(old_list_id_prefixes))

            if len(id_prefixes_difference) >= 1 and old_id_prefixes_block == "[]":
                old_id_prefixes_block = old_id_prefixes_block.replace("[]", "")

            for item in id_prefixes_difference:
                old_id_prefixes_block += "\n      - " + item
                if old_annotators_values is None:
                    old_annotators_values = "sqlite:obo:" + item.lower()
                else:
                    old_annotators_values += ", sqlite:obo:" + item.lower()

            if old_annotations_block == "{}" and new_annotators_values is not None:
                old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
            if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                updated_classes_section = replace_class_in_schema(classes_section, classes[0], "id_prefixes", old_id_prefixes_block)
                old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", old_annotators_values)
                updated_classes_section = replace_class_in_schema(updated_classes_section, classes[0], "annotations", old_annotations_block)
            else:
                updated_classes_section = classes_section
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AnnotateClassExample":
            old_prompt_example = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "prompt.examples")
            if old_prompt_example is not None:
                old_prompt_example = re.sub(r'>-\s*|\s+', ' ', old_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                old_prompt_example = re.sub(r'^>\s', '', old_prompt_example)                    # it removes possible > from the string
                old_prompt_example = re.sub(r'[.,;]+$', '', old_prompt_example.strip())         # it removes the punctuation at the end of the string

            new_prompt_example = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "prompt.examples")
            if new_prompt_example is not None:
                if new_prompt_example.count("'") > 1:
                    new_prompt_example = new_prompt_example[0] + new_prompt_example[1:-1].replace("'", "’") + new_prompt_example[-1]
                new_prompt_example = re.sub(r'>-\s*|\s+', ' ', new_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                new_prompt_example = re.sub(r'^>\s', '', new_prompt_example)                    # it removes possible > from the string
                new_prompt_example = re.sub(r'[.,;]+$', '', new_prompt_example.strip())

            if new_prompt_example != None:
                new_example_list = [example.strip() for example in new_prompt_example.split(',')]
                
                if old_prompt_example is None or old_prompt_example == "''":
                    old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "annotations")
                    
                    class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None)

                    if old_annotations_block == "{}":
                        new_annotations_block = "      prompt.examples: " + new_prompt_example
                        class_block = class_block.replace("    annotations: {}", "    annotations:\n" + new_annotations_block)
                    else:
                        new_annotations_block = old_annotations_block.replace("      prompt.examples: ''", "")
                        new_prompt_example = new_prompt_example.split(",")
                        new_prompt_example = [s.replace(",", "") for s in new_prompt_example]
                        new_prompt_example = ",".join(new_prompt_example)
                        new_annotations_block += "\n      prompt.examples: " + new_prompt_example
                        class_block = class_block.replace(old_annotations_block, new_annotations_block)
                    
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], None, class_block)
                else:
                    old_example_list = [example.strip() for example in old_prompt_example.split(',')]
                    old_prompt_example = "        " + old_prompt_example
                    for new_example in new_example_list:
                        if new_example not in old_example_list:
                            old_prompt_example += ", " + new_example
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], "prompt.examples", old_prompt_example)
            else:
                updated_classes_section = classes_section
            
            pattern_remove_prompt_examples = re.compile(r'(\s+range:\s+' + re.escape(classes[0]) + r'\s+annotations:\s*)\n?(\s*[^p][^\n]+)*\s*prompt\.examples:.*?(\n\s+[^ ]|$)', re.DOTALL)
            updated_classes_section = re.sub(pattern_remove_prompt_examples, r'\1\2', updated_classes_section)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixClassExample":
            old_prompt_example = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "prompt.examples")
            if old_prompt_example is not None:
                old_prompt_example = re.sub(r'>-\s*|\s+', ' ', old_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                old_prompt_example = re.sub(r'^>\s', '', old_prompt_example)                    # it removes possible > from the string
                old_prompt_example = re.sub(r'[.,;]+$', '', old_prompt_example.strip())         # it removes the punctuation at the end of the string

            new_prompt_example = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "prompt.examples")
            if new_prompt_example is not None:
                if new_prompt_example.count("'") > 1:
                    new_prompt_example = new_prompt_example[0] + new_prompt_example[1:-1].replace("'", "’") + new_prompt_example[-1]
                new_prompt_example = re.sub(r'>-\s*|\s+', ' ', new_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                new_prompt_example = re.sub(r'^>\s', '', new_prompt_example)                    # it removes possible > from the string
                new_prompt_example = re.sub(r'[.,;]+$', '', new_prompt_example.strip())
            
            if new_prompt_example != None:
                if old_prompt_example is None or old_prompt_example == "''":
                    old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "annotations")
                    
                    class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None)
                    
                    if old_annotations_block == "{}":
                        new_annotations_block = "      prompt.examples: " + new_prompt_example
                        class_block = class_block.replace("    annotations: {}", "    annotations:\n" + new_annotations_block)
                    else:
                        new_annotations_block = old_annotations_block.replace("      prompt.examples: ''", "")
                        new_prompt_example = new_prompt_example.split(",")
                        new_prompt_example = [s.replace(",", "") for s in new_prompt_example]
                        new_prompt_example = ",".join(new_prompt_example)
                        new_annotations_block += "\n      prompt.examples: " + new_prompt_example
                        class_block = class_block.replace(old_annotations_block, new_annotations_block)
                    
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], None, class_block)
                else:
                    old_prompt_example = "        " + new_prompt_example
                    updated_classes_section = replace_class_in_schema(classes_section, classes[0], "prompt.examples", old_prompt_example)
            else:
                updated_classes_section = classes_section
            
            pattern_remove_prompt_examples = re.compile(r'(\s+range:\s+' + re.escape(classes[0]) + r'\s+annotations:\s*)\n?(\s*[^p][^\n]+)*\s*prompt\.examples:.*?(\n\s+[^ ]|$)', re.DOTALL)
            updated_classes_section = re.sub(pattern_remove_prompt_examples, r'\1\2', updated_classes_section)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixClassOntology":
            old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "id_prefixes")
            old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "annotations")

            new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "annotations")

            new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")

            if new_annotators_values is not None:
                new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                
                new_annotators_list = new_annotators_values.split(", ")
                
                new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
            else:
                new_list_id_prefixes = []
            
            if len(new_list_id_prefixes) == 0:
                updated_id_prefixes_block = "{}"
            else:
                updated_id_prefixes_block = ""
            
            for item in new_list_id_prefixes:
                updated_id_prefixes_block += "\n      - " + item
            
            if old_annotations_block == "{}" and new_annotators_values is not None:
                old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
            if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                updated_classes_section = replace_class_in_schema(classes_section, classes[0], "id_prefixes", updated_id_prefixes_block)
                old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", new_annotators_values)
                updated_classes_section = replace_class_in_schema(updated_classes_section, classes[0], "annotations", old_annotations_block)
            else:
                updated_classes_section = classes_section
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixClassName":
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)
            
            closest_class = None
            min_distance = float('inf')         # it initializes min_distance to an infinite distance
            for name in new_classes:
                distance = Levenshtein.distance(name, classes[0])
                if distance < min_distance and name:
                    min_distance = distance
                    closest_class = name
            pattern = rf'^(  ){re.escape(classes[0])}:'
            classes_section = re.sub(pattern, rf'  {closest_class}:', classes_section, flags=re.MULTILINE)
            classes_section = re.sub(rf'(^[ \t]*range:\s*){re.escape(classes[0])}\n', 
                             rf'\1{closest_class}\n', 
                             classes_section, 
                             flags=re.MULTILINE)
            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixClassDescription":
            # it creates a copy of the informations of the class, making sure to remove the "attributes" informations so that the attributes "description" values are not mistaken with the class "description" value
            classes_section_copy = replace_class_in_schema(classes_section, classes[0], "attributes", "")
            
            old_description = extract_class_block_from_schema_UPDATED(classes_section_copy, classes[0], "description")
            new_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "description")
            if new_description is not None:
                new_description = new_description.removeprefix(">-\n")
            else:
                new_description = old_description
                    
            if old_description is None:
                new_class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None)
                new_class_block += "\n    description: " + new_description + "\n"
                classes_section = replace_class_in_schema(classes_section, classes[0], None, new_class_block)
            else:
                classes_section = replace_class_in_schema(classes_section, classes[0], "description", new_description)
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixClassAttributesName":
            old_class_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")
            
            pattern = re.compile(r'(\S+):(?:\n\s+\S+:.*)*?\n\s+description:\s*(.*?)(?=\n\s*\S+:|$)', re.DOTALL)
            
            old_description_map = {}        # dict that maps the attribute and its description. This is needed to make the similarity check

            for match in pattern.finditer(old_class_attributes_block):
                attribute = match.group(1)
                description = match.group(2).strip()

                # it removes the first line if it starts with >
                if description.startswith(">"):
                    description = description.split("\n", 1)[1]
                
                description = re.sub(r'^\s+', '', description)          # it removes indentation
                description = ' '.join(line.strip() for line in description.splitlines())           # it removes blank characters in each line

                old_description_map[attribute] = description
            
            new_class_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "attributes")
            new_description_map = {}
            for match in pattern.finditer(new_class_attributes_block):
                attribute = match.group(1)
                description = match.group(2).strip()
                
                # it removes the first line if it starts with >
                if description.startswith(">"):
                    description = description.split("\n", 1)[1]
                
                description = re.sub(r'^\s+', '', description)          # it removes indentation
                description = ' '.join(line.strip() for line in description.splitlines())           # it removes blank characters in each line

                new_description_map[attribute] = description
            
            for old_key, old_value in old_description_map.items():
                min_distance = float('inf')     # this is used to store the Levenshtein distance of the most similar description
                best_match_key = None           # this is used to store the most similar description

                for new_key, new_value in new_description_map.items():
                    distance = Levenshtein.distance(old_value, new_value)

                    if distance < min_distance:
                        min_distance = distance
                        best_match_key = new_key
                
                if best_match_key:          # it replaces the old description with the most similar one if the most similar one was found
                    old_class_attributes_block = re.sub(r'^\s{6}' + re.escape(old_key) + r':', f'      {best_match_key}:', old_class_attributes_block, count=1, flags=re.MULTILINE)
            
            old_class_attributes_block = old_class_attributes_block.rstrip('\n')
            updated_classes_section = replace_class_in_schema(classes_section, classes[0], "attributes", old_class_attributes_block)
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixClassAttributesDescription":
            old_class_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")

            new_class_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "attributes")
            
            new_descriptions = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}description:\s*(.*)',
                new_class_attributes_block,
                flags=re.MULTILINE
            ))

            updated_attributes_block = old_class_attributes_block
            for attr, new_desc in new_descriptions.items():
                updated_attributes_block = re.sub(
                    rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}description:\s*).+',
                    rf'\1{new_desc}',
                    updated_attributes_block,
                    flags=re.MULTILINE
                )

            updated_classes_section = replace_class_in_schema(classes_section, classes[0], "attributes", updated_attributes_block)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixClassAttributesType":
            old_class_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")

            new_class_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, classes[0], "attributes")
            
            new_types = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}range:\s*(.*)',
                new_class_attributes_block,
                flags=re.MULTILINE
            ))

            # it extracts the multivalued attributes from the class of the new produced schema
            multivalued_attrs_new = set(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}multivalued:\s*true',
                new_class_attributes_block,
                flags=re.MULTILINE
            ))

            # it extracts the multivalued attributes from the class of the original schema
            multivalued_attrs_orig = set(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}multivalued:\s*true',
                old_class_attributes_block,
                flags=re.MULTILINE
            ))

            attributes_with_array = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}array:\n\s{10}exact_number_dimensions:\s*(\d+)',
                old_class_attributes_block,
                flags=re.MULTILINE
            ))


            new_attributes_with_array = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}array:\n\s{10}exact_number_dimensions:\s*(\d+)',
                new_class_attributes_block,
                flags=re.MULTILINE
            ))

            updated_attributes_block = old_class_attributes_block
            for attr, new_type in new_types.items():
                # it replaces only the attribute "type:" value in the original class attributes section
                updated_attributes_block = re.sub(
                    rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}range:\s*).+',
                    rf'\1{new_type}',
                    updated_attributes_block,
                    flags=re.MULTILINE
                )
                # it adds "multivalued: true" if it is in the attribute's new informations but NOT in the original ones
                if attr in multivalued_attrs_new and attr not in multivalued_attrs_orig:
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)((?:\s{{8}}range:.*\n))',
                        rf'\1        multivalued: true\n\2',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                # it removes "multivalued: true" if it is in the attribute's original informations but NOT in the new ones
                elif attr in multivalued_attrs_orig and attr not in multivalued_attrs_new:
                    updated_attributes_block = re.sub(
                        rf'(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)\s{{8}}multivalued:\s*true\n',
                        rf'\1',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                
                if attr in attributes_with_array and attr not in new_attributes_with_array:
                    updated_attributes_block = re.sub(
                        rf'(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)\s{{8}}array:\s+exact_number_dimensions:\s+\d+\n',
                        rf'\1',  # it removes the "array" informations
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                elif attr not in attributes_with_array and attr in new_attributes_with_array:
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)',
                        rf'\1        array:\n            exact_number_dimensions: {new_attributes_with_array[attr]}\n',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )

            updated_classes_section = replace_class_in_schema(classes_section, classes[0], "attributes", updated_attributes_block+"\n")
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "ReifyClass":
            old_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], "attributes")
            old_attributes_block = '\n'.join([line for line in old_attributes_block.split('\n') if line.strip() != ''])
            pattern = r'^[ \t]*([a-zA-Z_][\w\-]*):\n(?=(?:[ \t]{2,}))'
            attributes_names = re.findall(pattern, old_attributes_block, flags=re.MULTILINE)

            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            added_named_etities = []        # it contains the classes that are progressively added to the schema
            classes_to_add = []         # it contains class whose is_a value is NOT "NamedEntity" (so they have a parent class) and whose parent class has not been added to classes_section yet
            
            for attribute in attributes_names:
                for new_class in new_classes:
                    new_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, "is_a")
                    
                    if (new_class_is_a_value == "NamedEntity" or new_class_is_a_value in new_schema_classes_names) and attribute.lower() in new_class.lower():
                        classes_section += '\n\n' + extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, None)
                        classes_section = replace_class_in_schema(classes_section, classes[0], attribute, "")
                        
                        old_class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None).lstrip('\n')
                        
                        updated_class_block = extract_class_block_from_schema_UPDATED(classes_section, classes[0], None).lstrip('\n')
                        
                        pattern = re.compile(r'^\s*' + re.escape(attribute) + r':\s*\n\s*\n', re.MULTILINE)
                        updated_class_block = re.sub(pattern, '', updated_class_block)          # this instruction is used to remove the attribute's name from the class attributes section. This is needed because a previous instruction that uses replace_class_in_schema function only removes attribute's informations, but not also its name
                        
                        old_class_pattern = re.escape(old_class_block).replace(r'\s+', r'\s+')
                        classes_section = re.sub(old_class_pattern, updated_class_block, classes_section)
                        
                        new_classes.remove(new_class)
                        added_named_etities.append(new_class)

                        if new_class_is_a_value != "NamedEntity" and new_class_is_a_value not in original_schema_classes_names:
                            classes_to_add.append(new_class_is_a_value)
                        break
            
            for new_class in new_classes:
                new_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, "is_a").strip()
                
                if new_class in classes_to_add and (new_class_is_a_value in original_schema_classes_names or new_class_is_a_value in added_named_etities):
                    classes_section += '\n\n' + extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, None)
                
                match new_class_is_a_value:
                    case "RelationshipType":
                        classes_section += '\n\n' + extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, None)
                    case "Triple":
                        class_block = extract_class_block_from_schema_UPDATED(new_schema_yaml, new_class, None)
                        for added_class in added_named_etities:
                            if f"range: {classes[0]}" in class_block and f"range: {added_class}" in class_block:
                                classes_section += '\n\n' + class_block
                                break
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AddAttributesToRelationship":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a").strip()
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a").strip()
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            # it extracts predicate's informations (description, slot_usage, etc.) from classes_section
            relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")

            # the following code save the initial part of slot_usage, so the part made by "subject:", "object:" e "predicate:"
            subject_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "subject")
            object_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "object")
            predicate_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "predicate")
            intro_slot_usage = "      subject:\n" + subject_block + "\n      object:\n" + object_block + "\n      predicate:\n" + predicate_block
            
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "subject", "")
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "object", "")
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "predicate", "")
            relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = relationship_attributes_block.lstrip('\n')
            
            # it finds out which are the names of predicate's attributes from the original schema
            pattern = r'^[ \t]*([a-zA-Z_][\w\-]*):\n(?=(?:[ \t]{2,}))'
            existing_attributes_names = re.findall(pattern, relationship_attributes_block, flags=re.MULTILINE)
            
            # it extracts predicate's informations from the new produced schema
            new_schema_relationship_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "slot_usage")

            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "subject", "")
            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "object", "")
            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "predicate", "")
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = new_schema_relationship_attributes_block.lstrip('\n')
            
            new_schema_attributes_names = re.findall(pattern, new_schema_relationship_attributes_block, flags=re.MULTILINE)
            
            new_attributes = set(new_schema_attributes_names) - set(existing_attributes_names)
            
            relationship_attributes_block += "\n"
            i = 0
            for attribute in new_attributes:
                pattern = rf'^[ ]{{6}}{attribute}:\n(.*?)(?=^[ ]{{6}}[a-zA-Z_][\w\-]*:|\Z)'
                match = re.search(pattern, new_schema_relationship_attributes_block, flags=re.DOTALL | re.MULTILINE)
                if i == 0:
                    new_attribute = f"      {attribute}:\n" + match.group(1)
                    i += 1
                else:
                    new_attribute = f"\n      {attribute}:\n" + match.group(1)
                relationship_attributes_block += new_attribute
            
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", intro_slot_usage + "\n" + relationship_attributes_block)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AddRelationshipAttributesDescription":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")

            # the following code save the initial part of slot_usage, so the part made by "subject:", "object:" e "predicate:"
            subject_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "subject")
            object_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "object")
            predicate_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "predicate")
            intro_slot_usage = "      subject:\n" + subject_block + "\n      object:\n" + object_block + "\n      predicate:\n" + predicate_block
            
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "subject", "")
            relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "object", "")
            relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = replace_class_in_schema(relationship_attributes_block, None, "predicate", "")
            relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', relationship_attributes_block, flags=re.MULTILINE)
            relationship_attributes_block = relationship_attributes_block.lstrip('\n')
            
            new_schema_relationship_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "slot_usage")

            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "subject", "")
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "object", "")
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = replace_class_in_schema(new_schema_relationship_attributes_block, None, "predicate", "")
            new_schema_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', new_schema_relationship_attributes_block, flags=re.MULTILINE)
            new_schema_relationship_attributes_block = new_schema_relationship_attributes_block.lstrip('\n')
            
            pattern_attribute_name = r"^\s{6}([\w\_]+):"
            
            attributes_names = re.findall(pattern_attribute_name, new_schema_relationship_attributes_block, re.MULTILINE)

            description_map = {}

            for attribute in attributes_names:
                pattern_description = r"^\s{6}" + re.escape(attribute) + r":\s*description:\s*(?P<continua>(\s*>\-\s*)?([\s\S]+?))(?=\n\s{2,}[\w_]+:|\Z)"
                match_description = re.search(pattern_description, new_schema_relationship_attributes_block, re.MULTILINE)
                if match_description:
                    if match_description.group(1).startswith(">-"):
                        description = match_description.group(3).strip().replace("\n", " ").strip()
                    else:
                        description = match_description.group(1)
                    description = re.sub(r'\s+', ' ', description)
                    description_map[attribute] = description

            updated_attributes_block = relationship_attributes_block
            for attr, new_desc in description_map.items():
                pattern_description = r"^\s{6}" + re.escape(attr) + r":\s*description:\s*(?P<continua>(\s*>\-\s*)?([\s\S]+?))(?=\n\s{2,}[\w_]+:|\Z)"
                match = re.search(
                    pattern_description,
                    updated_attributes_block,
                    flags=re.MULTILINE
                )
                if match:
                    if match.group(1).startswith(">-"):
                        old_desc = match.group(3).strip().replace("\n", " ").strip()
                        old_desc = re.sub(r'\s+', ' ', old_desc)
                    else:
                        old_desc = match.group(1)
                    
                    similarity = Levenshtein.ratio(old_desc, new_desc)
                    if similarity <= 0.2:           # it checks if old_desc and new_desc are different at least of 80%
                        if old_desc != "''":
                            combined_desc = f"{old_desc} {new_desc}".strip()
                        else:
                            combined_desc = new_desc
                    else:
                        combined_desc = old_desc
                    
                    # it replaces the old description with the new updated one
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}description:\s*).+',
                        rf'\1{combined_desc}',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )

            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", intro_slot_usage + "\n" + updated_attributes_block)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AnnotateRelationshipOntology":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Predicate", "is_a")
            if class_is_a_value != "RelationshipType" or new_schema_class_is_a_value != "RelationshipType":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "id_prefixes")
            old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "annotations")
            old_annotators_values = extract_class_block_from_schema_UPDATED(old_annotations_block, None, "annotators")
            if old_annotators_values is not None:
                old_annotators_values = old_annotators_values.lstrip('\n').rstrip('\n')
                old_annotators_values = ', '.join(line.strip('- ').strip() for line in old_annotators_values.splitlines() if line.strip())
                
                old_annotators_list = old_annotators_values.split(", ")
                
                old_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in old_annotators_list]
            else:
                old_list_id_prefixes = []

            new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Predicate", "annotations")

            new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
            if new_annotators_values is not None:
                new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                
                new_annotators_list = new_annotators_values.split(", ")
                
                new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
            else:
                new_list_id_prefixes = []
            
            id_prefixes_difference = list(set(new_list_id_prefixes) - set(old_list_id_prefixes))
            
            if len(id_prefixes_difference) >= 1 and old_id_prefixes_block == "[]":
                old_id_prefixes_block = old_id_prefixes_block.replace("[]", "")

            for item in id_prefixes_difference:
                old_id_prefixes_block += "\n      - " + item
                if old_annotators_values is None:
                    old_annotators_values = "sqlite:obo:" + item.lower()
                else:
                    old_annotators_values += ", sqlite:obo:" + item.lower()

            if old_annotations_block == "{}" and new_annotators_values is not None:
                old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
            if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Predicate", "id_prefixes", old_id_prefixes_block)
                old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", old_annotators_values)
                updated_classes_section = replace_class_in_schema(updated_classes_section, associations[0] + "Predicate", "annotations", old_annotations_block)
            else:
                updated_classes_section = classes_section

            updated_final_schema = intro_schema + "\n" + updated_classes_section

            updated_final_schema = new_schema_yaml.replace("sqlite:obo:gene_ontology", "sqlite:obo:go")  # it replaces the obsolete gene_ontology with go, as required by LinkML
            updated_final_schema = re.sub(r'-\s*[A-Z0-9_]+:\s*"http://purl\.obolibrary\.org/obo/([a-z0-9_]+)\.owl"', r'- sqlite:obo:\1', updated_final_schema)
            updated_final_schema = re.sub(r"(sqlite:obo:[a-z0-9_]+):[^,\s]+", r"\1", updated_final_schema)
            # sostituisci array di annotators con stringhe separate da virgola
            # cattura pattern come:
            # annotators:
            #   - sqlite:obo:ro
            #   - sqlite:obo:so
            pattern = r"annotators:\s*\n((?:\s*-\s*[^\n]+\n)+)"

            def array_to_string(match):
                items = match.group(1)
                # prendi ogni riga, rimuovi - e spazi
                cleaned = [i.replace("-", "").strip() for i in items.splitlines() if i.strip()]
                return f'annotators: "{", ".join(cleaned)}"'

            updated_final_schema = re.sub(pattern, array_to_string, updated_final_schema)

        case "AnnotateRelationshipExample":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            relationship_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", None)
            
            pattern = re.compile(r'^\s{4}annotations:\s*(.*?)(?=^\s{4}\S|\Z)', re.DOTALL | re.MULTILINE)
            matches = pattern.findall(relationship_block)
            for match in matches:
                relationship_annotations_block = match
            
            relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', relationship_annotations_block)
            
            new_relationship_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", None).lstrip('\n')

            matches = pattern.findall(new_relationship_block)
            for match in matches:
                new_relationship_annotations_block = match
            
            new_relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', new_relationship_annotations_block)
            
            similarity = Levenshtein.ratio(relationship_prompt_examples_value, new_relationship_prompt_examples_value)
            
            if similarity <= 0.25:           # it checks if relationship_prompt_examples_value and new_relationship_prompt_examples_value are different at least of 75%
                if not relationship_prompt_examples_value:
                    prompt_examples = new_relationship_prompt_examples_value
                    updated_relationship_annotations_block = relationship_annotations_block
                    updated_relationship_annotations_block = updated_relationship_annotations_block.replace("{}", "")
                    updated_relationship_annotations_block += "\n      prompt.examples: " + prompt_examples
                else:
                    if relationship_prompt_examples_value.strip() == "''":
                        prompt_examples = new_relationship_prompt_examples_value
                    else:
                        prompt_examples = relationship_prompt_examples_value + ". " + new_relationship_prompt_examples_value
                    updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, "prompt.examples", prompt_examples)
                
                pattern = r'(^\s{4}annotations:\s*)(.*?)(?=\n\s{4}\S|\Z)'       # it finds out "annotations" section
                relationship_block = re.sub(pattern, r'\1' + updated_relationship_annotations_block, relationship_block, flags=re.DOTALL | re.MULTILINE)
            else:
                updated_classes_section = classes_section

            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", None, relationship_block)
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AnnotateRelationshipDescription":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            old_relationship_description = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "description")
            new_relationship_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "description").rstrip('\n').lstrip("\n>-\\n")
            new_relationship_description = re.sub(r'\s+', ' ', new_relationship_description)

            similarity = Levenshtein.ratio(old_relationship_description, new_relationship_description)
            
            old_class_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", None)

            if similarity <= 0.50:           # it checks if old_relationship_description and new_relationship_description are different at least of 50%
                if not old_relationship_description:
                    description = new_relationship_description
                    old_class_block += "\n" + "    description: " + description
                    updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", None, old_class_block)
                else:
                    if old_relationship_description.strip() == "''":
                        description = new_relationship_description
                    else:
                        description = old_relationship_description + ". " + new_relationship_description
                    old_class_block = old_class_block.replace(old_relationship_description, description)
                    updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", None, old_class_block)
            else:
                updated_classes_section = classes_section

            print(updated_classes_section)
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipName":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)
            if extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Predicate", None) is not None:
                new_classes.add(associations[0] + "Predicate")
            
            closest_class = None
            min_distance = float('inf')         # it initializes min_distance to an infinite distance
            for name in new_classes:
                distance = Levenshtein.distance(name, associations[0] + "Predicate")
                if distance < min_distance:
                    min_distance = distance
                    closest_class = name
            
            # the following code checks if the closest_class is a Triple
            predicate_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, closest_class, "is_a")
            if predicate_class_is_a_value != "RelationshipType":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            predicate_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, closest_class, "attributes").lstrip('\n').rstrip('\n')
            predicate_id_pattern_value = extract_class_block_from_schema_UPDATED(predicate_attributes_block, None, "id").strip()
            predicate_id_pattern_value = predicate_id_pattern_value[len("pattern: '"):]
            predicate_id_pattern_value = predicate_id_pattern_value[:predicate_id_pattern_value.find("'")]
            
            relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")
            subject_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "subject").lstrip('\n').rstrip('\n')
            subject_range_value = extract_class_block_from_schema_UPDATED(subject_block, None, "range").strip().lower()
            
            object_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "object").lstrip('\n').rstrip('\n')
            object_range_value = extract_class_block_from_schema_UPDATED(object_block, None, "range").strip().lower()
            
            if predicate_id_pattern_value.lower().startswith(subject_range_value):      # if the predicate pattern value starts with the name of the subject class, this instruction removes that name, so that the final pattern won't include it in in order to avoid repeating the name twice (e.g. if the pattern is "drug is substance that treats", the final one will be "is substance that treats" so that the relationship name won't be "DrugDrugIsSubstanceThatTreatsDisease", but it will be "DrugIsSubstanceThatTreatsDisease")
                predicate_id_pattern_value = predicate_id_pattern_value[len(subject_range_value):]
            if predicate_id_pattern_value.lower().endswith(object_range_value):         # it checks if the predicate pattern value ends with the name of the object class and, if so, this instruction does the same thing as the previous one
                predicate_id_pattern_value = predicate_id_pattern_value[: -len(object_range_value)]
            predicate_id_pattern_value = predicate_id_pattern_value.strip()
            
            predicate_attributes_block = replace_class_in_schema(predicate_attributes_block, None, "id", "        pattern: '" + predicate_id_pattern_value + "'")
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Predicate", "attributes", predicate_attributes_block)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipDescription":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            # it creates a copy of the informations of the class, making sure to remove the "slot_usage" informations so that the attributes "description" values are not mistaken with the class "description" value
            classes_section_copy = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", "")
            
            old_description = extract_class_block_from_schema_UPDATED(classes_section_copy, associations[0] + "Relationship", "description")
            new_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "description")
            if new_description is not None:
                new_description = new_description.removeprefix(">-\n")
            else:
                new_description = old_description
                    
            if old_description is None:
                new_class_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", None)
                new_class_block += "\n    description: " + new_description + "\n"
                classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", None, new_class_block)
            else:
                classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "description", new_description)
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixRelationshipAttributesName":
            print("FixRelationshipAttributesName")
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            old_relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")

            subject_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "subject")
            object_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "object")
            predicate_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "predicate")
            intro_slot_usage = "      subject:\n" + subject_block + "\n      object:\n" + object_block + "\n      predicate:\n" + predicate_block
            
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "subject", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "object", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "predicate", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = old_relationship_attributes_block.lstrip('\n')
            
            pattern = re.compile(r'(\S+):(?:\n\s+\S+:.*)*?\n\s+description:\s*(.*?)(?=\n\s*\S+:|$)', re.DOTALL)
            
            old_description_map = {}        # dict that maps the attribute and its description. This is needed to make the similarity check
            
            for match in pattern.finditer(old_relationship_attributes_block):
                attribute = match.group(1)
                description = match.group(2).strip()

                # it removes the first line if it starts with >
                if description.startswith(">"):
                    description = description.split("\n", 1)[1]
                
                description = re.sub(r'^\s+', '', description)          # it removes indentation
                description = ' '.join(line.strip() for line in description.splitlines())           # it removes blank characters in each line

                old_description_map[attribute] = description
            
            new_relationship_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "slot_usage")
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "subject", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "object", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "predicate", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = new_relationship_attributes_block.lstrip('\n')

            print("New Relationship Attributes Block:")
            print(new_relationship_attributes_block)
            
            new_description_map = {}
            for match in pattern.finditer(new_relationship_attributes_block):
                attribute = match.group(1)
                description = match.group(2).strip()
                
                # it removes the first line if it starts with >
                if description.startswith(">"):
                    description = description.split("\n", 1)[1]
                
                description = re.sub(r'^\s+', '', description)          # it removes indentation
                description = ' '.join(line.strip() for line in description.splitlines())           # it removes blank characters in each line

                new_description_map[attribute] = description
            
            for old_key, old_value in old_description_map.items():
                min_distance = float('inf')     # this is used to store the Levenshtein distance of the most similar description
                best_match_key = None           # this is used to store the most similar description

                for new_key, new_value in new_description_map.items():
                    distance = Levenshtein.distance(old_value, new_value)

                    if distance < min_distance:
                        min_distance = distance
                        best_match_key = new_key
                
                if best_match_key:          # it replaces the old description with the most similar one if the most similar one was found
                    old_relationship_attributes_block = re.sub(r'^\s{6}' + re.escape(old_key) + r':', f'      {best_match_key}:', old_relationship_attributes_block, count=1, flags=re.MULTILINE)
            
            old_relationship_attributes_block = old_relationship_attributes_block.lstrip('\n').rstrip('\n')
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", intro_slot_usage + "\n" + old_relationship_attributes_block)
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipAttributesType":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            old_relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")

            subject_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "subject")
            object_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "object")
            predicate_block = extract_class_block_from_schema_UPDATED(old_relationship_attributes_block, None, "predicate")
            intro_slot_usage = "      subject:\n" + subject_block + "\n      object:\n" + object_block + "\n      predicate:\n" + predicate_block
            
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "subject", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "object", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = replace_class_in_schema(old_relationship_attributes_block, None, "predicate", "")
            old_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', old_relationship_attributes_block, flags=re.MULTILINE)
            old_relationship_attributes_block = old_relationship_attributes_block.lstrip('\n')
            
            new_relationship_attributes_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "slot_usage")
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "subject", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*subject:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "object", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*object:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = replace_class_in_schema(new_relationship_attributes_block, None, "predicate", "")
            new_relationship_attributes_block = re.sub(r'^[ \t]*predicate:\n', '', new_relationship_attributes_block, flags=re.MULTILINE)
            new_relationship_attributes_block = new_relationship_attributes_block.lstrip('\n')
            
            new_types = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}range:\s*(.*)',
                new_relationship_attributes_block,
                flags=re.MULTILINE
            ))

            # it extracts the multivalued attributes from the class of the new produced schema
            multivalued_attrs_new = set(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}multivalued:\s*true',
                new_relationship_attributes_block,
                flags=re.MULTILINE
            ))

            # it extracts the multivalued attributes from the class of the original schema
            multivalued_attrs_orig = set(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}multivalued:\s*true',
                old_relationship_attributes_block,
                flags=re.MULTILINE
            ))

            attributes_with_array = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}array:\n\s{10}exact_number_dimensions:\s*(\d+)',
                old_relationship_attributes_block,
                flags=re.MULTILINE
            ))


            new_attributes_with_array = dict(re.findall(
                r'^\s{6}([a-zA-Z_][\w\-]*):\n(?:\s{8}.*\n)*?\s{8}array:\n\s{10}exact_number_dimensions:\s*(\d+)',
                new_relationship_attributes_block,
                flags=re.MULTILINE
            ))

            updated_attributes_block = old_relationship_attributes_block
            for attr, new_type in new_types.items():
                # it replaces only the attribute "type:" value in the original class attributes section
                updated_attributes_block = re.sub(
                    rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?\s{{8}}range:\s*).+',
                    rf'\1{new_type}',
                    updated_attributes_block,
                    flags=re.MULTILINE
                )
                # it adds "multivalued: true" if it is in the attribute's new informations but NOT in the original ones
                if attr in multivalued_attrs_new and attr not in multivalued_attrs_orig:
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)((?:\s{{8}}range:.*\n))',
                        rf'\1        multivalued: true\n\2',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                # it removes "multivalued: true" if it is in the attribute's original informations but NOT in the new ones
                elif attr in multivalued_attrs_orig and attr not in multivalued_attrs_new:
                    updated_attributes_block = re.sub(
                        rf'(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)\s{{8}}multivalued:\s*true\n',
                        rf'\1',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                
                if attr in attributes_with_array and attr not in new_attributes_with_array:
                    updated_attributes_block = re.sub(
                        rf'(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)\s{{8}}array:\s+exact_number_dimensions:\s+\d+\n',
                        rf'\1',  # it removes the "array" informations
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
                elif attr not in attributes_with_array and attr in new_attributes_with_array:
                    updated_attributes_block = re.sub(
                        rf'^(\s{{6}}{re.escape(attr)}:\n(?:\s{{8}}.*\n)*?)',
                        rf'\1        array:\n            exact_number_dimensions: {new_attributes_with_array[attr]}\n',
                        updated_attributes_block,
                        flags=re.MULTILINE
                    )
            
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", intro_slot_usage + "\n" + updated_attributes_block)
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipOntology":
            # the following code checks if class named as associations[0] + "Predicate" is a RelationshipType
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Predicate", "is_a")
            if class_is_a_value != "RelationshipType" or new_schema_class_is_a_value != "RelationshipType":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "id_prefixes")
            old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Predicate", "annotations")

            new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Predicate", "annotations")
            
            new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
            if new_annotators_values is not None:
                new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                
                new_annotators_list = new_annotators_values.split(", ")
                
                new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
            else:
                new_list_id_prefixes = []
            
            if len(new_list_id_prefixes) == 0:
                updated_id_prefixes_block = "{}"
            else:
                updated_id_prefixes_block = ""
            
            for item in new_list_id_prefixes:
                updated_id_prefixes_block += "\n      - " + item

            if old_annotations_block == "{}" and new_annotators_values is not None:
                old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
            if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Predicate", "id_prefixes", updated_id_prefixes_block)
                old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", new_annotators_values)
                updated_classes_section = replace_class_in_schema(updated_classes_section, associations[0] + "Predicate", "annotations", old_annotations_block)
            else:
                updated_classes_section = classes_section
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipExample":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            relationship_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", None).lstrip('\n')
            
            pattern = re.compile(r'^\s{4}annotations:\s*(.*?)(?=^\s{4}\S|\Z)', re.DOTALL | re.MULTILINE)        # funzionante
            matches = pattern.findall(relationship_block)
            for match in matches:
                relationship_annotations_block = match

            new_relationship_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", None).lstrip('\n')
            
            matches = pattern.findall(new_relationship_block)
            for match in matches:
                new_relationship_annotations_block = match
            
            new_relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', new_relationship_annotations_block)
            
            if relationship_annotations_block == "{}":
                updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, None, new_relationship_annotations_block)
            else:
                updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, "prompt.examples", new_relationship_prompt_examples_value)
            
            pattern = r'(^\s{4}annotations:\s*)(.*?)(?=\n\s{4}\S|\Z)'
            relationship_block = re.sub(pattern, r'\1' + updated_relationship_annotations_block, relationship_block, flags=re.DOTALL | re.MULTILINE)
            
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", None, relationship_block)
            
            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "FixRelationshipCardinality":
            # the following code checks if class named as associations[0] + "Relationship" is a Triple
            class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "is_a")
            new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "is_a")
            if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                updated_final_schema = intro_schema + "\n" + classes_section
                return Response(content=updated_final_schema)
            
            relationship_slot_usage_block = extract_class_block_from_schema_UPDATED(classes_section, associations[0] + "Relationship", "slot_usage")
            
            new_relationship_slot_usage_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, associations[0] + "Relationship", "slot_usage")
            
            subject_match = re.search(r'subject:\s*\n([\s\S]*?)(?=\n\s*object:|\n\s*predicate:|$)', relationship_slot_usage_block, re.DOTALL)
            if subject_match:
                subject_block = "        " + subject_match.group(1).strip()
            
            object_match = re.search(r'object:\s*\n([\s\S]*?)(?=\n\s*predicate:)', relationship_slot_usage_block, re.DOTALL)
            if object_match:
                object_block = "        " + object_match.group(1).strip()
            
            subject_match = re.search(r'subject:\s*\n([\s\S]*?)(?=\n\s*object:|\n\s*predicate:|$)', new_relationship_slot_usage_block, re.DOTALL)
            if subject_match:
                new_subject_block = "        " + subject_match.group(1).strip()

            object_match = re.search(r'object:\s*\n([\s\S]*?)(?=\n\s*predicate:)', new_relationship_slot_usage_block, re.DOTALL)
            if object_match:
                new_object_block = "        " + object_match.group(1).strip()
            

            subject_min_cardinality = extract_class_block_from_schema_UPDATED(subject_block, None, "minimum_cardinality")
            if subject_min_cardinality:
                subject_min_cardinality = subject_min_cardinality.strip().split()[0]
            
            subject_max_cardinality = extract_class_block_from_schema_UPDATED(subject_block, None, "maximum_cardinality")
            if subject_max_cardinality:
                subject_max_cardinality = subject_max_cardinality.strip().split()[0]
            
            new_subject_min_cardinality = extract_class_block_from_schema_UPDATED(new_subject_block, None, "minimum_cardinality")
            if new_subject_min_cardinality:
                new_subject_min_cardinality = new_subject_min_cardinality.strip().split()[0]
            
            new_subject_max_cardinality = extract_class_block_from_schema_UPDATED(new_subject_block, None, "maximum_cardinality")
            if new_subject_max_cardinality:
                new_subject_max_cardinality = new_subject_max_cardinality.strip().split()[0]
            
            
            if (new_subject_min_cardinality and new_subject_max_cardinality and new_subject_min_cardinality < new_subject_max_cardinality and new_subject_max_cardinality > new_subject_min_cardinality) or new_subject_min_cardinality is None or new_subject_max_cardinality is None:
                if subject_min_cardinality and new_subject_min_cardinality and subject_min_cardinality != new_subject_min_cardinality:
                    subject_block = replace_class_in_schema(subject_block, None, "minimum_cardinality", new_subject_min_cardinality)
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                elif subject_min_cardinality is None and new_subject_min_cardinality is not None:
                    subject_block = subject_block + "\n        minimum_cardinality: " + new_subject_min_cardinality
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                elif subject_min_cardinality is not None and new_subject_min_cardinality is None:
                    subject_block = (re.sub(rf'        minimum_cardinality: {subject_min_cardinality}', '', subject_block)).rstrip('\n')
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                
                if subject_max_cardinality and new_subject_max_cardinality and subject_max_cardinality != new_subject_max_cardinality:
                    subject_block = replace_class_in_schema(subject_block, None, "maximum_cardinality", new_subject_max_cardinality)
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                elif subject_max_cardinality is None and new_subject_max_cardinality is not None:
                    subject_block = subject_block + "\n        maximum_cardinality: " + new_subject_max_cardinality
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                elif subject_max_cardinality is not None and new_subject_max_cardinality is None:
                    subject_block = (re.sub(rf'        maximum_cardinality: {subject_max_cardinality}', '', subject_block)).rstrip('\n')
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)

            
            object_min_cardinality = extract_class_block_from_schema_UPDATED(object_block, None, "minimum_cardinality")
            if object_min_cardinality:
                object_min_cardinality = object_min_cardinality.strip().split()[0]
            
            object_max_cardinality = extract_class_block_from_schema_UPDATED(object_block, None, "maximum_cardinality")
            if object_max_cardinality:
                object_max_cardinality = object_max_cardinality.strip().split()[0]
            
            new_object_min_cardinality = extract_class_block_from_schema_UPDATED(new_object_block, None, "minimum_cardinality")
            if new_object_min_cardinality:
                new_object_min_cardinality = new_object_min_cardinality.strip().split()[0]
            
            new_object_max_cardinality = extract_class_block_from_schema_UPDATED(new_object_block, None, "maximum_cardinality")
            if new_object_max_cardinality:
                new_object_max_cardinality = new_object_max_cardinality.strip().split()[0]
            
            
            if (new_object_min_cardinality and new_object_max_cardinality and new_object_min_cardinality < new_object_max_cardinality and new_object_max_cardinality > new_object_min_cardinality) or new_object_min_cardinality is None or new_object_max_cardinality is None:
                if object_min_cardinality and new_object_min_cardinality and object_min_cardinality != new_object_min_cardinality:
                    object_block = replace_class_in_schema(object_block, None, "minimum_cardinality", new_object_min_cardinality)
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                elif object_min_cardinality is None and new_object_min_cardinality is not None:
                    object_block = object_block + "\n        minimum_cardinality: " + new_object_min_cardinality
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                elif object_min_cardinality is not None and new_object_min_cardinality is None:
                    object_block = (re.sub(rf'        minimum_cardinality: {object_min_cardinality}', '', object_block)).rstrip('\n')
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                
                if object_max_cardinality and new_object_max_cardinality and object_max_cardinality != new_object_max_cardinality:
                    object_block = replace_class_in_schema(object_block, None, "maximum_cardinality", new_object_max_cardinality)
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                elif object_max_cardinality is None and new_object_max_cardinality is not None:
                    object_block = object_block + "\n        maximum_cardinality: " + new_object_max_cardinality
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                elif object_max_cardinality is not None and new_object_max_cardinality is None:
                    object_block = (re.sub(rf'        maximum_cardinality: {object_max_cardinality}', '', object_block)).rstrip('\n')
                    relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
            
            updated_classes_section = replace_class_in_schema(classes_section, associations[0] + "Relationship", "slot_usage", relationship_slot_usage_block)

            updated_final_schema = intro_schema + "\n" + updated_classes_section
        case "AddAssociationsSimilarToEntities":
            # it finds out which are the new classes by comparing elements of original_schema_classes_names and new_schema_classes_names
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)
            
            # it repeats the following action for each new produced class: if the class is not a "Triple" or "RelationshipType", it adds it to classes_section
            for name in new_classes:
                class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, None)

                is_a_value = extract_class_block_from_schema_UPDATED(class_block, None, "is_a")
                if is_a_value == "Triple" or is_a_value == "RelationshipType":
                    classes_section += "\n\n" + class_block
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AnnotateSubschemaDescription":
            for element in classes:
                old_class_block = extract_class_block_from_schema_UPDATED(classes_section, element, None)

                pattern_extract = r'^\s{4}description:\s*\|?\s*(.*?)(?=(^\s{4}[a-zA-Z]+:|^\s*$))'
                match = re.search(pattern_extract, old_class_block, re.DOTALL | re.MULTILINE)
                if match:
                    old_class_description = match.group(1).strip()
                    if old_class_description and old_class_description.strip() != "''":
                        old_class_description = re.sub(r'>-\s*|\s+', ' ', old_class_description).strip()
                        old_class_description = re.sub(r'^>\s', '', old_class_description)
                        old_class_description = re.sub(r'[.,;!?]+$', '', old_class_description.strip())
                else:
                    old_class_description = ''
                
                new_class_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, None)
                pattern_extract = r'^\s{4}description:\s*\|?\s*(.*?)(?=(^\s{4}[a-zA-Z]+:|^\s*$))'
                match = re.search(pattern_extract, new_class_block, re.DOTALL | re.MULTILINE)
                if match:
                    new_class_description = match.group(1).strip()
                    if new_class_description and new_class_description.strip() != "''":
                        new_class_description = re.sub(r'>-\s*|\s+', ' ', new_class_description).strip()
                        new_class_description = re.sub(r'^>\s', '', new_class_description)
                        new_class_description = re.sub(r'[.,;!?]+$', '', new_class_description.strip())         # it removes the punctuation at the end
                        new_class_description = new_class_description.replace(old_class_description, "")
                        new_class_description = re.sub(r'^[\s.,;!?-]+', '', new_class_description)              # it removes the punctuation at the beginning and also blank characters and initial empty lines
                else:
                    new_class_description = "''"
                
                similarity = Levenshtein.ratio(old_class_description, new_class_description)

                if similarity <= 0.9:           # it checks if old_class_description and new_class_description are different at least of 10%
                    if not old_class_description:
                        description = new_class_description
                        old_class_block += "\n" + "    description: " + description
                        classes_section = replace_class_in_schema(classes_section, element, None, old_class_block)
                    else:
                        if old_class_description.strip() == "''":
                            description = new_class_description
                        elif new_class_description == "''":
                            description = old_class_description
                        elif old_class_description.startswith(">-"):
                            description = old_class_description + ". " + new_class_description.strip()
                        else:
                            description = ">-\n      " + old_class_description + ". " + new_class_description.strip()
                        
                        old_class_block = replace_class_in_schema(old_class_block, None, "description", description)
                        classes_section = replace_class_in_schema(classes_section, element, None, old_class_block)
            
            for element in associations:
                # the following code checks if class named as element + "Relationship" is a Triple
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "is_a")
                if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
                
                # it creates a copy of the informations of the class, making sure to remove the "slot_usage" informations so that the attributes "description" values are not mistaken with the class "description" value
                classes_section_copy = replace_class_in_schema(classes_section, element + "Relationship", "slot_usage", "")
                
                old_relationship_description = extract_class_block_from_schema_UPDATED(classes_section_copy, element + "Relationship", "description")
                new_relationship_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "description").rstrip('\n').lstrip("\n>-\\n")
                new_relationship_description = re.sub(r'\s+', ' ', new_relationship_description)

                old_class_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", None)

                if old_relationship_description is not None:
                    similarity = Levenshtein.ratio(old_relationship_description, new_relationship_description)

                    if similarity <= 0.9:           # it checks if old_relationship_description and new_relationship_description are different at least of 10%
                        if not old_relationship_description:
                            description = new_relationship_description
                            old_class_block += "\n" + "    description: >-      " + description
                            classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, old_class_block)
                        else:
                            if old_relationship_description.strip() == "''":
                                description = ">-\n      " + new_relationship_description
                            elif old_relationship_description.startswith(">-"):
                                description = old_relationship_description + ". " + new_relationship_description.strip()
                            else:
                                description = ">-\n      " + old_relationship_description + ". " + new_relationship_description.strip()
                            old_class_block = old_class_block.replace(old_relationship_description, description)
                            classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, old_class_block)
                else:
                    old_class_block += "\n    description: " + new_relationship_description + "\n"
                    classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, old_class_block)
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "AnnotateSubschemaExample":
            for element in classes:
                old_prompt_example = extract_class_block_from_schema_UPDATED(classes_section, element, "prompt.examples")
                if old_prompt_example is not None:
                    old_prompt_example = re.sub(r'>-\s*|\s+', ' ', old_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                    old_prompt_example = re.sub(r'^>\s', '', old_prompt_example)                    # it removes possible > from the string
                    old_prompt_example = re.sub(r'[.,;]+$', '', old_prompt_example.strip())         # it removes the punctuation at the end of the string

                new_prompt_example = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "prompt.examples")
                if new_prompt_example is not None:
                    if new_prompt_example.count("'") > 1:
                        new_prompt_example = new_prompt_example[0] + new_prompt_example[1:-1].replace("'", "’") + new_prompt_example[-1]
                    new_prompt_example = re.sub(r'>-\s*|\s+', ' ', new_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                    new_prompt_example = re.sub(r'^>\s', '', new_prompt_example)                    # it removes possible > from the string
                    new_prompt_example = re.sub(r'[.,;]+$', '', new_prompt_example.strip())
                
                if new_prompt_example != None:
                    new_example_list = [example.strip() for example in new_prompt_example.split(',')]
                    
                    if old_prompt_example is None or old_prompt_example == "''":
                        old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element, "annotations")
                        
                        class_block = extract_class_block_from_schema_UPDATED(classes_section, element, None)
                        
                        if old_annotations_block == "{}":
                            new_annotations_block = "      prompt.examples: " + new_prompt_example
                            class_block = class_block.replace("    annotations: {}", "    annotations:\n" + new_annotations_block)
                        else:
                            new_annotations_block = old_annotations_block.replace("      prompt.examples: ''", "")
                            new_annotations_block += "\n      prompt.examples: " + new_prompt_example
                            class_block = class_block.replace(old_annotations_block, new_annotations_block)
                        
                        classes_section = replace_class_in_schema(classes_section, element, None, class_block)
                    else:
                        old_example_list = [example.strip() for example in old_prompt_example.split(',')]
                        old_prompt_example = "        " + old_prompt_example
                        for new_example in new_example_list:
                            if new_example not in old_example_list:
                                old_prompt_example += ", " + new_example
                        classes_section = replace_class_in_schema(classes_section, element, "prompt.examples", old_prompt_example)
                
                pattern_remove_prompt_examples = re.compile(r'(\s+range:\s+' + re.escape(element) + r'\s+annotations:\s*)\n?(\s*[^p][^\n]+)*\s*prompt\.examples:.*?(\n\s+[^ ]|$)', re.DOTALL)
                classes_section = re.sub(pattern_remove_prompt_examples, r'\1\2', classes_section)
            
            for element in associations:
                # the following code checks if class named as element + "Relationship" is a Triple
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "is_a")
                if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
                
                relationship_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", None).lstrip('\n')
                
                pattern = re.compile(r'^\s{4}annotations:\s*(.*?)(?=^\s{4}\S|\Z)', re.DOTALL | re.MULTILINE)
                matches = pattern.findall(relationship_block)
                for match in matches:
                    relationship_annotations_block = match
                
                relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', relationship_annotations_block)
                
                new_relationship_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", None).lstrip('\n')

                matches = pattern.findall(new_relationship_block)
                for match in matches:
                    new_relationship_annotations_block = match
                
                new_relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', new_relationship_annotations_block)
                
                similarity = Levenshtein.ratio(relationship_prompt_examples_value, new_relationship_prompt_examples_value)
                
                if similarity <= 0.25:          # it checks if relationship_prompt_examples_value and new_relationship_prompt_examples_value are different at least of 75%
                    if not relationship_prompt_examples_value:
                        prompt_examples = new_relationship_prompt_examples_value
                        updated_relationship_annotations_block = relationship_annotations_block
                        updated_relationship_annotations_block = updated_relationship_annotations_block.replace("{}", "")
                        updated_relationship_annotations_block += "\n      prompt.examples: " + prompt_examples
                    else:
                        if relationship_prompt_examples_value.strip() == "''":
                            prompt_examples = new_relationship_prompt_examples_value
                        else:
                            prompt_examples = relationship_prompt_examples_value + ". " + new_relationship_prompt_examples_value
                        updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, "prompt.examples", prompt_examples)
                    
                    pattern = r'(^\s{4}annotations:\s*)(.*?)(?=\n\s{4}\S|\Z)'
                    relationship_block = re.sub(pattern, r'\1' + updated_relationship_annotations_block, relationship_block, flags=re.DOTALL | re.MULTILINE)

                classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, relationship_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "AnnotateSubschemaOntology":
            for element in classes:
                old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, element, "id_prefixes").lstrip('\n').rstrip('\n')
                old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element, "annotations").lstrip('\n').rstrip('\n')
                old_annotators_values = extract_class_block_from_schema_UPDATED(old_annotations_block, None, "annotators")
                if old_annotators_values is not None:
                    old_annotators_values = old_annotators_values.lstrip('\n').rstrip('\n')
                    old_annotators_values = ', '.join(line.strip('- ').strip() for line in old_annotators_values.splitlines() if line.strip())
                    
                    old_annotators_list = old_annotators_values.split(", ")
                    
                    old_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in old_annotators_list]
                else:
                    old_list_id_prefixes = []
                
                new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "annotations")
                
                new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
                if new_annotators_values is not None:
                    new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                    new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                    
                    new_annotators_list = new_annotators_values.split(", ")
                    
                    new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
                else:
                    new_list_id_prefixes = []
                
                id_prefixes_difference = list(set(new_list_id_prefixes) - set(old_list_id_prefixes))
                
                if len(id_prefixes_difference) >= 1 and old_id_prefixes_block == "[]":
                    old_id_prefixes_block = old_id_prefixes_block.replace("[]", "")

                for item in id_prefixes_difference:
                    old_id_prefixes_block += "\n      - " + item
                    if old_annotators_values is None:
                        old_annotators_values = "sqlite:obo:" + item.lower()
                    else:
                        old_annotators_values += ", sqlite:obo:" + item.lower()

                if old_annotations_block == "{}" and new_annotators_values is not None:
                    old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
                if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                    classes_section = replace_class_in_schema(classes_section, element, "id_prefixes", old_id_prefixes_block)
                    old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", old_annotators_values)
                    classes_section = replace_class_in_schema(classes_section, element, "annotations", old_annotations_block)
            
            for element in associations:
                # the following code checks if class named as element + "Predicate" is a RelationshipType
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "is_a")
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Predicate", "is_a")
                if class_is_a_value != "RelationshipType" or new_schema_class_is_a_value != "RelationshipType":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
                
                old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "id_prefixes")
                old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "annotations")
                old_annotators_values = extract_class_block_from_schema_UPDATED(old_annotations_block, None, "annotators")
                if old_annotators_values is not None:
                    old_annotators_values = old_annotators_values.lstrip('\n').rstrip('\n')
                    old_annotators_values = ', '.join(line.strip('- ').strip() for line in old_annotators_values.splitlines() if line.strip())
                    
                    old_annotators_list = old_annotators_values.split(", ")
                    
                    old_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in old_annotators_list]
                else:
                    old_list_id_prefixes = []

                new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Predicate", "annotations")

                new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
                if new_annotators_values is not None:
                    new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                    new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                    
                    new_annotators_list = new_annotators_values.split(", ")
                    
                    new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
                else:
                    new_list_id_prefixes = []

                id_prefixes_difference = list(set(new_list_id_prefixes) - set(old_list_id_prefixes))
                
                if len(id_prefixes_difference) >= 1 and old_id_prefixes_block == "[]":
                    old_id_prefixes_block = old_id_prefixes_block.replace("[]", "")

                for item in id_prefixes_difference:
                    old_id_prefixes_block += "\n      - " + item
                    if old_annotators_values is None:
                        old_annotators_values = "sqlite:obo:" + item.lower()
                    else:
                        old_annotators_values += ", sqlite:obo:" + item.lower()

                if old_annotations_block == "{}" and new_annotators_values is not None:
                    old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
                if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                    classes_section = replace_class_in_schema(classes_section, element + "Predicate", "id_prefixes", old_id_prefixes_block)
                    old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", old_annotators_values)
                    classes_section = replace_class_in_schema(classes_section, element + "Predicate", "annotations", old_annotations_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixClassesAndAssociationsName":
            # it checks if elements in "associations" are actually associations names and NOT classes names
            for element in associations:
                is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                if is_a_value != "Triple":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
            
            new_classes = set(new_schema_classes_names) - set(original_schema_classes_names)

            for element in classes:
                closest_class = None
                min_distance = float('inf')         # it initializes min_distance to an infinite distance
                for name in new_classes:
                    element_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element, "is_a")
                    new_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, "is_a")
                    if element_is_a_value == new_class_is_a_value:
                        distance = Levenshtein.distance(name, element)
                        if distance < min_distance:
                            min_distance = distance
                            closest_class = name
                
                pattern = rf'^(  ){re.escape(element)}:'
                classes_section = re.sub(pattern, rf'  {closest_class}:', classes_section, flags=re.MULTILINE)
                classes_section = re.sub(rf'(^[ \t]*range:\s*){re.escape(element)}\n', 
                                rf'\1{closest_class}\n', 
                                classes_section, 
                                flags=re.MULTILINE)
                new_classes.discard(closest_class)
            
            for element in associations:
                closest_class = None
                min_distance = float('inf')         # it initializes min_distance to an infinite distance
                for name in new_classes:
                    new_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, name, "is_a")
                    if new_class_is_a_value == "Triple":
                        name = name.removesuffix("Relationship")
                        distance = Levenshtein.distance(name, element)
                    elif new_class_is_a_value == "RelationshipType":
                        name = name.removesuffix("Predicate")
                        distance = Levenshtein.distance(name, element)
                    else:
                        distance = min_distance
                    
                    if distance < min_distance:
                        min_distance = distance
                        closest_class = name
                
                old_predicate_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "attributes")
                parts = re.split(r'(?=[A-Z])', closest_class)
                new_pattern = ' '.join(p.lower() for p in parts if p)

                relationship_attributes_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "slot_usage")
                
                subject_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "subject")
                subject_range_value = extract_class_block_from_schema_UPDATED(subject_block, None, "range").strip().lower()
                
                object_block = extract_class_block_from_schema_UPDATED(relationship_attributes_block, None, "object").lstrip('\n').rstrip('\n')
                object_range_value = extract_class_block_from_schema_UPDATED(object_block, None, "range").strip().lower()
                
                if new_pattern.startswith(subject_range_value):
                    new_pattern = new_pattern[len(subject_range_value):]
                if new_pattern.endswith(object_range_value):
                    new_pattern = new_pattern[: -len(object_range_value)]
                new_pattern = new_pattern.strip()

                updated_predicate_attributes_block = replace_class_in_schema(old_predicate_attributes_block, None, "id", "        pattern: '" + new_pattern + "'")
                classes_section = replace_class_in_schema(classes_section, element + "Predicate", "attributes", updated_predicate_attributes_block)
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixClassesAndAssociationsDescription":
            for element in classes:
                is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element, "is_a")
                if is_a_value != "Triple" and is_a_value != "RelationshipType":
                    # it creates a copy of the informations of the class, making sure to remove the "attributes" informations so that the attributes "description" values are not mistaken with the class "description" value
                    classes_section_copy = replace_class_in_schema(classes_section, element, "attributes", "")

                    old_description = extract_class_block_from_schema_UPDATED(classes_section_copy, element, "description")
                    new_class_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "description")
                    if new_class_description is not None:
                        new_class_description = new_class_description.removeprefix(">-\n")
                    else:
                        new_class_description = old_description
                    
                    if old_description is None:
                        new_class_block = extract_class_block_from_schema_UPDATED(classes_section, element, None)
                        new_class_block += "\n    description: " + new_class_description + "\n"
                        classes_section = replace_class_in_schema(classes_section, element, None, new_class_block)
                    else:
                        classes_section = replace_class_in_schema(classes_section, element, "description", new_class_description)
            
            for element in associations:
                is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                if is_a_value == "Triple":
                    # it creates a copy of the informations of the class, making sure to remove the "slot_usage" informations so that the attributes "description" values are not mistaken with the class "description" value
                    classes_section_copy = replace_class_in_schema(classes_section, element + "Relationship", "slot_usage", "")
                    
                    old_description = extract_class_block_from_schema_UPDATED(classes_section_copy, element + "Relationship", "description")
                    new_relationship_description = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "description")
                    if new_relationship_description is not None:
                        new_relationship_description = new_relationship_description.removeprefix(">-\n")
                    else:
                        new_relationship_description = old_description
                    
                    if old_description is None:
                        new_relationship_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", None)
                        new_relationship_block += "\n    description: " + new_relationship_description + "\n"
                        classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, new_relationship_block)
                    else:
                        classes_section = replace_class_in_schema(classes_section, element + "Relationship", "description", new_relationship_description)
            
            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixSubschemaCardinalities":
            for element in associations:
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "is_a")

                if class_is_a_value == "Triple" and new_schema_class_is_a_value == "Triple":
                    relationship_slot_usage_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "slot_usage").lstrip('\n').rstrip('\n')
                    
                    new_relationship_slot_usage_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "slot_usage").lstrip('\n').rstrip('\n')
                    
                    subject_match = re.search(r'subject:\s*\n([\s\S]*?)(?=\n\s*object:|\n\s*predicate:|$)', relationship_slot_usage_block, re.DOTALL)
                    if subject_match:
                        subject_block = "        " + subject_match.group(1).strip()
                    
                    object_match = re.search(r'object:\s*\n([\s\S]*?)(?=\n\s*predicate:)', relationship_slot_usage_block, re.DOTALL)
                    if object_match:
                        object_block = "        " + object_match.group(1).strip()
                    
                    subject_match = re.search(r'subject:\s*\n([\s\S]*?)(?=\n\s*object:|\n\s*predicate:|$)', new_relationship_slot_usage_block, re.DOTALL)
                    if subject_match:
                        new_subject_block = "        " + subject_match.group(1).strip()

                    object_match = re.search(r'object:\s*\n([\s\S]*?)(?=\n\s*predicate:)', new_relationship_slot_usage_block, re.DOTALL)
                    if object_match:
                        new_object_block = "        " + object_match.group(1).strip()
                    

                    subject_min_cardinality = extract_class_block_from_schema_UPDATED(subject_block, None, "minimum_cardinality")
                    if subject_min_cardinality:
                        subject_min_cardinality = subject_min_cardinality.strip().split()[0]
                    
                    subject_max_cardinality = extract_class_block_from_schema_UPDATED(subject_block, None, "maximum_cardinality")
                    if subject_max_cardinality:
                        subject_max_cardinality = subject_max_cardinality.strip().split()[0]
                    
                    new_subject_min_cardinality = extract_class_block_from_schema_UPDATED(new_subject_block, None, "minimum_cardinality")
                    if new_subject_min_cardinality:
                        new_subject_min_cardinality = new_subject_min_cardinality.strip().split()[0]
                    
                    new_subject_max_cardinality = extract_class_block_from_schema_UPDATED(new_subject_block, None, "maximum_cardinality")
                    if new_subject_max_cardinality:
                        new_subject_max_cardinality = new_subject_max_cardinality.strip().split()[0]
                    
                    
                    if (new_subject_min_cardinality and new_subject_max_cardinality and new_subject_min_cardinality < new_subject_max_cardinality and new_subject_max_cardinality > new_subject_min_cardinality) or new_subject_min_cardinality is None or new_subject_max_cardinality is None:
                        if subject_min_cardinality and new_subject_min_cardinality and subject_min_cardinality != new_subject_min_cardinality:
                            subject_block = replace_class_in_schema(subject_block, None, "minimum_cardinality", new_subject_min_cardinality)
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                        elif subject_min_cardinality is None and new_subject_min_cardinality is not None:
                            subject_block = subject_block + "\n        minimum_cardinality: " + new_subject_min_cardinality
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                        elif subject_min_cardinality is not None and new_subject_min_cardinality is None:
                            subject_block = (re.sub(rf'        minimum_cardinality: {subject_min_cardinality}', '', subject_block)).rstrip('\n')
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                        
                        if subject_max_cardinality and new_subject_max_cardinality and subject_max_cardinality != new_subject_max_cardinality:
                            subject_block = replace_class_in_schema(subject_block, None, "maximum_cardinality", new_subject_max_cardinality)
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                        elif subject_max_cardinality is None and new_subject_max_cardinality is not None:
                            subject_block = subject_block + "\n        maximum_cardinality: " + new_subject_max_cardinality
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)
                        elif subject_max_cardinality is not None and new_subject_max_cardinality is None:
                            subject_block = (re.sub(rf'        maximum_cardinality: {subject_max_cardinality}', '', subject_block)).rstrip('\n')
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "subject", subject_block)

                    
                    object_min_cardinality = extract_class_block_from_schema_UPDATED(object_block, None, "minimum_cardinality")
                    if object_min_cardinality:
                        object_min_cardinality = object_min_cardinality.strip().split()[0]
                    
                    object_max_cardinality = extract_class_block_from_schema_UPDATED(object_block, None, "maximum_cardinality")
                    if object_max_cardinality:
                        object_max_cardinality = object_max_cardinality.strip().split()[0]
                    
                    new_object_min_cardinality = extract_class_block_from_schema_UPDATED(new_object_block, None, "minimum_cardinality")
                    if new_object_min_cardinality:
                        new_object_min_cardinality = new_object_min_cardinality.strip().split()[0]
                    
                    new_object_max_cardinality = extract_class_block_from_schema_UPDATED(new_object_block, None, "maximum_cardinality")
                    if new_object_max_cardinality:
                        new_object_max_cardinality = new_object_max_cardinality.strip().split()[0]
                    
                    
                    if (new_object_min_cardinality and new_object_max_cardinality and new_object_min_cardinality < new_object_max_cardinality and new_object_max_cardinality > new_object_min_cardinality) or new_object_min_cardinality is None or new_object_max_cardinality is None:
                        if object_min_cardinality and new_object_min_cardinality and object_min_cardinality != new_object_min_cardinality:
                            object_block = replace_class_in_schema(object_block, None, "minimum_cardinality", new_object_min_cardinality)
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                        elif object_min_cardinality is None and new_object_min_cardinality is not None:
                            object_block = object_block + "\n        minimum_cardinality: " + new_object_min_cardinality
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                        elif object_min_cardinality is not None and new_object_min_cardinality is None:
                            object_block = (re.sub(rf'        minimum_cardinality: {object_min_cardinality}', '', object_block)).rstrip('\n')
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                        
                        if object_max_cardinality and new_object_max_cardinality and object_max_cardinality != new_object_max_cardinality:
                            object_block = replace_class_in_schema(object_block, None, "maximum_cardinality", new_object_max_cardinality)
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                        elif object_max_cardinality is None and new_object_max_cardinality is not None:
                            object_block = object_block + "\n        maximum_cardinality: " + new_object_max_cardinality
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                        elif object_max_cardinality is not None and new_object_max_cardinality is None:
                            object_block = (re.sub(rf'        maximum_cardinality: {object_max_cardinality}', '', object_block)).rstrip('\n')
                            relationship_slot_usage_block = replace_class_in_schema(relationship_slot_usage_block, None, "object", object_block)
                    
                    classes_section = replace_class_in_schema(classes_section, element + "Relationship", "slot_usage", relationship_slot_usage_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixSubschemaExample":
            for element in classes:
                old_prompt_example = extract_class_block_from_schema_UPDATED(classes_section, element, "prompt.examples")
                if old_prompt_example is not None:
                    old_prompt_example = re.sub(r'>-\s*|\s+', ' ', old_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                    old_prompt_example = re.sub(r'^>\s', '', old_prompt_example)                    # it removes possible > from the string
                    old_prompt_example = re.sub(r'[.,;]+$', '', old_prompt_example.strip())         # it removes the punctuation at the end of the string

                new_prompt_example = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "prompt.examples")
                if new_prompt_example is not None:
                    if new_prompt_example.count("'") > 1:
                        new_prompt_example = new_prompt_example[0] + new_prompt_example[1:-1].replace("'", "’") + new_prompt_example[-1]
                    new_prompt_example = re.sub(r'>-\s*|\s+', ' ', new_prompt_example).strip()      # it removes >- at the beginning of the string if the value involves multiple lines
                    new_prompt_example = re.sub(r'^>\s', '', new_prompt_example)                    # it removes possible > from the string
                    new_prompt_example = re.sub(r'[.,;]+$', '', new_prompt_example.strip())
                
                if new_prompt_example != None:
                    if old_prompt_example is None or old_prompt_example == "''":
                        old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element, "annotations")
                        
                        class_block = extract_class_block_from_schema_UPDATED(classes_section, element, None)
                        
                        if old_annotations_block == "{}":
                            new_annotations_block = "      prompt.examples: " + new_prompt_example
                            class_block = class_block.replace("    annotations: {}", "    annotations:\n" + new_annotations_block)
                        else:
                            new_annotations_block = old_annotations_block.replace("      prompt.examples: ''", "")
                            new_annotations_block += "\n      prompt.examples: " + new_prompt_example
                            class_block = class_block.replace(old_annotations_block, new_annotations_block)
                        
                        classes_section = replace_class_in_schema(classes_section, element, None, class_block)
                    else:
                        old_prompt_example = "        " + new_prompt_example
                        classes_section = replace_class_in_schema(classes_section, element, "prompt.examples", old_prompt_example)
                else:
                    classes_section = classes_section
                
                pattern_remove_prompt_examples = re.compile(r'(\s+range:\s+' + re.escape(element) + r'\s+annotations:\s*)\n?(\s*[^p][^\n]+)*\s*prompt\.examples:.*?(\n\s+[^ ]|$)', re.DOTALL)
                classes_section = re.sub(pattern_remove_prompt_examples, r'\1\2', classes_section)
            
            for element in associations:
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", "is_a")
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", "is_a")
                if class_is_a_value != "Triple" or new_schema_class_is_a_value != "Triple":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
                
                relationship_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Relationship", None).lstrip('\n')

                pattern = re.compile(r'^\s{4}annotations:\s*(.*?)(?=^\s{4}\S|\Z)', re.DOTALL | re.MULTILINE)
                matches = pattern.findall(relationship_block)
                for match in matches:
                    relationship_annotations_block = match

                new_relationship_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Relationship", None).lstrip('\n')
                matches = pattern.findall(new_relationship_block)
                for match in matches:
                    new_relationship_annotations_block = match
                
                new_relationship_prompt_examples_value = re.sub(r'^\s*prompt.examples:\s*', '', new_relationship_annotations_block)
                
                if relationship_annotations_block == "{}":
                    updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, None, new_relationship_annotations_block)
                else:
                    updated_relationship_annotations_block = replace_class_in_schema(relationship_annotations_block, None, "prompt.examples", new_relationship_prompt_examples_value)
                
                pattern = r'(^\s{4}annotations:\s*)(.*?)(?=\n\s{4}\S|\Z)'
                relationship_block = re.sub(pattern, r'\1' + updated_relationship_annotations_block, relationship_block, flags=re.DOTALL | re.MULTILINE)

                classes_section = replace_class_in_schema(classes_section, element + "Relationship", None, relationship_block)

            updated_final_schema = intro_schema + "\n" + classes_section
        case "FixSubschemaOntology":
            for element in classes:
                old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, element, "id_prefixes")
                old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element, "annotations") if extract_class_block_from_schema_UPDATED(classes_section, element, "annotations") is not None else "{}"

                new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "annotations") if extract_class_block_from_schema_UPDATED(new_schema_classes_section, element, "annotations") is not None else "{}"

                new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
                if new_annotators_values is not None:
                    new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                    new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())
                    
                    new_annotators_list = new_annotators_values.split(", ")
                    
                    new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
                else:
                    new_list_id_prefixes = []
                
                if len(new_list_id_prefixes) == 0:
                    updated_id_prefixes_block = "{}"
                else:
                    updated_id_prefixes_block = ""
                
                for item in new_list_id_prefixes:
                    updated_id_prefixes_block += "\n      - " + item
                
                if old_annotations_block == "{}" and new_annotators_values is not None:
                    old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
                if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                    classes_section = replace_class_in_schema(classes_section, element, "id_prefixes", updated_id_prefixes_block)
                    old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", new_annotators_values)
                    classes_section = replace_class_in_schema(classes_section, element, "annotations", old_annotations_block)

            for element in associations:
                # the following code checks if class named as element[0] + "Predicate" is a RelationshipType
                class_is_a_value = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "is_a").strip()
                new_schema_class_is_a_value = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Predicate", "is_a").strip()
                if class_is_a_value != "RelationshipType" or new_schema_class_is_a_value != "RelationshipType":
                    updated_final_schema = intro_schema + "\n" + classes_section
                    return Response(content=updated_final_schema)
                
                old_id_prefixes_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "id_prefixes")
                old_annotations_block = extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "annotations") if extract_class_block_from_schema_UPDATED(classes_section, element + "Predicate", "annotations") is not None else "{}"
                
                new_annotations_block = extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Predicate", "annotations") if extract_class_block_from_schema_UPDATED(new_schema_classes_section, element + "Predicate", "annotations") is not None else "{}"

                new_annotators_values = extract_class_block_from_schema_UPDATED(new_annotations_block, None, "annotators")
                if new_annotators_values is not None:
                    new_annotators_values = new_annotators_values.lstrip('\n').rstrip('\n')
                    new_annotators_values = ', '.join(line.strip('- ').strip() for line in new_annotators_values.splitlines() if line.strip())

                    new_annotators_list = new_annotators_values.split(", ")
                    
                    new_list_id_prefixes = [item.replace("sqlite:obo:", "").upper() for item in new_annotators_list]
                else:
                    new_list_id_prefixes = []
                
                if len(new_list_id_prefixes) == 0:
                    updated_id_prefixes_block = "{}"
                else:
                    updated_id_prefixes_block = ""
                
                for item in new_list_id_prefixes:
                    updated_id_prefixes_block += "\n      - " + item
                
                if old_annotations_block == "{}" and new_annotators_values is not None:
                    old_annotations_block = old_annotations_block.replace("{}", "\n      annotators: {}")
                if old_annotations_block != "{}":           # if the condition is true, it means that {} has ben replaced by the previous if block or that old_annotations_block value was already different from {}
                    classes_section = replace_class_in_schema(classes_section, element + "Predicate", "id_prefixes", updated_id_prefixes_block)
                    old_annotations_block = replace_class_in_schema(old_annotations_block, None, "annotators", new_annotators_values)
                    classes_section = replace_class_in_schema(classes_section, element + "Predicate", "annotations", old_annotations_block)
            
            updated_final_schema = intro_schema + "\n" + classes_section


    # the following code is a fix to ensure that 'prompt.examples' is always defined as a YAML multiline block, even when there are no examples, by adding a default text to prevent errors.
    updated_final_schema = re.sub(
        r'prompt\.examples:\s*\'\'', 
        'prompt.examples: |\n      # no examples provided', 
        updated_final_schema
    )

    print("\n\n\nUpdated schema:\n", updated_final_schema)

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