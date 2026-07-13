from .base import BaseCollector
from .ebay import EbayCollector
from .yahoo_auctions import YahooAuctionsCollector
from .yahoo_flea import YahooFleaCollector
from .yahoo_flea_sold import YahooFleaSoldCollector
from .yahoo_seller import YahooSellerCollector

COLLECTORS = {
    "ebay": EbayCollector,
    "yahoo_auctions": YahooAuctionsCollector,
    "yahoo_flea": YahooFleaCollector,
    "yahoo_flea_sold": YahooFleaSoldCollector,
    "yahoo_seller": YahooSellerCollector,
}
