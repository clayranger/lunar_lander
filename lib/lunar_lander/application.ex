# lib/trading/application.ex
defmodule LunarLander.Application do
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      LunarLander.Repo,
      LunarLander.Services.ProcessingPool,
      {LunarLander.Services.TokenSelector, interval_minutes: 5}
      # Trading.Services.RateLimiter, ...
    ]
    IO.puts("Hello World")
    Supervisor.start_link(children, strategy: :one_for_one, name: LunarLander.Supervisor)
  end
end
