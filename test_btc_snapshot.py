import unittest

from btc_snapshot import CALIBRATION_START, HOUR, HOLDOUT_START, LISTING_START, candle_rows


class CandleRowsTest(unittest.TestCase):
    def setUp(self):
        self.start = CALIBRATION_START
        self.candles = [
            [self.start - HOUR, 100, 100, 100, 100, 1],
            [self.start, 99, 101, 100, 99, 1],
            [self.start + HOUR, 99, 102, 100, 100, 1],
        ]

    def test_rows_use_prior_hour_and_respect_requested_window(self):
        outside = [self.start - 2 * HOUR, 1, 2, 1, 2, 1]
        self.assertEqual(candle_rows([outside, *reversed(self.candles)], self.start, 2), [
            [f"BTC-USD:1h:{self.start}", 1, 201],
            [f"BTC-USD:1h:{self.start + HOUR}", 201, 301],
        ])

    def test_rejects_missing_duplicate_and_invalid_ohlc(self):
        bad_open = [self.start, 99, 101, 102, 100, 1]
        for candles in (self.candles[1:], self.candles + self.candles[:1],
                        [self.candles[0], bad_open, self.candles[2]]):
            with self.subTest(candles=candles), self.assertRaises(ValueError):
                candle_rows(candles, self.start, 2)

    def test_features_and_targets_do_not_overlap_across_splits(self):
        self.assertLess(CALIBRATION_START + 191 * HOUR, LISTING_START - HOUR)
        self.assertLess(LISTING_START + 63 * HOUR, HOLDOUT_START - HOUR)
