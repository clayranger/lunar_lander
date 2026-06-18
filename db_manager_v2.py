"""
db_manager_v2.py
Clean, modular, production-oriented database layer for Lunar Lander DeFi.
Includes: Gas security handling + Automatic tax withholding on profitable sales.
"""

from __future__ import annotations
from typing import List, Optional
import numpy as np
import base58
from contextlib import contextmanager
from datetime import datetime
import logging
import time

from sqlalchemy import select, func, create_engine
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary, Float
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Mapped, mapped_column, relationship, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, cast

from pydantic import BaseModel, Field
from result import Result, Ok, Err

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
    amount: int = Field(..., gt=0)
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


# ============================ CORE HELPERS ============================

def get_token_key(given_key: str) -> Result[np.ndarray]:
    try:
        if not given_key:
            return Err("given_key cannot be empty")
        if isinstance(given_key, str):
            given_key = given_key.encode("utf-8")
        decoded = base58.b58decode(given_key)
        if len(decoded) % 4 != 0:
            return Err("Decoded length not multiple of 4")
        return Ok(np.frombuffer(decoded, dtype="<i4"))
    except Exception as e:
        logging.error(f"[get_token_key] {e}")
        return Err(str(e))


def get_wallet_id_by_public_key(db_session: Session, public_key: str) -> Optional[int]:
    stmt = select(Wallet.id).where(Wallet.publicKey == public_key)
    return db_session.execute(stmt).scalar()


def get_single_wallet_pk(session: Session) -> Result[Optional[int]]:
    stmt = select(Wallet.id).select_from(Wallet).limit(2)
    try:
        ids = session.scalars(stmt).all()
        return Ok(ids[0]) if len(ids) == 1 else Ok(None)
    except Exception as e:
        return Err(str(e))


def is_number_wallets_1(session: Session) -> Result[bool]:
    stmt = select(func.count()).select_from(Wallet)
    try:
        return Ok(session.scalar(stmt) == 1)
    except Exception as e:
        return Err(str(e))


def ensure_asset_exists(session: Session, token_key: np.ndarray, wallet_pk: int) -> Result[int]:
    does_exist = session.query(session.query(Asset).filter_by(coin=cast(token_key, BYTEA)).exists()).scalar()
    if not does_exist:
        asset_obj = Asset(wallet=wallet_pk, coin=cast(token_key, BYTEA), isNative=False, isOfficialStable=False, isAltStable=False)
        session.add(asset_obj)
        session.flush()
    try:
        asset = session.execute(select(Asset).filter_by(coin=cast(token_key, BYTEA))).scalar_one()
        return Ok(asset.id)
    except Exception as e:
        return Err(str(e))


def aquire_wallet_key(session: Session, wallet_id: Optional[int] = None, wallet_public_key: Optional[str] = None) -> Result[int]:
    if wallet_id is not None:
        return Ok(wallet_id)
    if wallet_public_key is not None:
        pk = get_wallet_id_by_public_key(session, wallet_public_key)
        if pk: return Ok(pk)
    single = get_single_wallet_pk(session)
    if single.is_ok and single.value:
        return Ok(single.value)
    return Err("Cannot acquire wallet primary key")


# ============================ INSERT FUNCTIONS ============================

def insert_investment(session: Session, token_key: np.ndarray, investment_data: InvestmentCreate, wallet_id=None, wallet_public_key=None) -> Result[bool]:
    wallet_res = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_res.is_error: return wallet_res
    asset_res = ensure_asset_exists(session, token_key, wallet_res.value)
    if asset_res.is_error: return asset_res
    try:
        data = investment_data.model_dump()
        data["parent_id"] = asset_res.value
        session.add(Investment(**data))
        session.flush()
        return Ok(True)
    except Exception as exc:
        session.rollback()
        return Err(str(exc))


def insert_security(session: Session, token_key: np.ndarray, security_data: SecurityCreate, wallet_id=None, wallet_public_key=None) -> Result[bool]:
    wallet_res = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_res.is_error: return wallet_res
    asset_res = ensure_asset_exists(session, token_key, wallet_res.value)
    if asset_res.is_error: return asset_res
    try:
        data = security_data.model_dump()
        data["parent_id"] = asset_res.value
        session.add(Security(**data))
        session.flush()
        return Ok(True)
    except Exception as exc:
        session.rollback()
        return Err(str(exc))


# ============================ GAS HELPERS ============================

def get_available_gas_lamports(session: Session, wallet_pk: int) -> Result[int]:
    try:
        stmt = select(func.sum(Security.amount)).join(Asset, Security.parent_id == Asset.id).where(
            Asset.wallet == wallet_pk, Security.isGas == True, Security.isClosed == False)
        total = session.execute(stmt).scalar() or 0
        return Ok(int(total))
    except Exception as e:
        return Err(str(e))


def ensure_sufficient_gas(session: Session, required_lamports: int, wallet_pk: int) -> Result[bool]:
    gas_res = get_available_gas_lamports(session, wallet_pk)
    if gas_res.is_error: return gas_res
    if gas_res.value < required_lamports:
        return Err(f"Insufficient gas: need {required_lamports}, have {gas_res.value}")
    return Ok(True)


def spend_gas_security(session: Session, gas_security_id: int, used_lamports: int, tx_id: str) -> Result[bool]:
    try:
        sec = session.execute(select(Security).where(Security.id == gas_security_id)).scalar_one()
        if sec.isClosed: return Err("Gas security already closed")
        if used_lamports > sec.amount: return Err("Trying to spend more than available")
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
    try:
        stmt = select(Security.id).join(Asset, Security.parent_id == Asset.id).where(
            Asset.wallet == wallet_pk, Security.isGas == True, Security.isClosed == False
        ).order_by(Security.purchase_time_ms.asc()).limit(1)
        return Ok(session.execute(stmt).scalar())
    except Exception as e:
        return Err(str(e))


# ============================ TAX HELPERS ============================

def calculate_realized_gain(session: Session, investment_id: int, sell_price_usdc: float) -> Result[dict]:
    try:
        inv = session.execute(select(Investment).where(Investment.id == investment_id)).scalar_one()
        profit = sell_price_usdc - (inv.purchase_price_usdc or 0)
        return Ok({
            "profit_usdc": profit,
            "is_profitable": profit > 0,
            "purchase_price_usdc": inv.purchase_price_usdc or 0,
            "sell_price_usdc": sell_price_usdc
        })
    except Exception as e:
        return Err(str(e))


def withhold_tax_on_profitable_sale(session: Session, investment_id: int, sell_proceeds_usdc: float, wallet_pk: int) -> Result[bool]:
    try:
        gain = calculate_realized_gain(session, investment_id, sell_proceeds_usdc).value
        if not gain["is_profitable"]:
            return Ok(False)

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
            isTax=True
        )
        stable_key = get_token_key(WORLD_STABLE_COIN).value
        insert_security(session, stable_key, tax_sec, wallet_id=wallet_pk)
        logging.info(f"✅ Tax withheld: ${tax_amount:.2f} (rate {tax_rate*100:.0f}%)")
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(str(e))


def get_total_tax_owed(session: Session, wallet_pk: int) -> Result[float]:
    try:
        stmt = select(func.sum(Security.purchase_price_usdc)).join(Asset).where(
            Asset.wallet == wallet_pk, Security.isTax == True, Security.isClosed == False)
        return Ok(float(session.execute(stmt).scalar() or 0))
    except Exception as e:
        return Err(str(e))


def get_open_tax_securities(session: Session, wallet_pk: int):
    try:
        stmt = select(Security).join(Asset).where(
            Asset.wallet == wallet_pk, Security.isTax == True, Security.isClosed == False
        ).order_by(Security.purchase_time_ms.asc())
        return Ok(session.execute(stmt).scalars().all())
    except Exception as e:
        return Err(str(e))


# ============================ HIGH-LEVEL TRADE ============================

def record_partial_sell(session: Session, investment_id: int, sold_lamports: int, sell_tx_id: str,
                        sell_price_usdc: float, sell_fee_usdc: float = 0.0) -> Result[bool]:
    try:
        inv = session.execute(select(Investment).where(Investment.id == investment_id)).scalar_one()
        if inv.isClosed: return Err("Investment already closed")
        remaining = inv.amount - sold_lamports
        if remaining < 0: return Err("Sold more than available")

        inv.amount = sold_lamports
        inv.isClosed = True
        inv.sell_tx_id = sell_tx_id
        inv.sale_price_usdc = sell_price_usdc
        inv.sell_fee_usdc = sell_fee_usdc
        inv.sale_time_ms = int(time.time() * 1000)

        if remaining > 0:
            session.add(Investment(
                parent_id=inv.parent_id, amount=remaining,
                purchase_price_usdc=inv.purchase_price_usdc,
                purchase_time_ms=inv.purchase_time_ms,
                buy_fee_native_lamports=inv.buy_fee_native_lamports,
                buy_fee_usdc=inv.buy_fee_usdc,
                buy_tx_id=inv.buy_tx_id, isClosed=False
            ))
        session.flush()
        return Ok(True)
    except Exception as e:
        session.rollback()
        return Err(str(e))


def execute_trade_with_gas(
    session: Session,
    investment_id: int,
    jupiter_client,
    target_mint: str,
    estimated_gas_lamports: int,
    wallet_pk: int,
    keypair=None,
    gas_security_id: Optional[int] = None,
) -> Result[dict]:
    # 1. Gas check
    gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
    if gas_check.is_error: return gas_check

    if gas_security_id is None:
        oldest = get_oldest_gas_security(session, wallet_pk)
        if oldest.is_ok and oldest.value:
            gas_security_id = oldest.value

    # 2. Jupiter (simplified)
    from_mint = WORLD_STABLE_COIN
    quote = jupiter_client.get_quote(from_mint, target_mint, 0).value
    # ... (you can expand real quote + execute here)

    # For demo, we simulate a successful half sell
    inv = session.execute(select(Investment).where(Investment.id == investment_id)).scalar_one()
    sold_lamports = inv.amount // 2
    tx_sig = "demo_tx_" + str(int(time.time()))
    sell_price_usdc = 1234.56   # placeholder - replace with real from Jupiter

    record_partial_sell(session, investment_id, sold_lamports, tx_sig, sell_price_usdc)

    # 3. Spend gas
    if gas_security_id:
        spend_gas_security(session, gas_security_id, estimated_gas_lamports, "gas_" + tx_sig[:8])

    # 4. Automatic tax withholding
    tax_res = withhold_tax_on_profitable_sale(session, investment_id, sell_price_usdc, wallet_pk)

    return Ok({
        "status": "success",
        "investment_id": investment_id,
        "sold_lamports": sold_lamports,
        "tx_signature": tx_sig,
        "tax_withheld": tax_res.value if tax_res.is_ok else False,
        "gas_security_id": gas_security_id,
    })


print("✅ db_manager_v2 loaded — clean single file with gas + automatic tax withholding")
