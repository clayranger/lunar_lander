# lib/trading/record_not_found_error.ex
defmodule Trading.RecordNotFoundError do
  defexception [:entity, :id]

  @impl true
  def message(%{entity: entity, id: id}), do: "#{entity} not found: #{id}"
end
