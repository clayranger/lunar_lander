defmodule LunarLander.Repo.Migrations.CreateInitialSchema do
  use Ecto.Migration

  def change do
    # 1. Users
    create table(:users) do
      add :username, :string
      add :password, :string
      add :email, :string
      add :gas_level_choice, :float, default: 0.05
      add :tax_level_choice, :float, default: 0.30
      add :savings_level_choice, :float, default: 0.10
      # 0 = OFF, 1 = AUTOPILOT, 2 = AUTOTHROTTLE
      add :autopilot_on, :integer, default: 0
      add :created_at_ms, :bigint
      add :updated_at_ms, :bigint
    end

    create unique_index(:users, [:username])
    create unique_index(:users, [:email])



    # 2. Tokens
    create table(:token_table) do
      add :mint, :string, null: false
      add :ticker_symbol, :string
      add :name, :string
      add :decimals, :integer
      add :price_server, :string
      add :exchange_server, :string
      add :price_tracking, :boolean, default: true
      add :stable_coin_official, :boolean, default: false
      add :stable_coin_alt, :boolean, default: false
      add :is_selected, :boolean, default: false
      add :selected_at_ms, :bigint
      add :created_at_ms, :bigint
      add :updated_at_ms, :bigint
    end

    create unique_index(:token_table, [:mint])

    # 3. Wallets (references users)
    create table(:wallet_table) do
      add :user_id, references(:users, on_delete: :delete_all), null: false
      add :public_key, :string, null: false
      # may be encrypted, use binary
      add :private_key, :binary
      add :is_irl, :boolean, default: false
      add :dollars, :float
      add :dollars_counted_at_time, :bigint
      add :eth_output_account_pubkey, :string
      add :eth_input_account_pubkey, :string
      # consider encryption
      add :eth_input_account_privkey, :string
      add :created_at_ms, :bigint
      add :updated_at_ms, :bigint
    end

    create unique_index(:wallet_table, [:public_key])
    create index(:wallet_table, [:user_id])

    # 4. WalletTokens (references wallets and tokens)
    create table(:wallet_token_table) do
      add :wallet_id, references(:wallet_table, on_delete: :delete_all), null: false

      add :token_mint,
          references(:token_table, column: :mint, type: :string, on_delete: :delete_all),
          null: false

      add :audited_amount_lamports, :bigint, default: 0
      add :audited_time_ms, :bigint
      add :ata_exists, :boolean, default: false
      add :rent_paid, :boolean, default: false
      add :ata_created_time_ms, :bigint
      add :last_balance_change_ms, :bigint
      add :last_sync_ms, :bigint
      add :is_native, :boolean, default: false
      add :is_official_stable, :boolean, default: false
      add :is_alt_stable, :boolean, default: false
    end

    create unique_index(:wallet_token_table, [:wallet_id, :token_mint])
    create index(:wallet_token_table, [:wallet_id])
    create index(:wallet_token_table, [:token_mint])

    # 5. UserTokenSettings (references users and tokens)
    create table(:user_token_settings) do
      add :user_id, references(:users, on_delete: :delete_all), null: false

      add :token_mint,
          references(:token_table, column: :mint, type: :string, on_delete: :delete_all),
          null: false

      add :purchase_blocked, :boolean, default: false
      add :ignored, :boolean, default: false
      add :favorite, :boolean, default: false
      add :auto_trade, :boolean, default: true
      add :auto_sell, :boolean, default: true
      add :custom_slippage_bps, :integer
      add :max_position_usdc, :float
      add :notes, :string
    end

    create unique_index(:user_token_settings, [:user_id, :token_mint])
    create index(:user_token_settings, [:user_id])
    create index(:user_token_settings, [:token_mint])

    # 6. Positions (references wallet_token_table)
    create table(:position_table) do
      add :wallet_token_id, references(:wallet_token_table, on_delete: :delete_all), null: false
      # in lamports/token raw units
      add :amount, :bigint, null: false
      add :purchase_price_usdc, :float
      add :sale_price_usdc, :float
      add :purchase_time_ms, :bigint
      add :sale_time_ms, :bigint
      add :buy_fee_native_lamports, :bigint
      add :buy_fee_stablecoin, :float
      add :sell_fee_native_lamports, :bigint
      add :sell_fee_stablecoin, :float
      add :revenue_at_sale_stablecoin, :float
      add :priority_fee_lamports, :bigint, default: 0
      add :buy_tx_id, :string
      add :sell_tx_id, :string
      add :is_closed, :boolean, default: false
      add :is_in_transit, :boolean, default: false
      # not settled: 5
      add :position_type, :integer, null: false
    end

    create constraint(:position_table, :position_type_range,
             check: "position_type BETWEEN 0 AND 5"
           )

    create index(:position_table, [:wallet_token_id])
    create index(:position_table, [:is_closed])

    # 7. ErrorLogs (no enforced FK, matching the original)
    create table(:error_log) do
      add :timestamp_ms, :bigint
      add :error_type, :string
      add :message, :string
      add :stack_trace, :text
      add :tx_signature, :string
      add :wallet_id, :integer
      add :severity, :string, default: "ERROR"
    end
  end
end
