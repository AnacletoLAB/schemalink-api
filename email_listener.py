import asyncpg
import asyncio
import os
from dotenv import load_dotenv
from gmail_service import send_email
from datetime import datetime, timedelta, time
import pytz
import logging

local_tz = pytz.timezone("Europe/Rome")

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

async def handle_notify(connection, pid, channel_name, payload):
    # Handles notifications when they arrive on the user_approval channel
    user_email, username, status = payload.split(",")
    
    if channel_name == "user_status":
        if status == "active":
            subject = "Welcome to SchemaLink! Your account has been approved"
            message = (
                f"Hi {username},\n\n"
                "Great news! Your SchemaLink account has been approved.\n\n"
                "You have been granted a Trial policy that allows up to 10 intelligent requests "
                "within the next 24 hours. After this period, your access may be limited unless you upgrade "
                "your policy to an upper tier.\n\n"
                "Thank you for joining SchemaLink!\n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )
            now = datetime.now(local_tz)
            end_date = now + timedelta(hours=24)

            if now.time() <= time(12, 0):  # From 00:00:01 to 12:00:00
                end_date = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
            else:   # From 12:00:01 to 23:59:59
                end_date = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
            
            try:
                await connection.execute("""
                    INSERT INTO UserSubscribesPolicy (
                        username, startDate, endDate, requestDate, status, policyName
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                """, username, now, end_date, now, 'active', 'trial')

                print(f"Assigned 'trial' policy to user {username}")
            except Exception as e:
                print(f"Error assigning policy to user {username}: {e}")
        elif status == "blocked":
            subject = "SchemaLink account blocked"
            message = (
                f"Hi {username},\n\n"
                "Your SchemaLink account has been blocked. \n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )
        elif status == "disabled":
            subject = "SchemaLink account deleted"
            message = (
                f"Hi {username},\n\n"
                "Your SchemaLink account has been successfully deleted. \n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )
    elif channel_name == "policy_status":
        if status == "active":
            subject = "Your SchemaLink policy has been approved"
            message = (
                f"Hi {username},\n\n"
                "Your policy request has been approved. You can now enjoy the benefits associated with your policy.\n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )
        elif status == "rejected":
            subject = "Your SchemaLink policy request was rejected"
            message = (
                f"Hi {username},\n\n"
                "We regret to inform you that your policy request has been rejected. \n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )
        elif status == "expired":
            subject = "Your SchemaLink policy has expired"
            message = (
                f"Hi {username},\n\n"
                "Your current SchemaLink policy has expired. To continue enjoying uninterrupted service, "
                "please renew or upgrade your subscription.\n\n"
                f"Best regards,\n"
                f"The SchemaLink Team"
            )

    # Send the email asynchronously in a separate thread
    if subject and message:
        await asyncio.to_thread(send_email, user_email, subject, message)


async def listen_notifications():
    # Listens for user approval notifications and sends emails
    conn = None 

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        # Add the listener to the 'user_status' channel
        await conn.add_listener("user_status", handle_notify)
        await conn.add_listener("policy_status", handle_notify)
        print("Listening on 'user_status' and 'policy_status'...")

        # Keep listening for notifications
        while True:
            await asyncio.sleep(60)  # Keep the listener active without blocking
    except Exception as e:
        print(f"Error connecting to the database: {e}")

    finally:
        if conn:
            await conn.close()
            print("Database connection closed.")