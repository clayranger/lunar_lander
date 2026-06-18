"""
gas_trade_examples.py
Helper examples for gas security handling + full trade flow.
Copy cells into your notebook as needed.
"""

from db_manager_v2 import (
    engine, get_session,
    get_available_gas_lamports,
    ensure_sufficient_gas,
    get_oldest_gas_security,
    spend_gas_security,
    execute_trade_with_gas,
)
from global_values import WORLD_STABLE_COIN


def example_check_gas(wallet_pk: int = 1):
    """Cell: Check how much gas (SOL) security is available."""
    with get_session(engine) as session:
        res = get_available_gas_lamports(session, wallet_pk)
        if res.is_ok:
            print(f"Available gas: {res.value / 1_000_000_000:.6f} SOL ({res.value} lamports)")
        else:
            print("Error:", res.error)
        return res


def example_gas_guard(required_lamports: int = 5_000_000, wallet_pk: int = 1):
    """Cell: Pre-trade check - do we have enough gas?"""
    with get_session(engine) as session:
        check = ensure_sufficient_gas(session, required_lamports, wallet_pk)
        if check.is_error:
            print("❌ Not enough gas:", check.error)
        else:
            print("✅ Sufficient gas for trade")
        return check


def example_full_trade_with_auto_gas(
    investment_id: int,
    jupiter_client,
    target_mint: str = "So11111111111111111111111111111111111111112",
    estimated_gas: int = 5_000_000,
    wallet_pk: int = 1,
):
    """
    Cell: Full trade example.
    - Checks gas
    - Auto-picks oldest gas security
    - Calls Jupiter (real quote + swap via your client)
    - Records partial sell
    - Spends gas
    """
    with get_session(engine) as session:
        result = execute_trade_with_gas(
            session=session,
            investment_id=investment_id,
            jupiter_client=jupiter_client,
            target_mint=target_mint,
            estimated_gas_lamports=estimated_gas,
            wallet_pk=wallet_pk,
            # gas_security_id=None  → will auto-pick oldest
        )
        print(result)
        return result


if __name__ == "__main__":
    print("Gas trade examples loaded. Use the functions above in your notebook.")