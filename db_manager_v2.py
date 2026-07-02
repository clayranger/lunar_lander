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
from sqlalchemy.orm import Session, declarative_base, Mapped, mapped_column, relationship, sessionmaker
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
from solders.pubkey import Pubkey
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
    # cost_basis is purchase price plus + fees
    # cost_basis_usdc
    # (sale_price_usdc + fees) - (cost_basis)
    # taxable_gain_or_loss =
    purchase_time_ms = mapped_column(BigInteger)
    sale_time_ms = mapped_column(BigInteger)
    # buy_fee_native lamports = gas fee
    buy_fee_native_lamports = mapped_column(Integer)
    buy_fee_usdc = mapped_column(Float)
    sell_fee_native_lamports = mapped_column(Integer)
    sell_fee_usdc = mapped_column(Float)
    revenue_at_sale_usdc = mapped_column(Float)
    isClosed = mapped_column(Boolean, default=False)
    buy_tx_id = mapped_column(String)
    sell_tx_id = mapped_column(String)
    priority_fee_lamports = mapped_column(BigInteger, default=0)


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
    priority_fee_lamports = mapped_column(BigInteger, default=0)
    # fees_taxable_gain_or_loss


# Pydantic Schemas
class InvestmentCreate(BaseModel):
    amount: int = Field(..., gt=0)
    purchase_price_usdc: float = Field(..., ge=0)
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
    session = Session(engine, expire_on_commit=True)
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

def binary_token_to_mint(binary_key: bytes) -> str:
    """Convert stored binary token key back to base58 mint address."""
    import base58
    return base58.b58encode(binary_key).decode("utf-8")

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
) -> Result[int]:
    """Insert a new investment. Returns the new investment ID on success."""
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
        return Ok(inv.id)
    except Exception as exc:
        return Err(str(exc))   # No rollback here






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
    """
    Spend gas from a Security.
    Splits the security and calculates capital gain/loss on the used portion.
    """
    try:
        sec = session.execute(
            select(Security).where(Security.id == gas_security_id)
        ).scalar_one_or_none()

        if not sec or sec.isClosed:
            return Err("Gas security not found or already closed")

        if used_lamports > sec.amount:
            return Err("Trying to spend more gas than available")

        remaining = sec.amount - used_lamports

        # Calculate profit/loss on the used portion
        purchase_basis = sec.purchase_price_usdc or 0.0
        # Rough current value of used gas (in USDC)
        current_value = 0.0  # TODO: Use get_historical_price if we want extreme accuracy

        revenue = current_value - purchase_basis * (used_lamports / sec.amount) if sec.amount > 0 else 0.0

        # Close the used portion
        sec.amount = used_lamports
        sec.isClosed = True
        sec.sell_tx_id = tx_id
        sec.sale_time_ms = int(time.time() * 1000)
        sec.sale_price_usdc = current_value
        sec.revenue_at_sale_usdc = round(revenue, 6)
        sec.priority_fee_lamports = 0

        # Create remaining gas security if any
        if remaining > 0:
            new_gas = Security(
                parent_id=sec.parent_id,
                amount=remaining,
                purchase_price_usdc=sec.purchase_price_usdc,
                purchase_time_ms=sec.purchase_time_ms,
                buy_fee_native_lamports=sec.buy_fee_native_lamports,
                buy_fee_usdc=sec.buy_fee_usdc,
                buy_tx_id=sec.buy_tx_id,
                isClosed=False,
                isGas=True,
            )
            session.add(new_gas)

        session.flush()
        logging.info(f"[GAS] Spent {used_lamports} lamports from Security {gas_security_id} for tx {tx_id} | Revenue: ${revenue:.6f}")
        return Ok(True)

    except Exception as e:
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
        # only owner of session can roll back
        # session.rollback()
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


def get_current_priority_fee(min_fee: int = 5_000) -> int:
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
    estimated_gas_lamports: int = 5_000,
    wallet_pk: int = None,
    sell_lamports: int = None,
    gas_security_id: Optional[int] = None,
    max_retries: int = 3,
    keypair_path: str = "~/.config/solana/mainnet-test.json",
    slippage_bps: int = 50,
) -> Result[dict]:
    """
    Full trade orchestrator with proper error checking on every step.
    """
    logging.info(f"[TRADE] Starting trade | investment_id={investment_id}")

    if wallet_pk is None:
        single = get_single_wallet_pk(session)
        if single.is_ok() and single.value:
            wallet_pk = single.value
        else:
            return Err("Could not determine wallet_pk")

    helius_api_key = os.getenv("HELIUS_API_KEY")
    if not helius_api_key:
        return Err("HELIUS_API_KEY not found")

    # === 1. Read-only preparation ===
    inv = session.execute(
        select(Investment).where(Investment.id == investment_id)
    ).scalar_one_or_none()

    if not inv:
        return Err(f"Investment {investment_id} not found")
    if inv.isClosed:
        return Err(f"Investment {investment_id} is already closed")

    asset = session.execute(
        select(Asset).where(Asset.id == inv.parent_id)
    ).scalar_one_or_none()
    if not asset:
        return Err("Asset not found")

    input_mint = binary_token_to_mint(asset.coin)

    if sell_lamports is None:
        sell_lamports = inv.amount // 2
    if sell_lamports <= 0 or sell_lamports > inv.amount:
        return Err("Invalid sell amount")

    # === Gas requirement check ===
    if estimated_gas_lamports > 0:
        if gas_security_id is None:
            return Err("gas_security_id is required when estimated_gas_lamports > 0. Please provide a valid gas Security ID.")
        gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
        if gas_check.is_err():
            return gas_check

    safety = pre_trade_safety_check(session, investment_id, sell_lamports, estimated_gas_lamports, wallet_pk)
    if safety.is_err():
        return safety

    gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
    if gas_check.is_err():
        return gas_check

    # Load keypair
    try:
        keypair = load_keypair_from_file(os.path.expanduser(keypair_path))
        wallet_public_key = str(keypair.pubkey())
    except Exception as e:
        return Err(f"Failed to load keypair: {str(e)}")

    priority_fee = get_current_priority_fee()
    tx_sig = None

    # === 2. On-chain swap ===
    for attempt in range(1, max_retries + 1):
        try:
            swap_tx_res = get_jupiter_swap_transaction(
                wallet_public_key=wallet_public_key,
                input_mint=input_mint,
                output_mint=target_mint,
                amount=sell_lamports,
                slippage_bps=slippage_bps,
            )
            if swap_tx_res.is_err():
                if attempt == max_retries:
                    return Err(f"Swap failed: {swap_tx_res.err_value}")
                time.sleep(2)
                continue

            send_res = sign_and_send_transaction(swap_tx_res.ok_value, keypair)
            if send_res.is_err():
                if attempt == max_retries:
                    return Err(f"Sign/Send failed: {send_res.err_value}")
                time.sleep(2)
                continue

            tx_sig = send_res.ok_value
            confirm_res = confirm_transaction(tx_sig)
            if confirm_res.is_err():
                if attempt == max_retries:
                    return Err(f"Confirmation failed: {confirm_res.err_value}")
                time.sleep(2)
                continue

            logging.info(f"[TRADE] On-chain success: {tx_sig}")
            break
        except Exception as e:
            if attempt == max_retries:
                return Err(str(e))
            time.sleep(2)

    if not tx_sig:
        return Err("No confirmed transaction")

    # === 3. Database recording ===
    new_investment_id = None
    actual_usdc_received = 0.0

    try:
        # Gas spending (include both estimated gas + priority fee)
        total_gas_used = estimated_gas_lamports + priority_fee
        # Record buy side
        buy_res = record_buy_side(
            session=session,
            wallet_pk=wallet_pk,
            received_mint=target_mint,
            tx_signature=tx_sig,
            buy_fee_native_lamports=total_gas_used,   # ← Pass total gas used
        )
        if buy_res.is_err():
            return buy_res
        new_investment_id = buy_res.ok_value

        if target_mint == WORLD_STABLE_COIN and new_investment_id:
            usdc_inv = session.execute(
                select(Investment).where(Investment.id == new_investment_id)
            ).scalar_one_or_none()
            if usdc_inv:
                actual_usdc_received = float(usdc_inv.amount) / 1_000_000

        # Record sell side with proper price if selling into USDC
        sell_price_to_use = actual_usdc_received if target_mint == WORLD_STABLE_COIN else 0.0

        sell_res = record_partial_sell(
            session=session,
            inv=inv,
            sold_lamports=sell_lamports,
            sell_tx_id=tx_sig,
            sell_price_usdc=sell_price_to_use,
            sell_fee_usdc=0.0,
            priority_fee_lamports=priority_fee,   # ← Important for taxes
        )
        if sell_res.is_err():
            logging.info("ERROR wit sell")
            return sell_res



        if gas_security_id:
            logging.info(f"[GAS] Attempting to spend {total_gas_used} (gas + priority) from Security ID {gas_security_id}")
            gas_res = spend_gas_security(
                session=session,
                gas_security_id=gas_security_id,
                used_lamports=total_gas_used,
                tx_id=tx_sig
            )
            if gas_res.is_err():
                logging.warning(f"Gas spending failed: {gas_res.err_value}")

        withhold_tax_on_profitable_sale(
            session=session,
            investment_id=investment_id,
            sell_proceeds_usdc=sell_price_to_use,
            wallet_pk=wallet_pk,
        )

        # Auto-merge (non-fatal)
        if target_mint == WORLD_STABLE_COIN:
            try:
                merge_result = merge_usdc_investments(session=session, wallet_pk=wallet_pk)
            except Exception as merge_e:
                logging.warning(f"Auto USDC merge failed: {merge_e}")

        session.commit()

    except Exception as e:
        session.rollback()
        return Err(f"On-chain succeeded but DB update failed: {str(e)}")

    log_trade_result(
        investment_id=investment_id,
        wallet_pk=wallet_pk,
        status="success",
        tx_signature=tx_sig,
        sold_lamports=sell_lamports,
        priority_fee_lamports=priority_fee,
    )

    return Ok({
        "status": "success",
        "investment_id": investment_id,
        "tx_signature": tx_sig,
        "sold_lamports": sell_lamports,
        "new_investment_id": new_investment_id,
        "sell_price_usdc": sell_price_to_use,
        "priority_fee_lamports": priority_fee,
    })



def sync_wallet_balances(
    session: Session,
    wallet_pk: int,
    wallet_public_key: str = None,
) -> Result:
    """
    Syncs on-chain balances into Asset table.
    Uses get_token_key() consistently to avoid duplicate token additions.
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
        # === Native SOL ===
        platform_key_res = get_token_key(WORLD_PLATFORM_COIN)
        if platform_key_res.is_err():
            return Err(platform_key_res.err_value)

        platform_binary = platform_key_res.ok_value.tobytes()
        native_balance = client.get_balance(owner).value

        native_asset = session.execute(
            select(Asset).where(Asset.wallet == wallet_pk, Asset.coin == platform_binary)
        ).scalar_one_or_none()

        if native_asset:
            if native_asset.audited_amount_sum_lamports != native_balance:
                native_asset.audited_amount_sum_lamports = native_balance
                native_asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                updated += 1
        else:
            new_asset = Asset(
                wallet=wallet_pk,
                coin=platform_binary,
                audited_amount_sum_lamports=native_balance,
                audited_time_unix_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                isNative=True,
            )
            session.add(new_asset)
            created += 1

        # === SPL Tokens ===
        resp = client.get_token_accounts_by_owner(
            owner,
            TokenAccountOpts(program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")),
            commitment="confirmed",
        )
        token_accounts = resp.value or []

        for acc in token_accounts:
            try:
                raw = bytes(acc.account.data)
                if len(raw) < 72:
                    continue

                mint_bytes = raw[0:32]
                amount = struct.unpack_from("<Q", raw, 64)[0]
                mint = base58.b58encode(mint_bytes).decode("utf-8")

                # Use get_token_key consistently
                token_key_res = get_token_key(mint)
                if token_key_res.is_err():
                    continue

                token_binary = token_key_res.ok_value.tobytes()

                # Check existence using the same binary format
                token_exists = session.execute(
                    select(Token).where(Token.id == token_binary)
                ).scalar_one_or_none()

                if not token_exists:
                    decimals = 9
                    try:
                        supply_info = client.get_token_supply(Pubkey.from_string(mint))
                        if supply_info.value and supply_info.value.decimals:
                            decimals = supply_info.value.decimals
                    except:
                        pass

                    new_token = Token(
                        id=token_binary,
                        name=mint[:8],
                        tickerSymbol=mint[:6],
                        contractAddress=token_binary,
                        priceServer="jupiter",
                        exchangeSever="jupiter",
                        decimals=decimals,
                        price_tracking=False,
                    )
                    session.add(new_token)

                # Asset handling
                asset = session.execute(
                    select(Asset).where(Asset.wallet == wallet_pk, Asset.coin == token_binary)
                ).scalar_one_or_none()

                if asset:
                    if asset.audited_amount_sum_lamports != amount:
                        asset.audited_amount_sum_lamports = amount
                        asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                        updated += 1
                else:
                    new_asset = Asset(
                        wallet=wallet_pk,
                        coin=token_binary,
                        audited_amount_sum_lamports=amount,
                        audited_time_unix_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                        isNative=False,
                    )
                    session.add(new_asset)
                    created += 1

            except Exception as e:
                logging.warning(f"[SYNC] Token account error: {str(e)}")
                continue

        session.commit()
        return Ok({"created_assets": created, "updated_assets": updated})

    except Exception as e:
        session.rollback()
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
    gas_security_id: Optional[int] = None,   # ← Added
    keypair_path: str = "~/.config/solana/mainnet-test.json",
    slippage_bps: int = 50,
) -> Result[dict]:
    """
    Sells a percentage of an Investment and swaps it to another token (e.g. USDC).

    Safer flow:
    - Validates and calculates in read-only mode first
    - Delegates to execute_trade_with_gas (which handles on-chain first, then DB commit)
    - Returns useful data on success (tx_signature, new_investment_id, etc.)
    """
    if wallet_pk is None:
        single = get_single_wallet_pk(session)
        if single.is_ok() and single.value:
            wallet_pk = single.value
        else:
            return Err("Could not determine wallet_pk")

    # === Read-only validation phase ===
    inv = session.execute(
        select(Investment).where(Investment.id == investment_id)
    ).scalar_one_or_none()

    if not inv:
        return Err(f"Investment {investment_id} not found")

    if inv.isClosed:
        return Err(f"Investment {investment_id} is already closed")

    if sell_percentage <= 0 or sell_percentage > 100:
        return Err("sell_percentage must be between 0 and 100")

    sell_lamports = int(inv.amount * (sell_percentage / 100.0) + 0.5)  # round to nearest
    if sell_lamports <= 0:
        return Err("Calculated sell amount is zero or negative")

    # === Delegate to the core trade function ===
    # (execute_trade_with_gas now handles on-chain first + DB commit/rollback internally)
    return execute_trade_with_gas(
        session=session,
        investment_id=investment_id,
        target_mint=target_mint,
        estimated_gas_lamports=estimated_gas_lamports,
        wallet_pk=wallet_pk,
        sell_lamports=sell_lamports,
        gas_security_id=gas_security_id,   # ← Pass it through
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


def reconcile_recent_trades(
    wallet_pk: int,
    lookback_minutes: int = 60
) -> Result[dict]:
    """
    Scans recent on-chain activity and repairs the database for trades
    that succeeded on-chain but were not properly recorded.

    This version uses repair_investment_from_tx internally for consistency.
    """
    from rpc_client import get_solana_client
    from solders.signature import Signature
    from datetime import datetime, timedelta, timezone

    client = get_solana_client()

    wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
    if not wallet:
        return Err("Wallet not found")

    wallet_pubkey = Pubkey.from_string(wallet.publicKey)
    since = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

    repaired = 0
    errors = 0

    try:
        sigs_resp = client.get_signatures_for_address(wallet_pubkey, limit=50)

        if not sigs_resp.value:
            return Ok({"repaired": 0, "message": "No recent transactions found"})

        for sig_info in sigs_resp.value:
            if sig_info.err is not None:
                continue

            tx_sig = str(sig_info.signature)

            if sig_info.block_time:
                tx_time = datetime.fromtimestamp(sig_info.block_time, tz=timezone.utc)
                if tx_time < since:
                    continue

            try:
                tx_resp = client.get_transaction(
                    Signature.from_string(tx_sig),
                    commitment=Commitment("confirmed"),
                    max_supported_transaction_version=0,
                )

                if not tx_resp.value or tx_resp.value.transaction.meta is None:
                    continue

                meta = tx_resp.value.transaction.meta
                if meta.err is not None:
                    continue

                logs = meta.log_messages or []
                is_jupiter_swap = any("Jupiter" in log for log in logs)

                if not is_jupiter_swap:
                    continue

                # Find open investments that haven't been marked as sold yet
                open_investments = session.execute(
                    select(Investment)
                    .join(Asset, Investment.parent_id == Asset.id)
                    .where(
                        Asset.wallet == wallet_pk,
                        Investment.isClosed == False,
                        Investment.sell_tx_id.is_(None)
                    )
                ).scalars().all()

                for inv in open_investments:
                    # Use the dedicated repair function for consistency
                    repair_result = repair_investment_from_tx(
                        session=session,
                        investment_id=inv.id,
                        tx_signature=tx_sig,
                        sold_lamports=None  # Fully close for now (conservative)
                    )

                    if repair_result.is_ok() and repair_result.ok_value:
                        repaired += 1
                        logging.info(f"[RECONCILE] Repaired Investment {inv.id} via tx {tx_sig}")

            except Exception as e:
                logging.warning(f"[RECONCILE] Error processing tx {tx_sig}: {str(e)}")
                errors += 1
                continue

        session.commit()
        return Ok({
            "repaired": repaired,
            "errors": errors,
            "lookback_minutes": lookback_minutes
        })

    except Exception as e:
        session.rollback()
        return Err(str(e))


def repair_investment_from_tx(
    session: Session,
    investment_id: int,
    tx_signature: str,
    sold_lamports: int = None
) -> Result[bool]:
    """
    Repairs a single investment record using a known successful transaction signature.
    Uses the new record_partial_sell that accepts an Investment object.
    """
    try:
        inv = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one_or_none()

        if not inv:
            return Err(f"Investment {investment_id} not found")

        if inv.isClosed:
            return Ok(False)  # Already closed, nothing to do

        # Determine how much was sold
        if sold_lamports is None:
            sold_lamports = inv.amount  # Full close

        if sold_lamports > inv.amount:
            return Err(f"Cannot sell more than available ({inv.amount} lamports)")

        # Use the new signature that accepts the object
        repair_result = record_partial_sell(
            session=session,
            inv=inv,                    # ← Pass the object
            sold_lamports=sold_lamports,
            sell_tx_id=tx_signature,
            sell_price_usdc=0.0,        # Can be improved later with price lookup
            sell_fee_usdc=0.0,
        )

        if repair_result.is_err():
            return repair_result

        logging.info(
            f"[REPAIR] Repaired Investment {investment_id} | "
            f"sold={sold_lamports}, tx={tx_signature}"
        )

        return Ok(True)

    except Exception as e:
        # no let the error bubble back up to session owner
        # session.rollback()
        return Err(str(e))


def get_jupiter_swap_details(tx_signature: str) -> Result[dict]:
    """
    Fetches a Jupiter swap transaction and returns clean, structured details.
    Focuses on net token changes for the user's wallet.
    """
    helius_api_key = os.getenv("HELIUS_API_KEY")
    if not helius_api_key:
        return Err("HELIUS_API_KEY not found")

    url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed"
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return Err(str(data["error"]))

        tx = data.get("result")
        if not tx:
            return Err("Transaction not found")

        meta = tx.get("meta", {})
        if meta.get("err"):
            return Err(f"Transaction failed: {meta['err']}")

        # Get user's wallet from the transaction
        account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        user_wallet = None
        for acc in account_keys:
            if isinstance(acc, dict) and acc.get("signer"):
                user_wallet = acc.get("pubkey")
                break

        # Analyze token balance changes
        pre_balances = {b["mint"]: int(b["uiTokenAmount"]["amount"])
                        for b in meta.get("preTokenBalances", []) if b.get("owner") == user_wallet}
        post_balances = {b["mint"]: int(b["uiTokenAmount"]["amount"])
                         for b in meta.get("postTokenBalances", []) if b.get("owner") == user_wallet}

        changes = {}
        all_mints = set(pre_balances.keys()) | set(post_balances.keys())

        for mint in all_mints:
            before = pre_balances.get(mint, 0)
            after = post_balances.get(mint, 0)
            diff = after - before
            if diff != 0:
                changes[mint] = diff

        return Ok({
            "signature": tx_signature,
            "slot": tx.get("slot"),
            "block_time": tx.get("blockTime"),
            "user_wallet": user_wallet,
            "token_changes": changes,           # ← Clean summary of what was bought/sold
            "success": True
        })

    except Exception as e:
        return Err(f"Failed to parse transaction: {str(e)}")


def recover_trade_from_tx(
    tx_signature: str,
    wallet_pk: int = None
) -> Result[dict]:
    """
    Recovers/repairs an investment using on-chain data.
    More tolerant of messy database states during development.
    """
    from db_manager_v2 import get_jupiter_swap_details

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        # === Global duplicate check ===
        existing = session.execute(
            select(Investment).where(Investment.sell_tx_id == tx_signature)
        ).scalars().first()

        if existing:
            return Ok({
                "status": "already_recorded",
                "investment_id": existing.id,
                "message": "This transaction was already recorded"
            })

        # === Get swap details ===
        details_res = get_jupiter_swap_details(tx_signature)
        if details_res.is_err():
            return details_res

        details = details_res.ok_value
        token_changes = details.get("token_changes", {})

        if not token_changes:
            return Err("No token changes found")

        # Find sold token
        sold_mint = None
        sold_amount = 0
        for mint, change in token_changes.items():
            if change < 0 and abs(change) > abs(sold_amount):
                sold_mint = mint
                sold_amount = abs(change)

        if sold_amount == 0:
            return Err("Could not determine sold amount")

        # Find open investments
        open_investments = session.execute(
            select(Investment)
            .join(Asset, Investment.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Investment.isClosed == False,
                Investment.sell_tx_id.is_(None)
            )
        ).scalars().all()

        if not open_investments:
            return Err("No open investments to repair")

        target = open_investments[0]

        # Repair using the new record_partial_sell
        repair_res = repair_investment_from_tx(
            session=session,
            investment_id=target.id,
            tx_signature=tx_signature,
            sold_lamports=sold_amount
        )

        if repair_res.is_err():
            return repair_res

        return Ok({
            "status": "recovered",
            "investment_id": target.id,
            "tx_signature": tx_signature,
            "sold_lamports": sold_amount,
            "sold_mint": sold_mint
        })

    except Exception as e:
        session.rollback()
        return Err(str(e))
    finally:
        session.close()


def get_recent_swap_signatures(
    wallet_pk: int,
    limit: int = 30
) -> Result[list[str]]:
    """
    Returns recent transaction signatures for a wallet.
    Creates its own session internally.
    """
    from rpc_client import get_solana_client
    from sqlalchemy.orm import sessionmaker

    client = get_solana_client()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        # Get wallet public key
        wallet = session.execute(
            select(Wallet).where(Wallet.id == wallet_pk)
        ).scalar_one_or_none()

        if not wallet:
            return Err("Wallet not found")

        # Get recent signatures
        resp = client.get_signatures_for_address(
            Pubkey.from_string(wallet.publicKey),
            limit=limit
        )

        if not resp.value:
            return Ok([])

        # Return only successful transactions
        signatures = [
            str(sig.signature)
            for sig in resp.value
            if sig.err is None
        ]

        return Ok(signatures)

    except Exception as e:
        return Err(str(e))
    finally:
        session.close()


def record_buy_side(
    session: Session,
    wallet_pk: int,
    received_mint: str,
    tx_signature: str,
    received_amount: int = None,
    purchase_price_usdc: float = 0.0,
    buy_fee_native_lamports: int = 0,   # ← New parameter
) -> Result[int]:
    try:
        if received_amount is None or received_amount <= 0:
            details_res = get_jupiter_swap_details(tx_signature)
            if details_res.is_err():
                return details_res

            changes = details_res.ok_value.get("token_changes", {})
            received_amount = changes.get(received_mint, 0)

            if received_amount <= 0:
                return Err(f"Could not determine received amount for {received_mint}")

        # Historical price + decimals
        if purchase_price_usdc <= 0.0:
            price_res = get_historical_price(received_mint, int(time.time() * 1000))
            if price_res.is_ok():
                decimals = get_token_decimals(session, received_mint)
                human_amount = received_amount / (10 ** decimals)
                purchase_price_usdc = price_res.ok_value * human_amount

        # For now, buy fees are usually very small or zero on Jupiter
        buy_fee_native = 0
        buy_fee_usdc = 0.0

        key_res = get_token_key(received_mint)
        if key_res.is_err():
            return key_res
        token_key = key_res.ok_value

        investment_data = InvestmentCreate(
            amount=received_amount,
            purchase_price_usdc=round(purchase_price_usdc, 6),
            purchase_time_ms=int(time.time() * 1000),
            buy_fee_native_lamports=buy_fee_native_lamports,   # ← Use the passed value
            buy_fee_usdc=0.0,
            buy_tx_id=tx_signature,
        )

        result = insert_investment(
            session=session,
            token_key=token_key,
            investment_data=investment_data,
            wallet_id=wallet_pk
        )

        if result.is_err():
            return result

        new_investment_id = result.ok_value
        logging.info(f"[BUY] Created Investment {new_investment_id} | Cost: ${purchase_price_usdc:.6f} | Buy Fee: {buy_fee_native_lamports} lam")
        return Ok(new_investment_id)

    except Exception as e:
        return Err(f"Failed to record buy side: {str(e)}")


def merge_usdc_investments(
    session: Session,
    wallet_pk: int
) -> Result[int]:
    try:
        from global_values import WORLD_STABLE_COIN

        usdc_key_res = get_token_key(WORLD_STABLE_COIN)
        if usdc_key_res.is_err():
            return usdc_key_res
        usdc_binary = usdc_key_res.ok_value.tobytes()

        usdc_investments = session.execute(
            select(Investment)
            .join(Asset, Investment.parent_id == Asset.id)
            .where(
                Asset.wallet == wallet_pk,
                Asset.coin == usdc_binary,
                Investment.isClosed == False
            )
        ).scalars().all()

        if not usdc_investments:
            return Err("No open USDC Investments found to merge")

        if len(usdc_investments) == 1:
            return Ok(usdc_investments[0].id)

        total_amount = sum(inv.amount for inv in usdc_investments)
        asset_id = usdc_investments[0].parent_id

        merged_inv = Investment(
            parent_id=asset_id,
            amount=total_amount,
            purchase_price_usdc=0.0,
            purchase_time_ms=int(time.time() * 1000),
            buy_fee_native_lamports=0,
            buy_fee_usdc=0.0,
            buy_tx_id="merge_usdc_investments",
            isClosed=False,
        )
        session.add(merged_inv)
        session.flush()

        for old_inv in usdc_investments:
            old_inv.isClosed = True
            old_inv.sell_tx_id = "merge_usdc_investments"
            old_inv.sale_time_ms = int(time.time() * 1000)

        logging.info(f"[MERGE] Merged {len(usdc_investments)} USDC Investments into ID {merged_inv.id}")
        return Ok(merged_inv.id)

    except Exception as e:
        return Err(f"Merge USDC failed: {str(e)}")


def record_partial_sell(
    session: Session,
    inv: Investment,
    sold_lamports: int,
    sell_tx_id: str,
    sell_price_usdc: float = 0.0,
    sell_fee_usdc: float = 0.0,
    priority_fee_lamports: int = 0,
) -> Result[bool]:
    """
    Records a partial or full sale of an Investment.
    Correct profit calculation for taxes.
    """
    try:
        if not inv:
            return Err("Investment object is None")
        if inv.isClosed:
            return Err("Investment is already closed")

        if sold_lamports <= 0 or sold_lamports > inv.amount:
            return Err("Invalid sold amount")

        remaining = inv.amount - sold_lamports

        price = float(sell_price_usdc) if sell_price_usdc is not None else 0.0
        fee = float(sell_fee_usdc) if sell_fee_usdc is not None else 0.0

        # Update the sold portion
        inv.amount = sold_lamports
        inv.isClosed = True
        inv.sell_tx_id = sell_tx_id
        inv.sale_time_ms = int(time.time() * 1000)
        inv.sale_price_usdc = round(price, 6)
        inv.sell_fee_usdc = round(fee, 6)
        inv.priority_fee_lamports = priority_fee_lamports

        # Revenue = profit on the sold portion (sale price - purchase price)
        purchase_basis = inv.purchase_price_usdc or 0.0
        profit = price - purchase_basis
        inv.revenue_at_sale_usdc = round(profit - fee, 6)

        # Create new remaining Investment if needed
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
        return Err(str(e))


def get_historical_price(
    mint: str,
    timestamp_ms: int,
    fallback_to_current: bool = True
) -> Result[float]:
    """
    Gets approximate USD price of a token at a specific time using Birdeye.
    """
    logging.info(f"[PRICE] Looking up price for {mint} at {timestamp_ms}")

    birdeye_key = os.getenv("BIRDEYE_API_KEY")

    if birdeye_key:
        try:
            url = "https://public-api.birdeye.so/defi/history_price"
            params = {
                "address": mint,
                "address_type": "token",
                "type": "1m",
                "time_from": int(timestamp_ms / 1000) - 3600,
                "time_to": int(timestamp_ms / 1000),
                "ui_amount_mode": "raw"
            }
            headers = {"X-API-KEY": birdeye_key}

            resp = requests.get(url, params=params, headers=headers, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                price_items = data.get("data", {}).get("items", [])

                if price_items:
                    # Find closest price to our timestamp
                    closest = min(price_items, key=lambda x: abs(x.get("unixTime", 0) * 1000 - timestamp_ms))
                    price = float(closest.get("value", 0))
                    if price > 0:
                        logging.info(f"[PRICE] Found historical price: ${price:.6f}")
                        return Ok(price)
        except Exception as e:
            logging.warning(f"[BIRDEYE] Failed: {e}")

    # Fallback
    if fallback_to_current:
        current_res = get_current_price(mint)
        if current_res.is_ok():
            logging.warning(f"[PRICE] Using current price as fallback for {mint}")
            return current_res

    return Err("Could not fetch historical or current price")


def get_current_price(mint: str) -> Result[float]:
    """Fallback current price using Jupiter."""
    try:
        url = f"https://price.jup.ag/v6/price?ids={mint}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        price = data.get("data", {}).get(mint, {}).get("price")
        if price:
            return Ok(float(price))
        return Err("No price returned from Jupiter")
    except Exception as e:
        return Err(str(e))


def get_token_decimals(session: Session, mint: str) -> int:
    """
    Get token decimals from database first, then Jupiter API as fallback.
    """
    # 1. Try database first
    try:
        key_res = get_token_key(mint)
        if key_res.is_ok():
            token = session.execute(
                select(Token).where(Token.id == key_res.ok_value.tobytes())
            ).scalar_one_or_none()
            if token and token.decimals:
                return token.decimals
    except:
        pass

    # 2. Fallback to Jupiter
    try:
        url = f"https://api.jup.ag/price/v3/ids={mint}"
        headers = {}
        jup_key = os.getenv("JUPITER_API_KEY")
        if jup_key:
            headers["x-api-key"] = jup_key

        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        decimals = data.get(mint, {}).get("decimals")
        if decimals is not None:
            return int(decimals)
    except Exception as e:
        logging.warning(f"[DECIMALS] Jupiter fallback failed for {mint}: {e}")

    return 9




