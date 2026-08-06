defmodule LunarLander.Schema.WalletTokens do
  alias LunarLander.Repo
  alias LunarLander.Schemas.WalletToken
  alias LunarLander.Tokens

  def ensure_exists(wallet_id, token_mint, opts \\ []) do
    case Repo.get_by(WalletToken, wallet_id: wallet_id, token_mint: token_mint) do
      nil ->
        unless Tokens.find_by_mint(token_mint) do
          raise Trading.RecordNotFoundError, entity: "Token", id: token_mint
        end

        %WalletToken{}
        |> WalletToken.changeset(%{
          wallet_id: wallet_id,
          token_mint: token_mint,
          audited_amount_lamports: 0,
          audited_time_ms: System.system_time(:millisecond),
          is_native: Keyword.get(opts, :is_native, false),
          is_official_stable: Keyword.get(opts, :is_official_stable, false),
          is_alt_stable: Keyword.get(opts, :is_alt_stable, false)
        })
        |> Repo.insert!()

      existing ->
        existing
    end
  end
end
