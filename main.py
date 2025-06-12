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

local_tz = pytz.timezone("Europe/Rome")

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_THREAD_ID = os.getenv("OPENAI_THREAD_ID")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

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
    allow_origins=["schemalink.anacleto.di.unimi.it", "http://localhost:8000","http://localhost:4200",],
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
    to_email = "schemalinkanacleto@gmail.com"

    logging.info(f"Sending email to notify admin of new registration: {user.email}")

    send_email(to_email=to_email, subject=subject, message=body)
    
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

    admin_email = "schemalinkanacleto@gmail.com"
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

        db.execute(
            text("""
                UPDATE UserSubscribesPolicy
                SET status = 'expired', endDate = :now
                WHERE username = :username
                AND status = 'active'
                AND startDate <= :now AND endDate >= :now
            """),
            {"username": policySubscription.username, "now": now}
        )

        policySubscription.startDate = now

        if policySubscription.policyName == "silver":
            duration_days = 3
        elif policySubscription.policyName == "gold":
            duration_days = 7
        elif policySubscription.policyName == "platinum":
            duration_days = 7
        else:
            raise HTTPException(status_code=400, detail="Invalid policy name")
            
        noon_today = now.replace(hour=12, minute=0, second=0, microsecond=0)
        midnight_next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        if now.time() <= time(12, 0):  # From 00:00:01 to 12:00:00
            policySubscription.endDate = (now + timedelta(days=duration_days)).replace(hour=12, minute=0, second=0, microsecond=0)
        else:  # From 12:00:01 to 23:59:59
            policySubscription.endDate = (now + timedelta(days=duration_days + 1)).replace(hour=0, minute=0, second=0, microsecond=0)

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

    print("Username received:", username)
    print("Operation received:", operation)

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

    # Policy max access
    max_access = db.execute(
        text("SELECT maxAccess FROM Policy WHERE name = :name"),
        {"name": policy_name}
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

        if (operation.username != "schemalink"):

            subscription = db.query(models.UserSubscribesPolicy).filter(
                models.UserSubscribesPolicy.username == operation.username,
                models.UserSubscribesPolicy.status == 'active'
            ).order_by(models.UserSubscribesPolicy.startDate.desc()).first()

            if subscription:
                policy = db.query(models.Policy).filter_by(name=subscription.policyName).first()
                
                print("Loaded policy:", policy.name, policy.maxAccess, policy.threshold)
                if policy:
                    op_count = db.query(models.UserMadeOperation).filter(
                        models.UserMadeOperation.username == operation.username,
                        models.UserMadeOperation.date >= subscription.startDate,
                        models.UserMadeOperation.date <= now
                    ).count()

                    threshold_reached = False

                    if (policy.name != "platinum"):
                        threshold = policy.threshold if policy.threshold is not None else 0
                        if op_count == (policy.maxAccess - threshold):
                            threshold_reached = True
                            user = db.query(models.User).filter_by(username=operation.username).first()
                            if user:
                                subject = f"You have {policy.threshold} operations remaining on your '{policy.name}' plan"
                                body = (
                                    f"Hi {user.username},\n\n"
                                    f"You have {policy.threshold} intelligent requests remaining"
                                    f"under your current '{policy.name}' subscription plan.\n\n"
                                    f"Once you reach the limit of {policy.maxAccess} intelligent requests, your subscription will expire "
                                    f"and you will no longer be able to use intelligent requests.\n\n"
                                    f"To continue uninterrupted, consider upgrading or renewing your plan.\n\n"
                                    f"Thank you for using SchemaLink!\n"
                                    f"\nBest regards,\n"
                                    f"The SchemaLink Team"
                                )
                                send_email(to_email=user.email, subject=subject, message=body)

                        if op_count >= policy.maxAccess:
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
                "policyName": policy.name,
                "policyThreshold": policy.threshold,
                "policyMaxAccess": policy.maxAccess
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
    to_email = "schemalinkanacleto@gmail.com"

    logging.info(f"Sending email to notify policy request")

    send_email(to_email=to_email, subject=subject, message=body)

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
        "policyName": policy.name,
        "operationsDone": operations_done,
        "maxAccess": policy.maxAccess,
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

scheduler = BackgroundScheduler()

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
    to_email = "schemalinkanacleto@gmail.com"
    
    send_email(to_email=to_email, subject=subject, message=body, attachment=temp_file_path)

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

# Start the listener during the app's startup in FastAPI and set up the scheduler
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(listen_notifications()) # Start the listener in parallel

    scheduler.add_job(
        expire_subscriptions_job,
        CronTrigger(hour='0,12', minute='1')
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


@app.post("/api/openai/generate/")
async def generate(request: Request):
    if not (OPENAI_API_KEY and OPENAI_THREAD_ID and OPENAI_ASSISTANT_ID):
        return Response(
            status_code=500,
            content="OpenAI API key, thread ID, or assistant ID not set",
        )

    raw_body = await request.body()
    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        client.beta.threads.messages.create(
            thread_id=OPENAI_THREAD_ID, role="user", content=raw_body.decode("utf-8"),
        )
        run = client.beta.threads.runs.create_and_poll(
            thread_id=OPENAI_THREAD_ID, assistant_id=OPENAI_ASSISTANT_ID
        )
        if run.status == "completed":
            messages = client.beta.threads.messages.list(thread_id=run.thread_id)

        return Response(content=messages.data[0].content[0].text.value.replace("```yaml\n", "").replace("```", ""))
    
    except RateLimitError as e:
        subject = "SchemaLink Error: OpenAI rate or fund limit exceeded"
        body = (
            f"An OpenAI request failed due to a rate or funding limit being exceeded.\n\n"
            f"\n\nSchemaLink Notification System")
        to_email = "schemalinkanacleto@gmail.com"
        send_email(to_email=to_email, subject=subject, message=body)

        # include 'insufficient_quota'
        return JSONResponse(status_code=429, content={"error": "Quota exceeded or rate limited", "details": str(e)})

    except APIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI API error", "details": str(e)})
    except OpenAIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI error", "details": str(e)})


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
        return Response(content=response_text)

    except RateLimitError as e:
        subject = "SchemaLink Error: OpenAI rate or fund limit exceeded"
        body = (
            f"An OpenAI request failed due to a rate or funding limit being exceeded.\n\n"
            f"\n\nSchemaLink Notification System")
        to_email = "schemalinkanacleto@gmail.com"
        send_email(to_email=to_email, subject=subject, message=body)

        # include 'insufficient_quota'
        return JSONResponse(status_code=429, content={"error": "Quota exceeded or rate limited", "details": str(e)})

    except APIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI API error", "details": str(e)})
    except OpenAIError as e:
        return JSONResponse(status_code=500, content={"error": "OpenAI error", "details": str(e)})