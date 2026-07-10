from .base import BaseCollector
from .ebay import EbayCollector
from .yahoo_auctions import YahooAuctionsCollector

COLLECTORS = {
    "ebay": EbayCollector,
    "yahoo_auctions": YahooAuctionsCollector,
}
