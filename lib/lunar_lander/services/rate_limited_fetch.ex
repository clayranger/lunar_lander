# lib/trading/services/rate_limited_fetch.ex
defmodule Trading.Services.RateLimitedFetch do
  @moduledoc """
  Wraps Req with priority-bucket acquisition, retry-after-aware 429
  handling, and exponential backoff on transport errors — mirrors
  rateLimitedFetch() in the JS version.
  """
  alias Trading.Services.RateLimiter

  @default_max_retries 3

  @doc """
  opts:
    :bucket        - RateLimiter process name (defaults to RateLimiter)
    :max_retries   - default 3
    :cost          - token cost, default 1
    :priority      - 0 | 1 | 2, default 2
    (everything else is passed through to Req.request/1, e.g. :method,
     :json, :headers)
  """
  def request(url, opts \\ []) do
    bucket = Keyword.get(opts, :bucket, RateLimiter)
    max_retries = Keyword.get(opts, :max_retries, @default_max_retries)
    cost = Keyword.get(opts, :cost, 1)
    priority = Keyword.get(opts, :priority, 2)

    req_opts =
      opts
      |> Keyword.drop([:bucket, :max_retries, :cost, :priority])
      |> Keyword.put(:url, url)

    do_request(req_opts, bucket, cost, priority, max_retries, 0)
  end

  defp do_request(req_opts, bucket, cost, priority, max_retries, attempt) do
    :ok = RateLimiter.acquire(bucket, cost, priority)

    case Req.request(req_opts) do
      {:ok, %Req.Response{status: 429} = resp} ->
        backoff_ms =
          case Req.Response.get_header(resp, "retry-after") do
            [val | _] ->
              case Float.parse(val) do
                {seconds, _} -> round(seconds * 1000)
                :error -> exp_backoff(attempt)
              end

            _ ->
              exp_backoff(attempt)
          end

        RateLimiter.notify_429(bucket, backoff_ms)

        if attempt >= max_retries do
          {:ok, resp}
        else
          do_request(req_opts, bucket, cost, priority, max_retries, attempt + 1)
        end

      {:ok, resp} ->
        {:ok, resp}

      {:error, reason} ->
        if attempt >= max_retries do
          {:error, reason}
        else
          Process.sleep(500 * Integer.pow(2, attempt))
          do_request(req_opts, bucket, cost, priority, max_retries, attempt + 1)
        end
    end
  end

  defp exp_backoff(attempt), do: 1_000 * Integer.pow(2, attempt)
end
