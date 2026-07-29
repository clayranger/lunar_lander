// Shared DTOs
export interface TokenDTO {
    id: number;
    mint: string;
    tickerSymbol: string | null;
    name: string | null;
    decimals: number | null;
    priceServer: string | null;
    exchangeServer: string | null;
    priceTracking: boolean;
    stableCoinOfficial: boolean;
    stableCoinAlt: boolean;
    createdAtMs: number | null;
    updatedAtMs: number | null;
}

export interface WalletTokenDTO {
    id: number;
    walletId: number;
    tokenMint: string;
    auditedAmountLamports: number;
    auditedTimeMs: number | null;
    ataExists: boolean;
    rentPaid: boolean;
    ataCreatedTimeMs: number | null;
    lastBalanceChangeMs: number | null;
    lastSyncMs: number | null;
    isNative: boolean;
    isOfficialStable: boolean;
    isAltStable: boolean;
}

export interface PositionDTO {
    id: number;
    walletTokenId: number;
    amount: number;
    purchasePriceUsdc: number | null;
    salePriceUsdc: number | null;
    purchaseTimeMs: number | null;
    saleTimeMs: number | null;
    buyFeeNativeLamports: number | null;
    buyFeeStablecoin: number | null;
    sellFeeNativeLamports: number | null;
    sellFeeStablecoin: number | null;
    revenueAtSaleStablecoin: number | null;
    priorityFeeLamports: number;
    buyTxId: string | null;
    sellTxId: string | null;
    isClosed: boolean;
    positionType: number;
}
