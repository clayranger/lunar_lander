#!/usr/bin/env python3
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import sessionmaker
from db_manager_v2 import engine, execute_sell_percentage_investment

# Create session
Session = sessionmaker(bind=engine)
session = Session()

result = execute_sell_percentage_investment(
    session=session,
    investment_id=1,
    target_mint="SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt",
    sell_percentage=1.0,
    slippage_bps=100,
    estimated_gas_lamports=800_000
)

print(result)

session.close()
