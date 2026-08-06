defmodule LunarLander.Engine.F1 do
  # Resolve path absolute to this file's directory at compile-time
  @engine_dir Path.dirname(__ENV__.file)
  use Zig,
    otp_app: :lunar_lander,
    c: [
      include_dirs: [Path.join(@engine_dir, "../../../include")],
      library_dirs: [Path.join(@engine_dir, "../../../lib")],
      link_lib: ["libF-1-Engine.so"]
    ]

  ~Z"""
  const c = @cImport({
      @cInclude("f1_engine.h");
  });

  // Elixir binaries map cleanly to Zig []const u8 slices
  pub fn init_quest_db(host: []const u8, port: u16) bool {
      // Zigler gives you null-terminated or pointer access easily
      return c.initQuestDB(host.ptr, port) != 0;
  }

  pub fn start_price_engine(api_key: []const u8, poll_interval: u64) bool {
      return c.startPriceEngine(api_key.ptr, poll_interval);
  }

  pub fn add_token(mint_bytes: []const u8, pool_bytes: ?[]const u8, decimals: u8) bool {
      const pool_ptr = if (pool_bytes) |p| p.ptr else null;
      return c.addToken(mint_bytes.ptr, pool_ptr, decimals);
  }

  pub fn start_geyser() bool {
      return c.startGeyser();
  }

  pub fn start_engine() void {
      _ = c.startEngine();
  }
  """
end
