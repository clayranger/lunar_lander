"""
db_manager_v2.py
Clean, modular, production-oriented database layer for Lunar Lander DeFi.
Focus: Investment / Security tracking + tax record foundation.
No global session. All functions expect a SQLAlchemy Session.
Compatible with Jupyter notebook development.
"""

from __future__ import annotations
from typing import List, Optional
import numpy as np
import base58
from contextlib import contextmanager
from datetime import datetime
import logging
import time

from sqlalchemy import select, func, create_engine, update
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary, Float
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, cast

from pydantic import BaseModel, Field
from result import Result, Ok, Err  # assumes you have result.py

Base = declarative_base()

# ============================ MODELS ============================

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
    children: Mapped[List["SelectedToken"]] = relationship(back_populates="token", cascade="all,delete")
    decimals = mapped_column(Integer)


class SelectedToken(Base):
    __tablename__ = "selected_token_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("token_table.id"))
    token: Mapped["Token"] = relationship(back_populates="children")
    owner = mapped_column(ForeignKey("user_table.id"))
    latency = mapped_column(Integer)
    isIllegal = mapped_column(Boolean)
    dangerLevel = mapped_column(Float)
    character = mapped_column(String)


class Asset(Base):
    __tablename__ = "asset_table"
    id = mapped_column(Integer, primary_key=True)
    children_investment: Mapped[List["Investment"]] = relationship(back_populates="asset", cascade="all,delete")
    children_security: Mapped[List["Security"]] = relationship(back_populates="asset", cascade="all,delete")
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
    asset: Mapped["Asset"] = relationship(back_populates="children_investment")
    amount = mapped_column(BigInteger)  # lamports
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
    asset: Mapped["Asset"] = relationship(back_populates="children_security")
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


class TaxRecord(Base):
    __tablename__ = "taxRecord_table"
    id = mapped_column(Integer, primary_key=True)
    token_name = mapped_column(String)
    token_network = mapped_column(String)
    time_buy = mapped_column(Integer)
    time_sell = mapped_column(Integer)
    price_usdc_buy = mapped_column(Float)
    price_usdc_sell = mapped_column(Float)
    price_fee_buy_usdc = mapped_column(Float)
    price_fee_sell_usdc = mapped_column(Float)
    buy_tx_id = mapped_column(String)
    sell_tx_id = mapped_column(String)
    wallet_id = mapped_column(String)
    user_name = mapped_column(String)
    isTax = mapped_column(Boolean)
    isSavings = mapped_column(Boolean)
    isGas = mapped_column(Boolean)
    from_token_amount = mapped_column(Float)
    to_token_amount = mapped_column(Float)


# ============================ PYDANTIC SCHEMAS ============================

class InvestmentCreate(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in lamports")
    purchase_price_usdc: float = Field(..., gt=0)
    purchase_time_ms: int
    buy_fee_native_lamports: int = Field(..., ge=0)
    buy_fee_usdc: float = Field(..., ge=0)
    buy_tx_id: str

    isClosed: bool = False
    sale_price_usdc: Optional[float] = None
    sale_time_ms: Optional[int] = None
    sell_fee_native_lamports: Optional[int] = None
    sell_fee_usdc: Optional[float] = None
    revenue_at_sale_usdc: Optional[float] = None
    sell_tx_id: Optional[str] = None

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

    isClosed: bool = False
    sale_price_usdc: Optional[float] = None
    sale_time_ms: Optional[int] = None
    sell_fee_native_lamports: Optional[int] = None
    sell_fee_usdc: Optional[float] = None
    revenue_at_sale_usdc: Optional[float] = None
    sell_tx_id: Optional[str] = None

    model_config = {"from_attributes": True}


# ============================ SESSION & ENGINE ============================

DATABASE_URL = "postgresql+psycopg2://mypguser:m11ay321@localhost:5432/mypgdatabase"

engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set True only for debugging
    pool_size=10,
    max_overflow=20,
)


@contextmanager
def get_session(engine):
    """Clean context manager for sessions."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ============================ CORE HELPER FUNCTIONS ============================

def get_token_key(given_key: str) -> Result[np.ndarray]:
    """Convert base58 token mint to numpy array (for BYTEA storage)."""
    try:
        if not given_key:
            return Err("given_key cannot be empty")
        if isinstance(given_key, str):
            given_key = given_key.encode("utf-8")
        decoded = base58.b58decode(given_key)
        if len(decoded) % 4 != 0:
            return Err("Decoded length not multiple of 4")
        result = np.frombuffer(decoded, dtype="<i4")
        return Ok(result)
    except Exception as e:
        logging.error(f"[get_token_key] {e}")
        return Err(str(e))


def get_wallet_id_by_public_key(db_session: Session, public_key: str) -> Optional[int]:
    stmt = select(Wallet.id).where(Wallet.publicKey == public_key)
    return db_session.execute(stmt).scalar()


def get_single_wallet_pk(session: Session) -> Result[Optional[int]]:
    """Returns wallet PK if exactly one wallet exists."""
    stmt = select(Wallet.id).select_from(Wallet).limit(2)
    try:
        ids = session.scalars(stmt).all()
        if len(ids) == 1:
            return Ok(ids[0])
        return Ok(None)
    except Exception as e:
        logging.error(f"[get_single_wallet_pk] {e}")
        return Err(str(e))


def is_number_wallets_1(session: Session) -> Result[bool]:
    stmt = select(func.count()).select_from(Wallet)
    try:
        count = session.scalar(stmt)
        return Ok(count == 1)
    except Exception as e:
        logging.error(f"[is_number_wallets_1] {e}")
        return Err(str(e))


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
    session: Session, wallet_id: Optional[int] = None, wallet_public_key: Optional[str] = None
) -> Result[int]:
    if wallet_id is not None:
        return Ok(wallet_id)
    if wallet_public_key is not None:
        pk = get_wallet_id_by_public_key(session, wallet_public_key)
        if pk:
            return Ok(pk)
    single = get_single_wallet_pk(session)
    if single.is_ok and single.value:
        return Ok(single.value)
    return Err("Cannot acquire wallet primary key")


# ============================ INSERT FUNCTIONS ============================

def insert_investment(
    session: Session,
    token_key: np.ndarray,
    investment_data: InvestmentCreate,
    wallet_id: Optional[int] = None,
    wallet_public_key: Optional[str] = None,
) -> Result[bool]:
    """Insert a new investment. Clean, session-based."""
    wallet_res = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_res.is_error:
        return Err(f"Wallet error: {wallet_res.error}")

    asset_res = ensure_asset_exists(session, token_key, wallet_res.value)
    if asset_res.is_error:
        return asset_res

    try:
        data = investment_data.model_dump()
        data["parent_id"] = asset_res.value
        inv = Investment(**data)
        session.add(inv)
        session.flush()
        return Ok(True)
    except Exception as exc:
        session.rollback()
        return Err(str(exc))


def insert_security(
    session: Session,
    token_key: np.ndarray,
    security_data: SecurityCreate,
    wallet_id: Optional[int] = None,
    wallet_public_key: Optional[str] = None,
) -> Result[bool]:
    """Insert a new security (gas, tax, savings, etc.)."""
    wallet_res = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_res.is_error:
        return Err(f"Wallet error: {wallet_res.error}")

    asset_res = ensure_asset_exists(session, token_key, wallet_res.value)
    if asset_res.is_error:
        return asset_res

    try:
        data = security_data.model_dump()
        data["parent_id"] = asset_res.value
        sec = Security(**data)
        session.add(sec)
        session.flush()
        return Ok(True)
    except Exception as exc:
        session.rollback()
        return Err(str(exc))


# ============================ SWAP / TAX HELPERS (STUBS FOR NOTEBOOK) ============================

def record_partial_sell(
    session: Session,
    investment_id: int,
    sold_lamports: int,
    sell_tx_id: str,
    sell_price_usdc: float,
    sell_fee_usdc: float = 0.0,
) -> Result[bool]:
    """
    Example helper for 'sell half' scenario.
    Divides investment, closes sold portion, creates tax record stub.
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

        # Close sold portion
        inv.amount = sold_lamports
        inv.isClosed = True
        inv.sell_tx_id = sell_tx_id
        inv.sale_price_usdc = sell_price_usdc
        inv.sell_fee_usdc = sell_fee_usdc
        inv.sale_time_ms = int(time.time() * 1000)

        # Create remaining open investment if any left
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

        # TODO: create TaxRecord entry here (or call separate tax_filer)

        session.flush()
        return Ok(True)

    except Exception as e:
        session.rollback()
        return Err(str(e))


print("✅ db_manager_v2 loaded — clean modular version ready for notebook")