// repositories/TokenRepository.ts
import { db } from '../db';
import { Ok, Err, Result } from '../types/result';
import { TokenDTO } from '../types/dtos';

export class TokenRepository {
    addOrUpdate(
        mint: string,
        tickerSymbol?: string | null,
        name?: string | null,
        decimals?: number | null,
        stableCoinOfficial: boolean = false,
        stableCoinAlt: boolean = false,
        priceTracking: boolean = true
    ): Result<TokenDTO, string> {
        try {
            const nowMs = Date.now();

            // Check if token exists
            const existing = db.query('SELECT * FROM token_table WHERE mint = ?').get(mint) as any;

            if (!existing) {
                // INSERT
                const insert = db.run(
                    `INSERT INTO token_table (
                        mint, ticker_symbol, name, decimals, price_server, exchange_server,
                        price_tracking, stable_coin_official, stable_coin_alt,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                                      mint,
                                      tickerSymbol ?? mint.slice(0, 8),
                                      name ?? 'Unknown Token',
                                      decimals ?? null,
                                      'jupiter',
                                      'jupiter',
                                      priceTracking ? 1 : 0,
                                      stableCoinOfficial ? 1 : 0,
                                      stableCoinAlt ? 1 : 0,
                                      nowMs,
                                      nowMs
                );
                const id = insert.lastInsertRowid as number;
                const row = db.query('SELECT * FROM token_table WHERE id = ?').get(id);
                return Ok(this.mapRowToDTO(row));
            } else {
                // UPDATE only missing fields
                let needsUpdate = false;
                const updates: any = {};
                if (tickerSymbol != null && (existing.ticker_symbol == null || existing.ticker_symbol === existing.mint.slice(0, 8))) {
                    updates.ticker_symbol = tickerSymbol;
                    needsUpdate = true;
                }
                if (name != null && (existing.name == null || existing.name === 'Unknown Token')) {
                    updates.name = name;
                    needsUpdate = true;
                }
                if (decimals != null && existing.decimals == null) {
                    updates.decimals = decimals;
                    needsUpdate = true;
                }
                if (needsUpdate) {
                    updates.updated_at_ms = nowMs;
                    const setClause = Object.keys(updates).map(k => `${k} = ?`).join(', ');
                    const values = Object.values(updates);
                    db.run(`UPDATE token_table SET ${setClause} WHERE mint = ?`, ...values, mint);
                }
                const fresh = db.query('SELECT * FROM token_table WHERE mint = ?').get(mint);
                return Ok(this.mapRowToDTO(fresh));
            }
        } catch (e: any) {
            return Err(`Failed to add/update token ${mint}: ${e.message}`);
        }
    }

    findByMint(mint: string): Result<TokenDTO | null, string> {
        try {
            const row = db.query('SELECT * FROM token_table WHERE mint = ?').get(mint) as any;
            return Ok(row ? this.mapRowToDTO(row) : null);
        } catch (e: any) {
            return Err(`Database error finding token ${mint}: ${e.message}`);
        }
    }

    getDecimals(mint: string): Result<number, string> {
        try {
            const row = db.query('SELECT decimals FROM token_table WHERE mint = ?').get(mint) as any;
            if (row && row.decimals !== null && row.decimals !== undefined) {
                return Ok(row.decimals);
            }
            return Err(`Decimals not found for token ${mint}`);
        } catch (e: any) {
            return Err(`Failed to fetch decimals for ${mint}: ${e.message}`);
        }
    }

    private mapRowToDTO(row: any): TokenDTO {
        return {
            id: row.id,
            mint: row.mint,
            tickerSymbol: row.ticker_symbol,
            name: row.name,
            decimals: row.decimals,
            priceServer: row.price_server,
            exchangeServer: row.exchange_server,
            priceTracking: row.price_tracking === 1,
            stableCoinOfficial: row.stable_coin_official === 1,
            stableCoinAlt: row.stable_coin_alt === 1,
            createdAtMs: row.created_at_ms,
            updatedAtMs: row.updated_at_ms,
        };
    }
}
