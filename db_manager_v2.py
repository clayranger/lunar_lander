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

Base = declarative_base()

load_dotenv()

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
    jupiter_client,                    # Will be replaced with Helius later
    target_mint: str,
    estimated_gas_lamports: int,
    wallet_pk: int,
    keypair=None,
    gas_security_id: Optional[int] = None,
) -> Result[dict]:
    """
    High-level trade orchestrator.
    Includes safety checks, gas handling, tax withholding, and result logging.
    """
    logging.info(f"[TRADE] Starting trade | investment_id={investment_id} | wallet={wallet_pk}")

    inv = None
    sell_lamports = 0
    tx_sig = None
    received_amount = 0
    sell_price_usdc = 0.0

    try:
        # === 1. SAFETY CHECK ===
        inv = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one_or_none()

        if not inv:
            log_trade_result(investment_id, wallet_pk, "failed", error_message="Investment not found")
            return Err("Investment not found")

        sell_lamports = inv.amount // 2

        safety = pre_trade_safety_check(
            session=session,
            investment_id=investment_id,
            sell_lamports=sell_lamports,
            estimated_gas_lamports=estimated_gas_lamports,
            wallet_pk=wallet_pk
        )

        if safety.is_error:
            log_trade_result(investment_id, wallet_pk, "failed", error_message=safety.error)
            return Err(f"Safety check failed: {safety.error}")

        if safety.value.get("warnings"):
            logging.warning(f"[SAFETY] {safety.value['warnings']}")

        # === 2. GAS PREPARATION ===
        if gas_security_id is None:
            oldest = get_oldest_gas_security(session, wallet_pk)
            if oldest.is_ok and oldest.value:
                gas_security_id = oldest.value

        gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
        if gas_check.is_error:
            log_trade_result(investment_id, wallet_pk, "failed", error_message=gas_check.error)
            return gas_check

        # === 3. EXECUTE SWAP (Placeholder for now) ===
        logging.info("[SWAP] Executing swap (placeholder)...")

        # TODO: Replace this block with real Helius / Jupiter call
        tx_sig = f"devnet_tx_{int(time.time())}"
        received_amount = 1234567890          # placeholder
        sell_price_usdc = received_amount / 1_000_000

        logging.info(f"[SWAP] Completed | tx={tx_sig} | received={received_amount}")

        # === 4. RECORD PARTIAL SELL ===
        record_res = record_partial_sell(
            session=session,
            investment_id=investment_id,
            sold_lamports=sell_lamports,
            sell_tx_id=tx_sig,
            sell_price_usdc=sell_price_usdc,
        )
        if record_res.is_error:
            log_trade_result(investment_id, wallet_pk, "failed", error_message=record_res.error)
            return record_res

        # === 5. SPEND GAS ===
        if gas_security_id:
            spend_res = spend_gas_security(
                session=session,
                gas_security_id=gas_security_id,
                used_lamports=estimated_gas_lamports,
                tx_id="gas_" + tx_sig[:8]
            )
            if spend_res.is_error:
                logging.warning(f"[GAS] Could not spend gas security: {spend_res.error}")

        # === 6. WITHHOLD TAX ===
        tax_res = withhold_tax_on_profitable_sale(
            session=session,
            investment_id=investment_id,
            sell_proceeds_usdc=sell_price_usdc,
            wallet_pk=wallet_pk
        )
        if tax_res.is_error:
            logging.warning(f"[TAX] Tax withholding failed: {tax_res.error}")

        # === 7. LOG SUCCESS ===
        log_trade_result(
            investment_id=investment_id,
            wallet_pk=wallet_pk,
            status="success",
            tx_signature=tx_sig,
            sold_lamports=sell_lamports,
            received_amount=received_amount,
            sell_price_usdc=sell_price_usdc,
        )

        logging.info(f"[TRADE] Trade completed successfully | investment_id={investment_id}")

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
        logging.exception("[TRADE] Unexpected error during trade execution")
        log_trade_result(
            investment_id=investment_id,
            wallet_pk=wallet_pk,
            status="failed",
            error_message=str(e),
        )
        return Err(f"Trade failed with unexpected error: {str(e)}")


# ============================ SAFETY RAILS ============================

def pre_trade_safety_check(
    session: Session,
    investment_id: int,
    sell_lamports: int,
    estimated_gas_lamports: int,
    wallet_pk: int
) -> Result[dict]:
    """
    Runs multiple safety checks before executing a trade.
    Returns detailed status so we can decide whether to proceed.
    """
    issues = []
    warnings = []

    try:
        # 1. Check investment exists and is open
        inv = session.execute(
            select(Investment).where(Investment.id == investment_id)
        ).scalar_one_or_none()

        if not inv:
            issues.append("Investment does not exist")
        elif inv.isClosed:
            issues.append("Investment is already closed")
        elif sell_lamports > inv.amount:
            issues.append(f"Trying to sell more lamports ({sell_lamports}) than available ({inv.amount})")

        # 2. Gas check
        gas_res = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
        if gas_res.is_error:
            issues.append(gas_res.error)

        # 3. Basic tax readiness check
        wallet = session.execute(select(Wallet).where(Wallet.id == wallet_pk)).scalar_one_or_none()
        if wallet:
            user = session.execute(select(User).where(User.id == wallet.parent_id)).scalar_one_or_none()
            if user and (user.tax_level_choice is None or user.tax_level_choice <= 0):
                warnings.append("User tax_level_choice is not set or is zero — tax will not be withheld on profits")

        if issues:
            return Err({
                "status": "blocked",
                "issues": issues,
                "warnings": warnings
            })

        return Ok({
            "status": "ok",
            "warnings": warnings,
            "checks_passed": ["investment_open", "sufficient_gas"]
        })

    except Exception as e:
        return Err({"status": "error", "message": str(e)})



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
    helius_api_key: str,
    wallet_public_key: str,
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int = 50,
    priority_fee: float = 0.0005  # in SOL, adjust as needed
) -> Result[dict]:
    """
    Executes a Jupiter swap using Helius Swap Sender.
    Returns transaction signature and basic info on success.
    """
    if not helius_api_key:
        return Err("Helius API key is missing")

    url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-swap",
        "method": "getJupiterSwapTransaction",
        "params": {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
            "userPublicKey": wallet_public_key,
            "prioritizationFeeLamports": int(priority_fee * 1_000_000_000),
        }
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            return Err(f"Helius error: {data['error']}")

        result = data.get("result", {})
        tx_signature = result.get("signature") or result.get("swapTransaction")

        if not tx_signature:
            return Err("No transaction signature returned from Helius")

        return Ok({
            "status": "submitted",
            "signature": tx_signature,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
        })

    except requests.exceptions.RequestException as e:
        return Err(f"Request failed: {str(e)}")
    except Exception as e:
        return Err(f"Unexpected error: {str(e)}")


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
