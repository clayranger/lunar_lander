// repositories/PositionRepository.ts
import { db } from '../db';
import { PositionDTO } from '../types/dtos';
import { TokenRepository } from './TokenRepository';
import { WalletTokenRepository } from './WalletTokenRepository';
import {
    RecordNotFoundException,
    InvalidPositionStateException,
    InsufficientBalanceException,
    PositionTypeMismatchException,
    TokenRegistrationException,
    DatabaseException
} from '../errors/databaseErrors';

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
    ): PositionDTO {
        // 1. Ensure token exists
        let token = this.tokenRepository.findByMint(tokenMint);
        if (!token) {
            if (decimals == null) {
                throw new TokenRegistrationException(tokenMint, 'Decimals are missing.');
            }
            token = this.tokenRepository.addOrUpdate(tokenMint, undefined, undefined, decimals);
        }

        // 2. Ensure WalletToken mapping
        const walletToken = this.walletTokenRepository.ensureExists(walletId, tokenMint);

        // 3. Create position
        return this.create(walletToken.id, amount, positionType);
    }

    // ---------- Public reclassification helpers ----------
    changeSavingsToInvestment(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.INVESTMENT, PositionType.SAVINGS);
    }
    changeSavingsToTax(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.SAVINGS);
    }
    changeSavingsToGas(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.SAVINGS);
    }
    changeInvestmentToSavings(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.SAVINGS, PositionType.INVESTMENT);
    }
    changeInvestmentToTax(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.INVESTMENT);
    }
    changeInvestmentToGas(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.INVESTMENT);
    }
    changeUnknownToInvestment(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.INVESTMENT, PositionType.UNKNOWN);
    }
    changeUnknownToTax(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.TAX, PositionType.UNKNOWN);
    }
    changeUnknownToGas(sourceId: number, amount: number): ReclassificationResult {
        return this.reclassifyAmount(sourceId, amount, PositionType.GAS, PositionType.UNKNOWN);
    }

    // ---------- Private: reclassify amount (core) ----------
    private reclassifyAmount(
        sourcePositionId: number,
        amountToMove: number,
        targetType: PositionType,
        expectedSourceType: PositionType
    ): ReclassificationResult {
        if (amountToMove <= 0) {
            throw new DatabaseException('Amount to move must be strictly positive.');
        }

        // Standard exception throwing inside db.transaction() ensures automatic rollback if anything fails
        return db.transaction(() => {
            const sourceRow = db
            .query('SELECT * FROM position_table WHERE id = ? AND is_closed = 0')
            .get(sourcePositionId) as any;

            if (!sourceRow) {
                throw new RecordNotFoundException('Position', sourcePositionId);
            }
            const sourceDTO = this.mapRowToDTO(sourceRow);

            if (sourceDTO.positionType !== expectedSourceType) {
                throw new PositionTypeMismatchException(sourcePositionId, sourceDTO.positionType, expectedSourceType);
            }
            if (sourceDTO.amount < amountToMove) {
                throw new InsufficientBalanceException(sourcePositionId, amountToMove, sourceDTO.amount);
            }

            if (sourceDTO.amount === amountToMove) {
                // Full move – just update the type
                db.run('UPDATE position_table SET position_type = ? WHERE id = ?', targetType, sourcePositionId);
                const updatedRow = db.query('SELECT * FROM position_table WHERE id = ?').get(sourcePositionId);
                const updatedDTO = this.mapRowToDTO(updatedRow);
                return {
                    updatedSourcePosition: updatedDTO,
                    newOrUpdatedTargetPosition: updatedDTO,
                };
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

                return {
                    updatedSourcePosition: this.mapRowToDTO(updatedSourceRow),
                              newOrUpdatedTargetPosition: this.mapRowToDTO(newTargetRow),
                };
            }
        })();
    }

    // ---------- Private: divide position (prorates fees) ----------
    private dividePosition(
        id: number,
        amountToSplit: number,
        newPositionType?: PositionType | null
    ): PositionDTO {
        return db.transaction(() => {
            const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
            if (!existing) throw new RecordNotFoundException('Position', id);
            if (existing.is_closed === 1) {
                throw new InvalidPositionStateException(id, 'Position is already closed.');
            }

            const originalAmount = existing.amount;
            if (amountToSplit <= 0) {
                throw new DatabaseException('Split amount must be positive.');
            }
            if (amountToSplit >= originalAmount) {
                throw new DatabaseException(
                    `Split amount (${amountToSplit}) must be less than position full amount (${originalAmount}).`
                );
            }

            const remainderAmount = originalAmount - amountToSplit;

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
            const newPos = this.create(
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

            // Update original position with reduced amount and fees
            this.update(
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

            return newPos;
        })();
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
    ): PositionDTO {
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
        return this.mapRowToDTO(row);
    }

    // ---------- Public: finders ----------
    findById(id: number): PositionDTO | null {
        const row = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
        return row ? this.mapRowToDTO(row) : null;
    }

    findOpenByWalletTokenId(walletTokenId: number): PositionDTO[] {
        const rows = db
        .query('SELECT * FROM position_table WHERE wallet_token_id = ? AND is_closed = 0')
        .all(walletTokenId) as any[];
        return rows.map(row => this.mapRowToDTO(row));
    }

    findAllByWalletTokenId(walletTokenId: number): PositionDTO[] {
        const rows = db
        .query('SELECT * FROM position_table WHERE wallet_token_id = ?')
        .all(walletTokenId) as any[];
        return rows.map(row => this.mapRowToDTO(row));
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
    ): PositionDTO {
        const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
        if (!existing) throw new RecordNotFoundException('Position', id);
        if (existing.is_closed === 1) {
            throw new InvalidPositionStateException(id, 'Position is already closed.');
        }

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
        return this.mapRowToDTO(row);
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
    ): PositionDTO {
        const existing = db.query('SELECT * FROM position_table WHERE id = ?').get(id) as any;
        if (!existing) throw new RecordNotFoundException('Position', id);

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
        return this.mapRowToDTO(row);
    }

    // ---------- Private: delete ----------
    private delete(id: number): void {
        const result = db.run('DELETE FROM position_table WHERE id = ?', id);
        if (result.changes === 0) {
            throw new RecordNotFoundException('Position', id);
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
