from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from datetime import datetime
import pytz
import models
from database import SessionLocal

def expire_subscriptions_job():
    print("Running scheduled job...")

    db: Session = SessionLocal()

    try:
        local_tz = pytz.timezone("Europe/Rome")
        now = datetime.now(local_tz)

        # Data expiration
        expired = db.query(models.UserSubscribesPolicy).filter(
            models.UserSubscribesPolicy.status == 'active',
            models.UserSubscribesPolicy.endDate <= now
        ).update({"status": "expired"}, synchronize_session=False)

        db.commit()
        print(f"Marked {expired} subscriptions as expired based on date.")
    except Exception as e:
        print(f"Error during scheduled job: {e}")
    finally:
        db.close()