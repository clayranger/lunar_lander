defmodule LunarLander.Schemas.Tokens do
  import Ecto.Query
  alias LunarLander.Repo
  alias LunarLander.Schemas.Token

  def find_by_mint(mint), do: Repo.get_by(Token, mint: mint)

  def get_decimals!(mint) do
    case Repo.one(from t in Token, where: t.mint == ^mint, select: t.decimals) do
      nil -> raise Trading.RecordNotFoundError, entity: "Token Decimals", id: mint
      decimals -> decimals
    end
  end

  def get_selected, do: Repo.all(from t in Token, where: t.is_selected == true)

  def add_or_update(mint, opts \\ []) do
    now = System.system_time(:millisecond)

    case find_by_mint(mint) do
      nil ->
        %Token{}
        |> Token.changeset(%{
          mint: mint,
          ticker_symbol: opts[:ticker_symbol] || String.slice(mint, 0, 8),
          name: opts[:name] || "Unknown Token",
          decimals: opts[:decimals],
          price_server: "jupiter",
          exchange_server: "jupiter",
          price_tracking: Keyword.get(opts, :price_tracking, true),
          stable_coin_official: Keyword.get(opts, :stable_coin_official, false),
          stable_coin_alt: Keyword.get(opts, :stable_coin_alt, false),
          created_at_ms: now,
          updated_at_ms: now
        })
        |> Repo.insert!()

      existing ->
        updates =
          %{}
          |> maybe_put(:ticker_symbol, opts[:ticker_symbol], existing.ticker_symbol in [nil, String.slice(existing.mint, 0, 8)])
          |> maybe_put(:name, opts[:name], existing.name in [nil, "Unknown Token"])
          |> maybe_put(:decimals, opts[:decimals], is_nil(existing.decimals))

        if map_size(updates) > 0 do
          existing
          |> Token.changeset(Map.put(updates, :updated_at_ms, now))
          |> Repo.update!()
        else
          existing
        end
    end
  end

  defp maybe_put(map, _key, nil, _cond), do: map
  defp maybe_put(map, _key, _val, false), do: map
  defp maybe_put(map, key, val, true), do: Map.put(map, key, val)

  def set_selected(mint, selected?) do
    now = System.system_time(:millisecond)

    {count, _} =
      from(t in Token, where: t.mint == ^mint)
      |> Repo.update_all(set: [
        is_selected: selected?,
        selected_at_ms: if(selected?, do: now, else: nil),
        updated_at_ms: now
      ])

    if count == 0, do: raise(Trading.RecordNotFoundError, entity: "Token", id: mint)
    :ok
  end

  def clear_all_selected do
    now = System.system_time(:millisecond)
    from(t in Token, where: t.is_selected == true)
    |> Repo.update_all(set: [is_selected: false, selected_at_ms: nil, updated_at_ms: now])
  end

  def replace_selected_mints(mints) do
    now = System.system_time(:millisecond)
    unique = Enum.uniq(mints)

    Repo.transaction(fn ->
      clear_all_selected()

      if unique != [] do
        from(t in Token, where: t.mint in ^unique)
        |> Repo.update_all(set: [is_selected: true, selected_at_ms: now, updated_at_ms: now])
      end
    end)
  end
end
