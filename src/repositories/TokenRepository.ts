// repositories/TokenRepository.ts
import { db } from '../db';
import { TokenDTO } from '../types/dtos';
import { RecordNotFoundException } from '../errors/databaseErrors';

export class TokenRepository {
    addOrUpdate(
        mint: string,
        tickerSymbol?: string | null,
        name?: string | null,
        decimals?: number | null,
        stableCoinOfficial: boolean = false,
        stableCoinAlt: boolean = false,
        priceTracking: boolean = true
    ): TokenDTO {
        const nowMs = Date.now();

        // Check if token exists
        const existing = db.query('SELECT * FROM token_table WHERE mint = ?').get(mint) as any;

        if (!existing) {
            // INSERT
            const insert = db.run(
                `INSERT INTO token_table (
                    mint, ticker_symbol, name, decimals, price_server, exchange_server,
                    price_tracking, stable_coin_official, stable_coin_alt,
                    is_selected, selected_at_ms,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                mint,
                tickerSymbol ?? mint.slice(0, 8),
                name ?? 'Unknown Token',
                decimals ?? null,
                'jupiter',
                'jupiter',
                priceTracking ? 1 : 0,
                stableCoinOfficial ? 1 : 0,
                stableCoinAlt ? 1 : 0,
                0,
                null,
                nowMs,
                nowMs
            );
            const id = insert.lastInsertRowid as number;
            const row = db.query('SELECT * FROM token_table WHERE id = ?').get(id);
            return this.mapRowToDTO(row);
        } else {
            // UPDATE only missing fields
            let needsUpdate = false;
            const updates: Record<string, unknown> = {};
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
            return this.mapRowToDTO(fresh);
        }
    }

    findByMint(mint: string): TokenDTO | null {
        const row = db.query('SELECT * FROM token_table WHERE mint = ?').get(mint) as any;
        return row ? this.mapRowToDTO(row) : null;
    }

    getDecimals(mint: string): number {
        const row = db.query('SELECT decimals FROM token_table WHERE mint = ?').get(mint) as any;
        if (row && row.decimals !== null && row.decimals !== undefined) {
            return row.decimals;
        }
        throw new RecordNotFoundException('Token Decimals', mint);
    }

    /** All tokens currently marked as selected. */
    getSelected(): TokenDTO[] {
        const rows = db
            .query('SELECT * FROM token_table WHERE is_selected = 1')
            .all() as any[];
        return rows.map(row => this.mapRowToDTO(row));
    }

    /** Mark a single token as selected or not. Token must already exist. */
    setSelected(mint: string, selected: boolean): void {
        const nowMs = Date.now();
        const result = db.run(
            `UPDATE token_table
             SET is_selected = ?, selected_at_ms = ?, updated_at_ms = ?
             WHERE mint = ?`,
            selected ? 1 : 0,
            selected ? nowMs : null,
            nowMs,
            mint
        );
        if (result.changes === 0) {
            throw new RecordNotFoundException('Token', mint);
        }
    }

    /** Clear the selected flag on every token. */
    clearAllSelected(): void {
        const nowMs = Date.now();
        db.run(
            `UPDATE token_table
             SET is_selected = 0, selected_at_ms = NULL, updated_at_ms = ?
             WHERE is_selected = 1`,
            nowMs
        );
    }

    /**
     * Replace the entire selected set with the given mints.
     * Clears is_selected on everything, then sets it on the provided mints.
     * Tokens that do not exist yet are ignored (caller should ensure they exist first).
     */
    replaceSelectedMints(mints: string[]): void {
        const nowMs = Date.now();
        const uniqueMints = [...new Set(mints)];

        db.transaction(() => {
            db.run(
                `UPDATE token_table
                 SET is_selected = 0, selected_at_ms = NULL, updated_at_ms = ?
                 WHERE is_selected = 1`,
                nowMs
            );

            if (uniqueMints.length === 0) return;

            const placeholders = uniqueMints.map(() => '?').join(', ');
            db.run(
                `UPDATE token_table
                 SET is_selected = 1, selected_at_ms = ?, updated_at_ms = ?
                 WHERE mint IN (${placeholders})`,
                nowMs,
                nowMs,
                ...uniqueMints
            );
        })();
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
            isSelected: row.is_selected === 1,
            selectedAtMs: row.selected_at_ms ?? null,
            createdAtMs: row.created_at_ms,
            updatedAtMs: row.updated_at_ms,
        };
    }
}
