# lib/trading/services/rate_limiter.ex
defmodule Trading.Services.RateLimiter do
  @moduledoc """
  Priority token bucket rate limiter.

  Priority 0 = critical (e.g. order submission)
  Priority 1 = high
  Priority 2 = routine (e.g. polling) — this is the default
  """
  use GenServer
  require Logger

  defstruct [
    :capacity,
    :target_refill_rate,
    :min_refill_rate,
    :tokens,
    :current_refill_rate,
    :last_refill,
    paused_until: 0,
    queue: [],
    timer_ref: nil
  ]

  # ---- Public API ----------------------------------------------------

  def start_link(opts) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Blocks the caller until `cost` tokens are available for the given
  priority, then returns :ok. Mirrors the JS acquire(cost, priority)
  promise.
  """
  def acquire(name \\ __MODULE__, cost \\ 1, priority \\ 2) do
    # Long timeout: callers should be relying on the bucket/queue logic
    # to resolve this, not the GenServer call timeout. Bump per use case.
    GenServer.call(name, {:acquire, cost, priority}, :infinity)
  end

  @doc """
  Signal a 429 response. Pauses the bucket, drains tokens, and backs
  off the refill rate — same behavior as notify429 in the JS version.
  """
  def notify_429(name \\ __MODULE__, retry_after_ms \\ 1_000) do
    GenServer.cast(name, {:notify_429, retry_after_ms})
  end

  # ---- GenServer callbacks --------------------------------------------

  @impl true
  def init(opts) do
    capacity = Keyword.fetch!(opts, :capacity)
    target_refill_rate = Keyword.fetch!(opts, :target_refill_rate)
    min_refill_rate = Keyword.get(opts, :min_refill_rate, 2)

    state = %__MODULE__{
      capacity: capacity,
      target_refill_rate: target_refill_rate,
      min_refill_rate: min_refill_rate,
      tokens: capacity,
      current_refill_rate: target_refill_rate,
      last_refill: now_ms()
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:acquire, cost, priority}, from, state) do
    state = refill(state)

    # Fast path: empty queue, not paused, enough tokens right now.
    if state.queue == [] and now_ms() >= state.paused_until and state.tokens >= cost do
      state = %{state | tokens: state.tokens - cost}
      {:reply, :ok, state}
    else
      entry = %{priority: priority, cost: cost, from: from, timestamp: now_ms()}
      state = %{state | queue: state.queue ++ [entry]}
      state = process_queue(state)
      {:noreply, state}
    end
  end

  @impl true
  def handle_cast({:notify_429, retry_after_ms}, state) do
    jitter = :rand.uniform() * 0.2 + 0.9
    delay = retry_after_ms * jitter

    state = %{
      state
      | paused_until: now_ms() + delay,
        tokens: 0,
        current_refill_rate: max(state.min_refill_rate, state.current_refill_rate * 0.5)
    }

    state = schedule_queue_check(state, delay)
    {:noreply, state}
  end

  @impl true
  def handle_info(:process_queue, state) do
    state = %{state | timer_ref: nil}
    {:noreply, process_queue(state)}
  end

  # ---- Internals --------------------------------------------------------

  defp refill(state) do
    now = now_ms()

    # Gradually recover toward target refill rate
    current_refill_rate =
      if state.current_refill_rate < state.target_refill_rate do
        min(state.target_refill_rate, state.current_refill_rate + 0.5)
      else
        state.current_refill_rate
      end

    elapsed_sec = (now - state.last_refill) / 1000
    tokens = min(state.capacity, state.tokens + elapsed_sec * current_refill_rate)

    %{state | tokens: tokens, current_refill_rate: current_refill_rate, last_refill: now}
  end

  defp process_queue(%{queue: []} = state), do: state

  defp process_queue(state) do
    now = now_ms()

    if now < state.paused_until do
      schedule_queue_check(state, state.paused_until - now)
    else
      state = refill(state)

      sorted =
        Enum.sort(state.queue, fn a, b ->
          if a.priority != b.priority do
            a.priority < b.priority
          else
            a.timestamp <= b.timestamp
          end
        end)

      {remaining, tokens} = grant_from_front(sorted, state.tokens)
      state = %{state | queue: remaining, tokens: tokens}

      case remaining do
        [] ->
          state

        [next | _] ->
          needed = next.cost - state.tokens
          wait_ms = max(10, needed / state.current_refill_rate * 1000)
          schedule_queue_check(state, wait_ms)
      end
    end
  end

  # Grants tokens to queued callers in priority/FIFO order until the
  # budget runs out; replies to each granted caller directly.
  defp grant_from_front([], tokens), do: {[], tokens}

  defp grant_from_front([entry | rest] = queue, tokens) do
    if tokens >= entry.cost do
      GenServer.reply(entry.from, :ok)
      grant_from_front(rest, tokens - entry.cost)
    else
      {queue, tokens}
    end
  end

  defp schedule_queue_check(state, delay_ms) do
    if state.timer_ref, do: Process.cancel_timer(state.timer_ref)
    ref = Process.send_after(self(), :process_queue, round(delay_ms))
    %{state | timer_ref: ref}
  end

  defp now_ms, do: System.monotonic_time(:millisecond)
end
