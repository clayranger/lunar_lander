defmodule LunarLander.Schemas.ErrorLog do
  use Ecto.Schema
  import Ecto.Changeset

  schema "error_log" do
    field :timestamp_ms, :integer
    field :error_type, :string
    field :message, :string
    field :stack_trace, :string
    field :tx_signature, :string
    field :wallet_id, :integer
    field :severity, :string, default: "ERROR"
  end

  def changeset(log, attrs) do
    log
    |> cast(attrs, [:timestamp_ms, :error_type, :message, :stack_trace,
                    :tx_signature, :wallet_id, :severity])
    |> validate_required([:error_type, :message])
    |> validate_inclusion(:severity, ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"])
  end
end
