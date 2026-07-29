// services/tokenSelector.ts
import { processingPoolService, type ProcessingPoolEntryDTO } from './processingPool';
import { TokenRepository } from '../repositories/TokenRepository';
import type { TokenDTO } from '../types/dtos';

/**
 * Keeps token_table.is_selected in sync with the current processing pool.
 *
 * Flow on refresh():
 *  1. Optionally pull a fresh pool from the scoring service.
 *  2. Ensure every pool entry exists in token_table (addOrUpdate).
 *  3. Replace the selected set so only current pool mints are flagged.
 */
export class TokenSelector {
    private refreshing = false;
    private lastRefreshMs: number | null = null;
    private lastError: string | null = null;
    private autoRefreshHandle: ReturnType<typeof setInterval> | null = null;

    constructor(
        private readonly tokenRepository: TokenRepository = new TokenRepository()
    ) {}

    /** Tokens currently marked selected in the DB. */
    getSelected(): TokenDTO[] {
        return this.tokenRepository.getSelected();
    }

    getLastRefreshMs(): number | null {
        return this.lastRefreshMs;
    }

    getLastError(): string | null {
        return this.lastError;
    }

    /**
     * Sync selected tokens to the current processing pool.
     *
     * @param refreshPool - if true (default), call processingPoolService.refresh() first
     * @returns the TokenDTOs that are now selected
     */
    async refresh(refreshPool: boolean = true): Promise<TokenDTO[]> {
        if (this.refreshing) {
            throw new Error('TokenSelector refresh already in progress');
        }
        this.refreshing = true;

        try {
            if (refreshPool) {
                const poolResult = await processingPoolService.refresh();
                if (!poolResult.ok) {
                    // Keep last-known pool; still apply whatever is in memory
                    this.lastError = poolResult.error;
                    // If we have never successfully loaded a pool, surface the error
                    if (processingPoolService.getPool().length === 0) {
                        throw new Error(poolResult.error);
                    }
                } else {
                    this.lastError = null;
                }
            }

            const pool: readonly ProcessingPoolEntryDTO[] = processingPoolService.getPool();
            const mints = pool.map(entry => entry.mint);

            // Ensure every pool token is registered (fills decimals etc. from the pool)
            for (const entry of pool) {
                this.tokenRepository.addOrUpdate(
                    entry.mint,
                    undefined,
                    undefined,
                    entry.decimals
                );
            }

            // Atomically replace the selected set
            this.tokenRepository.replaceSelectedMints(mints);

            this.lastRefreshMs = Date.now();
            return this.tokenRepository.getSelected();
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            this.lastError = message;
            throw err;
        } finally {
            this.refreshing = false;
        }
    }

    /** Poll refresh() on a fixed interval. Safe to call once at startup. */
    startAutoRefresh(intervalMinutes: number): void {
        this.stopAutoRefresh();
        const intervalMs = intervalMinutes * 60_000;
        this.autoRefreshHandle = setInterval(() => {
            void this.refresh().catch(err => {
                console.error('[TokenSelector] auto-refresh failed:', err);
            });
        }, intervalMs);
    }

    stopAutoRefresh(): void {
        if (this.autoRefreshHandle) {
            clearInterval(this.autoRefreshHandle);
            this.autoRefreshHandle = null;
        }
    }
}

// Shared singleton
export const tokenSelector = new TokenSelector();
