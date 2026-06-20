"""
dev_setup.py
Development-only database setup helpers.
Do NOT import this in production.
"""

import logging
from typing import Optional
from result import Result, Ok, Err

from sqlalchemy.orm import sessionmaker
from db_manager_v2 import (
    engine,
    Base,
    User,
    Wallet,
    Token,
    get_token_key,
    get_token_metadata,
    sync_wallet_balances,
    get_session,
)
from global_values import solana_tokens
import bcrypt
from solders.pubkey import Pubkey
from solana.rpc.api import Client


def create_tables() -> Result:
    """Create all database tables if they don't exist."""
    try:
        Base.metadata.create_all(engine)
        logging.info("[SETUP] Database tables created")
        return Ok(True)
    except Exception as e:
        return Err(str(e))


def add_default_user() -> Result:
    """Create default development user if it doesn't exist."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if session.query(User).filter_by(username="adam").first():
            logging.info("[SETUP] Default user already exists")
            return Ok(True)

        password = b"m11ay321"
        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

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
        return Err(str(e))
    finally:
        session.close()


def insert_test_wallet(public_key: str) -> Result:
    """Insert a wallet using only the public key (safe - no private key in DB)."""
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if session.query(Wallet).filter_by(publicKey=public_key).first():
            logging.info("[SETUP] Wallet already exists")
            return Ok(True)

        user = session.query(User).filter_by(username="adam").first()
        if not user:
            return Err("Default user not found")

        wallet = Wallet(
            publicKey=public_key,
            parent_id=user.id,
            is_irl=False,
        )
        session.add(wallet)
        session.commit()
        logging.info(f"[SETUP] Test wallet inserted: {public_key[:8]}...")
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(str(e))
    finally:
        session.close()


def setup_known_tokens() -> Result:
    """
    Robust version that creates Token records even if metadata is incomplete.
    Prioritizes getting correct decimals.
    """
    Session = sessionmaker(bind=engine)
    session = Session()

    created = 0
    skipped = 0
    failed = 0

    try:
        client = Client(os.getenv("HELIUS_API_KEY"))

        for mint_address in solana_tokens:
            try:
                token_key = get_token_key(mint_address)
                if token_key.is_err:
                    failed += 1
                    continue

                token_id = token_key.value.tobytes()

                # Skip if already exists
                if session.execute(select(Token).where(Token.id == token_id)).scalar_one_or_none():
                    skipped += 1
                    continue

                # Get decimals (most important)
                decimals = 9
                try:
                    mint_info = client.get_account_info(Pubkey.from_string(mint_address))
                    if mint_info.value and mint_info.value.data:
                        decimals = mint_info.value.data[44]
                except Exception as e:
                    logging.warning(f"[SETUP] Could not get decimals for {mint_address[:8]}: {str(e)}")

                new_token = Token(
                    id=token_id,
                    name="Unknown",
                    tickerSymbol="UNK",
                    contractAddress=token_id,
                    priceServer="jupiter",
                    exchangeSever="jupiter",
                    decimals=decimals,
                    price_tracking=True,
                )

                session.add(new_token)
                session.commit()
                created += 1
                logging.info(f"[SETUP] Added token {mint_address[:8]}... (decimals={decimals})")

            except Exception as e:
                logging.error(f"[SETUP] Error with {mint_address[:8]}: {str(e)}")
                session.rollback()
                failed += 1

        summary = {"created": created, "skipped": skipped, "failed": failed}
        logging.info(f"[SETUP] Token setup complete: {summary}")
        return Ok(summary)

    except Exception as e:
        session.rollback()
        return Err(str(e))
    finally:
        session.close()

def full_dev_setup(public_key: Optional[str] = None) -> Result:
    """
    Full development database setup.
    If public_key is provided, it will be inserted as a test wallet.
    """
    logging.info("[SETUP] Starting full development setup...")

    results = {}

    results["create_tables"] = create_tables()
    results["add_default_user"] = add_default_user()
    results["setup_known_tokens"] = setup_known_tokens()

    wallet_id = None

    if public_key:
        wallet_res = insert_test_wallet(public_key)
        results["insert_test_wallet"] = wallet_res

        if wallet_res.is_ok:
            Session = sessionmaker(bind=engine)
            session = Session()
            try:
                wallet = session.query(Wallet).filter_by(publicKey=public_key).first()
                if wallet:
                    wallet_id = wallet.id
            finally:
                session.close()
    else:
        results["insert_test_wallet"] = "Skipped (no public_key provided)"

    # Sync balances (currently read-only to avoid FK issues)
    if wallet_id:
        with get_session(engine) as session:
            sync_res = sync_wallet_balances(session=session, wallet_pk=wallet_id)
        results["sync_wallet_balances"] = sync_res.value if sync_res.is_ok else str(sync_res.error)
    else:
        results["sync_wallet_balances"] = "Skipped"

    logging.info("[SETUP] Full development setup completed")
    return Ok(results)
