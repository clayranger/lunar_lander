import os
from dotenv import load_dotenv
from solana.rpc.api import Client
from functools import lru_cache
import logging

load_dotenv()

PRIMARY_RPC = os.getenv("PRIMARY_RPC_URL")
BACKUP_RPC  = os.getenv("BACKUP_RPC_URL")

@lru_cache(maxsize=1)
def get_solana_client() -> Client:
    """
    Returns a working Solana RPC client with automatic fallback.
    """
    if not PRIMARY_RPC:
        logging.warning("[RPC] PRIMARY_RPC_URL not set. Using BACKUP only.")
        return Client(BACKUP_RPC) if BACKUP_RPC else None

    try:
        client = Client(PRIMARY_RPC)
        # More compatible health/version check
        version = client.get_version()
        if version.value:
            logging.info(f"[RPC] Using PRIMARY: {PRIMARY_RPC.split('?')[0]}")
            return client
        else:
            raise Exception("Invalid response from primary")
    except Exception as e:
        logging.warning(f"[RPC] Primary failed: {str(e)[:120]}. Falling back to BACKUP...")
        if BACKUP_RPC:
            return Client(BACKUP_RPC)
        else:
            raise RuntimeError("Both PRIMARY and BACKUP RPCs failed") from e
