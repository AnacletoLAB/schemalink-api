from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv
import os

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL) # Creates the database connection engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # Creates a database session factory

Base = declarative_base() # Defines the base class for SQLAlchemy models