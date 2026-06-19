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
from datetime import datetime
from global_values import WORLD_STABLE_COIN
from contextlib import contextmanager

from sqlalchemy import create_engine, select, func
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import Session, declarative_base, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary, Float, ForeignKey, cast

from pydantic import BaseModel, Field
from result import Result, Ok, Err

import os
from dotenv import load_dotenv
import requests

from solana.rpc.api import Client
from solana.rpc.commitment import Commitment

from logging_config import setup_logging

Base = declarative_base()

load_dotenv()

setup_logging(log_file="trades.log")

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")

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
    if single.is_ok and single.value:
        return Ok(single.value)

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
    if gas_res.is_error:
        return gas_res

    if gas_res.value < required_lamports:
        return Err(
            f"Insufficient gas: need {required_lamports} lamports, "
            f"only {gas_res.value} available"
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
        if gain_res.is_error:
            return gain_res

        gain = gain_res.value
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

        stable_key = get_token_key(WORLD_STABLE_COIN).value
        insert_res = insert_security(session, stable_key, tax_sec, wallet_id=wallet_pk)

        if insert_res.is_error:
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
# =============================================================================





def execute_trade_with_gas(
    session: Session,
    investment_id: int,
    target_mint: str,
    estimated_gas_lamports: int,
    wallet_pk: int,
    sell_lamports: int = None,
    gas_security_id: Optional[int] = None,
    max_retries: int = 3,
) -> Result[dict]:
    """
    High-level trade orchestrator using Helius for Jupiter swaps.
    Includes safety rails, gas handling, tax withholding, retry logic,
    and synchronous transaction confirmation.
    """
    logging.info(f"[TRADE] Starting trade | investment_id={investment_id} | wallet={wallet_pk}")

    helius_api_key = os.getenv("HELIUS_API_KEY")
    wallet_public_key = os.getenv("WALLET_PUBLIC_KEY")

    if not helius_api_key or not wallet_public_key:
        return Err("Missing HELIUS_API_KEY or WALLET_PUBLIC_KEY environment variables")

    for attempt in range(1, max_retries + 1):
        try:
            # === 1. Load Investment ===
            inv = session.execute(
                select(Investment).where(Investment.id == investment_id)
            ).scalar_one_or_none()

            if not inv:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message="Investment not found")
                return Err("Investment not found")

            if sell_lamports is None:
                sell_lamports = inv.amount // 2

            if sell_lamports <= 0 or sell_lamports > inv.amount:
                return Err("Invalid sell amount")

            # === 2. Safety Check ===
            safety = pre_trade_safety_check(
                session=session,
                investment_id=investment_id,
                sell_lamports=sell_lamports,
                estimated_gas_lamports=estimated_gas_lamports,
                wallet_pk=wallet_pk
            )
            if safety.is_error:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=safety.error)
                return Err(f"Safety check failed: {safety.error}")

            # === 3. Gas Preparation ===
            if gas_security_id is None:
                oldest = get_oldest_gas_security(session, wallet_pk)
                if oldest.is_ok and oldest.value:
                    gas_security_id = oldest.value

            gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
            if gas_check.is_error:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=gas_check.error)
                return gas_check

            # === 4. Execute Swap via Helius ===
            logging.info(f"[SWAP] Attempt {attempt}/{max_retries} via Helius...")

            swap_res = execute_jupiter_swap_via_helius(
                input_mint=WORLD_STABLE_COIN,
                output_mint=target_mint,
                amount=sell_lamports,
                slippage_bps=50,
                helius_api_key=helius_api_key,
                wallet_public_key=wallet_public_key,
            )

            if swap_res.is_error:
                if attempt == max_retries:
                    log_trade_result(investment_id, wallet_pk, status="failed", error_message=swap_res.error)
                    return Err(f"Helius swap failed after {max_retries} attempts")
                logging.warning(f"[SWAP] Attempt {attempt} failed. Retrying...")
                time.sleep(2)
                continue

            tx_sig = swap_res.value["signature"]

            # === 5. Confirm Transaction (Synchronous) ===
            confirm_res = confirm_transaction(tx_sig)
            if confirm_res.is_error:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=confirm_res.error)
                return Err(f"Transaction confirmation failed: {confirm_res.error}")

            logging.info(f"[CONFIRM] Transaction confirmed: {tx_sig}")

            received_amount = swap_res.value.get("received_amount", 0)
            sell_price_usdc = received_amount / 1_000_000 if received_amount else 0.0

            # === 6. Record Partial Sell ===
            record_res = record_partial_sell(
                session=session,
                investment_id=investment_id,
                sold_lamports=sell_lamports,
                sell_tx_id=tx_sig,
                sell_price_usdc=sell_price_usdc,
            )
            if record_res.is_error:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=record_res.error)
                return record_res

            # === 7. Spend Gas ===
            if gas_security_id:
                spend_res = spend_gas_security(
                    session=session,
                    gas_security_id=gas_security_id,
                    used_lamports=estimated_gas_lamports,
                    tx_id="gas_" + tx_sig[:8]
                )
                if spend_res.is_error:
                    logging.warning(f"[GAS] Could not spend gas security: {spend_res.error}")

            # === 8. Withhold Tax ===
            tax_res = withhold_tax_on_profitable_sale(
                session=session,
                investment_id=investment_id,
                sell_proceeds_usdc=sell_price_usdc,
                wallet_pk=wallet_pk
            )
            if tax_res.is_error:
                logging.warning(f"[TAX] Tax withholding failed: {tax_res.error}")

            # === 9. Log Success ===
            log_trade_result(
                investment_id=investment_id,
                wallet_pk=wallet_pk,
                status="success",
                tx_signature=tx_sig,
                sold_lamports=sell_lamports,
                received_amount=received_amount,
                sell_price_usdc=sell_price_usdc,
            )

            logging.info(f"[TRADE] Completed successfully | investment_id={investment_id}")

            return Ok({
                "status": "success",
                "investment_id": investment_id,
                "tx_signature": tx_sig,
                "sold_lamports": sell_lamports,
                "received_amount": received_amount,
                "sell_price_usdc": sell_price_usdc,
                "gas_security_id": gas_security_id,
                "tax_withheld": tax_res.value if tax_res.is_ok else False,
            })

        except Exception as e:
            logging.exception(f"[TRADE] Unexpected error on attempt {attempt}")
            if attempt == max_retries:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=str(e))
                return Err(f"Trade failed after {max_retries} attempts: {str(e)}")
            time.sleep(2)

    return Err(f"Trade failed after {max_retries} attempts")


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
        total_tax_reserved = tax_res.value if tax_res.is_ok else 0.0

        # 3. Total gas available (lamports + SOL)
        gas_res = get_available_gas_lamports(session, wallet_pk)
        total_gas_lamports = gas_res.value if gas_res.is_ok else 0

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
    extra_info: dict = None
):
    """
    Simple trade result logger using Python logging.
    Easy to extend later with database persistence.
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
    }

    if extra_info:
        log_entry.update(extra_info)

    if status.lower() == "success":
        logging.info(f"[TRADE] {log_entry}")
    else:
        logging.error(f"[TRADE] {log_entry}")


def confirm_transaction(
    tx_signature: str,
    rpc_url: str = "https://api.devnet.solana.com",
    max_retries: int = 30,
    sleep_seconds: float = 2.0
) -> Result[dict]:
    """
    Waits for a transaction to be confirmed on-chain.
    Returns transaction status once confirmed or fails after max retries.
    """
    client = Client(rpc_url)

    for attempt in range(max_retries):
        try:
            response = client.get_transaction(
                tx_signature,
                commitment=Commitment("confirmed"),
                max_supported_transaction_version=0
            )

            if response.value:
                meta = response.value.transaction.meta
                if meta and meta.err is None:
                    logging.info(f"[CONFIRM] Transaction confirmed: {tx_signature}")
                    return Ok({
                        "signature": tx_signature,
                        "status": "confirmed",
                        "slot": response.value.slot,
                    })
                else:
                    return Err(f"Transaction failed on-chain: {meta.err if meta else 'Unknown error'}")

            logging.info(f"[CONFIRM] Attempt {attempt + 1}/{max_retries} - not confirmed yet...")
            time.sleep(sleep_seconds)

        except Exception as e:
            logging.warning(f"[CONFIRM] Error checking transaction: {str(e)}")
            time.sleep(sleep_seconds)

    return Err(f"Transaction not confirmed after {max_retries} attempts")



def execute_sell_half_investment(
    session,
    investment_id: int,
    target_mint: str,
    estimated_gas_lamports: int = 5_000_000,
    wallet_pk: int = None,
) -> Result[dict]:
    """
    Easy helper function for testing.
    Sells half of an investment using Helius + all safety rails.

    Usage in notebook:
        result = execute_sell_half_investment(session, investment_id=42, target_mint="So1111...")
    """
    if wallet_pk is None:
        # Try to get the single wallet if only one exists
        single_wallet = get_single_wallet_pk(session)
        if single_wallet.is_ok and single_wallet.value:
            wallet_pk = single_wallet.value
        else:
            return Err("wallet_pk not provided and could not determine default wallet")

    return execute_trade_with_gas(
        session=session,
        investment_id=investment_id,
        target_mint=target_mint,
        estimated_gas_lamports=estimated_gas_lamports,
        wallet_pk=wallet_pk,
    )


def execute_sell_percentage_investment(
    session,
    investment_id: int,
    target_mint: str,
    sell_percentage: float = 50.0,           # e.g. 25, 50, 75, 100
    estimated_gas_lamports: int = 5_000_000,
    wallet_pk: int = None,
) -> Result[dict]:
    """
    Sells a specific percentage of an investment.

    Example:
        execute_sell_percentage_investment(session, investment_id=42, target_mint=..., sell_percentage=50)
    """
    if wallet_pk is None:
        single = get_single_wallet_pk(session)
        if single.is_ok and single.value:
            wallet_pk = single.value
        else:
            return Err("Could not determine wallet_pk")

    # Get the investment to calculate sell amount
    inv = session.execute(
        select(Investment).where(Investment.id == investment_id)
    ).scalar_one_or_none()

    if not inv:
        return Err(f"Investment {investment_id} not found")

    if inv.isClosed:
        return Err(f"Investment {investment_id} is already closed")

    sell_lamports = int(inv.amount * (sell_percentage / 100))

    if sell_lamports <= 0:
        return Err("Calculated sell amount is zero")

    return execute_trade_with_gas(
        session=session,
        investment_id=investment_id,
        target_mint=target_mint,
        estimated_gas_lamports=estimated_gas_lamports,
        wallet_pk=wallet_pk,
        sell_lamports=sell_lamports,
    )
