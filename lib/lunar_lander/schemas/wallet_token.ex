defmodule LunarLander.Schemas.WalletToken do
  use Ecto.Schema
  import Ecto.Changeset

  alias LunarLander.Schemas.{Wallet, Token}

  schema "wallet_token_table" do
    field :audited_amount_lamports, :integer, default: 0
    field :audited_time_ms, :integer
    field :ata_exists, :boolean, default: false
    field :rent_paid, :boolean, default: false
    field :ata_created_time_ms, :integer
    field :last_balance_change_ms, :integer
    field :last_sync_ms, :integer
    field :is_native, :boolean, default: false
    field :is_official_stable, :boolean, default: false
    field :is_alt_stable, :boolean, default: false

    belongs_to :wallet, Wallet
    belongs_to :token, Token, references: :mint, foreign_key: :token_mint, type: :string

    has_many :positions, LunarLander.Schemas.Position
  end

  def changeset(wt, attrs) do
    wt
    |> cast(attrs, [:wallet_id, :token_mint, :audited_amount_lamports,
                    :audited_time_ms, :ata_exists, :rent_paid, :ata_created_time_ms,
                    :last_balance_change_ms, :last_sync_ms, :is_native,
                    :is_official_stable, :is_alt_stable])
    |> validate_required([:wallet_id, :token_mint])
    |> unique_constraint([:wallet_id, :token_mint], name: :wallet_token_table_wallet_id_token_mint_index)
    |> foreign_key_constraint(:wallet_id)
    |> foreign_key_constraint(:token_mint)
  end
end
