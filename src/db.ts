import { Database } from 'bun:sqlite';

const db = new Database('./database/trading.db');

// Enable foreign key enforcement (must be done per connection)
db.run('PRAGMA foreign_keys = ON');

// Create tables if they don't exist
db.run(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,
    password TEXT,
    email TEXT UNIQUE,
    gas_level_choice REAL DEFAULT 0.05,
    tax_level_choice REAL DEFAULT 0.30,
    savings_level_choice REAL DEFAULT 0.10,
    autopilot_on INTEGER DEFAULT 0,
    created_at_ms INTEGER,
    updated_at_ms INTEGER
  )
`);


// To be Depricated
db.run(`
  CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,       -- 'buy' or 'sell'
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    total REAL NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  )
`);



// 2. Tokens
db.run(`
  CREATE TABLE IF NOT EXISTS token_table (
    id INTEGER PRIMARY KEY,
    mint TEXT UNIQUE NOT NULL,
    ticker_symbol TEXT,
    name TEXT,
    decimals INTEGER,
    price_server TEXT,
    exchange_server TEXT,
    price_tracking INTEGER DEFAULT 1,  -- boolean
    stable_coin_official INTEGER DEFAULT 0,
    stable_coin_alt INTEGER DEFAULT 0,
    created_at_ms INTEGER,
    updated_at_ms INTEGER
  )
`);

// 3. Wallets (references users)
db.run(`
  CREATE TABLE IF NOT EXISTS wallet_table (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    public_key TEXT UNIQUE NOT NULL,
    private_key BLOB,                  -- may be encrypted, use BLOB
    is_irl INTEGER DEFAULT 0,
    dollars REAL,
    dollars_counted_at_time INTEGER,
    eth_output_account_pubkey TEXT,
    eth_input_account_pubkey TEXT,
    eth_input_account_privkey TEXT,    -- consider encryption
    created_at_ms INTEGER,
    updated_at_ms INTEGER
  )
`);
// Index on wallet_table.user_id (matching Kotlin index)
db.run(`
  CREATE INDEX idx_wallet_user ON wallet_table(user_id);
`);
// 4. WalletTokens (references wallets and tokens)
db.run(`
  CREATE TABLE IF NOT EXISTS wallet_token_table (
    id INTEGER PRIMARY KEY,
    wallet_id INTEGER NOT NULL REFERENCES wallet_table(id) ON DELETE CASCADE,
    token_mint TEXT NOT NULL REFERENCES token_table(mint) ON DELETE CASCADE,
    audited_amount_lamports INTEGER DEFAULT 0,
    audited_time_ms INTEGER,
    ata_exists INTEGER DEFAULT 0,
    rent_paid INTEGER DEFAULT 0,
    ata_created_time_ms INTEGER,
    last_balance_change_ms INTEGER,
    last_sync_ms INTEGER,
    is_native INTEGER DEFAULT 0,
    is_official_stable INTEGER DEFAULT 0,
    is_alt_stable INTEGER DEFAULT 0,
    UNIQUE(wallet_id, token_mint)      -- composite unique key
  )
`);



// Indexes
db.run(`
  CREATE INDEX idx_wallet_token_wallet ON wallet_token_table(wallet_id)
`);
db.run(`
  CREATE INDEX idx_wallet_token_mint ON wallet_token_table(token_mint)
`);

// 5. UserTokenSettings (references users and tokens)
db.run(`
    CREATE TABLE IF NOT EXISTS user_token_settings (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_mint TEXT NOT NULL REFERENCES token_table(mint) ON DELETE CASCADE,
    purchase_blocked INTEGER DEFAULT 0,
    ignored INTEGER DEFAULT 0,
    favorite INTEGER DEFAULT 0,
    auto_trade INTEGER DEFAULT 1,
    auto_sell INTEGER DEFAULT 1,
    custom_slippage_bps INTEGER,
    max_position_usdc REAL,
    notes TEXT,
    UNIQUE(user_id, token_mint)
    )
`);


// Indexes
db.run(`
  CREATE INDEX idx_settings_user ON user_token_settings(user_id)
`);
db.run(`
  CREATE INDEX idx_settings_token ON user_token_settings(token_mint);
`);
// 6. Positions (references wallet_token_table)
db.run(`
  CREATE TABLE IF NOT EXISTS position_table (
    id INTEGER PRIMARY KEY,
    wallet_token_id INTEGER NOT NULL REFERENCES wallet_token_table(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,            -- in lamports/token raw units
    purchase_price_usdc REAL,
    sale_price_usdc REAL,
    purchase_time_ms INTEGER,
    sale_time_ms INTEGER,
    buy_fee_native_lamports INTEGER,
    buy_fee_stablecoin REAL,
    sell_fee_native_lamports INTEGER,
    sell_fee_stablecoin REAL,
    revenue_at_sale_stablecoin REAL,
    priority_fee_lamports INTEGER DEFAULT 0,
    buy_tx_id TEXT,
    sell_tx_id TEXT,
    is_closed INTEGER DEFAULT 0,
    position_type INTEGER NOT NULL CHECK (position_type BETWEEN 0 AND 4),
    FOREIGN KEY (wallet_token_id) REFERENCES wallet_token_table(id) ON DELETE CASCADE
  )
`);

// Indexes (matching Kotlin)
db.run(`
CREATE INDEX idx_position_token ON position_table(wallet_token_id)
`);
db.run(`
CREATE INDEX idx_security_open ON position_table(is_closed)
`);

// 7. ErrorLogs (no foreign keys in Kotlin, but we can add a FK to wallet if desired)
// We'll keep it simple as in Kotlin.
db.run(`
  CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY,
    timestamp_ms INTEGER,
    error_type TEXT,
    message TEXT,
    stack_trace TEXT,
    tx_signature TEXT,
    wallet_id INTEGER,   -- optionally references wallet_table(id) but Kotlin didn't enforce
    severity TEXT DEFAULT 'ERROR'
  )
`);

// Optionally, add a foreign key to wallet_table if you want:
// FOREIGN KEY (wallet_id) REFERENCES wallet_table(id) ON DELETE SET NULL
export { db };
