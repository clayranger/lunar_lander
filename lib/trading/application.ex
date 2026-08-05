# lib/trading/application.ex
defmodule Trading.Application do
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      Trading.Repo,
      Trading.Services.ProcessingPool,
      {Trading.Services.TokenSelector, interval_minutes: 5}
      # Trading.Services.RateLimiter, ...
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: Trading.Supervisor)
  end
end
