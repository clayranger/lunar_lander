import express from 'express';
import { getMeta, getTest, getQuote, createWallet, getWalletContents } from '../src/controller';


export const router = express.Router();


router.get('/test', getTest);
router.get('/get_meta/:tokenId', getMeta);
router.get('/get_quote/:tokenId', getQuote);
router.get('/create_wallet', createWallet);
router.get('/get_wallet_contents/:walletId', getWalletContents);