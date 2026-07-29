import { processingPoolService } from './processingPool';

processingPoolService.startAutoRefresh(15_000); // or call refresh() wherever you trigger it now
