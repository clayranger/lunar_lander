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
import base64
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

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import to_bytes_versioned
import json



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
    if wallet_res.is_err:
        return Err(f"Wallet error: {wallet_res.error}")

    asset_res = ensure_asset_exists(session, token_key, wallet_res.value)
    if asset_res.is_err:
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
    if gas_res.is_err:
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
        if gain_res.is_err:
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

        if insert_res.is_err:
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

import os
import time
import base64
import json
import logging
from typing import Optional
from result import Result, Ok, Err

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solana.rpc.api import Client
from solana.rpc.commitment import Commitment


def load_keypair_from_file(filepath: str) -> Keypair:
    with open(filepath, "r") as f:
        secret = json.load(f)
    return Keypair.from_bytes(bytes(secret))


def get_jupiter_swap_transaction_from_helius(
    helius_api_key: str,
    wallet_public_key: str,
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int = 50,
    priority_fee_lamports: int = 500_000,
) -> Result[str]:
    url = f"https://api.helius.xyz/v0/transactions/swap?api-key={helius_api_key}"

    payload = {
        "quoteResponse": {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
        },
        "userPublicKey": wallet_public_key,
        "prioritizationFeeLamports": priority_fee_lamports,
        "wrapAndUnwrapSol": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()

        tx_base64 = data.get("swapTransaction")
        if not tx_base64:
            return Err("No swapTransaction returned from Helius")

        return Ok(tx_base64)
    except requests.exceptions.HTTPError as e:
        return Err(f"Helius HTTP error: {e.response.text if e.response else str(e)}")
    except Exception as e:
        return Err(f"Failed to get swap tx from Helius: {str(e)}")


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
            opts={"skip_preflight": False, "preflight_commitment": Commitment("confirmed")}
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
                tx_signature,
                commitment=Commitment("confirmed"),
                max_supported_transaction_version=0
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
    estimated_gas_lamports: int,
    wallet_pk: int,
    sell_lamports: int = None,
    gas_security_id: Optional[int] = None,
    max_retries: int = 3,
    keypair_path: str = "~/.config/solana/mainnet-test.json",
) -> Result[dict]:
    """
    Full trade orchestrator for mainnet using Helius + local signing with solders.
    """
    logging.info(f"[TRADE] Starting trade | investment_id={investment_id} | wallet={wallet_pk}")

    helius_api_key = os.getenv("HELIUS_API_KEY")
    if not helius_api_key:
        return Err("HELIUS_API_KEY not found in environment variables")

    # Load keypair
    try:
        keypair = load_keypair_from_file(os.path.expanduser(keypair_path))
        wallet_public_key = str(keypair.pubkey())
    except Exception as e:
        return Err(f"Failed to load keypair from {keypair_path}: {str(e)}")

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
            if safety.is_err:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=safety.err_value)
                return Err(f"Safety check failed: {safety.err_value}")

            # === 3. Gas Check ===
            if gas_security_id is None:
                oldest = get_oldest_gas_security(session, wallet_pk)
                if oldest.is_ok and oldest.value:
                    gas_security_id = oldest.value

            gas_check = ensure_sufficient_gas(session, estimated_gas_lamports, wallet_pk)
            if gas_check.is_err:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=gas_check.err_value)
                return gas_check

            # === 4. Get unsigned transaction from Helius ===
            logging.info(f"[SWAP] Attempt {attempt}/{max_retries} via Helius...")

            swap_tx_res = get_jupiter_swap_transaction_from_helius(
                helius_api_key=helius_api_key,
                wallet_public_key=wallet_public_key,
                input_mint=WORLD_STABLE_COIN,
                output_mint=target_mint,
                amount=sell_lamports,
            )

            if swap_tx_res.is_err:
                error_msg = swap_tx_res.err_value
                logging.warning(f"[SWAP] Attempt {attempt} failed: {error_msg}")

                if attempt == max_retries:
                    log_trade_result(investment_id, wallet_pk, status="failed", error_message=error_msg)
                    return Err(f"Helius swap failed after {max_retries} attempts: {error_msg}")

                time.sleep(2)
                continue

            tx_base64 = swap_tx_res.ok_value

            # === 5. Sign and send transaction ===
            send_res = sign_and_send_transaction(tx_base64, keypair)

            if send_res.is_err:
                error_msg = send_res.err_value
                logging.warning(f"[SWAP] Sign/Send failed on attempt {attempt}: {error_msg}")

                if attempt == max_retries:
                    log_trade_result(investment_id, wallet_pk, status="failed", error_message=error_msg)
                    return Err(f"Failed to sign/send after {max_retries} attempts: {error_msg}")

                time.sleep(2)
                continue

            tx_sig = send_res.ok_value
            logging.info(f"[SWAP] Transaction sent: {tx_sig}")

            # === 6. Confirm Transaction ===
            confirm_res = confirm_transaction(tx_sig)

            if confirm_res.is_err:
                error_msg = confirm_res.err_value
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=error_msg)
                return Err(f"Transaction confirmation failed: {error_msg}")

            logging.info(f"[CONFIRM] Transaction confirmed: {tx_sig}")

            received_amount = 0  # You can parse this from the transaction if needed
            sell_price_usdc = 0.0

            # === 7. Record Partial Sell ===
            record_res = record_partial_sell(
                session=session,
                investment_id=investment_id,
                sold_lamports=sell_lamports,
                sell_tx_id=tx_sig,
                sell_price_usdc=sell_price_usdc,
            )
            if record_res.is_err:
                log_trade_result(investment_id, wallet_pk, status="failed", error_message=record_res.err_value)
                return record_res

            # === 8. Spend Gas ===
            if gas_security_id:
                spend_res = spend_gas_security(
                    session=session,
                    gas_security_id=gas_security_id,
                    used_lamports=estimated_gas_lamports,
                    tx_id="gas_" + tx_sig[:8]
                )
                if spend_res.is_err:
                    logging.warning(f"[GAS] Could not spend gas security: {spend_res.err_value}")

            # === 9. Withhold Tax ===
            tax_res = withhold_tax_on_profitable_sale(
                session=session,
                investment_id=investment_id,
                sell_proceeds_usdc=sell_price_usdc,
                wallet_pk=wallet_pk
            )
            if tax_res.is_err:
                logging.warning(f"[TAX] Tax withholding failed: {tax_res.err_value}")

            # === 10. Log Success ===
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
                "tax_withheld": tax_res.ok_value if tax_res.is_ok else False,
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





def execute_sell_percentage_investment(
    session: Session,
    investment_id: int,
    target_mint: str,
    sell_percentage: float = 50.0,
    estimated_gas_lamports: int = 5_000_000,
    wallet_pk: int = None,
    keypair_path: str = "~/.config/solana/mainnet-test.json",
) -> Result[dict]:
    """
    Sells a specific percentage of an investment on mainnet.

    Example usage:
        result = execute_sell_percentage_investment(
            session=session,
            investment_id=10,
            target_mint="So11111111111111111111111111111111111111112",
            sell_percentage=25,           # Sell 25%
        )
    """
    if wallet_pk is None:
        single = get_single_wallet_pk(session)
        if single.is_ok and single.value:
            wallet_pk = single.value
        else:
            return Err("wallet_pk not provided and no default wallet could be determined")

    # Load the investment to calculate how much to sell
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

    return execute_trade_with_gas(
        session=session,
        investment_id=investment_id,
        target_mint=target_mint,
        estimated_gas_lamports=estimated_gas_lamports,
        wallet_pk=wallet_pk,
        sell_lamports=sell_lamports,
        keypair_path=keypair_path,
    )




def sync_wallet_balances(
    session: Session,
    wallet_pk: int,
    rpc_url: str = None,
    wallet_public_key: str = None,
) -> Result[dict]:
    """
    Syncs on-chain balances (SOL + SPL tokens) into the Asset table.
    Idempotent: only updates if the on-chain amount differs from the database.
    """
    if rpc_url is None:
        helius_key = os.getenv("HELIUS_API_KEY")
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"

    if wallet_public_key is None:
        # Try to get public key from Wallet table
        wallet = session.execute(
            select(Wallet).where(Wallet.id == wallet_pk)
        ).scalar_one_or_none()
        if not wallet:
            return Err("Wallet not found")
        wallet_public_key = wallet.publicKey

    client = Client(rpc_url)
    owner = Pubkey.from_string(wallet_public_key)

    created = 0
    updated = 0
    unchanged = 0

    try:
        # 1. Get SOL balance
        sol_balance = client.get_balance(owner).value
        sol_mint = "So11111111111111111111111111111111111111112"  # Wrapped SOL mint

        sol_asset = session.execute(
            select(Asset).where(
                Asset.wallet == wallet_pk,
                Asset.coin == sol_mint.encode()  # You may need to adjust storage
            )
        ).scalar_one_or_none()

        if sol_asset:
            if sol_asset.audited_amount_sum_lamports != sol_balance:
                sol_asset.audited_amount_sum_lamports = sol_balance
                sol_asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                updated += 1
                logging.info(f"[SYNC] Updated SOL balance for wallet {wallet_pk}")
            else:
                unchanged += 1
        else:
            # Create new Asset for SOL
            new_asset = Asset(
                wallet=wallet_pk,
                coin=sol_mint.encode(),
                audited_amount_sum_lamports=sol_balance,
                audited_time_unix_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
                isNative=True,
            )
            session.add(new_asset)
            created += 1
            logging.info(f"[SYNC] Created SOL asset for wallet {wallet_pk}")

        # 2. Get all SPL token accounts
        token_accounts = client.get_token_accounts_by_owner(
            owner,
            opts={"program_id": Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")}
        ).value

        for account in token_accounts:
            mint = str(account.account.data.parsed["info"]["mint"])
            amount = int(account.account.data.parsed["info"]["tokenAmount"]["amount"])

            asset = session.execute(
                select(Asset).where(
                    Asset.wallet == wallet_pk,
                    Asset.coin == mint.encode()
                )
            ).scalar_one_or_none()

            if asset:
                if asset.audited_amount_sum_lamports != amount:
                    asset.audited_amount_sum_lamports = amount
                    asset.audited_time_unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                    updated += 1
                    logging.info(f"[SYNC] Updated token {mint} for wallet {wallet_pk}")
                else:
                    unchanged += 1
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
                logging.info(f"[SYNC] Created new asset for token {mint} (wallet {wallet_pk})")

        session.commit()

        summary = {
            "created_assets": created,
            "updated_assets": updated,
            "unchanged_assets": unchanged,
            "total_assets": created + updated + unchanged,
        }

        logging.info(f"[SYNC] Wallet {wallet_pk} sync complete: {summary}")
        return Ok(summary)

    except Exception as e:
        session.rollback()
        logging.error(f"[SYNC] Failed to sync wallet {wallet_pk}: {str(e)}")
        return Err(str(e))



def automatic_setuper():
    '''
    TODO
    get this ready for ALPHA
    '''
    def create_database():
        Base.metadata.create_all(engine)
        print("created")
        return

    def delete_database():
        Base.metadata.drop_all(engine)
        return
    def add_default_user():
        '''
        TODO
        store salt in db
        '''
        given_password = b"m11ay321"
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(given_password, salt)
        user = User(
            username="adam",
            password=hashed_password)
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            session.add(user)
            session.commit()
        except Exception as e:
            print(f"error with database:  {e}")
            session.rollback()
        finally:
            session.close()
        return
    def testing_insert_wallet_id():
        '''version 0.1. This function is for testing purposes only
        It inserts a given wallet string into the database for all users.'''
        #for all users
        #delete any wallets already owned
        #insert the given wallet string
        given_public_key = "FnEKih68qukzTfhJ8TLQHWGHvFv3vrRUsgfsPq6Fe19y"
        Session = sessionmaker(bind=engine)
        session = Session()
        my_users = session.query(User).all()
        wallets = session.query(Wallet).all()
        for person in my_users:
            user_id = person.id
            print("a user has been located: " + str(user_id))
            #for each token in selected token list
            #   add to list of tokens
            #   record lowest latency request
            #token list is a list of the tokens and their lowest latencyies
            for entry in wallets:
                row_to_delete = session.query(Wallet).get(entry.id)
                session.delete(row_to_delete)
                session.commit()
            #now lets insert the wallet into a new entry
            #TODO correct for actual wallet data structure.
            wallet = Wallet(
                publicKey=given_public_key,
                parent_id=person.id
            )
            session.add(wallet)
            session.commit()
            print("database has been modified")
        session.close()
        return
    def testing_setupKnownTokens():
            ######################################################################################################################
            #!|!|!|!|!|!|!MAJOR BUG -> MUST take in decimals into token from metadata                                            #
            ######################################################################################################################
        print("hello. I am setupDatabases 0.1")
        Session = sessionmaker(bind=engine)
        session = Session()
        for entry in solana_tokens:
            error = None
            newNumber = base58.b58decode(entry)
            print("token id")
            # < represents little endian
            # i represent integer
            # 4 represendts 4 byte array entries which I chose because 20/4 r=0
            numberist = np.frombuffer(newNumber, dtype='<i4')
            print("numberist")
            print(numberist)
            does_exist = session.query(session.query(Token).filter_by(id=cast(numberist, BYTEA)).exists()).scalar()
            print("database query complete")
            if does_exist:
                print("does exist")
                error= ('exsists')
            else:
                print("does not exist")
                try:
                    url_to_go = "http://" + BANK_MANAGER + "/api/get_meta/" + entry + "/"
                    my_response = requests.get(url_to_go)
                    resp_dict = my_response.json()
                    #addition of decimal insertion as testing approaches
                    second_url_to_go = "http://" + BANK_MANAGER + "/api/get_quote/" + entry + "/"
                    my_second_response = requests.get(second_url_to_go)
                    resp_second_dict = my_second_response.json()
                except Exception as e:
                    print("error getting url: " + e)
                else:
                    print("token name:" + resp_dict['name'])
                    print("token symbol:" + resp_dict['symbol'])
                    if error is None:
                        print("token id")
                        currentToken = Token(
                            id=cast(numberist, BYTEA),
                            name=resp_dict['name'],
                            tickerSymbol=resp_dict['symbol'],
                            priceServer='jupiter',
                            exchangeSever='jupiter',
                            decimals=resp_second_dict["decimals"]
                        )
                        text = resp_dict['name'] + " was added to the database."
                        print("enter name as")
                        print(resp_dict['name'])
                        try:
                            session.add(currentToken)
                            session.commit()
                        except Exception as e:
                            print(f"db error: {e}")
        session.close()
        return
    def testing_selectAllTokens():
        Session = sessionmaker(bind=engine)
        session = Session()
        my_users = session.query(User).all()
        tokens = session.query(Token).all()
        for person in my_users:
            user_id = person.id
            for entry in tokens:
                print(" token:" + entry.name)
                print("selected current token")
                print("token id")
                # < represents little endian
                # i represent integer
                # 4 represendts 4 byte array entries which I chose because 20/4 r=0
                numberist = np.frombuffer(entry.id, dtype='<i4')
                does_exist = session.query(select(SelectedToken).filter(SelectedToken.parent_id==entry.id, SelectedToken.owner==user_id).exists()).scalar()
                if does_exist:
                    print(does_exist)
                else:
                    selectedToken = SelectedToken(
                        owner = user_id,
                        parent_id = entry.id#,
                        #depricated
                        #latency = 2
                    )
                    session.add(selectedToken)
                    session.commit()
        session.close()
        print("select all tokens: action complete")
        return
    delete_database()
    create_database()
    add_default_user()
    testing_insert_wallet_id()
    testing_setupKnownTokens()
    testing_selectAllTokens()
    sync_wallet_balances(#...)
    return
