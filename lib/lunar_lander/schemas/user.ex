defmodule LunarLander.Schemas.User do
  use Ecto.Schema
  import Ecto.Changeset

  schema "users" do
    field :username, :string
    field :password, :string
    field :email, :string
    field :gas_level_choice, :float, default: 0.05
    field :tax_level_choice, :float, default: 0.30
    field :savings_level_choice, :float, default: 0.10
    field :autopilot_on, :integer, default: 0
    field :created_at_ms, :integer
    field :updated_at_ms, :integer

    has_many :wallets, LunarLander.Schemas.Wallet
    has_many :user_token_settings, LunarLander.Schemas.UserTokenSetting
    has_many :trades, LunarLander.Schemas.Trade
  end

  def changeset(user, attrs) do
    user
    |> cast(attrs, [:username, :password, :email, :gas_level_choice,
                    :tax_level_choice, :savings_level_choice, :autopilot_on,
                    :created_at_ms, :updated_at_ms])
    |> validate_required([:username, :email, :password])
    |> validate_inclusion(:autopilot_on, [0, 1, 2])
    |> unique_constraint(:username)
    |> unique_constraint(:email)
  end
end
