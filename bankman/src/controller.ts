import { Request, Response } from 'express';
import { quoteResponse, usdc_decimal_differencer, JupGlobals, getTokenMetadata, getNewWallet } from '../src/jupiter';
import bs58 from 'bs58';
export namespace AppGlobals {
    type Token = {
        multiplier: number;
        decimals: number;
    }
    export const tokens: Dictionary <string, Token> = { };
}

export const getTest = (req: Request, res: Response) => {

 res.json({
   message: 'Hello World',
 });
};

//https://medium.com/@elchuo160/exploring-solana-wallets-with-quicknode-a-comprehensive-guide-2023-f141f5441b24#:~:text=To%20create%20a%20wallet%20in%20Solana%2C%20we%E2%80%99ll%20employ,console.log%28%27Solana%20Wallet%3A%27%2C%20SolanaWallet%29%3B%20console.log%28%27Solana%20Wallet%20Public%20Key%3A%27%2C%20SolanaWallet.publicKey%29%3B
export const createWallet = async (req: Request, res: Response) => {
    console.log("i am createwallet");
    let new_wallet = await getNewWallet();
    if (new_wallet == null) {
        res.json({
            message: 'failure',
        });
    } else {
        res.json({
            pub: new_wallet.publicKeyArray.toBase58(),
            private: new_wallet.secretKeyArray,
        });
    }

};

export const getWalletContents = async (req: Request, res: Response) => {
    console.log("i am getWalletContents");
    let new_wallet = await getNewWallet();
    if (new_wallet == null) {
        res.json({
            message: 'failure',
        });
    } else {
        res.json({
            pub: new_wallet.publicKeyArray.toBase58(),
            private: new_wallet.secretKeyArray,
        });
    }

};

export const getMeta = async (req: Request, res: Response) => {
    let tempToken;
    if ((req.params.tokenId) in JupGlobals.meta_tokens) {
        //check for and get decimals
    } else {
        tempToken = await getTokenMetadata(req.params.tokenId);
        if (tempToken != null) {
            JupGlobals.meta_tokens[req.params.tokenId] = tempToken;
        } else {
            console.log("error in getMeta");
            res.json({
                error: "error"
            });
            return;
        }
        //JupGlobals.meta_tokens[req.params.tokenId] = await getTokenMetadata(req.params.tokenId);




    }
    console.log(JupGlobals.meta_tokens[req.params.tokenId])
    res.json({
        name: JupGlobals.meta_tokens[req.params.tokenId].name,
        symbol: JupGlobals.meta_tokens[req.params.tokenId].symbol
    });
};

export const getQuote = async (req: Request, res: Response) => {
    //Return fee as well as quote
    if ((req.params.tokenId) in AppGlobals.tokens) {
        //console.log("found entry");
    } else {
        AppGlobals.tokens[req.params.tokenId] = await usdc_decimal_differencer(req.params.tokenId);
    }
    //console.log('out of db got:' + AppGlobals.tokens[req.params.tokenId].multiplier)
    try {
        let words = await quoteResponse(req.params.tokenId, AppGlobals.tokens[req.params.tokenId].multiplier);
        let price = (words.outAmount / words.inAmount) * AppGlobals.tokens[req.params.tokenId].multiplier;
        res.json({
            dollar: price,
            decimals: AppGlobals.tokens[req.params.tokenId].decimals
        });
    } catch (errorz: unknown) {
        console.log('Server did not respond as expected');
        console.log(errorz.message)
        res.json({
            ERROR: "SERVER_ERROR",
            dollar: undefined
        });
    }

    //if the token has less decimans than usdc (6) then move decimal left for each zero
    //if token has more decimals more right for each zero


};

