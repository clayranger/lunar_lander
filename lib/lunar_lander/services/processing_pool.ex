# lib/trading/services/processing_pool.ex
defmodule Trading.Services.ProcessingPool do
  use GenServer
  require Logger

  @url "http://localhost:8080/processing-pool"
  @timeout 5_000

  defstruct pool: [], last_updated_ms: nil, last_error: nil

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  def get_pool, do: GenServer.call(__MODULE__, :get_pool)
  def get_by_mint(mint), do: Enum.find(get_pool(), &(&1.mint == mint))
  def refresh, do: GenServer.call(__MODULE__, :refresh, @timeout + 1_000)

  @impl true
  def init(_opts), do: {:ok, %__MODULE__{}}

  @impl true
  def handle_call(:get_pool, _from, state), do: {:reply, state.pool, state}

  @impl true
  def handle_call(:refresh, _from, state) do
    case Req.get(@url, receive_timeout: @timeout) do
      {:ok, %{status: 200, body: body}} when is_list(body) ->
        parsed = Enum.map(body, &map_entry/1)
        new_state = %{state | pool: parsed, last_updated_ms: System.system_time(:millisecond), last_error: nil}
        {:reply, {:ok, parsed}, new_state}

      {:ok, %{status: status}} ->
        err = "Processing pool server responded with status #{status}"
        {:reply, {:error, err}, %{state | last_error: err}}

      {:error, reason} ->
        err = "Failed to contact processing pool server: #{inspect(reason)}"
        {:reply, {:error, err}, %{state | last_error: err}}
    end
  end

  defp map_entry(e) do
    %{
      mint: e["mint"],
      ewma_score: e["ewma_score"],
      tenure_minutes: e["tenure_minutes"],
      pool_address: e["pool_address"],
      decimals: e["decimals"]
    }
  end
end
