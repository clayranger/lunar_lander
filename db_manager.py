from __future__ import annotations
# so my idea was to have all the sql in this document to promote cleanlyness, production quality, and reuse.
from typing import List
# dont think ima use ndwarray
#from numpy.typing import NDArray
import numpy as np
#for handling solana tokens
import base58
# create the sql connection
# from sqlalchemy import *
from sqlalchemy import select, func, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, types, cast
from sqlalchemy import Integer, String, exists, Column
from sqlalchemy.types import LargeBinary, Float, Boolean, BigInteger
from sqlalchemy.dialects.postgresql import UUID, BYTEA
import uuid
from sqlalchemy.orm import Mapped, mapper
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import relationship, sessionmaker
#
from sqlalchemy.orm import Session
from contextlib import contextmanager
# error shit
from result import Result, Ok, Err
import traceback
#
import time
from datetime import datetime
#
import logging
from logging import ERROR
# pydantic
from pydantic import BaseModel, Field
from typing import Optional

Base = declarative_base()


class User(Base):
    __tablename__ = "user_table"
    id = mapped_column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(LargeBinary)
    socket_sid = Column(String, unique=True)
    children : Mapped[List["Wallet"]] = relationship(back_populates="user", cascade="all,delete")
    gas_level_choice = Column(Float)
    tax_level_choice = Column(Float)
    savings_level_choice = Column(Float)
    export_delay_mins = Column(Integer)
    email = Column(String)


#Wallet contains values to represent each users cryto wallet.
#   the wallet is tied to assets. each asset has a wallet id.
#   for irl accounts the wallet it will contain real wallet info
#       it is intended for a new wallet to be created at account generation (TODO)->0.1_BETA
#   for fantasy accounts the wallet will be created still but wont have any keys
#   the wallet is to contain values for default trade settings for each user.
class Wallet(Base):
    __tablename__ = "wallet_table"
    id = mapped_column(Integer, primary_key=True)
    publicKey = Column(String)
    privateKey = Column(Integer)
    parent_id = mapped_column(ForeignKey("user_table.id"))
    dollars = Column(Float)
    dollars_counted_at_time = Column(Integer)
    ethOutputAccountPublicKey = Column(String)
    ethInputAccountPublicKey = Column(String)
    ethInputAccountPrivateKey = Column(String)
    user: Mapped["User"] = relationship(back_populates="children")
    #TODO
    #IRL
    is_irl = Column(Boolean)
    #default settings


# #a hero is a message to be pushed to users by socket connections.
# class Hero(Base):
#     id = Column(Integer, primary_key=True)
#     owner = Column(Integer, ForeignKey('user_table.id'))
#     title = Column(String)
#     message = Column(String)
#     birth = Column(DateTime)
#     ttl_hours = Column(Integer)
#     picture = Column(String)
#     link_route = Column(String)
#     link_text = Column(String)


#A token represents a coin that the application belives to exist.
class Token(Base):
    __tablename__ = "token_table"
    id = mapped_column(LargeBinary, primary_key=True)
    tickerSymbol = Column(String)
    contractAddress = Column(LargeBinary)
    name = Column(String)
    priceServer = Column(String)
    exchangeSever = Column(String)
    #This is supposedly to be depricated
    #   the new vision for price tracking
    price_tracking = Column(Boolean)
    stable_coin_official = Column(Boolean)
    stable_coin_alt = Column(Boolean)
    children : Mapped[List["SelectedToken"]] = relationship(back_populates="token", cascade="all,delete")
    decimals = Column(Integer)


#A selected token is a token selected for price calculation and ML.
#   the badly named latency value is to set if it is ML or price only (TODO)->0.1_BETA
#   if a token is not selected to by any user it is to be ignored. (TODO)->0.1_BETA
class SelectedToken(Base):
    __tablename__ = "selected_token_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("token_table.id"))
    token: Mapped["Token"] = relationship(back_populates="children")
    owner = Column(Integer, ForeignKey('user_table.id'))
    # latency is important for many things and everything falls apart if i try to depricate it.
    latency = Column(Integer)
    #add all settings
    #the illegal var is to temporarily freeze a token out for a user
    isIllegal = Column(Boolean)
    dangerLevel = Column(Float)
    character = Column(String)
######################################################################################################################
#
#
#
#!|!|!|!|!|!|!terrible bug -> WHY THE FUCK DOES ASSET NEED LAMPORTS!!!???
#
#                              DEPRICATED the amount field
#
######################################################################################################################


# an asset is just a thing in my wallet
#   the amount field is depricated. The amount is kept within investments and secuirties.
#       amount is to be replaced with: (TODO) -> change in progress for 0.1 beta
#           audited_amount (float)
#           audited_time (float)
#           jan 18 -> pulling amount feild from testing_rosebud_all_users
class Asset(Base):
    __tablename__ = "asset_table"
    id = mapped_column(Integer, primary_key=True)
    children_investment : Mapped[List["Investment"]] = relationship(back_populates="asset", cascade="all,delete")
    children_secuirty : Mapped[List["Security"]] = relationship(back_populates="asset", cascade="all,delete")
    wallet = mapped_column(ForeignKey("wallet_table.id"))
    coin = mapped_column(ForeignKey("token_table.id"))
    #amount is DEPRICATED
    #amount = Column(BigInteger)
    audited_amount_sum_lamports = Column(BigInteger)
    audited_time_unix_ms = Column(BigInteger)
    #SOL
    isNative = Column(Boolean)
    #USDC
    isOfficialStable = Column(Boolean)
    #USDT
    isAltStable = Column(Boolean)


# an investment represents an asset in wallet or portion of an asset that has been selected trading by the user/autopilot
class Investment(Base):
    __tablename__ = "investment_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("asset_table.id"))
    #parent = relationship("Asset", back_populates="children")
    asset: Mapped["Asset"] = relationship(back_populates="children_investment")
    #amount is in lamports
    amount = Column(BigInteger)
    purchase_price_usdc = Column(Float)
    sale_price_usdc = Column(Float)
    purchase_time_ms = Column(BigInteger)
    sale_time_ms = Column(BigInteger)
    buy_fee_native_lamports = Column(Integer)
    buy_fee_usdc = Column(Float)
    sell_fee_native_lamports = Column(Float)
    sell_fee_usdc = Column(Float)
    revenue_at_sale_usdc = Column(Float)
    isClosed = Column(Boolean)
    buy_tx_id = Column(String)
    sell_tx_id = Column(String)


class InvestmentCreate(BaseModel):
    """Schema for creating a new investment (buy side)."""

    # Required fields at purchase time
    # parent_id: int                          # FK to asset_table
    amount: int = Field(..., gt=0, description="Amount in lamports")
    purchase_price_usdc: float = Field(..., gt=0)
    purchase_time_ms: int
    buy_fee_native_lamports: int = Field(..., ge=0)
    buy_fee_usdc: float = Field(..., ge=0)
    buy_tx_id: str

    # Fields that can be set later (when selling)
    isClosed: bool = False
    sale_price_usdc: Optional[float] = None
    sale_time_ms: Optional[int] = None
    sell_fee_native_lamports: Optional[int] = None
    sell_fee_usdc: Optional[float] = None
    revenue_at_sale_usdc: Optional[float] = None
    sell_tx_id: Optional[str] = None

    model_config = {
        "from_attributes": True,   # Allows easy conversion from SQLAlchemy objects later
    }


# A security is in the wallet but not open for investment.
#   This could be gas, savings, taxes or just tokens that have appeared in wallet from an external source.
class Security(Base):
    __tablename__ = "security_table"
    id = mapped_column(Integer, primary_key=True)
    parent_id = mapped_column(ForeignKey("asset_table.id"))
    asset: Mapped["Asset"] = relationship(back_populates="children_secuirty")
    #amount is in lamports
    amount = Column(BigInteger)
    purchase_price_usdc = Column(Float)
    sale_price_usdc = Column(Float)
    purchase_time_ms = Column(BigInteger)
    sale_time_ms = Column(BigInteger)
    buy_fee_native_lamports = Column(Integer)
    buy_fee_usdc = Column(Float)
    sell_fee_native_lamports = Column(Float)
    sell_fee_usdc = Column(Float)
    revenue_at_sale_usdc = Column(Float)
    isClosed = Column(Boolean)
    buy_tx_id = Column(String)
    sell_tx_id = Column(String)
    isTax = Column(Boolean)
    isSavings = Column(Boolean)
    isGas = Column(Boolean)


class SecurityCreate(BaseModel):
    """Schema for creating a new security entry (gas, tax reserve, savings, or external token credit).

    Used for recording non-tradable positions like gas top-ups, tax allocations,
    and savings buckets in the DeFi wallet for accurate tax record keeping.
    """

    # Required fields at creation time
    amount: int = Field(..., gt=0, description="Amount in lamports")
    purchase_price_usdc: float = Field(..., ge=0)
    purchase_time_ms: int
    buy_fee_native_lamports: int = Field(..., ge=0)
    buy_fee_usdc: float = Field(..., ge=0)
    buy_tx_id: str

    # Classification flags - exactly one should typically be True for gas/tax/savings
    isTax: bool = False
    isSavings: bool = False
    isGas: bool = False

    # Fields that can be set later (when closing the security position)
    isClosed: bool = False
    sale_price_usdc: Optional[float] = None
    sale_time_ms: Optional[int] = None
    sell_fee_native_lamports: Optional[int] = None
    sell_fee_usdc: Optional[float] = None
    revenue_at_sale_usdc: Optional[float] = None
    sell_tx_id: Optional[str] = None

    model_config = {
        "from_attributes": True,
    }


# the intention is that once an investment/secuirty is closed it would be turned into a tax record.
#   this is not yet implemented and the vision is not yet clear.
class taxRecord(Base):
    __tablename__ = "taxRecord_table"
    id = mapped_column(Integer, primary_key=True)
    token_name = Column(String)
    token_network = Column(String)
    time_buy = Column(Integer)
    time_sell = Column(Integer)
    price_usdc_buy = Column(Float)
    price_of_usdc_at_buy = Column(Float)
    price_of_usdc_at_sell = Column(Float)
    price_usdc_sell = Column(Float)
    #price_exchange_usd_buy = Column(Float)
    #price_exchange_usd_sell = Column(Float)
    price_fee_buy_usdc = Column(Float)
    price_fee_buy_native_lamports = Column(Float)
    price_fee_sell_usdc = Column(Float)
    price_fee_sell_native_lamports = Column(Float)
    buy_tx_id = Column(String)
    sell_tx_id = Column(String)
    wallet_id = Column(String)
    user_name = Column(String)
    isTax = Column(Boolean)
    isSavings = Column(Boolean)
    isGas = Column(Boolean)
    #TODO do these come in as floats or integers?
    from_token_amount = Column(Float)
    from_token = Column(Float)
    to_token_amount = Column(Float)
    to_token = Column(String)


DATABASE_URL = "postgresql+psycopg2://mypguser:m11ay321@localhost:5432/mypgdatabase"

# Create engine with PostgreSQL-specific settings
engine = create_engine(
    DATABASE_URL,
    echo=True,  # Set to False in production
    pool_size=10,  # Connection pool size
    max_overflow=20  # Max connections beyond pool_size
)


@contextmanager
def get_session(engine):
    '''
    Testing Alpha Ready
    '''
    session = Session(engine, expire_on_commit=False)  # or your sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_asset_exists(
    session: Session,
    token_key,
    wallet_pk
) -> Result[int]:
    '''
    Returns Parent_id
    Pre Alpha -> Early Development
    '''
    # if no wallet keys are given, check if only one wallet is there and get its KeyError


    # this part is to go to ensure_asset_exists
    does_exist = session.query(session.query(Asset).filter_by(coin=cast(token_key, BYTEA)).exists()).scalar()
    if does_exist:
        print("native is here. nothing to do but get the id handle")
    #now lets insert the native asset
    else:
        asset_obj = Asset(
            wallet = wallet_pk,
            coin = cast(token_key, BYTEA),
            isNative = True,
            isOfficialStable = False,
            isAltStable = False
        )
        session.add(asset_obj)
        session.commit()
    try:
        solana_asset = session.execute(select(Asset).filter_by(coin=cast(token_key, BYTEA))).scalar_one()
    except Exception as e:
        return Err(str(e))
    return Ok(solana_asset.id)


def get_wallet_id_by_public_key(db_session: Session, public_key: str) -> int | None:
    """
    Look up a wallet by its publicKey and return the wallet's ID.

    Returns:
        The wallet ID (int) if found, otherwise None.
    """
    stmt = select(Wallet.id).where(Wallet.publicKey == public_key)
    return db_session.execute(stmt).scalar()


def insert_security(
    session: Session,
    token_key,
    security_data: SecurityCreate,
    wallet_id=None,
    wallet_public_key=None,
) -> Result[bool]:
    '''
    Early Development Stage
    Insert a new security (gas, tax, or savings allocation) using validated Pydantic data.
    Mirrors the production pattern used by insert_investment for consistent
    wallet resolution, asset handling, and tax-record-ready data flow.
    '''
    wallet_status = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_status.is_error:
        return Err(f"Wallet key error: {wallet_status.error}")
    else:
        wallet_pk = wallet_status.value

    # This should return the asset's id (parent_id)
    asset_result = ensure_asset_exists(session, token_key, wallet_pk)
    if asset_result.is_error:
        return asset_result  # propagate the failure

    parent_id = asset_result.value   # ← This is the key line for tax record linkage

    try:
        security_dict = security_data.model_dump()
        security_dict["parent_id"] = parent_id

        security = Security(**security_dict)

        session.add(security)
        session.flush()                    # or session.commit() depending on your style
        # session.refresh(security)        # uncomment if you need the generated ID back

        return Ok(True)

    except Exception as exc:
        session.rollback()
        return Err(str(exc))


def aquire_wallet_key(
    session: Session,
    wallet_id=None,
    wallet_public_key=None
) -> Result[int]:
    '''
    Pre alpha
    '''
    if wallet_id is not None:
        wallet_pk = wallet_id
    elif wallet_public_key is not None:
        wallet_pk = get_wallet_id_by_public_key(session, wallet_public_key)
    else:
        single_result = get_single_wallet_pk(session)
        wallet_pk = single_result.value if hasattr(single_result, "value") else single_result

    if not wallet_pk:
        return Err("cannot grab a wallet primary key")
    return Ok(wallet_pk)


def insert_investment(
    session: Session,
    token_key,
    investment_data: InvestmentCreate,
    wallet_id=None,
    wallet_public_key=None,
) -> Result[bool]:
    '''
    Early Development Stage
    Insert a new investment using validated Pydantic data.
    '''
    wallet_status = aquire_wallet_key(session, wallet_id, wallet_public_key)
    if wallet_status.is_error:
        return Err(f"Token key error: {wallet_status.error}")
    else:
        wallet_pk = wallet_status.value
    # This should return the asset's id (parent_id)
    asset_result = ensure_asset_exists(session, token_key, wallet_pk)
    if asset_result.is_error:
        return asset_result  # propagate the failure

    parent_id = asset_result.value   # ← This is the key line

        # then
    try:
        investment_dict = investment_data.model_dump()
        investment_dict["parent_id"] = parent_id

        investment = Investment(**investment_dict)

        session.add(investment)
        session.flush()                    # or session.commit() depending on your style
        # session.refresh(investment)      # uncomment if you need the generated ID back

        return Ok(True)

    except Exception as exc:
        session.rollback()
        return Err(str(exc))

    return Ok(False)


def get_single_wallet_pk(session) -> Result[Optional[int]]:
    '''
    Returns the primary key (id) of the Wallet if there is exactly one wallet.
    Returns None (inside Ok) if there are 0 or more than 1 wallets.
    '''
    stmt = select(Wallet.id).select_from(Wallet).limit(2)

    try:
        ids = session.scalars(stmt).all()

        if len(ids) == 1:
            return Ok(ids[0])
        else:
            return Ok(None)

    except Exception as e:
        logging.error(f"[get_single_wallet_pk] {datetime.now()}\n{traceback.format_exc()}")
        return Err(str(e))


def is_number_wallets_1(session) -> Result[bool]:
    '''
    Testing Alpha Ready
    '''
    stmt = select(func.count()).select_from(Wallet)
    #
    try:
        count = session.scalar(stmt)   # returns the integer count directly
        return Ok(True)
    except Exception as e:
        logging.error(f"[is_number_wallets_1] {datetime.now()}\n{traceback.format_exc()}")
        return Err(str(e))
    return Ok(False)


def get_token_key(given_key) -> Result[np.ndarray]:
    '''
    ALPHA
    TODO
    -> now returns a "opt" -> fix calling fns
    -> in theory ready for alpha
    '''
    try:
        if not given_key:
            raise ValueError("given_key cannot be empty or None")

        # Handle string input
        if isinstance(given_key, str):
            given_key = given_key.encode('utf-8')

        decoded = base58.b58decode(given_key)

        if len(decoded) % 4 != 0:
            raise ValueError(
                f"Decoded Base58 data length ({len(decoded)}) "
                "is not a multiple of 4"
            )

        result = np.frombuffer(decoded, dtype='<i4')
        return Ok(result)

    except Exception as e:
        logging.error(
            f"[get_token_key] {datetime.now()}\n"
            f"{traceback.format_exc()}"
        )
        return Err(str(e))


def is_token_key_in_db(session, token_key):
    '''
    TODO
    top priority
    '''
    does_exist = session.query(session.query(Token).filter_by(id=cast(token_key, BYTEA)).exists()).scalar()
    if does_exist:
        return True
    else:
        return False


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


def create_database():
    Base.metadata.create_all(engine)
    print("created")
    return


def delete_database():
    Base.metadata.drop_all(engine)
    return



def how_many_lamports_is_one(given_token_contract) -> Integer:
    '''
    Returns a "multiplier" which is 1 + the number of decimals for the token.
    0.2 PRODUCTION. Copyright 2024 - 2025 Matthew Clay. Private and confidential.
    '''
    #Rather, the number of zeros in your multiplier should match the decimals of the token.
    given_token_lamports = None
    given_token_multiplier = 1
    newNumber = base58.b58decode(given_token_contract)
    logging.debug("[how_many_lamports_is_one]:token id: " + str(given_token_contract))
    # < represents little endian
    # i represent integer
    # 4 represendts 4 byte array entries which I chose because 20/4 r=0
    numberist = np.frombuffer(newNumber, dtype='<i4')
    Session = sessionmaker(bind=engine)
    session = Session()
    does_exist = session.query(session.query(Token).filter_by(id=cast(numberist, BYTEA)).exists()).scalar()
    logging.debug("[how_many_lamports_is_one]:database query complete")
    if does_exist:
        logging.debug("[how_many_lamports_is_one]:does exist")
        currentToken = session.execute(select(Token).filter_by(id=cast(numberist, BYTEA))).scalar_one()
        given_token_lamports  = currentToken.decimals
        for i in range (given_token_lamports):
            given_token_multiplier = given_token_multiplier * 10
    else:
        #if this function fails trade will be corrupted!
        print("[how_many_lamports_is_one]:FATAL ERROR does not exist")
        logging.critical("[how_many_lamports_is_one]:FATAL ERROR does not exist. Will now RECCOMEND TO HALT TRADING!")
        #trading is now halted due to fatal error!
        mayday("[how_many_lamports_is_one]:FATAL ERROR. TOKEN does not exist. VALUES IN DATABASE LIKELY CORRUPTED!")
        return None
    session.close()
    return given_token_multiplier


def divideInvestment(investment_id, lamports_closed, sell_transaction_id, *transaction_time):
    '''
    i divide
    lots of wierd things happening here
    usually there is a free lamports left of 1
    which then gets made into anouther investment and merged by usdc investments
    this should always only run on dollar coins for as for as I know
    so we should add a test and warning to see if this happens without dollar coins ever
    thing is it doesnt actually know its daddy lol
    '''
    error = None
    free_lamports = 0
    #new investment object id ->

    logging.info("[divideInvestment]:Investment is:" + str(investment_id) + " with " + str(lamports_closed) + " and a txid of: " + sell_transaction_id +  ".")
    try:
        this_investment = session.execute(select(Investment).filter_by(id=investment_id)).scalar_one()
    except:
        error = "[divideInvestment]:ERROR A. (all errors fatal because of database corruption risk."
    else:
        free_lamports = this_investment.amount - lamports_closed
        logging.info("[divideInvestment]:Total Lamports->" + str(this_investment.amount))
        logging.info("[divideInvestment]:Free Lamports->" + str(free_lamports))
        this_thing = what_is_this_asset_by_id(this_investment.parent_id)
        if this_thing == WORLD_STABLE_COIN:
            logging.info("[divideInvestment]:Working with world stable as is expected")
        else:
            logging.critical("[divideInvestment]:Working with NOT WORLD STABLE: " + this_thing)
        if this_investment:
            logging.info("[divideInvestment]:" + str(this_investment.amount))
            ms = time.time_ns() // 1_000_000
            remaining_investment = Investment(
                parent_id = this_investment.parent_id,
                amount = free_lamports,
                isClosed = False,
                purchase_time_ms = ms,
                buy_tx_id = this_investment.buy_tx_id
            )

            try:
                session.add(remaining_investment)
                session.commit()
            except:
                error = "[divideInvestment]:ERROR I. (all errors fatal because of database corruption risk."
            else:
                logging.info("[divideInvestment]:partitioning and closing")
                u_stmt = update(Investment).where(Investment.id == investment_id).values(sell_tx_id=sell_transaction_id)
                if session.execute(u_stmt):
                    try:
                        session.commit()
                    except:
                        error = "[divideInvestment]:ERROR G. (all errors fatal because of database corruption risk."
                    else:
                        logging.info("[divideInvestment]:change statement executed.")
                        logging.info("[divideInvestment]:closing investment")
                        c_stmt = update(Investment).where(Investment.id == investment_id).values(isClosed=True)
                        if session.execute(c_stmt):
                            try:
                                session.commit()
                            except:
                                error = "[divideInvestment]:ERROR H. (all errors fatal because of database corruption risk."
                            else:
                                logging.info("[divideInvestment]:closed")
                                l_stmt = update(Investment).where(Investment.id == investment_id).values(amount=lamports_closed)
                                if session.execute(l_stmt):
                                    try:
                                        session.commit()
                                    except:
                                        error = "[divideInvestment]:ERROR F. (all errors fatal because of database corruption risk."
                                    else:
                                        logging.info("[divideInvestment]:finished with databased")
                                else:
                                    error = "[divideInvestment]:ERROR B. (all errors fatal because of database corruption risk."
                        else:
                            error = "[divideInvestment]:ERROR C. (all errors fatal because of database corruption risk."
                else:
                    error = "[divideInvestment]:ERROR D. (all errors fatal because of database corruption risk."
        else:
            error = "[divideInvestment]:ERROR E. (all errors fatal because of database corruption risk."
    if error:
        mayday(error)
        return -1
    else:
        return 0



def closeInvestment(investment_id, given_lamports, transaction_id, *transaction_time):
    '''
    depricate given lamports??? otherwise production quality.
    doesnt actually do anything with given lamports but if it is zero it was supposed to symbolize to a fn above what was happening.
    0.1 DEVELOPMENT
    Copyright 2024 - 2025. Matthew Clay. Private and confidential.
    '''
    error = None
    #first i do a query with my investment id
    #then i modify the fields c
    stmt = select(Investment).where(Investment.id == investment_id)
    #stmt = select(Token).where(Token.id == cast(from_token_solana_number, BYTEA))
    if session.execute(stmt):
        session.commit()
        logging.info("[closeInvestment]:calling database to close investment id -->" +str(investment_id))
        u_stmt = update(Investment).where(Investment.id == investment_id).values(sell_tx_id=transaction_id)
        if session.execute(u_stmt):
            session.commit()
            logging.debug("[closeInvestment]:database change statement executed.")
            c_stmt = update(Investment).where(Investment.id == investment_id).values(isClosed=True)
            session.commit()
            if session.execute(c_stmt):
                session.commit()
                logging.info("[closeInvestment]:closed investment id -->" +str(investment_id))
            else:
                error = "[closeInvestment]:ERROR A"
        else:
            error = "[closeInvestment]:ERROR B"
    else:
        error = "[closeInvestment]:ERROR C"
    #all errors are fatal. if there is an error the database is possibly corrupted.
    if error:
        logging.critical(error)
        mayday(error)
        return -1
    else:
        tax_filer(investment_id)
        return 0


def divideInvestmentsAndClose(investment_id, lamports_closed, transaction_id, *transaction_time):
    '''
    chop an investment up. close the part that has been sold. write tx_id is closed section.
    privateInvestor may want to divide investments before trade so that they can be traded to different things.
    '''
    print("[divideInvestmentsAndClose]: Good day.")
    print("[divideInvestmentsAndClose]:Investment is:" + str(investment_id) + " with " + str(lamports_closed) + " and a txid of: " + transaction_id +  ".")
    good = divideInvestment(investment_id, lamports_closed, transaction_id)
    if good:
        closeInvestment(investment_id, lamports_closed, transaction_id)
    return 1

def tradeTerminal(given_token_contract, given_lamports, given_target_contract):
    '''
    -> 0.2 Production asap
    ->clean commented code
    ->beautiful logging
    ->error returns

    executes the given trade
    I call trade terminal with the setoshis I want to sell, the target currency
    trade terminal returns a dictionary with explicit details of the transaction, including an id
    '''
    #i need a real as mechanism to make sure transactions are settled before they are sold or maybe even created and that can take 20 seconds
    tx_id = str(uuid.uuid4())
    return_dictionary = {}
    my_lamports = 0
    #if im expected to buy a tax I actually probs am just moving to dollars but its probs already dollars so i just
    #   call tax_payer
    #first I have to gather and split investment objects to prepare for trade
    #and as i trade
    #for example, if i have made a sale and i have to put some aside for taxes I will do that then make it right in the objects
    #then, when we get back to buying i will have to rescale the dataframe for the money i have leftover
    print("[trade terminal]: Good day. " + given_token_contract + "---->----->" + str(given_lamports) + " lamports to " + "---->----->" + str(given_target_contract))
    logging.info("[trade terminal]: Good day. " + given_token_contract + "---->----->" + str(given_lamports) + " lamports to " + "---->----->" + str(given_target_contract))

    investment_token_multipler = how_many_lamports_is_one(given_token_contract)
    target_token_multipler = how_many_lamports_is_one(given_target_contract)
    #target_token_qty = _ / target_token_multipler
    invs_units_qty = float(given_lamports) / float(investment_token_multipler)
    investment_dollar_potential = float(how_much_are_these_tokens_worth(given_token_contract, invs_units_qty))
    new_price = float(how_much_is_this_can_i_get(given_target_contract))
    new_qty = float(investment_dollar_potential) / float(new_price)

    my_lamports = float(new_qty) * float(target_token_multipler) * float(WORLD_TRADE_FEE)
    print("[tradeTerminal]->new price->" + str(new_price) + " new qty " + str(new_qty) + " lamports " + str(my_lamports))
    return_dictionary["tx-id"] = tx_id
    return_dictionary["lamports"] = int(my_lamports)
    print(return_dictionary)
    logging.info("[tradeTerminal]->new price->" + str(new_price) + " new qty " + str(new_qty) + " lamports " + str(my_lamports))
    logging.info(return_dictionary)
    return (True, return_dictionary)


def tax_filer(given_investment_id):
    '''
    VISIONARY:
        saves tax record in postgres database ->taxes owed in closed investment and taxes paid
        exports transaction data to quest for backup and juptyr
        owed taxes is cached for player_boy to pay them
    '''
    stmt = select(Investment).where(Investment.id == int(given_investment_id))
    ######################################################################################################################
    #
    #
    # maybe problem is due to wallets with assets scaling
    #REALLY BAD BUT IMA SET IT TO GRAB VALUE AT THIS MOMENT IT SHOULD BE SENT FROM TRADE TERMINAL
    #
    #
    #
    ######################################################################################################################
    result_dict = {}
    try:
        result = session.execute(stmt).one()
    except:
        logging.critical("[tax_filer]: database error")
    else:
        result_dict["profit"] =0.0
        result_dict["z_gain_loss_percent"] = 0.0
        logging.info("[tax_filer]: Filing taxes for investment: " + str(given_investment_id))
        result_dict["this_asset"] = what_is_this_asset_by_id(result[0].parent_id)
        result_dict["this_token"] = what_is_this_token_name_by_contract_string(result_dict["this_asset"])
        result_dict["lamports"] = result[0].amount
        result_dict["this_dollars"] = how_much_are_these_lamports_worth(result_dict["this_asset"], result[0].amount)
        try:
            purchase_price = float(result[0].purchase_price_usdc)
        except:
            logging.critical("[tax_filer]: purchase price zero??")
            purchase_price = None
        else:
            try:
                profit = float(result_dict["this_dollars"]) - float(purchase_price)
                changed = (Decimal(profit) / Decimal(purchase_price)) * 100
            except:
                changed = None
                profit = None
                logging.critical("[tax_filer]: purchase price zero")
            else:
                result_dict["profit"] =profit
                result_dict["z_gain_loss_percent"] = changed
        myTitle = "SOLD TOKEN: " + str(result_dict["this_token"])
        myText = "profit " + str(result_dict["profit"]) + " gain percent"+ str(result_dict["z_gain_loss_percent"])
        current_user = session.get('user_id')
        current_sid = session.get('socket_id')
        makeHero(current_sid, current_user, myTitle, myText, "link", "image", 10, "view record", "www.google.com")
        logging.info(result_dict)
    return 1


def mergeUSDCInvestments():
    '''I can only imagine investments being merged in stablecoins.
    For tax reasons investments could never be merged otherwise.'''
    from_token_solana_number = base58.b58decode(WORLD_STABLE_COIN)
    my_asset = session.execute(select(Asset).filter_by(coin=cast(from_token_solana_number, BYTEA))).scalar_one()
    my_amount = 0
    my_parent_id = 0
    investment_id_list = []
    investment_counter = 0
    logging.debug("[mergeUSDCInvestments]:my asset " + str(my_asset))
    my_parent_id = my_asset.id
    #we want investments that are children of the asset that we are after
    my_investments = my_asset.children_investment
    for entry in my_investments:
        if entry.isClosed is not True:
            investment_counter += 1

            logging.debug("[mergeUSDCInvestments]:dollar investment asset:" + str(entry.parent_id) + " investment amount " + str(entry.amount))
            my_amount += entry.amount
            investment_id_list.append(entry.id)
            #my_parent_id = entry.parent_i

            #we add up all the data from all the investments
            #we make a list of investment ids
            #we make the new investment
            #we close all the investment ids
    if investment_counter > 1:
        logging.debug("[mergeUSDCInvestments]:total size for new investment:" + str(my_amount))
        ms = time.time_ns() // 1_000_000
        new_investment = Investment(
            parent_id = my_parent_id,
            amount = my_amount,
            isClosed = False,
            purchase_time_ms = ms,
            buy_tx_id = "merged"
        )
        session.add(new_investment)
        session.commit()
        for thing in investment_id_list:
            c_stmt = update(Investment).where(Investment.id == thing).values(isClosed=True)
            if session.execute(c_stmt):
                ######################################################################################################################
                #!|!|!|!|!|!|!maybe write more precise data to the closed dollar investment like "merged in the sell_tx_id           #
                ######################################################################################################################
                logging.debug("[mergeUSDCInvestments]:closed id: " + str(thing))
                session.commit()
    else:
        logging.debug("[mergeUSDCInvestments]:There is one USDC investment or less. Returning with no database commit")
    return 1


def createInvestment(given_token, given_lamports, transaction_id, *transaction_time):
    '''
    make new investment in postgres
    0.2 ALPHA. Copyright 2020-2025 Matthew Clay. Private and confidential.
    '''
    error = None
    logging.info("[createInvestment 2.0]:new investment is:" + given_token + " with " + str(given_lamports) + " and a txid of: " + transaction_id +  ".")
    from_token_solana_number = base58.b58decode(given_token)
    stmt = select(Asset).where(Asset.coin == cast(from_token_solana_number, BYTEA))
    ######################################################################################################################
    #
    #
    # maybe problem is due to wallets with assets scaling
    #REALLY BAD BUT IMA SET IT TO GRAB VALUE AT THIS MOMENT IT SHOULD BE SENT FROM TRADE TERMINAL
    #
    #
    #
    ######################################################################################################################
    while True:
        result = session.execute(stmt).all()
        if len(result) > 1:
            logging.critical("[createInvestment]:!!!FATAL ERROR!!!: multiple entries for the same investment.")
            error = ("why the fuck are there two of the same asset!")
        if len(result) == 0:
            #create an asset
            #can i add an if or a try catch stastement or whatever
            logging.critical("[createInvestment]:creating asset")
            create_asset(given_token)
            continue
        elif len(result) == 1:
            #create an investment
            ms = time.time_ns() // 1_000_000
            my_id = result[0][0].id
            this_asset = what_is_this_asset_by_id(my_id)
            value = how_much_are_these_lamports_worth(this_asset, given_lamports)
            new_investment = Investment(
                parent_id = my_id,
                amount = given_lamports,
                isClosed = False,
                purchase_time_ms = ms,
                buy_tx_id = transaction_id,
                purchase_price_usdc = float(value)
            )
            try:
                session.add(new_investment)
                session.commit()
            except:
                error = "database failure"
                logging.critical("[createInvestment]:!!!FATAL ERROR!!!: DATABASE FAILURE.")
                break
            else:
                logging.info("[create investment]:-->new investment created->asset id-->" + str(my_id))
        else:
            #too many results HALT everything
            logging.critical("[createInvestment]:!!!FATAL ERROR!!!: multiple entries for the same investment.")
            error = ("why the fuck are there two of the same asset!")
        break
    if error is not None:
        mayday(error)
        return error
    else:
        return 0


def privateUSDBanker(from_token, to_token, to_qty, *investment_list):
    '''
        THIS IS DISGUSTING -> must depricate replace.
        handles the paperwork around investment objects needed to commit a trade
        calls tradeTerminal to commit to the trade and if sucsessful edits objects
        not sure yet about an optional argument of released investment ojects????
    '''
    verbose = True
    #total lamports avaliable for the investment we will be liquidating
    investment_lamports_total = 0
    #total dollars avaliable for the investment we will be liquidating
    investment_dollar_potential = 0.0
    #how much we commit to trade
    investment_lamports_selection = 0
    # list of touples containing investment ids and amounts
    investment_objects_list = []
    #unknown use DEPRICATED?
    asset_name_list = []
    #this fn is to be applied to a dataframe (but why)
    def make_list_of_investment_objs(passed_row):
        global investment_lamports_total
        investment_objects_list.append((passed_row["id"], passed_row["amount"]))

    new_investment_object_id = 1
    if verbose:
        #print("[privateBanker()] from[:]" + from_token + "->to->" + to_token + "->$:" + str(to_qty))
        pass
    if investment_list:
        print("there is an investment list I will attempt to trade using the lsit")
        print("WARNING: code has not beeen written for this feature! Shit will go wrong.")
        if not from_token:
            print("from token is none")
            print("my investment list thing to pull from is")
            my_loc = int(investment_list[0][0])
            print(investment_list[0][0])
            my_investy = session.execute(select(Investment).filter_by(id=my_loc)).scalar_one()
            my_lamports = my_investy.amount

            my_parent_id = my_investy.parent_id
            my_asset = session.execute(select(Asset).filter_by(id=my_parent_id)).scalar_one()
            my_coin = my_asset.coin
            my_string_name = base58.b58encode(my_coin).decode('utf8')
            from_token = my_string_name
            investment_objects_list.append((my_loc, my_lamports))
            investment_token_multipler = how_many_lamports_is_one(from_token)
            to_qty = how_much_are_these_lamports_worth(from_token, my_lamports)
    else:
        from_token_solana_number = base58.b58decode(from_token)
        print("there is not an investment list. i must gather investment objects")
        ######################################################################################################################
        #!|!|!|!|!|!|!NEW PLAN -> move gathering of investments into a new function                                          #
        ######################################################################################################################

        #this code is to test new syntax for sqlalchemy
        #stmt = select(Asset.coin).select_from(Investment).join(Asset.children_investment).filter(Asset.coin == cast(from_token_solana_number, BYTEA))
        #
        stmt = select(Asset).where(Asset.coin == cast(from_token_solana_number, BYTEA))
        #stmt = select(Token).where(Token.id == cast(from_token_solana_number, BYTEA))
        for row in session.execute(stmt):
            print("here is a thing")
            print(row)
        ######################################################################################################################
        #!|!|!|!|!|!|!try catch statements needed                                                                            #
        ######################################################################################################################
        #i want to grab the asset of our target token. an asset is a real thing in the wallet. we need to know what it is even.
        my_asset = session.execute(select(Asset).filter_by(coin=cast(from_token_solana_number, BYTEA))).scalar_one()
        if verbose:
            print("my asset")
            print(my_asset)
        #we want investments that are children of the asset that we are after
        my_investments = my_asset.children_investment
        #i will build a dataframe of my target investments
        investment_objects = pd.DataFrame(columns=['id', 'amount', 'purchase_time'])
        for a_investment in my_investments:
            a_inv_dict = {}
            #closed investments don't exist. move on.
            if a_investment.isClosed:
                continue
            if verbose:
                print("i have found a qualified investment")
                print(str(a_investment.amount))
            a_inv_dict["id"] = a_investment.id
            a_inv_dict["amount"] = a_investment.amount
            a_inv_dict["purchase_time"]= a_investment.purchase_time_ms
            investment_objects = investment_objects._append(a_inv_dict, ignore_index=True)
        #I must know if I am partitioning my investment or if I am using the whole thing or almost the whole thing.
        ######################################################################################################################
        #!|!|!|!|!|!|!if i automatically round up wont i shove off my taxes? maybe buy in order of size? so i do that?       #
        ######################################################################################################################


        #so i will have to compare my target qty to my oldest investment qty
        #if they are within a certain percent I grab the entire investment and be happy
        #else I have to gather/split investments (only allowed for dollar coin)
        #i make a dataframe
        if verbose:
            print("here are my investment objects")
            print(investment_objects)
        investment_count = 0
        investment_token_stablecoin_value = 0.0
        target_change_percent = 0.0
        #target_token_stablecoin_value = how_much_are_these_tokens_worth(to_token)
        investment_token_multipler = how_many_lamports_is_one(from_token)
        #does this do anything or even make sense? DEPRICATED?
        target_token_multiplier = how_many_lamports_is_one(from_token)
        #I make a list of investment objects. I use this for the coming if/elif
        investment_objects.apply(make_list_of_investment_objs, axis=1)

    print("here is the investment objects list")
    #(investment_id, lamports)
    print(investment_objects_list)
    if investment_list:
        print("here is the ur objects list")
        print(investment_list)


    for an_object in investment_objects_list:
        investment_lamports_total += int(an_object[1])
    investment_count = len(investment_objects_list)
    #if the investment count is less than 1 the trade cannot continue
    ######################################################################################################################
    #!|!|!|!|!|!|!need error control                                                                                     #
    ######################################################################################################################
    #lets implement an error system
    if investment_count < 1:
        print("investment count is less than one")
        raise Exception("investment count is less than one. This should never happen.")
    elif investment_count == 1:
        if verbose:
            print("investment count is one")
            print("investment lamports total is : " + str(investment_lamports_total))
            print("investment multiplier is : " + str(investment_token_multipler))
        #I seek to know how many dollars are avaliable for my investment
        invs_units_qty = investment_lamports_total / investment_token_multipler
        investment_dollar_potential = how_much_are_these_tokens_worth(from_token, invs_units_qty)
        #I want to know the difference in percent of my investment and my target token
        #change_percent = ((float(investment_dollar_potential))/float(to_qty))*float(100)
        #change_percent = ((float(to_qty))/float(investment_dollar_potential))*float(100)
        if to_qty < 0:
            to_qty = to_qty * -1
    ######################################################################################################################
    #!|!|!|!|!|!|!MAJOR BUG=> need divide by zero protection                                                             #
    ######################################################################################################################
        change_percent = 0.0
        if investment_dollar_potential <= 0.000:
            pass
        else:
            change_percent = ((float(to_qty))/float(investment_dollar_potential))


        if verbose:
            print("investment dollar potential is")
            print(investment_dollar_potential)
            print("change qty")

            print(to_qty)

            print("change percent")
            print(change_percent)
        #not enough space in my investment for the dollar demand
        if investment_dollar_potential < to_qty:
            print("purchase is being shrunk. dollar potential is too small.")
            #I now check for how close?
            investment_lamports_selection = investment_lamports_total
        elif investment_dollar_potential >= to_qty:
            print("purchase will not be shrunk. it may be enlarged.")
            #I now check for how close
            #if it is close i take it all
            #here I have to figure out how much lamport I need from my investment to reach my dollar target
            #then I save that as lamports selection
            change_diff = 100.0-change_percent
            change_diff = change_percent
            print("change diff is ->" + str(change_diff))
            #when i want .93 i have 7
            if 0 - change_diff < .1:
                investment_lamports_selection = int(investment_lamports_total)
            investment_lamports_selection = int(investment_lamports_total * change_diff)


    #         if change_diff < .1:

    #         else:
    # ######################################################################################################################
    # #!|!|!|!|!|!|!if i automatically round up wont i shove off my taxes? maybe buy in order of size? so i do that?       #
    # ######################################################################################################################
    #             print("im taking it all")
    #             investment_lamports_selection = investment_lamports_total

    elif investment_count > 1:
        #plan:
        #take everything from each investment in order until we have enough
        #if we have taken everything close
        #if not divide
        #pass list to trade terminal?
        #this has (id=int, lamports_to_split=int)
        qualified_investment_object_list = []
        #if i magically finished by the numbers being perfect
        if investment_lamports_total == investment_lamports_selection:
            print("exiting loop cause lamports gathered and wanted are the same")
        print("investment count is greater than one. This is a precarious situation. I print the investments:")
        print(investment_objects_list)
        for an_obj in investment_objects_list:
            investment_lamports_total = int(an_obj[1])
            if verbose:
                print("investment count is many")
                print("investment lamports total is : " + str(investment_lamports_total))
                print("investment multiplier is : " + str(investment_token_multipler))
            #I seek to know how many dollars are avaliable for my investment
            invs_units_qty = investment_lamports_total / investment_token_multipler
            investment_dollar_potential = how_much_are_these_tokens_worth(from_token, invs_units_qty)
            #I want to know the difference in percent of my investment and my target token
            #change_percent = ((float(investment_dollar_potential))/float(to_qty))*float(100)
            #change_percent = ((float(to_qty))/float(investment_dollar_potential))*float(100)
            if to_qty < 0:
                to_qty = to_qty * -1
            change_percent = 0.0
            if investment_dollar_potential <= 0.000:
                pass
            else:
                change_percent = ((float(to_qty))/float(investment_dollar_potential))
            if verbose:
                print("investment dollar potential is")
                print(investment_dollar_potential)
                print("change qty")
                print(to_qty)
                print("change percent")
                print(change_percent)
            #not enough space in my investment for the dollar demand
            if investment_dollar_potential <= to_qty:
                print("maybe i need to grab more investment pieces. dollar potential is too small.")
                #I now check for how close?
                investment_lamports_selection += investment_lamports_total
                qualified_investment_object_list.append((an_obj[0], 0))
            elif investment_dollar_potential > to_qty:
                print("purchase will not be shrunk. it may be enlarged.")
                #I now check for how close
                #if it is close i take it all
                #here I have to figure out how much lamport I need from my investment to reach my dollar target
                #then I save that as lamports selection
                change_diff = 100.0-change_percent
                change_diff = change_percent
                print("change diff is ->" + str(change_diff))
                #when i want .93 i have 7
                lamports_im_taking_now = int(investment_lamports_total * change_diff)
                investment_lamports_selection += lamports_im_taking_now
                qualified_investment_object_list.append((an_obj[0], lamports_im_taking_now))
        print("here is the qualified object list that has been gathered")
        print(qualified_investment_object_list)
        #raise Exception("investment count is greater than one. This should never happen unless we have dollar coins")
        #check if dollar coins
        #call investment merging fn
        #because this is the usdc version we know? the invetment is probs from dollars and be combined
        #if its not it may have to be sold which is super complex
        #here is the plan
        #I look thru the investments and see if they have enough lamports by themselves
        #if they do i split that investment
        #if money is needed from more than 1 investment I close one and pull from anouther
        #I could close all the investments if i need to
    #i order the dataframe by age
    #i apply a magical function to the rows, it decides which row to split or what to do by setting flags
    #the flags are in hand on and how the split would be done is calculated, a list of investments to liquidate is on hand
    #i calculate the total setoshis for all the investment objects and call trade terminal

    #2.0 work
    #we need:
    #from_token, lamports, to_token, investment_objects_list with single item ?investment id?
    #investment_object_id = investment_objects_list[0][0]
    #investment_lamports_selection?
    #investment_lamports_total
    #investment_count = 1



    print("total lamports has been calculated : " + str(investment_lamports_selection))
    #maybe if invesment is a tax i call tax payer instead, and then clean up the objects seperatingly
    good = tradeTerminal(from_token, investment_lamports_selection, to_token)
    if good[0]:
        returned_trade_data = good[1]
        print("i must now do shit to the actual investment objects")
        #split the investment objects
        #we need to grab the investment object id from investment_objects
        #then I can call devide and close
        print("this is the investment objects list (will crash if more than 1")
        print(investment_objects_list)
    ######################################################################################################################
    #!|!|!|!|!|!|!change this to close all the investments that i listed                                              #
    ######################################################################################################################
        print("preparing to divide/close")
        print("lamports target -> " + str(investment_lamports_selection))
        print("investment_lamports_total -> " + str(investment_lamports_total))
        if investment_count == 1:
            investment_object_id = investment_objects_list[0][0]
            if investment_lamports_selection < investment_lamports_total:
                divideInvestmentsAndClose(investment_object_id, investment_lamports_selection, returned_trade_data["tx-id"])
            else: #all was traded
                print("closing investment directionly because everything was taken")
                closeInvestment(investment_object_id, investment_lamports_selection, returned_trade_data["tx-id"], (time.time_ns() // 1_000_000))
        elif investment_count > 1:
            print("operating on qualified investment object list {experimental}")
            for u in qualified_investment_object_list:
                if u[1] == 0:
                    #we will close the investment
                    closeInvestment(u[0], 0, returned_trade_data["tx-id"], (time.time_ns() // 1_000_000))
                else:
                    #we devicde and close
                    divideInvestmentsAndClose(u[0], u[1], returned_trade_data["tx-id"])
                print(u)
        ##I must make a new investment
        createInvestment(to_token, returned_trade_data["lamports"],  returned_trade_data["tx-id"])
        #close
    else:
        print("trade action failure")
    #I now operate on the flags and finalize the investment objects
    #-> lets have this run by mission control later and not in the middle of a trade I call tax collector to write records/bills
    #I return the object id of the new created investment object
    mergeUSDCInvestments()
    refresh_portfolio_cache()
    return new_investment_object_id

def privateInvestmentBanker(given_investment_id, to_token):
    '''
    0.2 -> PRODUCTION
    ->clean logging
    ->code review
    ->error system
    ->nice comments

    want to work in a more modular and understandable fashion that privateUSDBanker
    I will take an investment id and trade it to the target token.
    A wrapper could be made to do things like locate ids, and gather investments like privateUSDBanker does
    '''
    verbose = True
    if verbose:
        print("[privateInvestmentBanker()]")
    new_investment_object_id = None
    from_token = None
    investment_lamports_total = None
    #investment_objects_list.append((passed_row["id"], passed_row["amount"]))
    #amount appears to be lamports
    investment_objects_list = []
    #counter for num of investments
    a_counter = 0
    error = None
    #lets grab a investment from database
    try:
        stmt = select(Investment).where(Investment.id == given_investment_id)
        result = session.execute(stmt).all()
    except:
        error = "[privateInvestmentBanker]:Database failure."
        result = None
    else:
        logging.debug("[privateInvestmentBanker()]: database good. proceeding to sale")
        #logging.debug("error is")
        #print(error)
        #print("result is")
        #print(result[0][0].amount)
        #print("result len")
        #print(len(result))
        if len(result) == 1:
            logging.debug("[privateInvestmentBanker]: here is a lamports total")
            investment_lamports_total = result[0][0].amount
            if result[0][0].isClosed == True:
                error = "[privateInvestmentBanker]:FATAL ERROR. investment is closed."
                logging.critical("[privateInvestmentBanker]:FATAL ERROR. investment is closed.")
                mayday(error)
            else:
                logging.debug(investment_lamports_total)
                my_asset_id = result[0][0].parent_id
                from_token = what_is_this_asset_by_id(my_asset_id)
                investment_objects_list.append((given_investment_id , investment_lamports_total))
        else:
            error = "[privateInvestmentBanker]:two investments when I can only operate on one."
    if error is None:
        logging.debug("[privateInvestmentBanker]:proceeding to sale")
        logging.debug("[privateInvestmentBanker]:total lamports has been calculated : " + str(investment_lamports_total))
        #maybe if invesment is a tax i call tax payer instead, and then clean up the objects seperatingly
        good = tradeTerminal(from_token, investment_lamports_total, to_token)
        if good[0]:
            ###################################################################
            #terrible bug:
            # make sure to check that everything is good in returned trade data
            #or abort trade
            #and check for slippage
            #document and log trade stats and slippage
            ####################################################################
            returned_trade_data = good[1]
            #{'tx-id': '12d4e1d4-c248-460a-98fc-263f13103a4d', 'lamports': 152804668422270}
            print("[privateInvestmentBanker]:here is my returned trade data")
            print(returned_trade_data)
            print("[privateInvestmentBanker]:i must now do shit to the actual investment objects")
            #split the investment objects
            #we need to grab the investment object id from investment_objects
            #then I can call devide and close
            print("[privateInvestmentBanker]:this is the investment objects list (will crash if more than 1")
            print(investment_objects_list)
        ######################################################################################################################
        #!|!|!|!|!|!|!change this to close all the investments that i listed                                              #
        ######################################################################################################################
            print("[privateInvestmentBanker]:preparing to divide/close")
            print("[privateInvestmentBanker]:lamports target -> " + str(investment_lamports_total))
            print("[privateInvestmentBanker]:investment_lamports_total -> " + str(investment_lamports_total))
            #investment count is always one now

            investment_object_id = investment_objects_list[0][0]

            print("[privateInvestmentBanker]:closing investment directionly because everything was taken")
            closeInvestment(investment_object_id, investment_lamports_total, returned_trade_data["tx-id"], (time.time_ns() // 1_000_000))

            ##I must make a new investment
            createInvestment(to_token, returned_trade_data["lamports"],  returned_trade_data["tx-id"])
            #close
        else:
            print("[privateInvestmentBanker]:trade action failure")
            logging.critical("[privateInvestmentBanker]:trade action failure")
        #I now operate on the flags and finalize the investment objects
        #-> lets have this run by mission control later and not in the middle of a trade I call tax collector to write records/bills
        #I return the object id of the new created investment object
        mergeUSDCInvestments()
        refresh_portfolio_cache()
        return new_investment_object_id
    else:
        print(error)
        logging.critical(error)
        mayday(error)
        return -1
