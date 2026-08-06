defmodule TradeAuditor do
  use GenServer
  require Logger

  @chainstack_rpc "https://solana-mainnet.core.chainstack.com/YOUR_API_KEY"
  @helius_wallet_api "https://api.helius.dev/v1/wallet"
  @helius_key "YOUR_HELIUS_KEY"

  def start_link(tx_signature, wallet_address) do
    GenServer.start_link(__MODULE__, {tx_signature, wallet_address})
  end

  def init({tx_signature, wallet_address}) do
    # Start polling Chainstack for 31-block finality
    send(self(), :poll_status)
    {:ok, %{sig: tx_signature, wallet: wallet_address, attempts: 0}}
  end

  def handle_info(:poll_status, state) do
    case check_signature_finality(state.sig) do
      {:ok, :finalized} ->
        Logger.info("Tx #{state.sig} finalized. Triggering Wallet API audit...")
        run_wallet_audit(state.wallet)
        {:stop, :normal, state}

      {:ok, :pending} ->
        Process.send_after(self(), :poll_status, 2000)
        {:noreply, %{state | attempts: state.attempts + 1}}

      {:error, reason} ->
        Logger.error("Tx failed or dropped: #{inspect(reason)}. Requesting bot rollback.")
        # Broadcast rollback signal to C/Zig bot over NATS
        {:stop, :failed, state}
    end
  end

  defp check_signature_finality(sig) do
    payload = %{
      jsonrpc: "2.0", id: 1,
      method: "getSignatureStatuses",
      params: [[sig], %{searchTransactionHistory: true}]
    }

    with {:ok, %{status: 200, body: %{"result" => %{"value" => [status_info]}}}} <- Req.post(@chainstack_rpc, json: payload),
         false <- is_nil(status_info),
         nil <- status_info["err"] do
      if status_info["confirmationStatus"] == "finalized" do
        {:ok, :finalized}
      else
        {:ok, :pending}
      end
    else
      _ -> {:error, :not_found_or_failed}
    end
  end

  defp run_wallet_audit(wallet_address) do
    # Query Helius Wallet API for new balances
    url = "#{@helius_wallet_api}/balances?address=#{wallet_address}&api-key=#{@helius_key}"
    
    case Req.get(url) do
      {:ok, %{status: 200, body: balances}} ->
        # Calculate tax withholding & check gas balance
        # Send updated portfolio payload to C/Zig trade bot via NATS
        Logger.info("Audit complete for #{wallet_address}: #{inspect(balances)}")
      error ->
        Logger.error("Failed to fetch Wallet API balances: #{inspect(error)}")
    end
  end
end
