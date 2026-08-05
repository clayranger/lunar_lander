defmodule Robot.TradeBotEngine do
  alias Robot.F1
  alias Robot.TokenRepository # Assuming your Ecto/DB repo

  @doc """
  Loads all selected tokens from the DB and adds them to the native F1 engine.
  Raises immediately if any selected token lacks explicit decimals configuration.
  """
  def sync_selected_tokens do
    selected_tokens = TokenRepository.get_selected()

    IO.puts("[Engine] Syncing #{length(selected_tokens)} selected tokens to F1 engine...")

    Enum.each(selected_tokens, fn token ->
      # Strict Validation: Decimals MUST be explicitly defined
      cond do
        is_nil(token.decimals) ->
          error_msg = "CRITICAL EMISSIONS/COMPLIANCE ERROR: Token #{token.mint} (#{token.ticker_symbol}) has null/missing decimals. Halting engine to prevent illegal trade sizing."
          IO.puts(:stderr, "[Engine] #{error_msg}")
          raise RuntimeError, message: error_msg

        token.decimals < 0 or token.decimals > 18 ->
          error_msg = "CRITICAL EMISSIONS/COMPLIANCE ERROR: Token #{token.mint} has out-of-bounds decimals (#{token.decimals})."
          IO.puts(:stderr, "[Engine] #{error_msg}")
          raise RuntimeError, message: error_msg

        true ->
          # Convert Solana base58 mint string to 32-byte binary (equivalent to Uint8Array in Bun)
          mint_bytes = B58.decode58!(token.mint)

          # Pass binary slice and decimals straight into Zigler NIF
          F1.add_token(mint_bytes, nil, token.decimals)

          IO.puts("[Engine] Added token #{token.ticker_symbol || token.mint} (#{token.decimals} decimals)")
      end
    end)
  end

  @doc """
  Starts the F1 engine pipeline and loads env vars.
  """
  def start do
    try do
      IO.puts("Loading API Key")

      # Fetch environment variables using System.fetch_env! (fails fast if missing)
      api_key    = System.fetch_env!("JUPITER_API_KEY")
      wallet_key = System.fetch_env!("WALLET_PUBLIC_KEY")
      quest_host = System.fetch_env!("QUESTDB_HOST")
      quest_port = System.fetch_env!("QUESTDB_PORT") |> String.to_integer()

      # Initialize engine via Zigler bridge
      F1.init_quest_db(quest_host, quest_port)
      F1.start_price_engine(api_key, 3)

      # Sync tokens from DB
      sync_selected_tokens()

      # Start Geyser plugin / WebSocket stream
      F1.start_geyser()
    rescue
      e in RuntimeError ->
        IO.puts(:stderr, "[Engine] Refusing to start engine due to unhandled configuration exception: #{Exception.message(e)}")
        reraise e, __STACKTRACE__
    end
  end
end
