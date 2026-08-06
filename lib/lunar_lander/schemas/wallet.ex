defmodule LunarLander.Schemas.Wallet do
  use Ecto.Schema
  import Ecto.Changeset

  schema "wallet_table" do
    field :public_key, :string
    field :private_key, :binary
    field :is_irl, :boolean, default: false
    field :dollars, :float
    field :dollars_counted_at_time, :integer
    field :eth_output_account_pubkey, :string
    field :eth_input_account_pubkey, :string
    field :eth_input_account_privkey, :string
    field :created_at_ms, :integer
    field :updated_at_ms, :integer

    belongs_to :user, LunarLander.Schemas.User
    has_many :wallet_tokens, LunarLander.Schemas.WalletToken
  end

  def changeset(wallet, attrs) do
    wallet
    |> cast(attrs, [:user_id, :public_key, :private_key, :is_irl, :dollars,
                    :dollars_counted_at_time, :eth_output_account_pubkey,
                    :eth_input_account_pubkey, :eth_input_account_privkey,
                    :created_at_ms, :updated_at_ms])
    |> validate_required([:user_id, :public_key])
    |> unique_constraint(:public_key)
    |> foreign_key_constraint(:user_id)
  end
end
