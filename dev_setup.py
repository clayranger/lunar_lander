"""
dev_setup.py
Development-only helpers.
Do NOT use in production.
"""

import logging
from typing import Optional
from result import Result, Ok, Err

from sqlalchemy.orm import sessionmaker
from db_manager_v2 import engine, Base, User, Wallet
import bcrypt


def create_tables() -> Result[bool]:
    """Create all tables if they don't exist."""
    try:
        Base.metadata.create_all(engine)
        logging.info("[SETUP] Tables created (or already exist)")
        return Ok(True)
    except Exception as e:
        return Err(f"Failed to create tables: {str(e)}")


def add_default_user() -> Result[bool]:
    """Create default dev user if it doesn't exist."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        existing = session.query(User).filter_by(username="adam").first()
        if existing:
            logging.info("[SETUP] Default user already exists")
            return Ok(True)

        password = b"m11ay321"
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password, salt)

        user = User(
            username="adam",
            password=hashed,
            gas_level_choice=0.05,
            tax_level_choice=0.30,
            savings_level_choice=0.10,
        )
        session.add(user)
        session.commit()
        logging.info("[SETUP] Default user 'adam' created")
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(f"Failed to create default user: {str(e)}")
    finally:
        session.close()


def insert_test_wallet(public_key: str) -> Result[bool]:
    """
    Inserts a wallet record using ONLY the public key.
    Private keys should never be stored in the database.
    """
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Check if this public key already exists
        existing = session.query(Wallet).filter_by(publicKey=public_key).first()
        if existing:
            logging.info(f"[SETUP] Wallet with public key {public_key[:8]}... already exists")
            return Ok(True)

        # Get the default user (adam)
        user = session.query(User).filter_by(username="adam").first()
        if not user:
            return Err("Default user not found. Run add_default_user() first.")

        wallet = Wallet(
            publicKey=public_key,
            parent_id=user.id,
            is_irl=False,           # Mark as development/test wallet
        )
        session.add(wallet)
        session.commit()
        logging.info(f"[SETUP] Test wallet inserted: {public_key[:8]}...")
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(f"Failed to insert test wallet: {str(e)}")
    finally:
        session.close()


def setup_known_tokens() -> Result[dict]:
    """Setup known tokens (implementation from previous message)."""
    # ... (keep the version I gave you earlier)
    pass


def full_dev_setup(public_key: Optional[str] = None) -> Result[dict]:
    """
    Runs a full development database setup.
    If public_key is provided, it will be added as a test wallet.
    """
    logging.info("[SETUP] Starting full development setup...")

    results = {}

    # 1. Create tables
    results["create_tables"] = create_tables()

    # 2. Add default user
    results["add_default_user"] = add_default_user()

    # 3. Setup known tokens
    results["setup_known_tokens"] = setup_known_tokens()

    # 4. Insert test wallet (if public key provided)
    if public_key:
        results["insert_test_wallet"] = insert_test_wallet(public_key)
    else:
        results["insert_test_wallet"] = "Skipped (no public_key provided)"

    logging.info("[SETUP] Full development setup completed")
    return Ok(results)
