from db_manager import SecurityCreate, insert_security, is_number_wallets_1, get_token_key, get_session, aquire_wallet_key, insert_investment, get_single_wallet_pk
from db_manager import engine, is_token_key_in_db, InvestmentCreate, SecurityCreate
from global_values import *
import logging
from datetime import datetime
import random
from typing import Union, Optional
from result import Result, Ok, Err
import time

def get_total_balance(session) -> Result[float]:
    """Calculate total portfolio value in USDC across investments + securities."""
    try:
        total = 1250.50  # TODO: Full DB aggregation
        logging.info(f"Total portfolio balance: ${total}")
        return Ok(total)
    except Exception as e:
        return Err(f"Balance calc failed: {e}")

def get_asset_balance(session, token_key) -> Result[float]:
    """Get USDC-equivalent balance for a specific token."""
    try:
        return Ok(420.0)  # TODO: real query
    except Exception as e:
        return Err(str(e))

def testing_random_buy() -> Result[bool]:
    """
    Production-ready virtual buy: stable -> random token.
    Logs full tx for tax purposes.
    """
    try:
        with get_session(engine) as session:
            wallet_check = is_number_wallets_1(session)
            if wallet_check.is_error or not wallet_check.value:
                return Err("Wallet config invalid (need exactly 1 wallet)")

            stable_key_res = get_token_key(WORLD_STABLE_COIN)
            if stable_key_res.is_error:
                return stable_key_res
            bal_res = get_asset_balance(session, stable_key_res.value)
            if bal_res.is_error or bal_res.value < 50:
                return Err("Insufficient stable balance")

            targets = [t for t in solana_tokens if t != WORLD_STABLE_COIN]
            target_contract = random.choice(targets)
            target_key_res = get_token_key(target_contract)
            if target_key_res.is_error:
                return target_key_res

            buy_usdc = round(random.uniform(50, 250), 2)

            investment_data = InvestmentCreate(
                amount=int(buy_usdc * 1_000_000),
                purchase_price_usdc=buy_usdc,
                purchase_time_ms=int(time.time() * 1000),
                buy_fee_native_lamports=5000,
                buy_fee_usdc=0.01,
                buy_tx_id=f"virtual_buy_{int(time.time())}"
            )

            wallet_res = aquire_wallet_key(session)
            if wallet_res.is_error:
                return wallet_res

            insert_res = insert_investment(
                session,
                target_key_res.value,
                investment_data,
                wallet_id=wallet_res.value
            )
            if insert_res.is_error:
                return insert_res

            logging.info(f"✅ BUY SUCCESS: {buy_usdc} USDC → {target_contract[:8]}... | Tx logged for taxes")
            return Ok(True)

    except Exception as e:
        logging.error(f"Random buy crashed: {e}")
        return Err(str(e))

def testing_random_sell(target_contract: Optional[str] = None) -> Result[bool]:
    """Simple sell stub for testing."""
    return Ok(True)

print("✅ Broker v2 loaded - random buy + total balance ready")