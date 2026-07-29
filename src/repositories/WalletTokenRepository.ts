// repositories/WalletTokenRepository.ts
import { db } from '../db';
import { Ok, Err, Result } from '../types/result';
import { WalletTokenDTO } from '../types/dtos';

export class WalletTokenRepository {
    // Ensure a (walletId, tokenMint) mapping exists; create if missing.
    ensureExists(
        walletId: number,
        tokenMint: string,
        isNative: boolean = false,
        isOfficialStable: boolean = false,
        isAltStable: boolean = false
    ): Result<WalletTokenDTO, string> {
        try {
            const existing = db
            .query('SELECT * FROM wallet_token_table WHERE wallet_id = ? AND token_mint = ?')
            .get(walletId, tokenMint) as any;
            if (existing) {
                return Ok(this.mapRowToDTO(existing));
            }

            // Verify token exists in token_table (foreign key will catch, but we check)
            const tokenExists = db.query('SELECT 1 FROM token_table WHERE mint = ?').get(tokenMint);
            if (!tokenExists) {
                return Err(`Cannot link WalletToken: Token mint '${tokenMint}' does not exist in token_table.`);
            }

            const nowMs = Date.now();
            const insert = db.run(
                `INSERT INTO wallet_token_table (
                    wallet_id, token_mint, audited_amount_lamports, audited_time_ms,
                    ata_exists, rent_paid, is_native, is_official_stable, is_alt_stable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                                  walletId, tokenMint, 0, nowMs,
                                  0, 0,
                                  isNative ? 1 : 0,
                                  isOfficialStable ? 1 : 0,
                                  isAltStable ? 1 : 0
            );
            const id = insert.lastInsertRowid as number;
            const row = db.query('SELECT * FROM wallet_token_table WHERE id = ?').get(id);
            return Ok(this.mapRowToDTO(row));
        } catch (e: any) {
            return Err(`Database error securing wallet token: ${e.message}`);
        }
    }

    // Additional methods used by PositionRepository (like findAllByWallet) can be added if needed.

    private mapRowToDTO(row: any): WalletTokenDTO {
        return {
            id: row.id,
            walletId: row.wallet_id,
            tokenMint: row.token_mint,
            auditedAmountLamports: row.audited_amount_lamports,
            auditedTimeMs: row.audited_time_ms,
            ataExists: row.ata_exists === 1,
            rentPaid: row.rent_paid === 1,
            ataCreatedTimeMs: row.ata_created_time_ms,
            lastBalanceChangeMs: row.last_balance_change_ms,
            lastSyncMs: row.last_sync_ms,
            isNative: row.is_native === 1,
            isOfficialStable: row.is_official_stable === 1,
            isAltStable: row.is_alt_stable === 1,
        };
    }
}
