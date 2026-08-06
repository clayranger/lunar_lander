defmodule LunarLander.Schemas.Position do
  use Ecto.Schema
  import Ecto.Changeset

  schema "position_table" do
    field :amount, :integer
    field :purchase_price_usdc, :float
    field :sale_price_usdc, :float
    field :purchase_time_ms, :integer
    field :sale_time_ms, :integer
    field :buy_fee_native_lamports, :integer
    field :buy_fee_stablecoin, :float
    field :sell_fee_native_lamports, :integer
    field :sell_fee_stablecoin, :float
    field :revenue_at_sale_stablecoin, :float
    field :priority_fee_lamports, :integer, default: 0
    field :buy_tx_id, :string
    field :sell_tx_id, :string
    field :is_closed, :boolean, default: false
    field :is_in_transit, :boolean, default: false
    # 0..4 mirror the position types used elsewhere in the system
    # (investment/gas/tax/savings/unknown); 5 = not settled.
    field :position_type, :integer

    belongs_to :wallet_token, LunarLander.Schemas.WalletToken
  end

  def changeset(position, attrs) do
    position
    |> cast(attrs, [:wallet_token_id, :amount, :purchase_price_usdc, :sale_price_usdc,
                    :purchase_time_ms, :sale_time_ms, :buy_fee_native_lamports,
                    :buy_fee_stablecoin, :sell_fee_native_lamports, :sell_fee_stablecoin,
                    :revenue_at_sale_stablecoin, :priority_fee_lamports, :buy_tx_id,
                    :sell_tx_id, :is_closed, :is_in_transit, :position_type])
    |> validate_required([:wallet_token_id, :amount, :position_type])
    |> validate_inclusion(:position_type, 0..5)
    |> foreign_key_constraint(:wallet_token_id)
    |> check_constraint(:position_type, name: :position_type_range)
  end
end
