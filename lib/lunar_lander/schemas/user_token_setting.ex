defmodule LunarLander.Schemas.UserTokenSetting do
  use Ecto.Schema
  import Ecto.Changeset

  alias LunarLander.Schemas.{User, Token}

  schema "user_token_settings" do
    field :purchase_blocked, :boolean, default: false
    field :ignored, :boolean, default: false
    field :favorite, :boolean, default: false
    field :auto_trade, :boolean, default: true
    field :auto_sell, :boolean, default: true
    field :custom_slippage_bps, :integer
    field :max_position_usdc, :float
    field :notes, :string

    belongs_to :user, User
    belongs_to :token, Token, references: :mint, foreign_key: :token_mint, type: :string
  end

  def changeset(settings, attrs) do
    settings
    |> cast(attrs, [:user_id, :token_mint, :purchase_blocked, :ignored, :favorite,
                    :auto_trade, :auto_sell, :custom_slippage_bps, :max_position_usdc,
                    :notes])
    |> validate_required([:user_id, :token_mint])
    |> unique_constraint([:user_id, :token_mint], name: :user_token_settings_user_id_token_mint_index)
    |> foreign_key_constraint(:user_id)
    |> foreign_key_constraint(:token_mint)
  end
end
