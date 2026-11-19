import copy
import unittest

from btc_value import measured_outcome, price_preview


def rows(start, count):
    # Rising ranges make this deliberately nonstationary training task learnable.
    return [[f'BTC-USD:1h:{1704067200 + hour * 3600}', hour + 1, hour + 2]
            for hour in range(start, start + count)]


class BTCValueTests(unittest.TestCase):
    def setUp(self):
        self.full = rows(192, 64)
        self.sample = self.full[::8]
        self.benchmark = {'calibration': rows(0, 192), 'holdout': rows(256, 64)}

    def price(self, sample=None, benchmark=None, price=1, gas=1, budget=10000, reward=100):
        return price_preview(self.sample if sample is None else sample,
                             self.benchmark if benchmark is None else benchmark,
                             price, gas, budget, reward, listing_start=1704067200 + 192 * 3600)

    def test_current_sample_and_only_prior_benchmark_can_set_price(self):
        receipt = self.price()
        self.assertEqual(receipt, self.price(list(reversed(self.sample)), {'calibration': self.benchmark['calibration']}))
        self.assertEqual(receipt['decision'], 'buy')
        shifted = [[key, x + 100000, y + 100000] for key, x, y in self.sample]
        self.assertEqual(self.price(shifted)['decision'], 'pass')
        shifted_targets = [[key, x, y + 100000] for key, x, y in self.sample]
        self.assertEqual(self.price(shifted_targets)['decision'], 'pass')
        self.assertGreater(int(receipt['estimated_value_base_units']), 2)
        self.assertEqual(self.price(budget=1)['decision'], 'pass')
        self.assertEqual(self.price(price=int(receipt['estimated_value_base_units']), gas=0)['decision'], 'pass')
        self.assertEqual(self.price(reward=0)['decision'], 'pass')

    def test_full_listing_must_begin_after_calibration_even_if_none_of_the_eight_overlap(self):
        with self.assertRaisesRegex(ValueError, "overlaps buyer calibration"):
            price_preview(self.sample, self.benchmark, 1, 0, 1000, 100,
                          listing_start=1704067200 + 191 * 3600)

    def test_after_delivery_measures_holdout_and_checks_sample(self):
        result = measured_outcome(self.sample, self.full, self.benchmark)
        self.assertGreater(result['realized_gain_bps'], 0)
        self.assertAlmostEqual(result['retained_mae_bps'] - result['full_mae_bps'], result['realized_gain_bps'], places=5)
        altered = copy.deepcopy(self.full)
        altered[0][2] += 1
        with self.assertRaises(ValueError):
            measured_outcome(self.sample, altered, self.benchmark)
        with self.assertRaises(ValueError):
            measured_outcome(self.sample, self.full, dict(self.benchmark, holdout=self.full))

    def test_invalid_inputs_and_time_leakage(self):
        for args in ({'sample': self.sample[:7]}, {'sample': [self.sample[0]]*8},
                     {'price': float('nan')}, {'gas': -1}, {'budget': True},
                     {'benchmark': {'calibration': rows(100, 192)}}):
            with self.subTest(args=list(args)), self.assertRaises(ValueError):
                self.price(**args)

if __name__ == '__main__':
    unittest.main()
