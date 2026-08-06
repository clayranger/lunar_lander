defmodule LunarLander.Schemas.Token do
  use Ecto.Schema
  import Ecto.Changeset

  schema "token_table" do
    field :mint, :string
    field :ticker_symbol, :string
    field :name, :string
    field :decimals, :integer
    field :price_server, :string
    field :exchange_server, :string
    field :price_tracking, :boolean, default: true
    field :stable_coin_official, :boolean, default: false
    field :stable_coin_alt, :boolean, default: false
    field :is_selected, :boolean, default: false
    field :selected_at_ms, :integer
    field :created_at_ms, :integer
    field :updated_at_ms, :integer

    has_many :wallet_tokens, LunarLander.Schemas.WalletToken,
      foreign_key: :token_mint,
      references: :mint

    has_many :user_token_settings, LunarLander.Schemas.UserTokenSetting,
      foreign_key: :token_mint,
      references: :mint
  end

  def changeset(token, attrs) do
    token
    |> cast(attrs, [:mint, :ticker_symbol, :name, :decimals, :price_server,
                    :exchange_server, :price_tracking, :stable_coin_official,
                    :stable_coin_alt, :is_selected, :selected_at_ms,
                    :created_at_ms, :updated_at_ms])
    |> validate_required([:mint])
    |> unique_constraint(:mint)
  end
end
