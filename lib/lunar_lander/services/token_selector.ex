defmodule LunarLander.Services.TokenSelector do
  use GenServer
  require Logger
  # To be honest im not sure about this line.
  alias LunarLander.Services.{Tokens, Services.ProcessingPool}

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  def refresh, do: GenServer.call(__MODULE__, :refresh, 15_000)

  @impl true
  def init(opts) do
    interval_min = Keyword.get(opts, :interval_minutes, 5)
    :timer.send_interval(interval_min * 60_000, :auto_refresh)
    {:ok, %{}}
  end

  @impl true
  def handle_info(:auto_refresh, state) do
    case do_refresh() do
      {:ok, _} -> :ok
      {:error, reason} -> Logger.error("TokenSelector auto-refresh failed: #{inspect(reason)}")
    end
    {:noreply, state}
  end

  @impl true
  def handle_call(:refresh, _from, state) do
    {:reply, do_refresh(), state}
  end
defp do_refresh do
    case ProcessingPool.refresh() do
      {:error, reason} ->
        if ProcessingPool.get_pool() == [] do
          raise reason
        end

      _ ->
        :ok
    end

    pool = ProcessingPool.get_pool()

    Enum.each(pool, fn entry ->
      Tokens.add_or_update(entry.mint, decimals: entry.decimals)
    end)

    Tokens.replace_selected_mints(Enum.map(pool, & &1.mint))

    {:ok, Tokens.get_selected()}
  end
end
