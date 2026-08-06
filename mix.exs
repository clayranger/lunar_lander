defmodule LunarLander.MixProject do
  use Mix.Project

  def project do
    [
      app: :lunar_lander,
      version: "0.1.0",
      elixir: "~> 1.18",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  # Run "mix help compile.app" to learn about applications.
  def application do
    [
      extra_applications: [:logger],
      mod: {LunarLander.Application, []}
    ]
  end

  # Run "mix help deps" to learn about dependencies.
  defp deps do
    [
      # HTTP client (ProcessingPool already uses Req)
      {:req, "~> 0.5"},

      # Database
      {:ecto_sql, "~> 3.12"},
      {:postgrex, ">= 0.0.0"},          # change if you use a different adapter

      # Zig NIF bridge for the F1 engine
      {:zigler, "~> 0.15.2"},

      # Solana mint (base58) decoding — used in TradeBotEngine
      {:base58, "~> 0.1"},              # or {:base58_ex, "~> 0.1"} if you prefer

      # JSON (Req uses it; useful for APIs later)
      {:jason, "~> 1.4"},

      # Optional but recommended
      {:dotenvy, "~> 0.8"},              # nice for loading .env in dev

      {:websockex, "~> 0.5.1"}
    ]
  end
end
