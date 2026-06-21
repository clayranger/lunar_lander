import os
from solana.rpc.api import Client
from functools import lru_cache
import logging

PRIMARY_RPC = os.getenv("PRIMARY_RPC_URL")
BACKUP_RPC  = os.getenv("BACKUP_RPC_URL")

@lru_cache(maxsize=1)
def get_solana_client() -> Client:
    """
    Returns a working Solana RPC client.
    Tries PRIMARY_RPC first. Falls back to BACKUP_RPC automatically on failure.
    """
    if not PRIMARY_RPC:
        logging.warning("PRIMARY_RPC_URL not set. Using BACKUP_RPC only.")
        return Client(BACKUP_RPC)

    try:
        client = Client(PRIMARY_RPC)
        # Quick health check
        client.get_health()
        logging.info(f"[RPC] Using primary: {PRIMARY_RPC.split('?')[0]}")
        return client
    except Exception as e:
        logging.warning(f"[RPC] Primary failed ({str(e)[:80]}). Switching to backup...")
        if BACKUP_RPC:
            return Client(BACKUP_RPC)
        else:
            raise RuntimeError("Both PRIMARY and BACKUP RPC URLs are unavailable") from e
