defmodule LunarLander.Services.SolanaSignatureWatcher do
  @moduledoc """
  Subscribes to Chainstack Solana WebSocket events for 31-block finality (`signatureSubscribe`).
  """

  use WebSockex
  require Logger

  @ping_interval :timer.minutes(1)

  # Client API

  @doc """
  Starts the WebSocket process connected to your Chainstack endpoint.
  """
  def start_link(url, opts \\ []) do
    state = %{
      req_id: 1,
      # Maps JSON-RPC request IDs -> {signature, caller_pid}
      pending_reqs: %{},
      # Maps Solana WebSocket subscription IDs -> {signature, caller_pid}
      active_subs: %{}
    }

    WebSockex.start_link(url, __MODULE__, state, opts)
  end

  @doc """
  Registers a signature to monitor. 

  When Solana emits the terminal `signatureNotification` event, `caller_pid` will receive:
    - `{:solana_tx_finalized, signature, slot}` on success
    - `{:solana_tx_failed, signature, error_details}` on execution failure
  """
  def watch_signature(pid, signature, caller_pid \\ self()) do
    send(pid, {:subscribe_signature, signature, caller_pid})
  end

  # WebSockex Callbacks

  @impl true
  def handle_connect(_conn, state) do
    Logger.info("[SolanaWS] Connected to Chainstack WebSocket.")
    # Start periodic ping timer to satisfy the 10-min inactivity timeout
    schedule_ping()
    {:ok, state}
  end

  @impl true
  def handle_info({:subscribe_signature, signature, caller_pid}, state) do
    req_id = state.req_id

    payload = %{
      jsonrpc: "2.0",
      id: req_id,
      method: "signatureSubscribe",
      params: [
        signature,
        %{commitment: "finalized", enableReceivedNotification: false}
      ]
    }

    frame = {:text, Jason.encode!(payload)}

    new_state = %{
      state
      | req_id: req_id + 1,
        pending_reqs: Map.put(state.pending_reqs, req_id, {signature, caller_pid})
    }

    Logger.info("[SolanaWS] Sent signatureSubscribe for #{signature} (req_id: #{req_id})")
    {:reply, frame, new_state}
  end

  @impl true
  def handle_info(:send_ping, state) do
    schedule_ping()
    # Send standard WebSocket ping frame
    {:reply, :ping, state}
  end

  @impl true
  def handle_frame({:text, msg}, state) do
    case Jason.decode(msg) do
      {:ok, %{"id" => req_id, "result" => sub_id}} when is_integer(sub_id) ->
        # Step 1: Subscription ACK received from Chainstack
        {new_pending, new_active} = promote_pending_to_active(state, req_id, sub_id)
        {:ok, %{state | pending_reqs: new_pending, active_subs: new_active}}

      {:ok, %{"method" => "signatureNotification", "params" => params}} ->
        # Step 2: Terminal notification pushed by Solana node
        new_active = handle_signature_notification(state.active_subs, params)
        {:ok, %{state | active_subs: new_active}}

      {:ok, %{"error" => err}} ->
        Logger.error("[SolanaWS] RPC Error payload received: #{inspect(err)}")
        {:ok, state}

      _other ->
        {:ok, state}
    end
  end

  @impl true
  def handle_disconnect(%{reason: reason}, state) do
    Logger.warning("[SolanaWS] Disconnected: #{inspect(reason)}. WebSockex will auto-reconnect.")
    {:ok, state}
  end

  # Helper Functions

  defp promote_pending_to_active(state, req_id, sub_id) do
    case Map.pop(state.pending_reqs, req_id) do
      {{signature, caller_pid}, remaining_pending} ->
        Logger.debug("[SolanaWS] Subscribed to #{signature} with sub_id: #{sub_id}")
        updated_active = Map.put(state.active_subs, sub_id, {signature, caller_pid})
        {remaining_pending, updated_active}

      {nil, remaining_pending} ->
        {remaining_pending, state.active_subs}
    end
  end

  defp handle_signature_notification(active_subs, %{"result" => result, "subscription" => sub_id}) do
    case Map.pop(active_subs, sub_id) do
      {{signature, caller_pid}, remaining_subs} ->
        slot = get_in(result, ["context", "slot"])
        err = get_in(result, ["value", "err"])

        if is_nil(err) do
          Logger.info("[SolanaWS] Signature #{signature} finalized at slot #{slot}.")
          send(caller_pid, {:solana_tx_finalized, signature, slot})
        else
          Logger.error("[SolanaWS] Signature #{signature} failed on-chain: #{inspect(err)}")
          send(caller_pid, {:solana_tx_failed, signature, err})
        end

        # Note: Solana automatically cancels signature subscriptions after emitting the terminal notification
        remaining_subs

      {nil, remaining_subs} ->
        remaining_subs
    end
  end

  defp schedule_ping do
    Process.send_after(self(), :send_ping, @ping_interval)
  end
end


# # 1. Start the watcher in your application supervision tree
# url = "wss://solana-mainnet.core.chainstack.com/YOUR_API_KEY"
# {:ok, watcher_pid} = SolanaSignatureWatcher.start_link(url)
#
# # 2. When the C/Zig trade bot sends a new tx signature over NATS:
# signature = "2EBVM6cB8vAAD93Ktr6Vd8p67XPbQzCJX47..."
# SolanaSignatureWatcher.watch_signature(watcher_pid, signature)
#
# # 3. Receive the notification in your Elixir process / GenServer
# receive do
#   {:solana_tx_finalized, ^signature, slot} ->
#     # Transaction is 31-block finalized!
#     # Call Helius Wallet API -> Calculate Tax Withholding -> Sync Portfolio to C/Zig bot
#     run_helius_audit(signature)
#
#   {:solana_tx_failed, ^signature, err} ->
#     # Transaction dropped/failed on-chain. Send rollback signal to C/Zig bot over NATS.
#     broadcast_nats_rollback(signature, err)
# after
#   20_000 ->
#     # Safety timeout if notification takes longer than 20 seconds
#     check_fallback_rpc(signature)
# end
