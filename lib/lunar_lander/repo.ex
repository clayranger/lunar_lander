defmodule LunarLander.Repo do
  use Ecto.Repo,
    otp_app: :lunar_lander,
    adapter: Ecto.Adapters.Postgres
end
