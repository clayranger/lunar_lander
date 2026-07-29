// repositories/PositionRepository.ts
import { db } from '../db';
import { Ok, Err, Result } from '../types/result';
import { PositionDTO } from '../types/dtos';
import { TokenRepository } from './TokenRepository';
import { WalletTokenRepository } from './WalletTokenRepository';

export enum PositionType {
    INVESTMENT = 0,
    GAS = 1,
    TAX = 2,
    SAVINGS = 3,
    UNKNOWN = 4,
}

export interface ReclassificationResult {
    updatedSourcePosition: PositionDTO;
    newOrUpdatedTargetPosition: PositionDTO;
}

export class PositionRepository {
    private tokenRepository: TokenRepository;
    private walletTokenRepository: WalletTokenRepository;

    constructor(
        tokenRepo?: TokenRepository,
        walletTokenRepo?: WalletTokenRepository
    ) {
        this.tokenRepository = tokenRepo ?? new TokenRepository();
        this.walletTokenRepository = walletTokenRepo ?? new WalletTokenRepository();
    }

    // ---------- Public: identify unknown platform position ----------
    identifyUnknownPlatformPosition(
        amount: number,
        walletId: number,
        tokenMint: string,
        positionType: number = PositionType.UNKNOWN,
        decimals?: number | null
    ): Result<PositionDTO, string> {
        // 1. Ensure token exists
        const tokenResult = this.tokenRepository.findByMint(tokenMint);
        if (!tokenResult.ok) return Err(tokenResult.error);
        let token = tokenResult.value;
        if (!token) {
            if (decimals == null) {
                return Err(`Unable to add token '${tokenMint}': Decimals are missing.`);
            }
            const addResult = this.tokenRepository.addOrUpdate(tokenMint, undefined, undefined, decimals);
            if (!addResult.ok) return Err(`Failed to auto-register missing token '${tokenMint}': ${addResult.error}`);
            token = addResult.value;
        }

        // 2. Ensure WalletToken mapping
        const wtResult = this.walletTokenRepository.ensureExists(walletId, tokenMint);
        if (!wtResult.ok) return Err(`Failed to ensure wallet token mapping: ${wtResult.error}`);
        const walletToken = wtResult.value;

        // 3. Create position
        return this.create(walletToken.id, amount, positionType);
    }

    // ---------- Public reclassification helpers ----------
    changeSavingsToInvestment(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.INVESTMENT, PositionType.SAVINGS);
    }
    changeSavingsToTax(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.SAVINGS);
    }
    changeSavingsToGas(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.SAVINGS);
    }
    changeInvestmentToSavings(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.SAVINGS, PositionType.INVESTMENT);
    }
    changeInvestmentToTax(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.INVESTMENT);
    }
    changeInvestmentToGas(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.INVESTMENT);
    }
    changeUnknownToInvestment(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.INVESTMENT, PositionType.UNKNOWN);
    }
    changeUnknownToTax(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.UNKNOWN);
    }
    changeUnknownToGas(sourceId: number, amount: number) {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.UNKNOWN);
    }

    // ---------- Private: reclassify amount (core) ----------
    private reclassifyAmount(
        sourcePositionId: number,
        amountToMove: number,
        targetType: PositionType,
        expectedSourceType: PositionType
    ): Result<ReclassificationResult, string> {
        if (amountToMove <= 0) {
            return Err('Amount to move must be strictly positive.');
        }

        return db.transaction(() => {
            try {
                // Fetch open source position
                const sourceRow = db
                .query('SELECT * FROM position_table WHERE id = ? AND is_closed = 0')
                .get(sourcePositionId) as any;
                if (!sourceRow) {
                    return Err(`Open position ${sourcePositionId} not found.`);
                }
                const sourceDTO = this.mapRowToDTO(sourceRow);

                if (sourceDTO.positionType !== expectedSourceType) {
                    return Err(`Position ${sourcePositionId} is type ${sourceDTO.positionType}, expected ${expectedSourceType}.`);
                }
                if (sourceDTO.amount < amountToMove) {
                    return Err(`Cannot move ${amountToMove} from position ${sourcePositionId}. Available: ${sourceDTO.amount}.`);
                }

                if (sourceDTO.amount === amountToMove) {
                    // Full move – just update the type
                    db.run('UPDATE position_table SET position_type = ? WHERE id = ?', targetType, sourcePositionId);
                    const updatedRow = db.query('SELECT * FROM position_table WHERE id = ?').get(sourcePositionId);
                    const updatedDTO = this.mapRowToDTO(updatedRow);
                    return Ok({
                        updatedSourcePosition: updatedDTO,
                        newOrUpdatedTargetPosition: updatedDTO,
                    });
                } else {
                    // Partial split
                    const remainingAmount = sourceDTO.amount - amountToMove;
                    db.run('UPDATE position_table SET amount = ? WHERE id = ?', remainingAmount, sourcePositionId);
                    const updatedSourceRow = db.query('SELECT * FROM position_table WHERE id = ?').get(sourcePositionId);

                    // Insert new position for the moved amount
                    const newId = db.run(
                        `INSERT INTO position_table (
                            wallet_token_id, amount, purchase_price_usdc, purchase_time_ms,
                            buy_fee_native_lamports, buy_fee_stablecoin, priority_fee_lamports,
                            buy_tx_id, is_closed, position_type
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                                         sourceDTO.walletTokenId,
                                         amountToMove,
                                         sourceDTO.purchasePriceUsdc,
                                         Date.now(),
                                         null, // buy fees not transferred on split
                                         null,
                                         0,
                                         sourceDTO.buyTxId,
                                         0,
                                         targetType
                    ).lastInsertRowid;
                    const newTargetRow = db.query('SELECT * FROM position_table WHERE id = ?').get(newId);

                    return Ok({
                        updatedSourcePosition: this.mapRowToDTO(updatedSourceRow),
                              newOrUpdatedTargetPosition: this.mapRowToDTO(newTargetRow),
                    });
                }
            } catch (e: any) {
                return Err(`Database error during reclassification: ${e.message}`);
            }
        }) as Result<ReclassificationResult, string>;
    }

    // ---------- Private: divide position (prorates fees) ----------
    private dividePosition(
        id: number,
        amountToSplit: number,
        newPositionType?: PositionType | null
    ): Result<PositionDTO, string> {
        return db.transaction(() => {
            try {
                const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
                if (!existing) return Err(`Position with ID ${id} not found.`);
                if (existing.is_closed === 1) return Err(`Cannot divide closed position ${id}.`);

                const originalAmount = existing.amount;
                if (amountToSplit <= 0) return Err('Split amount must be positive.');
                if (amountToSplit >= originalAmount) {
                    return Err(
                        `Split amount (${amountToSplit}) must be less than position full amount (${originalAmount}).`
                    );
                }

                const remainderAmount = originalAmount - amountToSplit;

                // Helper to split numeric fields proportionally
                const splitLong = (total: number | null): [number | null, number | null] => {
                    if (total == null) return [null, null];
                    const splitShare = Math.round((total / originalAmount) * amountToSplit);
                    return [splitShare, total - splitShare];
                };
                const splitDouble = (total: number | null): [number | null, number | null] => {
                    if (total == null) return [null, null];
                    const splitShare = (total / originalAmount) * amountToSplit;
                    return [splitShare, total - splitShare];
                };

                const [buyFeeNativeSplit, buyFeeNativeRemainder] = splitLong(existing.buy_fee_native_lamports);
                const [buyFeeStableSplit, buyFeeStableRemainder] = splitDouble(existing.buy_fee_stablecoin);
                const [priorityFeeSplit, priorityFeeRemainder] = splitLong(existing.priority_fee_lamports);

                // Create new position for the split-off amount
                const newPosResult = this.create(
                    existing.wallet_token_id,
                    amountToSplit,
                    existing.purchase_price_usdc,
                    existing.purchase_time_ms,
                    buyFeeNativeSplit ?? undefined,
                    buyFeeStableSplit ?? undefined,
                    priorityFeeSplit ?? 0,
                    existing.buy_tx_id,
                    newPositionType ?? existing.position_type
                );
                if (!newPosResult.ok) return Err(`Failed creating split-off position: ${newPosResult.error}`);
                const newPos = newPosResult.value;

                // Update original position with reduced amount and fees
                const updateResult = this.update(
                    id,
                    remainderAmount,
                    undefined, undefined, undefined, undefined,
                    buyFeeNativeRemainder ?? undefined,
                    buyFeeStableRemainder ?? undefined,
                    undefined, undefined, undefined,
                    priorityFeeRemainder ?? undefined,
                    undefined, undefined,
                    undefined
                );
                if (!updateResult.ok) {
                    return Err(`Split-off position created, but failed shrinking original: ${updateResult.error}`);
                }

                return Ok(newPos);
            } catch (e: any) {
                return Err(`Database error dividing position ${id}: ${e.message}`);
            }
        }) as Result<PositionDTO, string>;
    }

    // ---------- Private: create ----------
    private create(
        walletTokenId: number,
        amount: number,
        purchasePriceUsdc?: number | null,
        purchaseTimeMs?: number | null,
        buyFeeNativeLamports?: number | null,
        buyFeeStablecoin?: number | null,
        priorityFeeLamports: number = 0,
        buyTxId?: string | null,
        positionType: number = PositionType.INVESTMENT
    ): Result<PositionDTO, string> {
        try {
            const now = purchaseTimeMs ?? Date.now();
            const id = db.run(
                `INSERT INTO position_table (
                    wallet_token_id, amount, purchase_price_usdc, purchase_time_ms,
                    buy_fee_native_lamports, buy_fee_stablecoin, priority_fee_lamports,
                    buy_tx_id, is_closed, position_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                              walletTokenId, amount,
                              purchasePriceUsdc ?? null,
                              now,
                              buyFeeNativeLamports ?? null,
                              buyFeeStablecoin ?? null,
                              priorityFeeLamports,
                              buyTxId ?? null,
                              0,
                              positionType
            ).lastInsertRowid;
            const row = db.query('SELECT * FROM position_table WHERE id = ?').get(id);
            return Ok(this.mapRowToDTO(row));
        } catch (e: any) {
            return Err(`Database error creating position: ${e.message}`);
        }
    }

    // ---------- Public: finders ----------
    findById(id: number): Result<PositionDTO | null, string> {
        try {
            const row = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
            return Ok(row ? this.mapRowToDTO(row) : null);
        } catch (e: any) {
            return Err(`Database error fetching position ${id}: ${e.message}`);
        }
    }

    findOpenByWalletTokenId(walletTokenId: number): Result<PositionDTO[], string> {
        try {
            const rows = db
            .query('SELECT * FROM position_table WHERE wallet_token_id = ? AND is_closed = 0')
            .all(walletTokenId) as any[];
            return Ok(rows.map(row => this.mapRowToDTO(row)));
        } catch (e: any) {
            return Err(`Database error fetching open positions for walletTokenId ${walletTokenId}: ${e.message}`);
        }
    }

    findAllByWalletTokenId(walletTokenId: number): Result<PositionDTO[], string> {
        try {
            const rows = db
            .query('SELECT * FROM position_table WHERE wallet_token_id = ?')
            .all(walletTokenId) as any[];
            return Ok(rows.map(row => this.mapRowToDTO(row)));
        } catch (e: any) {
            return Err(`Database error fetching positions for walletTokenId ${walletTokenId}: ${e.message}`);
        }
    }

    // ---------- Private: close position ----------
    private closePosition(
        id: number,
        salePriceUsdc: number | null,
        saleTimeMs?: number | null,
        sellFeeNativeLamports?: number | null,
        sellFeeStablecoin?: number | null,
        revenueAtSaleStablecoin?: number | null,
        sellTxId?: string | null
    ): Result<PositionDTO, string> {
        try {
            const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
            if (!existing) return Err(`Position with ID ${id} not found.`);
            if (existing.is_closed === 1) return Err(`Position ${id} is already closed.`);

            const now = saleTimeMs ?? Date.now();
            db.run(
                `UPDATE position_table SET
                sale_price_usdc = ?,
                sale_time_ms = ?,
                sell_fee_native_lamports = ?,
                sell_fee_stablecoin = ?,
                revenue_at_sale_stablecoin = ?,
                sell_tx_id = ?,
                is_closed = 1
                WHERE id = ?`,
                salePriceUsdc ?? null,
                now,
                sellFeeNativeLamports ?? null,
                sellFeeStablecoin ?? null,
                revenueAtSaleStablecoin ?? null,
                sellTxId ?? null,
                id
            );
            const row = db.query('SELECT * FROM position_table WHERE id = ?').get(id);
            return Ok(this.mapRowToDTO(row));
        } catch (e: any) {
            return Err(`Database error closing position ${id}: ${e.message}`);
        }
    }

    // ---------- Private: general update ----------
    private update(
        id: number,
        amount?: number | null,
        purchasePriceUsdc?: number | null,
        salePriceUsdc?: number | null,
        purchaseTimeMs?: number | null,
        saleTimeMs?: number | null,
        buyFeeNativeLamports?: number | null,
        buyFeeStablecoin?: number | null,
        sellFeeNativeLamports?: number | null,
        sellFeeStablecoin?: number | null,
        revenueAtSaleStablecoin?: number | null,
        priorityFeeLamports?: number | null,
        buyTxId?: string | null,
        sellTxId?: string | null,
        isClosed?: boolean | null,
        positionType?: number | null
    ): Result<PositionDTO, string> {
        try {
            const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
            if (!existing) return Err(`Position with ID ${id} not found.`);

            const updates: any = {};
            if (amount !== undefined && amount !== null) updates.amount = amount;
            if (purchasePriceUsdc !== undefined) updates.purchase_price_usdc = purchasePriceUsdc;
            if (salePriceUsdc !== undefined) updates.sale_price_usdc = salePriceUsdc;
            if (purchaseTimeMs !== undefined && purchaseTimeMs !== null) updates.purchase_time_ms = purchaseTimeMs;
            if (saleTimeMs !== undefined && saleTimeMs !== null) updates.sale_time_ms = saleTimeMs;
            if (buyFeeNativeLamports !== undefined && buyFeeNativeLamports !== null) updates.buy_fee_native_lamports = buyFeeNativeLamports;
            if (buyFeeStablecoin !== undefined && buyFeeStablecoin !== null) updates.buy_fee_stablecoin = buyFeeStablecoin;
            if (sellFeeNativeLamports !== undefined && sellFeeNativeLamports !== null) updates.sell_fee_native_lamports = sellFeeNativeLamports;
            if (sellFeeStablecoin !== undefined && sellFeeStablecoin !== null) updates.sell_fee_stablecoin = sellFeeStablecoin;
            if (revenueAtSaleStablecoin !== undefined && revenueAtSaleStablecoin !== null) updates.revenue_at_sale_stablecoin = revenueAtSaleStablecoin;
            if (priorityFeeLamports !== undefined && priorityFeeLamports !== null) updates.priority_fee_lamports = priorityFeeLamports;
            if (buyTxId !== undefined) updates.buy_tx_id = buyTxId;
            if (sellTxId !== undefined) updates.sell_tx_id = sellTxId;
            if (isClosed !== undefined && isClosed !== null) updates.is_closed = isClosed ? 1 : 0;
            if (positionType !== undefined && positionType !== null) updates.position_type = positionType;

            if (Object.keys(updates).length > 0) {
                const setClause = Object.keys(updates).map(k => `${k} = ?`).join(', ');
                const values = Object.values(updates);
                db.run(`UPDATE position_table SET ${setClause} WHERE id = ?`, ...values, id);
            }

            const row = db.query('SELECT * FROM position_table WHERE id = ?').get(id);
            return Ok(this.mapRowToDTO(row));
        } catch (e: any) {
            return Err(`Database error updating position ${id}: ${e.message}`);
        }
    }

    // ---------- Private: delete ----------
    private delete(id: number): Result<void, string> {
        try {
            const result = db.run('DELETE FROM position_table WHERE id = ?', id);
            if (result.changes > 0) {
                return Ok(undefined);
            } else {
                return Err(`Position with ID ${id} not found for deletion.`);
            }
        } catch (e: any) {
            return Err(`Database error deleting position ${id}: ${e.message}`);
        }
    }

    // ---------- Mapper ----------
    private mapRowToDTO(row: any): PositionDTO {
        return {
            id: row.id,
            walletTokenId: row.wallet_token_id,
            amount: row.amount,
            purchasePriceUsdc: row.purchase_price_usdc,
            salePriceUsdc: row.sale_price_usdc,
            purchaseTimeMs: row.purchase_time_ms,
            saleTimeMs: row.sale_time_ms,
            buyFeeNativeLamports: row.buy_fee_native_lamports,
            buyFeeStablecoin: row.buy_fee_stablecoin,
            sellFeeNativeLamports: row.sell_fee_native_lamports,
            sellFeeStablecoin: row.sell_fee_stablecoin,
            revenueAtSaleStablecoin: row.revenue_at_sale_stablecoin,
            priorityFeeLamports: row.priority_fee_lamports,
            buyTxId: row.buy_tx_id,
            sellTxId: row.sell_tx_id,
            isClosed: row.is_closed === 1,
            positionType: row.position_type,
        };
    }
}
