"""
db_manager_v2.py
Lunar Lander DeFi - Database & Business Logic Layer

Design goals:
- Clean separation for future extraction into Rust/Zig/C
- Consistent Result[Ok/Err] pattern (FFI friendly)
- Clear boundaries between DB access, business logic, and trading
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
import numpy as np
import base58
import logging
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Session, declarative_base, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary, Float, ForeignKey, cast

from pydantic import BaseModel, Field
from result import Result, Ok, Err

Base = declarative_base()

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

def get_token_key(given_key: str) -> Result[np.ndarray]:
    """Convert base58 mint to numpy array for BYTEA storage."""
    try:
        decoded = base58.b58decode(given_key.encode())
        return Ok(np.frombuffer(decoded, dtype="<i4"))
    except Exception as e:
        return Err(str(e))


def ensure_asset_exists(session: Session, token_key: np.ndarray, wallet_pk: int) -> Result[int]:
    # ... (implementation stays similar)
    pass


def aquire_wallet_key(session: Session, wallet_id: Optional[int] = None, wallet_public_key: Optional[str] = None) -> Result[int]:
    # ... (implementation stays similar)
    pass


# =============================================================================
# 4. INVESTMENT OPERATIONS
# =============================================================================

def insert_investment(session: Session, token_key: np.ndarray, data: InvestmentCreate, wallet_pk: int) -> Result[bool]:
    """Insert a new investment position."""
    # Implementation...
    pass


def record_partial_sell(session: Session, investment_id: int, sold_lamports: int,
                        sell_tx_id: str, sell_price_usdc: float, sell_fee_usdc: float = 0.0) -> Result[bool]:
    """Close (part of) an investment and optionally create remaining position."""
    # Implementation...
    pass


def calculate_realized_gain(session: Session, investment_id: int, sell_price_usdc: float) -> Result[dict]:
    """Pure calculation — good candidate for later Rust/Zig if needed."""
    # Implementation...
    pass


# =============================================================================
# 5. SECURITY OPERATIONS (Gas + Tax buckets)
# =============================================================================

def get_available_gas_lamports(session: Session, wallet_pk: int) -> Result[int]:
    """Get total open gas security in lamports."""
    pass


def ensure_sufficient_gas(session: Session, required_lamports: int, wallet_pk: int) -> Result[bool]:
    pass


def spend_gas_security(session: Session, security_id: int, used_lamports: int, tx_id: str) -> Result[bool]:
    pass


def get_oldest_gas_security(session: Session, wallet_pk: int) -> Result[Optional[int]]:
    pass


# =============================================================================
# 6. TAX LOGIC (High value to keep clean)
# =============================================================================

def withhold_tax_on_profitable_sale(session: Session, investment_id: int,
                                    sell_proceeds_usdc: float, wallet_pk: int) -> Result[bool]:
    """
    Automatically creates a Security(isTax=True) based on user's tax_level_choice.
    This is business logic — keep it isolated.
    """
    pass


def get_total_tax_owed(session: Session, wallet_pk: int) -> Result[float]:
    """Total USDC currently reserved for taxes."""
    pass


def get_open_tax_securities(session: Session, wallet_pk: int) -> Result[List[Security]]:
    """List of open tax securities (for review/payment)."""
    pass


# =============================================================================
# 7. HIGH-LEVEL TRADE EXECUTION (Orchestrator)
# =============================================================================

def execute_trade_with_gas(
    session: Session,
    investment_id: int,
    jupiter_client: Any,
    target_mint: str,
    estimated_gas_lamports: int,
    wallet_pk: int,
    keypair: Any = None,
    gas_security_id: Optional[int] = None,
) -> Result[dict]:
    """
    Main orchestrator.
    
    This function coordinates:
    - Gas check + spending
    - Jupiter swap execution
    - Investment recording
    - Automatic tax withholding
    
    Good candidate to keep in Python or move orchestration to Rust later.
    """
    # 1. Gas pre-check
    if ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk).is_error:
        return Err("Insufficient gas")

    # 2. Auto-select oldest gas security if not provided
    if gas_security_id is None:
        gas_security_id = get_oldest_gas_security(session, wallet_pk).value

    # 3. Execute Jupiter swap (placeholder for real implementation)
    # ... call jupiter_client.get_quote() + execute_swap()

    # 4. Record investment change
    record_partial_sell(...)  

    # 5. Spend gas
    if gas_security_id:
        spend_gas_security(session, gas_security_id, estimated_gas_lamports, tx_sig)

    # 6. Automatic tax withholding (critical business rule)
    withhold_tax_on_profitable_sale(session, investment_id, sell_price_usdc, wallet_pk)

    return Ok({...})
