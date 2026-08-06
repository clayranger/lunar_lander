defmodule LunarLander.RecordNotFoundError do
  defexception [:entity, :id]

  @impl true
  def message(%{entity: entity, id: id}), do: "#{entity} not found: #{id}"
end
