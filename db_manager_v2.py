"""
db_manager_v2.py
Lunar Lander DeFi - Database & Business Logic Layer

Design goals:
- Clean separation for future extraction into Rust/Zig/C
- Consistent Result[Ok/Err] pattern (FFI friendly)
- Clear boundaries between DB access, business logic, and trading
"""

from __future__ import annotations
from dotenv import load_dotenv
import struct
from typing import List, Optional, Dict, Any
import numpy as np
import base58
import base64
import logging
import time
from rpc_client import get_solana_client
from datetime import datetime
from global_values import WORLD_STABLE_COIN, solana_tokens, WORLD_PLATFORM_COIN
from contextlib import contextmanager

from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Session, declarative_base, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary, Float, ForeignKey, cast

from pydantic import BaseModel, Field
from result import Result, Ok, Err

import os

import requests

from solana.rpc.api import Client
from solana.rpc.commitment import Commitment

from logging_config import setup_logging

from solders.message import to_bytes_versioned
import json

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey          # ← Add this line
from solana.rpc.types import TokenAccountOpts
from solders.signature import Signature
from solana.rpc.api import Client
from solana.rpc.commitment import Commitment
from solana.rpc.types import TxOpts
from datetime import datetime, timezone
Base = declarative_base()

load_dotenv()

setup_logging(log_file="trades.log")

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")

# =============================================================================
# 1. MODELS & SCHEMAS
# =============================================================================

class User(Base):
    __tablename__ = "user_table"
    id = mapped_column(Integer, primary_key=True)
    username = mapped_column(String, unique=True, nullable=False)
    password = mapped_column(LargeBinary)
    socket_sid = mapped_column(String, unique=True)
    children: Mapped[List["Wallet"]] = relationship(back_populates="user", cascade="all,delete")
    gas_level_choice = mapped_column(Float)
    tax_level_choice = mapped_column(Float)
    savings_level_choice = mapped_column(Float)
    export_delay_mins = mapped_column(Integer)
    email = mapped_column(String)


class Wallet(Base):
    __tablename__ = "wallet_table"
    id = mapped_column(Integer, primary_key=True)
    publicKey = mapped_column(String)
    privateKey = mapped_column(Integer)
    parent_id = mapped_column(ForeignKey("user_table.id"))
    dollars = mapped_column(Float)
    dollars_counted_at_time = mapped_column(Integer)
    ethOutputAccountPublicKey = mapped_column(String)
    ethInputAccountPublicKey = mapped_column(String)
    ethInputAccountPrivateKey = mapped_column(String)
    user: Mapped["User"] = relationship(back_populates="children")
    is_irl = mapped_column(Boolean)


class Token(Base):
    __tablename__ = "token_table"
    id = mapped_column(LargeBinary, primary_key=True)
    tickerSymbol = mapped_column(String)
    contractAddress = mapped_column(LargeBinary)
    name = mapped_column(String)
    priceServer = mapped_column(String)
    exchangeSever = mapped_column(String)
    price_tracking = mapped_column(Boolean)
    stable_coin_official = mapped_column(Boolean)
    stable_coin_alt = mapped_column(Boolean)
    decimals = mapped_column(Integer)


class Asset(Base):
    __tablename__ = "asset_table"
    id = mapped_column(Integer, primary_key=True)
    wallet = mapped_column(ForeignKey("wallet_table.id"))
    coin = mapped_column(ForeignKey("token_table.id"))
    audited_amount_sum_lamports = mapped_column(BigInteger)
    audited_time_unix_ms = mapped_column(BigInteger)
    isNative = mapped_column(Boolean)
    isOfficialStable = mapped_column(Boolean)
    isAltStable = mapped_column(Boolean)


class Investment(Base):
    __tablename__ = "investment_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("asset_table.id"))
    amount = mapped_column(BigInteger)
    purchase_price_usdc = mapped_column(Float)
    sale_price_usdc = mapped_column(Float)
    purchase_time_ms = mapped_column(BigInteger)
    sale_time_ms = mapped_column(BigInteger)
    buy_fee_native_lamports = mapped_column(Integer)
    buy_fee_usdc = mapped_column(Float)
    sell_fee_native_lamports = mapped_column(Integer)
    sell_fee_usdc = mapped_column(Float)
    revenue_at_sale_usdc = mapped_column(Float)
    isClosed = mapped_column(Boolean, default=False)
    buy_tx_id = mapped_column(String)
    sell_tx_id = mapped_column(String)


class Security(Base):
    __tablename__ = "security_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("asset_table.id"))
    amount = mapped_column(BigInteger)
    purchase_price_usdc = mapped_column(Float)
    sale_price_usdc = mapped_column(Float)
    purchase_time_ms = mapped_column(BigInteger)
    sale_time_ms = mapped_column(BigInteger)
    buy_fee_native_lamports = mapped_column(Integer)
    buy_fee_usdc = mapped_column(Float)
    sell_fee_native_lamports = mapped_column(Integer)
    sell_fee_usdc = mapped_column(Float)
    revenue_at_sale_usdc = mapped_column(Float)
    isClosed = mapped_column(Boolean, default=False)
    buy_tx_id = mapped_column(String)
    sell_tx_id = mapped_column(String)
    isTax = mapped_column(Boolean, default=False)
    isSavings = mapped_column(Boolean, default=False)
    isGas = mapped_column(Boolean, default=False)


# Pydantic Schemas
class InvestmentCreate(BaseModel):
    amount: int = Field(..., gt=0)
    purchase_price_usdc: float = Field(..., gt=0)
    purchase_time_ms: int
    buy_fee_native_lamports: int = Field(..., ge=0)
    buy_fee_usdc: float = Field(..., ge=0)
    buy_tx_id: str
    model_config = {"from_attributes": True}


class SecurityCreate(BaseModel):
    amount: int = Field(..., gt=0)
    purchase_price_usdc: float = Field(..., ge=0)
    purchase_time_ms: int
    buy_fee_native_lamports: int = Field(..., ge=0)
    buy_fee_usdc: float = Field(..., ge=0)
    buy_tx_id: str
    isTax: bool = False
    isSavings: bool = False
    isGas: bool = False
    model_config = {"from_attributes": True}


# =============================================================================
# 2. DATABASE CONNECTION
# =============================================================================

DATABASE_URL = "postgresql+psycopg2://mypguser:m11ay321@localhost:5432/mypgdatabase"
engine = create_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)


@contextmanager
def get_session(engine):
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =============================================================================
# 3. CORE DATABASE HELPERS (Low-level, likely stay in Python)
# =============================================================================

# def get_token_key(given_key: str) -> Result[np.ndarray]:
#     """Convert base58 mint to numpy array for BYTEA storage."""
#     try:
#         decoded = base58.b58decode(given_key.encode())
#         return Ok(np.frombuffer(decoded, dtype="<i4"))
#     except Exception as e:
#         return Err(str(e))


def get_token_key(given_key: str) -> Result:
    """Convert base58 mint → numpy array (for BYTEA storage)."""
    try:
        decoded = base58.b58decode(given_key)
    except Exception as e:
        return Err(f"Invalid base58 key: {e}")

    if len(decoded) % 4 != 0:
        return Err(f"Decoded key length ({len(decoded)} bytes) is not divisible by 4")

    try:
        array = np.frombuffer(decoded, dtype="<i4").copy()
        return Ok(array)
    except Exception as e:
        return Err(f"Failed to create numpy array: {e}")


# def get_token_key(given_key: str) -> Result[np.ndarray, str]:
#     """
#     Convert a base58-encoded mint key into a writable int32 numpy array.
#     """
#     try:
#         decoded = base58.b58decode(given_key)
#     except (ValueError, binascii.Error) as e:
#         return Err(f"Invalid base58 key: {e}")
#     except Exception as e:
#         return Err(f"Failed to decode key: {e}")
#
#     if len(decoded) % 4 != 0:
#         return Err(
#             f"Decoded key length ({len(decoded)} bytes) is not divisible by 4"
#         )
#
#     try:
#         array = np.frombuffer(decoded, dtype="<i4").copy()
#         return Ok(array)
#     except ValueError as e:
#         return Err(f"Invalid buffer for int32 conversion: {e}")
#     except Exception as e:
#         return Err(f"Failed to create numpy array: {e}")


def ensure_asset_exists(
    session: Session, token_key: np.ndarray, wallet_pk: int
) -> Result[int]:
    """Ensure asset row exists for (wallet, token). Returns asset.id."""
    does_exist = session.query(
        session.query(Asset).filter_by(coin=cast(token_key, BYTEA)).exists()
    ).scalar()

    if not does_exist:
        asset_obj = Asset(
            wallet=wallet_pk,
            coin=cast(token_key, BYTEA),
            isNative=False,
            isOfficialStable=False,
            isAltStable=False,
        )
        session.add(asset_obj)
        session.flush()

    try:
        asset = session.execute(
            select(Asset).filter_by(coin=cast(token_key, BYTEA))
        ).scalar_one()
        return Ok(asset.id)
    except Exception as e:
        return Err(str(e))


def aquire_wallet_key(
    session: Session,
    wallet_id: Optional[int] = None,
    wallet_public_key: Optional[str] = None
) -> Result[int]:
    """Get wallet primary key from ID, public key, or fall back to single wallet."""
    if wallet_id is not None:
        return Ok(wallet_id)

    if wallet_public_key is not None:
        pk = get_wallet_id_by_public_key(session, wallet_public_key)
        if pk:
            return Ok(pk)

    single = get_single_wallet_pk(session)
    if single.is_ok() and single.unwrap():
        return Ok(single.unwrap())

    return Err("Cannot acquire wallet primary key")


# =============================================================================
# 4. INVESTMENT OPERATIONS
# =============================================================================

def insert_investment(
    session: Session,
    token_key: np.ndarray,
    investment_data: InvestmentCreate,
    wallet_id: Optional[int] = None,
    wallet_public_key: Optional[str] = None,
) -> Result[bool]:
    """Insert a new investment. Clean, session-based."""
    wallet_res = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_res.is_err():
        return Err(f"Wallet error: {wallet_res.unwrap_err()}")

    asset_res = ensure_asset_exists(session, token_key, wallet_res.unwrap())
    if asset_res.is_err():
        return asset_res

    try:
        data = investment_data.model_dump()
        data["parent_id"] = asset_res.unwrap()
        inv = Investment(**data)
        session.add(inv)
        session.flush()
        return Ok(True)
    except Exception as exc:
        session.rollback()
        return Err(str(exc))


def record_partial_sell(
    session: Session,
    investment_id: int,
    sold_lamports: int,
    sell_tx_id: str,
    sell_price_usdc: float,
    sell_fee_usdc: float = 0.0,
) -> Result[bool]:
    """
    Close part (or all) of an investment.
    If there's remaining amount, create a new open investment for it.
    """
    try:
        inv = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one()

        if inv.isClosed:
            return Err("Investment already closed")

        remaining = inv.amount - sold_lamports
        if remaining < 0:
            return Err("Sold more lamports than available")

        # Close the sold portion
        inv.amount = sold_lamports
        inv.isClosed = True
        inv.sell_tx_id = sell_tx_id
        inv.sale_price_usdc = sell_price_usdc
        inv.sell_fee_usdc = sell_fee_usdc
        inv.sale_time_ms = int(time.time() * 1000)

        # Create remaining open investment if anything is left
        if remaining > 0:
            new_inv = Investment(
                parent_id=inv.parent_id,
                amount=remaining,
                purchase_price_usdc=inv.purchase_price_usdc,
                purchase_time_ms=inv.purchase_time_ms,
                buy_fee_native_lamports=inv.buy_fee_native_lamports,
                buy_fee_usdc=inv.buy_fee_usdc,
                buy_tx_id=inv.buy_tx_id,
                isClosed=False,
            )
            session.add(new_inv)

        session.flush()
        return Ok(True)

    except Exception as e:
        session.rollback()
        return Err(str(e))



# =============================================================================
# 5. SECURITY OPERATIONS (Gas + Tax buckets)
# =============================================================================

def get_available_gas_lamports(session: Session, wallet_pk: int) -> Result[int]:
    """Returns total lamports available in open gas securities for this wallet."""
    try:
        stmt = (
            select(func.sum(Security.amount))
            .join(Asset, Security.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Security.isGas == True,
                Security.isClosed == False
            )
        )
        total = session.execute(stmt).scalar() or 0
        return Ok(int(total))
    except Exception as e:
        return Err(str(e))


def ensure_sufficient_gas(session: Session, required_lamports: int, wallet_pk: int) -> Result[bool]:
    """Check if the wallet has enough open gas security."""
    gas_res = get_available_gas_lamports(session, wallet_pk)
    if gas_res.is_err():
        return gas_res

    if gas_res.unwrap() < required_lamports:
        return Err(
            f"Insufficient gas: need {required_lamports} lamports, "
            f"only {gas_res.unwrap()} available"
        )
    return Ok(True)


def spend_gas_security(
    session: Session,
    gas_security_id: int,
    used_lamports: int,
    tx_id: str,
) -> Result[bool]:
    """Reduce gas from a Security after using it for fees."""
    try:
        sec = session.execute(
            select(Security).where(Security.id == gas_security_id)
        ).scalar_one()

        if sec.isClosed:
            return Err("Gas security already closed")

        if used_lamports > sec.amount:
            return Err("Trying to spend more gas than available")

        remaining = sec.amount - used_lamports
        sec.amount = max(0, remaining)
        sec.isClosed = remaining <= 0
        sec.sell_tx_id = tx_id
        sec.sale_time_ms = int(time.time() * 1000)

        session.flush()
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(str(e))


def get_oldest_gas_security(session: Session, wallet_pk: int) -> Result[Optional[int]]:
    """Get the oldest open gas security ID for auto-selection."""
    try:
        stmt = (
            select(Security.id)
            .join(Asset, Security.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Security.isGas == True,
                Security.isClosed == False
            )
            .order_by(Security.purchase_time_ms.asc())
            .limit(1)
        )
        sec_id = session.execute(stmt).scalar()
        return Ok(sec_id)
    except Exception as e:
        return Err(str(e))


# =============================================================================
# 6. TAX LOGIC (High value to keep clean)
# =============================================================================

def calculate_realized_gain(
    session: Session,
    investment_id: int,
    sell_price_usdc: float
) -> Result[dict]:
    """Calculate profit/loss when closing an investment."""
    try:
        inv = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one()

        purchase_price = inv.purchase_price_usdc or 0.0
        profit = sell_price_usdc - purchase_price

        return Ok({
            "profit_usdc": profit,
            "is_profitable": profit > 0,
            "purchase_price_usdc": purchase_price,
            "sell_price_usdc": sell_price_usdc,
        })
    except Exception as e:
        return Err(str(e))


def withhold_tax_on_profitable_sale(
    session: Session,
    investment_id: int,
    sell_proceeds_usdc: float,
    wallet_pk: int
) -> Result[bool]:
    """Automatically withhold tax into a Security(isTax=True) on profitable sales."""
    try:
        gain_res = calculate_realized_gain(session, investment_id, sell_proceeds_usdc)
        if gain_res.is_err():
            return gain_res

        gain = gain_res.unwrap()
        if not gain["is_profitable"]:
            return Ok(False)

        # Get user's tax rate
        wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one()
        user = session.execute(select(User).where(User.id == wallet.parent_id)).scalar_one()
        tax_rate = user.tax_level_choice or 0.30

        tax_amount = round(gain["profit_usdc"] * tax_rate, 2)
        if tax_amount <= 0:
            return Ok(False)

        tax_sec = SecurityCreate(
            amount=0,
            purchase_price_usdc=tax_amount,
            purchase_time_ms=int(time.time() * 1000),
            buy_fee_native_lamports=0,
            buy_fee_usdc=0,
            buy_tx_id=f"tax_withhold_{investment_id}",
            isTax=True,
        )

        _stable_key_res = get_token_key(WORLD_STABLE_COIN)
        if _stable_key_res.is_err():
            return _stable_key_res
        stable_key = _stable_key_res.unwrap()
        insert_res = insert_security(session, stable_key, tax_sec, wallet_id=wallet_pk)

        if insert_res.is_err():
            return insert_res

        logging.info(f"✅ Tax withheld: ${tax_amount:.2f}")
        return Ok(True)

    except Exception as e:
        session.rollback()
        return Err(str(e))


def get_total_tax_owed(session: Session, wallet_pk: int) -> Result[float]:
    """
    Returns the total USDC value currently held in open tax securities
    for this wallet.
    """
    try:
        stmt = (
            select(func.sum(Security.purchase_price_usdc))
            .join(Asset, Security.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Security.isTax == True,
                Security.isClosed == False
            )
        )
        total = session.execute(stmt).scalar()

        # Handle case where there are no tax securities
        if total is None:
            total = 0.0

        return Ok(float(total))

    except Exception as e:
        return Err(str(e))


def get_open_tax_securities(session: Session, wallet_pk: int) -> Result[List[Security]]:
    """List of open tax securities (for review/payment)."""
    pass


# =============================================================================
# 7. HIGH-LEVEL TRADE EXECUTION (Orchestrator)
# ============================================================================

def load_keypair_from_file(filepath: str) -> Keypair:
    with open(filepath, "r") as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))

def get_current_priority_fee(min_fee: int = 100_000) -> int:
    """Get dynamic priority fee using the primary/backup RPC client."""
    from rpc_client import get_solana_client
    client = get_solana_client()

    try:
        fees = client.get_recent_prioritization_fees()
        if fees.value:
            recent_fees = [f.prioritization_fee for f in fees.value if f.prioritization_fee > 0]
            if recent_fees:
                suggested = int(np.percentile(recent_fees, 75))
                return max(min_fee, suggested * 2)
    except Exception as e:
        logging.warning(f"[RPC] Priority fee fetch failed: {str(e)}")

    return min_fee * 5


def get_jupiter_swap_transaction(
    wallet_public_key: str,
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int = 50,
) -> Result[str]:
    priority_fee = get_current_priority_fee()

    jupiter_api_key = JUPITER_API_KEY
    if not jupiter_api_key:
        return Err("JUPITER_API_KEY not found in environment variables — get a free key at portal.jup.ag")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": jupiter_api_key,                 #  Correct header format
    }

    # Step 1: Get a quote from Jupiter (new api.jup.ag domain, paths unchanged)
    quote_url = f"https://lite-api.jup.ag/swap/v1/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={slippage_bps}"

    try:
        quote_response = requests.get(quote_url, headers=headers, timeout=15)
        logging.info(f"STATUS: {quote_response.status_code}")
        logging.info(f"BODY: {quote_response.text}")
        quote_response.raise_for_status()
        quote_data = quote_response.json()
        # For Free Tier
        time.sleep(1.1)
    except Exception as e:
        return Err(f"Jupiter quote request failed: {str(e)}")

    # Step 2: Request the swap transaction
    # Free devel
    # swap_url = "https://api.jup.ag/swap/v1/swap"
    swap_url = "https://lite-api.jup.ag/swap/v1/swap"
    payload = {
        "quoteResponse": quote_data,
        "userPublicKey": wallet_public_key,
        "prioritizationFeeLamports": priority_fee,
        "wrapAndUnwrapSol": True,
    }

    try:
        response = requests.post(swap_url, json=payload, headers=headers, timeout=30)
        logging.info(f"STATUS: {quote_response.status_code}")
        logging.info(f"BODY: {quote_response.text}")
        response.raise_for_status()
        data = response.json()
        tx_base64 = data.get("swapTransaction")
        if not tx_base64:
            return Err("No swapTransaction returned")
        logging.info(f"[SWAP] Using priority fee: {priority_fee} lamports")
        return Ok(tx_base64)
    except Exception as e:
        return Err(f"Swap request failed: {str(e)}")

def sign_and_send_transaction(
    tx_base64: str,
    keypair: Keypair,
    rpc_url: str = None
) -> Result[str]:
    if rpc_url is None:
        helius_key = os.getenv("HELIUS_API_KEY")
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"

    try:
        client = Client(rpc_url)
        tx_bytes = base64.b64decode(tx_base64)
        tx = VersionedTransaction.from_bytes(tx_bytes)

        signed_tx = VersionedTransaction(tx.message, [keypair])

        result = client.send_transaction(
            signed_tx,
            opts=TxOpts(
                skip_preflight=False,
                preflight_commitment=Commitment("confirmed"),
            )
        )
        return Ok(str(result.value))
    except Exception as e:
        return Err(f"Failed to sign and send transaction: {str(e)}")


def confirm_transaction(
    tx_signature: str,
    rpc_url: str = None,
    max_retries: int = 30,
    sleep_seconds: float = 2.0
) -> Result[dict]:
    if rpc_url is None:
        helius_key = os.getenv("HELIUS_API_KEY")
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"

    client = Client(rpc_url)

    for attempt in range(max_retries):
        try:
            response = client.get_transaction(
                Signature.from_string(tx_signature),
                commitment=Commitment("confirmed"),
                max_supported_transaction_version=0,
            )

            if response.value:
                meta = response.value.transaction.meta
                if meta and meta.err is None:
                    return Ok({
                        "signature": tx_signature,
                        "status": "confirmed",
                        "slot": response.value.slot,
                    })
                else:
                    return Err(f"Transaction failed on-chain: {meta.err if meta else 'Unknown error'}")

            time.sleep(sleep_seconds)
        except Exception as e:
            logging.warning(f"[CONFIRM] Error checking transaction: {str(e)}")
            time.sleep(sleep_seconds)

    return Err(f"Transaction not confirmed after {max_retries} attempts")


def execute_trade_with_gas(
    session: Session,
    investment_id: int,
    target_mint: str,
    estimated_gas_lamports: int = 500_000,
    wallet_pk: int = None,
    sell_lamports: int = None,
    gas_security_id: Optional[int] = None,
    max_retries: int = 3,
    keypair_path: str = "~/.config/solana/mainnet-test.json",
    slippage_bps: int = 50,
) -> Result[dict]:
    """
    Full trade orchestrator with dynamic priority fees and automatic RPC fallback.
    """
    logging.info(f"[TRADE] Starting trade | investment_id={investment_id}")

    helius_api_key = os.getenv("HELIUS_API_KEY")
    if not helius_api_key:
        return Err("HELIUS_API_KEY not found in environment variables")

    # Load keypair
    try:
        keypair = load_keypair_from_file(os.path.expanduser(keypair_path))
        wallet_public_key = str(keypair.pubkey())
    except Exception as e:
        return Err(f"Failed to load keypair: {str(e)}")

    # Calculate priority fee once
    priority_fee = get_current_priority_fee()

    for attempt in range(1, max_retries + 1):
        try:
            # === Load Investment ===
            inv = session.execute(
                select(Investment).where(Investment.id == investment_id)
            ).scalar_one_or_none()

            if not inv:
                log_trade_result(
                    investment_id=investment_id,
                    wallet_pk=wallet_pk,
                    status="failed",
                    error_message="Investment not found",
                    priority_fee_lamports=priority_fee,
                )
                return Err("Investment not found")

            if sell_lamports is None:
                sell_lamports = inv.amount // 2

            if sell_lamports <= 0 or sell_lamports > inv.amount:
                return Err("Invalid sell amount")

            # === Safety + Gas checks ===
            safety = pre_trade_safety_check(
                session=session,
                investment_id=investment_id,
                sell_lamports=sell_lamports,
                estimated_gas_lamports=estimated_gas_lamports,
                wallet_pk=wallet_pk,
            )
            if safety.is_err():
                log_trade_result(
                    investment_id=investment_id,
                    wallet_pk=wallet_pk,
                    status="failed",
                    error_message=f"Safety check failed: {safety.err_value}",
                    priority_fee_lamports=priority_fee,
                )
                return Err(f"Safety check failed: {safety.err_value}")

            gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
            if gas_check.is_err():
                return gas_check

            # === Get swap transaction (now uses dynamic priority fee + RPC fallback) ===
            logging.info(f"[SWAP] Attempt {attempt}/{max_retries} | Priority fee: {priority_fee} lamports")

            swap_tx_res = get_jupiter_swap_transaction(   # ← renamed function
                wallet_public_key=wallet_public_key,
                input_mint=WORLD_STABLE_COIN,
                output_mint=target_mint,
                amount=sell_lamports,
                slippage_bps=slippage_bps,
            )

            if swap_tx_res.is_err():
                error_msg = swap_tx_res.err_value
                log_trade_result(
                    investment_id=investment_id,
                    wallet_pk=wallet_pk,
                    status="failed",
                    error_message=error_msg,
                    priority_fee_lamports=priority_fee,
                )
                if attempt == max_retries:
                    return Err(f"Swap failed after {max_retries} attempts: {error_msg}")
                time.sleep(2)
                continue

            tx_base64 = swap_tx_res.ok_value

            # === Sign and send ===
            send_res = sign_and_send_transaction(tx_base64, keypair)
            if send_res.is_err():
                error_msg = send_res.err_value
                log_trade_result(
                    investment_id=investment_id,
                    wallet_pk=wallet_pk,
                    status="failed",
                    error_message=error_msg,
                    priority_fee_lamports=priority_fee,
                )
                if attempt == max_retries:
                    return Err(f"Sign/Send failed after {max_retries} attempts: {error_msg}")
                time.sleep(2)
                continue

            tx_sig = send_res.ok_value
            logging.info(f"[SWAP] Transaction sent: {tx_sig}")

            # === Confirm ===
            confirm_res = confirm_transaction(tx_sig)
            if confirm_res.is_err():
                log_trade_result(
                    investment_id=investment_id,
                    wallet_pk=wallet_pk,
                    status="failed",
                    error_message=confirm_res.err_value,
                    priority_fee_lamports=priority_fee,
                )
                return Err(f"Transaction confirmation failed: {confirm_res.err_value}")

            logging.info(f"[CONFIRM] Transaction confirmed: {tx_sig}")

            # === Record trade ===
            record_res = record_partial_sell(
                session=session,
                investment_id=investment_id,
                sold_lamports=sell_lamports,
                sell_tx_id=tx_sig,
                sell_price_usdc=0.0,
            )
            if record_res.is_err():
                return record_res

            # Spend gas + withhold tax
            if gas_security_id:
                spend_gas_security(session, gas_security_id, estimated_gas_lamports, tx_sig)

            withhold_tax_on_profitable_sale(
                session=session,
                investment_id=investment_id,
                sell_proceeds_usdc=0.0,
                wallet_pk=wallet_pk,
            )

            # === Final success log ===
            log_trade_result(
                investment_id=investment_id,
                wallet_pk=wallet_pk,
                status="success",
                tx_signature=tx_sig,
                sold_lamports=sell_lamports,
                priority_fee_lamports=priority_fee,
            )

            logging.info(f"[TRADE] Completed successfully")
            return Ok({
                "status": "success",
                "investment_id": investment_id,
                "tx_signature": tx_sig,
                "sold_lamports": sell_lamports,
                "priority_fee_lamports": priority_fee,
            })

        except Exception as e:
            log_trade_result(
                investment_id=investment_id,
                wallet_pk=wallet_pk,
                status="failed",
                error_message=str(e),
                priority_fee_lamports=priority_fee,
            )
            if attempt == max_retries:
                return Err(f"Trade failed after {max_retries} attempts: {str(e)}")
            time.sleep(2)

    return Err(f"Trade failed after {max_retries} attempts")



def sync_wallet_balances(
    session: Session,
    wallet_pk: int,
    wallet_public_key: str = None,
) -> Result:
    """
    Syncs on-chain balances into the Asset table (with debug logging).
    """
    from rpc_client import get_solana_client
    from global_values import WORLD_PLATFORM_COIN

    if wallet_public_key is None:
        wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
        if not wallet:
            return Err("Wallet not found")
        wallet_public_key = wallet.publicKey

    client = get_solana_client()
    owner = Pubkey.from_string(wallet_public_key)

    created = 0
    updated = 0

    try:
        # === 1. Native Platform Coin ===
        platform_key = get_token_key(WORLD_PLATFORM_COIN)
        if platform_key.is_err():
            return Err(platform_key.err_value)

        platform_mint = platform_key.unwrap().tobytes()
        native_balance = client.get_balance(owner).value

        native_asset = session.execute(
            select(Asset).where(Asset.wallet == wallet_pk, Asset.coin == platform_mint)
        ).scalar_one_or_none()

        if native_asset:
            if native_asset.audited_amount_sum_lamports != native_balance:
                native_asset.audited_amount_sum_lamports = native_balance
                native_asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                updated += 1
        else:
            new_asset = Asset(
                wallet=wallet_pk,
                coin=platform_mint,
                audited_amount_sum_lamports=native_balance,
                audited_time_unix_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                isNative=True,
            )
            session.add(new_asset)
            created += 1

        # === 2. SPL Tokens with Debug Logging ===
        try:
            resp = client.get_token_accounts_by_owner(
                owner,
                TokenAccountOpts(
                    program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                ),
                commitment="confirmed",
            )
            token_accounts = resp.value or []
        except Exception as e:
            logging.warning(f"[SYNC] Could not fetch token accounts: {str(e)}")
            token_accounts = []

        print(f"\n[DEBUG] Found {len(token_accounts)} token accounts for this wallet")

        for idx, acc in enumerate(token_accounts):
            try:
                raw = bytes(acc.account.data)

                # SPL Token account layout:
                # mint: [0:32], owner: [32:64], amount: [64:72] (u64 little-endian)
                if len(raw) < 72:
                    print(f"[DEBUG] [{idx}] Skipped - account data too short ({len(raw)} bytes)")
                    continue

                mint_bytes = raw[0:32]
                amount = struct.unpack_from("<Q", raw, 64)[0]

                import base58
                mint = base58.b58encode(mint_bytes).decode("utf-8")

                print(f"[DEBUG] [{idx}] Found token: {mint[:8]}... amount={amount}")

                # ... rest of your token_exists / asset upsert logic unchanged ...

                # Check if token exists in token_table
                token_exists = session.execute(
                    select(Token).where(Token.id == mint.encode())
                ).scalar_one_or_none()

                if not token_exists:
                    print(f"[DEBUG] [{idx}] Token {mint[:8]} not in database - trying to add it...")
                    try:
                        token_key = get_token_key(mint)
                        if token_key.is_ok():
                            decimals = 9
                            try:
                                supply = client.get_token_supply(Pubkey.from_string(mint))
                                if supply.value and supply.value.decimals is not None:
                                    decimals = supply.value.decimals
                            except:
                                pass

                            new_token = Token(
                                id=mint.encode(),
                                name="Unknown Token",
                                tickerSymbol="UNK",
                                contractAddress=mint.encode(),
                                priceServer="jupiter",
                                exchangeSever="jupiter",
                                decimals=decimals,
                                price_tracking=False,
                            )
                            session.add(new_token)
                            session.commit()
                            print(f"[DEBUG] [{idx}] Successfully added unknown token: {mint[:8]}")
                    except Exception as e:
                        print(f"[DEBUG] [{idx}] Failed to add unknown token: {str(e)}")
                        continue

                # Create or update Asset
                asset = session.execute(
                    select(Asset).where(Asset.wallet == wallet_pk, Asset.coin == mint.encode())
                ).scalar_one_or_none()

                if asset:
                    if asset.audited_amount_sum_lamports != amount:
                        asset.audited_amount_sum_lamports = amount
                        asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                        updated += 1
                        print(f"[DEBUG] [{idx}] Updated existing Asset for {mint[:8]}")
                else:
                    new_asset = Asset(
                        wallet=wallet_pk,
                        coin=mint.encode(),
                        audited_amount_sum_lamports=amount,
                        audited_time_unix_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                        isNative=False,
                    )
                    session.add(new_asset)
                    created += 1
                    print(f"[DEBUG] [{idx}] Created NEW Asset for token: {mint[:8]}")

            except Exception as e:
                print(f"[DEBUG] [{idx}] Error processing account: {str(e)}")
                continue

        session.commit()
        summary = {"created_assets": created, "updated_assets": updated}
        print(f"\n[DEBUG] Final summary: {summary}")
        logging.info(f"[SYNC] Wallet {wallet_pk} sync complete: {summary}")
        return Ok(summary)

    except Exception as e:
        session.rollback()
        logging.error(f"[SYNC] Failed to sync wallet {wallet_pk}: {str(e)}")
        return Err(str(e))



# ============================ AUDIT / WALLET SUMMARY ============================

def get_wallet_summary(session: Session, wallet_pk: int) -> Result[dict]:
    """
    Returns a high-level summary of the wallet for auditing and monitoring.
    More defensive version with better error handling.
    """
    try:
        # 1. Count open investments
        open_inv_stmt = (
            select(func.count())
            .select_from(Investment)
            .join(Asset, Investment.parent_id == Asset.id)
            .where(Asset.wallet == wallet_pk, Investment.isClosed == False)
        )
        open_investments = session.execute(open_inv_stmt).scalar() or 0

        # 2. Total tax reserved (USDC)
        tax_res = get_total_tax_owed(session, wallet_pk)
        total_tax_reserved = tax_res.unwrap() if tax_res.is_ok() else 0.0

        # 3. Total gas available (lamports + SOL)
        gas_res = get_available_gas_lamports(session, wallet_pk)
        total_gas_lamports = gas_res.unwrap() if gas_res.is_ok() else 0

        # 4. Total value in open investments (purchase price in USDC)
        inv_value_stmt = (
            select(func.sum(Investment.purchase_price_usdc))
            .join(Asset, Investment.parent_id == Asset.id)
            .where(Asset.wallet == wallet_pk, Investment.isClosed == False)
        )
        total_investment_value = session.execute(inv_value_stmt).scalar() or 0.0

        summary = {
            "wallet_id": wallet_pk,
            "open_investments_count": open_investments,
            "total_investment_value_usdc": round(total_investment_value, 2),
            "total_tax_reserved_usdc": round(total_tax_reserved, 2),
            "total_gas_lamports": total_gas_lamports,
            "total_gas_sol": round(total_gas_lamports / 1_000_000_000, 6),
            "timestamp": int(time.time()),
        }

        return Ok(summary)

    except Exception as e:
        return Err(f"Failed to build wallet summary: {str(e)}")



# ============================ OPEN INVESTMENTS ============================

def get_open_investments(session: Session, wallet_pk: int) -> Result[List[dict]]:
    """
    Returns a list of currently open investments for the wallet.
    Useful for reviewing positions before trading.
    """
    try:
        stmt = (
            select(Investment)
            .join(Asset, Investment.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Investment.isClosed == False
            )
            .order_by(Investment.purchase_time_ms.desc())
        )

        investments = session.execute(stmt).scalars().all()

        result = []
        for inv in investments:
            result.append({
                "investment_id": inv.id,
                "amount_lamports": inv.amount,
                "purchase_price_usdc": inv.purchase_price_usdc,
                "purchase_time_ms": inv.purchase_time_ms,
                "buy_tx_id": inv.buy_tx_id,
            })

        return Ok(result)

    except Exception as e:
        return Err(str(e))



def execute_jupiter_swap_via_helius(
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int = 50,
    priority_fee_lamports: int = 500_000,
    helius_api_key: str = None,
    wallet_public_key: str = None,
) -> Result[dict]:
    """
    Executes a Jupiter swap using Helius Swap Sender.
    Automatically reads HELIUS_API_KEY and WALLET_PUBLIC_KEY from environment variables
    if not passed explicitly.
    """
    # Load from environment variables if not provided
    helius_api_key = helius_api_key or os.getenv("HELIUS_API_KEY")
    wallet_public_key = wallet_public_key or os.getenv("WALLET_PUBLIC_KEY")

    if not helius_api_key:
        return Err("Helius API key is missing (set HELIUS_API_KEY environment variable)")
    if not wallet_public_key:
        return Err("Wallet public key is missing (set WALLET_PUBLIC_KEY environment variable)")

    url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-jupiter-swap",
        "method": "getJupiterSwapTransaction",
        "params": {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
            "userPublicKey": wallet_public_key,
            "prioritizationFeeLamports": priority_fee_lamports,
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            return Err(f"Helius API error: {data['error']}")

        result = data.get("result", {})
        signature = result.get("signature")

        if not signature:
            return Err("No transaction signature returned from Helius")

        return Ok({
            "signature": signature,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
            "wallet_public_key": wallet_public_key,
        })

    except requests.exceptions.RequestException as e:
        return Err(f"Helius request failed: {str(e)}")
    except Exception as e:
        return Err(f"Unexpected error during Helius swap: {str(e)}")


def is_number_wallets_1(session: Session) -> Result[bool]:
    """Check if there is exactly one wallet in the database."""
    try:
        stmt = select(func.count()).select_from(Wallet)
        count = session.scalar(stmt)
        return Ok(count == 1)
    except Exception as e:
        return Err(str(e))


def get_single_wallet_pk(session: Session) -> Result[Optional[int]]:
    """Returns wallet PK if exactly one wallet exists in the database."""
    try:
        stmt = select(Wallet.id).select_from(Wallet).limit(2)
        ids = session.scalars(stmt).all()
        if len(ids) == 1:
            return Ok(ids[0])
        return Ok(None)
    except Exception as e:
        return Err(str(e))


def get_wallet_id_by_public_key(db_session: Session, public_key: str) -> Optional[int]:
    """Get wallet primary key from a public key string."""
    try:
        stmt = select(Wallet.id).where(Wallet.publicKey == public_key)
        return db_session.execute(stmt).scalar()
    except Exception as e:
        logging.error(f"[get_wallet_id_by_public_key] {e}")
        return None


def get_wallet_for_asset(session: Session, asset_id: int) -> Result[int]:
    """
    Returns the wallet primary key (wallet_pk) that owns the given asset.
    Uses your custom Result class.
    """
    try:
        asset = session.execute(
            select(Asset).where(Asset.id == asset_id)
        ).scalar_one_or_none()

        if not asset:
            return Err(f"Asset with id {asset_id} not found")

        return Ok(asset.wallet)

    except Exception as e:
        return Err(str(e))


def log_trade_result(
    investment_id: int,
    wallet_pk: int,
    status: str,                    # "success" or "failed"
    tx_signature: str = None,
    sold_lamports: int = None,
    received_amount: int = None,
    sell_price_usdc: float = None,
    error_message: str = None,
    extra_info: dict = None,
    priority_fee_lamports: int = None,   # ← NEW
):
    """
    Enhanced trade result logger.
    Now includes priority fee used.
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "investment_id": investment_id,
        "wallet_id": wallet_pk,
        "status": status,
        "tx_signature": tx_signature,
        "sold_lamports": sold_lamports,
        "received_amount": received_amount,
        "sell_price_usdc": sell_price_usdc,
        "error_message": error_message,
        "priority_fee_lamports": priority_fee_lamports,   # ← NEW
    }

    if extra_info:
        log_entry.update(extra_info)

    if status.lower() == "success":
        logging.info(f"[TRADE] {log_entry}")
    else:
        logging.error(f"[TRADE] {log_entry}")



def execute_sell_percentage_investment(
    session: Session,
    investment_id: int,
    target_mint: str,
    sell_percentage: float = 50.0,
    estimated_gas_lamports: int = 500_000,
    wallet_pk: int = None,
    keypair_path: str = "~/.config/solana/mainnet-test.json",
    slippage_bps: int = 50,
) -> Result[dict]:
    """
    Sells a percentage of an investment.
    Cleanly exposes slippage_bps and uses the latest trade engine.
    """
    if wallet_pk is None:
        single = get_single_wallet_pk(session)
        if single.is_ok() and single.value:
            wallet_pk = single.value
        else:
            return Err("wallet_pk not provided and no default wallet could be determined")

    # Load the investment
    inv = session.execute(
        select(Investment).where(Investment.id == investment_id)
    ).scalar_one_or_none()

    if not inv:
        return Err(f"Investment {investment_id} not found")

    if inv.isClosed:
        return Err(f"Investment {investment_id} is already closed")

    if sell_percentage <= 0 or sell_percentage > 100:
        return Err("sell_percentage must be between 0 and 100")

    sell_lamports = int(inv.amount * (sell_percentage / 100))

    if sell_lamports <= 0:
        return Err("Calculated sell amount is zero or negative")

    # Call the main trade engine
    return execute_trade_with_gas(
        session=session,
        investment_id=investment_id,
        target_mint=target_mint,
        estimated_gas_lamports=estimated_gas_lamports,
        wallet_pk=wallet_pk,
        sell_lamports=sell_lamports,
        keypair_path=keypair_path,
        slippage_bps=slippage_bps,
    )







def get_jupiter_quote(
    input_mint: str,
    output_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    amount: int = 100_000_000,  # in smallest units (e.g. 0.1 SOL = 100000000)
    slippage_bps: int = 50,
) -> Result[dict]:
    """
    Gets a Jupiter swap quote.
    Falls back between two Jupiter endpoints if one fails.
    """
    endpoints = [
        "https://public.jupiterapi.com/quote",
        "https://quote-api.jup.ag/v6/quote",
    ]

    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount),
        "slippageBps": str(slippage_bps),
    }

    for url in endpoints:
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return Ok(response.json())
        except Exception as e:
            logging.warning(f"[JUPITER] Quote failed on {url}: {str(e)}. Trying next...")

    return Err("Failed to get Jupiter quote from all endpoints")


def get_token_metadata(mint_address: str) -> Result[dict]:
    """
    Fetches token name and symbol.
    Uses Metaplex first, falls back to Solana Token List.
    """
    try:
        from metaplex import Metaplex  # You may need to install a Python Metaplex lib or implement manually
        # For now we'll use a simpler RPC-based approach
    except ImportError:
        pass

    try:
        # Try Metaplex-style metadata account
        metadata_pda = PublicKey.find_program_address(
            [b"metadata", bytes(METAPLEX_PROGRAM_ID), bytes(PublicKey(mint_address))],
            METAPLEX_PROGRAM_ID
        )[0]

        account_info = Client(os.getenv("HELIUS_API_KEY")).get_account_info(metadata_pda)
        if account_info.value:
            # Parse metadata (simplified)
            return Ok({"name": "Parsed Name", "symbol": "SYM"})  # TODO: proper parsing

    except Exception:
        pass

    # Fallback: Use known token list or Jupiter token list
    try:
        url = f"https://token.jup.ag/all"
        resp = requests.get(url, timeout=10)
        tokens = resp.json()
        for token in tokens:
            if token.get("address") == mint_address:
                return Ok({
                    "name": token.get("name"),
                    "symbol": token.get("symbol"),
                })
    except Exception as e:
        return Err(f"Failed to fetch token metadata: {str(e)}")

    return Err("Token metadata not found")


def calculate_decimal_multiplier(mint_address: str) -> Result[dict]:
    """
    Returns the multiplier needed to convert token amount to USDC-equivalent units.
    """
    try:
        client = get_solana_client()
        mint_info = client.get_account_info(PublicKey(mint_address))

        if not mint_info.value or not mint_info.value.data:
            return Err("Could not fetch mint info")

        # Parse decimals from mint account (simplified)
        decimals = int.from_bytes(mint_info.value.data[44:45], "little")

        usdc_decimals = 6
        difference = decimals - usdc_decimals

        if difference > 0:
            multiplier = 10 ** difference
        else:
            multiplier = 1 / (10 ** abs(difference))

        return Ok({
            "decimals": decimals,
            "multiplier": multiplier,
        })

    except Exception as e:
        return Err(f"Failed to calculate decimal multiplier: {str(e)}")


def deposit_usdc_to_savings(
    session: Session,
    wallet_pk: int,
    amount_lamports: int,
) -> Result[int]:
    """
    Deposits USDC into a Savings Security.
    Creates a new Savings Security if none exists.
    """
    if amount_lamports <= 0:
        return Err("Amount must be greater than zero")

    # Check wallet exists
    wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
    if not wallet:
        return Err("Wallet not found")

    # Find or create Savings Security
    savings_sec = session.execute(
        select(Security)
        .join(Asset, Security.parent_id == Asset.id)
        .where(
            Asset.wallet == wallet_pk,
            Security.isClosed == False,
            Security.isSavings == True
        )
        .order_by(Security.purchase_time_ms.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not savings_sec:
        main_asset = session.execute(
            select(Asset).where(Asset.wallet == wallet_pk).limit(1)
        ).scalar_one_or_none()

        if not main_asset:
            return Err("No asset found for this wallet")

        savings_sec = Security(
            parent_id=main_asset.id,
            amount=0,
            purchase_price_usdc=0.0,
            purchase_time_ms=int(time.time() * 1000),
            buy_fee_native_lamports=0,
            buy_fee_usdc=0.0,
            buy_tx_id=f"deposit_{wallet_pk}_{int(time.time())}",
            isClosed=False,
            isSavings=True,
        )
        session.add(savings_sec)
        session.flush()

    savings_sec.amount += amount_lamports
    return Ok(savings_sec.id)


def allocate_to_trading(
    session: Session,
    wallet_pk: int,
    amount_lamports: int,
) -> Result[int]:
    """
    Moves capital from the latest Savings Security into a new Investment.
    """
    if amount_lamports <= 0:
        return Err("Amount must be greater than zero")

    wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
    if not wallet:
        return Err("Wallet not found")

    savings_sec = session.execute(
        select(Security)
        .join(Asset, Security.parent_id == Asset.id)
        .where(
            Asset.wallet == wallet_pk,
            Security.isClosed == False,
            Security.isSavings == True
        )
        .order_by(Security.purchase_time_ms.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not savings_sec:
        return Err("No open Savings Security found for this wallet")

    if amount_lamports > savings_sec.amount:
        return Err(f"Insufficient Savings balance (have {savings_sec.amount}, requested {amount_lamports})")

    return allocate_from_security_to_investment(
        session=session,
        security_id=savings_sec.id,
        amount_lamports=amount_lamports,
    )


def return_to_savings(
    session: Session,
    wallet_pk: int,
    amount_lamports: int,
) -> Result[int]:
    """
    Moves capital from an open Investment back into Savings.
    """
    if amount_lamports <= 0:
        return Err("Amount must be greater than zero")

    wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
    if not wallet:
        return Err("Wallet not found")

    investment = session.execute(
        select(Investment)
        .join(Asset, Investment.parent_id == Asset.id)
        .where(
            Asset.wallet == wallet_pk,
            Investment.isClosed == False
        )
        .order_by(Investment.purchase_time_ms.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not investment:
        return Err("No open Investment found for this wallet")

    if amount_lamports > investment.amount:
        return Err(f"Insufficient Investment balance (have {investment.amount}, requested {amount_lamports})")

    return return_from_investment_to_savings(
        session=session,
        investment_id=investment.id,
        amount_lamports=amount_lamports,
    )

def return_from_investment_to_savings(
    session: Session,
    investment_id: int,
    amount_lamports: int,
) -> Result[int]:
    """
    Moves capital from an Investment back into a Savings Security.
    Creates a new Savings Security if one doesn't exist on that Asset.
    """
    inv = session.execute(
        select(Investment).where(Investment.id == investment_id)
    ).scalar_one_or_none()

    if not inv or inv.isClosed:
        return Err("Investment not found or already closed")

    if amount_lamports > inv.amount:
        return Err("Insufficient balance in this investment")

    # Reduce the investment
    inv.amount -= amount_lamports
    if inv.amount <= 0:
        inv.isClosed = True

    asset_id = inv.parent_id

    # Find an open Savings Security on the same Asset, or create one
    savings_sec = session.execute(
        select(Security).where(
            Security.parent_id == asset_id,
            Security.isClosed == False,
            Security.isSavings == True
        )
    ).scalar_one_or_none()

    if not savings_sec:
        savings_sec = Security(
            parent_id=asset_id,
            amount=0,
            purchase_price_usdc=0.0,
            purchase_time_ms=int(time.time() * 1000),
            buy_fee_native_lamports=0,
            buy_fee_usdc=0.0,
            buy_tx_id=f"return_to_savings_{investment_id}",
            isClosed=False,
            isSavings=True,
        )
        session.add(savings_sec)
        session.flush()

    savings_sec.amount += amount_lamports

    return Ok(savings_sec.id)



def allocate_from_security_to_investment(
    session: Session,
    security_id: int,
    amount_lamports: int,
) -> Result[int]:
    """
    Moves capital from a Security bucket into a new open Investment.
    Returns the new investment_id.
    """
    sec = session.execute(
        select(Security).where(Security.id == security_id)
    ).scalar_one_or_none()

    if not sec or sec.isClosed:
        return Err("Security not found or already closed")

    if amount_lamports > sec.amount:
        return Err("Insufficient balance in this security")

    # Reduce the security
    sec.amount -= amount_lamports
    if sec.amount <= 0:
        sec.isClosed = True

    # Create new Investment
    new_inv = Investment(
        parent_id=sec.parent_id,
        amount=amount_lamports,
        purchase_price_usdc=0.0,
        purchase_time_ms=int(time.time() * 1000),
        buy_fee_native_lamports=0,
        buy_fee_usdc=0.0,
        buy_tx_id=f"allocate_from_security_{security_id}",
        isClosed=False,
    )
    session.add(new_inv)
    session.flush()

    return Ok(new_inv.id)


def deposit_and_start_trading(
    session: Session,
    wallet_pk: int,
    deposit_lamports: int,
    allocate_lamports: int = None,
) -> Result[dict]:
    """
    All-in-one: Deposit USDC into Savings, then allocate some (or all) to a new Investment.
    If allocate_lamports is None, it allocates the full deposit amount.
    """
    if deposit_lamports <= 0:
        return Err("Deposit amount must be greater than zero")

    if allocate_lamports is None:
        allocate_lamports = deposit_lamports

    if allocate_lamports > deposit_lamports:
        return Err("Cannot allocate more than deposited amount")

    # Step 1: Deposit into Savings
    deposit_res = deposit_usdc_to_savings(session, wallet_pk, deposit_lamports)
    if deposit_res.is_err():
        return deposit_res

    savings_security_id = deposit_res.ok_value

    # Step 2: Allocate to Investment
    allocate_res = allocate_from_security_to_investment(
        session=session,
        security_id=savings_security_id,
        amount_lamports=allocate_lamports,
    )
    if allocate_res.is_err():
        return allocate_res

    new_investment_id = allocate_res.ok_value

    return Ok({
        "status": "success",
        "savings_security_id": savings_security_id,
        "new_investment_id": new_investment_id,
        "deposited_lamports": deposit_lamports,
        "allocated_lamports": allocate_lamports,
    })


def return_investment_to_savings(
    session: Session,
    wallet_pk: int,
    investment_id: int = None,
    amount_lamports: int = None,
) -> Result[int]:
    """
    All-in-one: Return capital from an Investment back to Savings.
    - If investment_id is not provided → uses the latest open Investment for the wallet.
    - If amount_lamports is not provided → returns the **entire remaining balance**.
    """
    if investment_id is None:
        investment = session.execute(
            select(Investment)
            .join(Asset, Investment.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Investment.isClosed == False
            )
            .order_by(Investment.purchase_time_ms.desc())
            .limit(1)
        ).scalar_one_or_none()

        if not investment:
            return Err("No open Investment found for this wallet")
        investment_id = investment.id
    else:
        investment = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one_or_none()

        if not investment or investment.isClosed:
            return Err("Investment not found or already closed")

    if amount_lamports is None:
        amount_lamports = investment.amount

    if amount_lamports <= 0:
        return Err("Amount must be greater than zero")

    if amount_lamports > investment.amount:
        return Err(f"Cannot return more than available ({investment.amount} lamports)")

    return return_from_investment_to_savings(
        session=session,
        investment_id=investment_id,
        amount_lamports=amount_lamports,
    )


def pre_trade_safety_check(
    session: Session,
    investment_id: int,
    sell_lamports: int,
    estimated_gas_lamports: int,
    wallet_pk: int = None
) -> Result[bool]:
    """
    Basic safety check before trading.
    Currently a placeholder that always passes.
    """
    try:
        # TODO: Add real checks later (enough balance, enough gas, etc.)
        if sell_lamports <= 0:
            return Err("Sell amount must be greater than zero")

        # For now we just approve the trade
        return Ok(True)

    except Exception as e:
        return Err(str(e))
