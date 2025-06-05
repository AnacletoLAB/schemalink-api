from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, Date, DateTime, CheckConstraint
from sqlalchemy.orm import relationship
from database import Base

# SQLAlchemy Models

class User(Base):
    __tablename__ = "users"
    
    username = Column(String(50), primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    password = Column(String(255), nullable=False)
    firstName = Column("firstname", String(20), nullable=False, index=True)
    lastName = Column("lastname", String(20), nullable=False, index=True)
    birthDate = Column("birthdate", Date, nullable=False)
    status = Column(String(8), nullable=False, default="pending")

    subscriptions = relationship("UserSubscribesPolicy", back_populates="user")
    operations = relationship("UserMadeOperation", back_populates="user")

    __table_args__ = (
    CheckConstraint("status IN ('pending', 'active', 'disabled', 'blocked')", name='status_check'),
    )

class Policy(Base):
    __tablename__ = "policy"
    
    name = Column(String(8), primary_key=True, index=True)
    maxAccess = Column("maxaccess", Integer)
    threshold = Column(Integer)
    
    allowed_categories = relationship("PolicyAllowsCategory", back_populates="policy")
    subscriptions = relationship("UserSubscribesPolicy", back_populates="policy")

    __table_args__ = (
        CheckConstraint("name IN ('trial', 'silver', 'gold', 'platinum')", name="policy_name_check"),
    )

class Operation(Base):
    __tablename__ = "operations"
    
    name = Column(String(50), primary_key=True, index=True)
    target = Column(String(8), nullable=True)
    description = Column(String(100), nullable=False)
    
    __table_args__ = (
        CheckConstraint("target IN ('class', 'relation', 'subgraph')", name='target_check'),
    )

    categories = relationship("OperationIsCategory", back_populates="operation")
    user_operations = relationship("UserMadeOperation", back_populates="operation")

class Category(Base):
    __tablename__ = "categories"
    
    name = Column(String(13), primary_key=True, index=True)
    
    __table_args__ = (
    CheckConstraint("name IN ('add', 'fix', 'reification', 'explain', 'openGPTDialog', 'generate')", name='category_check'),
    )
    
    operations = relationship("OperationIsCategory", back_populates="category")
    policy = relationship("PolicyAllowsCategory", back_populates="category")

class UserSubscribesPolicy(Base):
    __tablename__ = "usersubscribespolicy"
    
    username = Column(String(50), ForeignKey("users.username", ondelete="CASCADE"), primary_key=True)
    startDate = Column("startdate", DateTime)
    endDate = Column("enddate", DateTime)
    requestDate = Column("requestdate", DateTime, primary_key=True)
    status = Column(String(8), nullable=False)
    policyName = Column("policyname", String(8), ForeignKey("policy.name", ondelete="RESTRICT"), nullable=False)
    
    user = relationship("User", back_populates="subscriptions")
    policy = relationship("Policy", back_populates="subscriptions")

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'rejected', 'expired')", name="subscription_status_check"),
        CheckConstraint("policyName IN ('trial', 'silver', 'gold', 'platinum,)", name="subscription_policy_check"),
    )

class UserMadeOperation(Base):
    __tablename__ = "usermadeoperation"
    
    username = Column(String(50), ForeignKey("users.username", ondelete="CASCADE"), primary_key=True)
    date = Column(DateTime, primary_key=True)
    operationName = Column("operationname", String(50), ForeignKey("operations.name", ondelete="RESTRICT"), nullable=False)
    
    user = relationship("User", back_populates="operations")
    operation = relationship("Operation", back_populates="user_operations")

class OperationIsCategory(Base):
    __tablename__ = "operationiscategory"
    
    operationName = Column("operationname", String(50), ForeignKey("operations.name", ondelete="CASCADE"), primary_key=True)
    categoryName = Column("categoryname", String(13), ForeignKey("categories.name", ondelete="RESTRICT"), primary_key=True)
    
    operation = relationship("Operation", back_populates="categories")
    category = relationship("Category", back_populates="operations")

    __table_args__ = (
        CheckConstraint("categoryName IN ('add', 'fix', 'reification', 'explain', 'openGPTDialog', 'generate')", name="operation_category_check"),
    )

class PolicyAllowsCategory(Base):
    __tablename__ = "policyallowscategory"
    
    policyName = Column("policyname", String(8), ForeignKey("policy.name", ondelete="CASCADE"), primary_key=True)
    categoryName = Column("categoryname", String(13), ForeignKey("categories.name", ondelete="RESTRICT"), primary_key=True)
    
    policy = relationship("Policy", back_populates="allowed_categories")
    category = relationship("Category", back_populates="policy")

    __table_args__ = (
        CheckConstraint("policyName IN ('trial', 'silver', 'gold', 'platinum')", name="policy_category_policy_check"),
        CheckConstraint("categoryName IN ('add', 'fix', 'reification', 'explain', 'openGPTDialog', 'generate')", name="policy_category_name_check"),
    )
