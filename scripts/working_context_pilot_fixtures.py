"""Frozen synthetic coding tasks and independent unittest oracles for the pilot.

Only stub, contract, and history are copied into an agent's repository.
Reference implementations validate the grader before any provider call.
"""

TASKS = [
    {
        "id": "expiry",
        "goal": "Implement expiration and lookup for Cache in solution.py.",
        "stub": """class Cache:
    def __init__(self, clock):
        self.clock = clock
        self.entries = {}

    def put(self, key, value, ttl):
        raise NotImplementedError

    def get(self, key, default=None):
        raise NotImplementedError

    def purge(self):
        raise NotImplementedError
""",
        "contract": """Cache(clock) uses the injected clock, never wall time.
put(key,value,ttl) overwrites an entry with deadline clock()+ttl.
ttl=None means no expiration. ttl<=0 removes the existing key immediately.
get(key,default=None) returns the stored value, including None, before deadline;
at or after deadline remove the entry and return default. Missing keys return default.
purge() removes all expired entries and returns their count; immortal entries survive.
Keep all public method signatures and use only Python standard library.
""",
        "stale": "Expiration is strictly after the deadline; ttl=0 means immortal.",
        "reference": """class Cache:
    def __init__(self, clock):
        self.clock = clock
        self.entries = {}
    def put(self, key, value, ttl):
        if ttl is not None and ttl <= 0:
            self.entries.pop(key, None)
        else:
            self.entries[key] = (value, None if ttl is None else self.clock() + ttl)
    def get(self, key, default=None):
        if key not in self.entries:
            return default
        value, deadline = self.entries[key]
        if deadline is not None and self.clock() >= deadline:
            del self.entries[key]
            return default
        return value
    def purge(self):
        now = self.clock()
        expired = [k for k, (_, d) in self.entries.items() if d is not None and now >= d]
        for k in expired:
            del self.entries[k]
        return len(expired)
""",
        "tests": """import unittest
from solution import Cache
class Checks(unittest.TestCase):
    def setUp(self):
        self.now = 10
        self.c = Cache(lambda: self.now)
    def test_boundary(self):
        self.c.put('x', 7, 5)
        self.now = 14.99
        self.assertEqual(self.c.get('x'), 7)
        self.now = 15
        self.assertEqual(self.c.get('x', 'miss'), 'miss')
        self.assertEqual(self.c.purge(), 0)
    def test_zero_removes(self):
        self.c.put('x', 7, None)
        self.c.put('x', 9, 0)
        self.assertEqual(self.c.get('x', 'miss'), 'miss')
    def test_negative_removes(self):
        self.c.put('x', 7, None)
        self.c.put('x', 9, -2)
        self.assertEqual(self.c.get('x', 'miss'), 'miss')
    def test_none_value(self):
        self.c.put('x', None, None)
        self.now = 100000
        self.assertIsNone(self.c.get('x', 'miss'))
    def test_overwrite(self):
        self.c.put('x', 7, 5)
        self.now = 14
        self.c.put('x', 9, 8)
        self.now = 15
        self.assertEqual(self.c.get('x'), 9)
    def test_purge(self):
        self.c.put('a', 1, 2)
        self.c.put('b', 2, 4)
        self.c.put('c', 3, None)
        self.now = 14
        self.assertEqual(self.c.purge(), 2)
        self.assertEqual(self.c.purge(), 0)
        self.assertEqual(self.c.get('c'), 3)
""",
    },
    {
        "id": "ledger",
        "goal": "Implement replay-safe Ledger.apply in solution.py.",
        "stub": """class Ledger:
    def __init__(self):
        self.balances = {}
        self.seen = {}
    def apply(self, events):
        raise NotImplementedError
""",
        "contract": """Ledger has balances and seen dictionaries.
apply(events) accepts a list of dictionaries with id, account, amount.
id/account must be nonempty strings. amount must be an int, excluding bool.
Each new id changes that account balance by amount. Same id/account/amount replay is ignored,
both across calls and within one batch. Conflicting reuse of an id raises ValueError.
Any malformed event raises ValueError. The whole batch is atomic: on error neither balances
nor seen changes. Do not mutate input. Keep zero balances. Return a detached balances copy.
Keep public signatures, no dependencies beyond Python standard library.
""",
        "stale": "Apply valid events before an invalid event; duplicate ids always ignored.",
        "reference": """class Ledger:
    def __init__(self):
        self.balances = {}
        self.seen = {}
    def apply(self, events):
        balances, seen = self.balances.copy(), self.seen.copy()
        for e in events:
            if not isinstance(e, dict):
                raise ValueError('event')
            key, account, amount = e.get('id'), e.get('account'), e.get('amount')
            if not isinstance(key, str) or not key or not isinstance(account, str) or not account:
                raise ValueError('identity')
            if type(amount) is not int:
                raise ValueError('amount')
            value = (account, amount)
            if key in seen:
                if seen[key] != value:
                    raise ValueError('conflict')
                continue
            seen[key] = value
            balances[account] = balances.get(account, 0) + amount
        self.balances, self.seen = balances, seen
        return balances.copy()
""",
        "tests": """import copy
import unittest
from solution import Ledger
def event(i, amount=3, account='a'):
    return dict(id=i, account=account, amount=amount)
class Checks(unittest.TestCase):
    def test_replays(self):
        x = Ledger()
        self.assertEqual(x.apply([event('1'), event('1')]), {'a': 3})
        self.assertEqual(x.apply([event('1')]), {'a': 3})
    def test_conflict_atomic(self):
        x = Ledger()
        x.apply([event('1')])
        before = copy.deepcopy((x.balances, x.seen))
        with self.assertRaises(ValueError):
            x.apply([event('2'), event('1', 9)])
        self.assertEqual((x.balances, x.seen), before)
    def test_bad_atomic(self):
        for bad in [True, 1.0, '2', None]:
            x = Ledger()
            with self.assertRaises(ValueError):
                x.apply([event('1'), event('2', bad)])
            self.assertEqual(x.balances, {})
            self.assertEqual(x.seen, {})
    def test_input_and_output_detached(self):
        x = Ledger()
        events = [event('1')]
        before = copy.deepcopy(events)
        result = x.apply(events)
        result['a'] = 999
        self.assertEqual(x.balances, {'a': 3})
        self.assertEqual(events, before)
    def test_zero_and_accounts(self):
        self.assertEqual(Ledger().apply([event('1'), event('2', -3), event('3', 9, 'b')]),
                         {'a': 0, 'b': 9})
    def test_invalid_identity(self):
        for bad in [{}, None, event(''), event('x', account=''),
                    event(7), event('x', account=7)]:
            x = Ledger()
            with self.assertRaises(ValueError):
                x.apply([event('valid'), bad])
            self.assertEqual(x.balances, {})
            self.assertEqual(x.seen, {})
""",
    },
    {
        "id": "intervals",
        "goal": "Implement normalize_intervals in solution.py.",
        "stub": """def normalize_intervals(intervals):
    raise NotImplementedError
""",
        "contract": """normalize_intervals(intervals) returns sorted half-open integer intervals.
Validate every input pair: exactly two integer endpoints, excluding bool; start <= end.
Invalid input raises ValueError. Ignore empty intervals (start==end) after validation.
Merge overlapping intervals, including nested/duplicate ranges. Adjacent ranges stay separate:
[(1,3),(3,5)] remains two intervals. Negative endpoints are valid. Never mutate the input.
Return a list of tuples. Keep signature; Python standard library only.
""",
        "stale": "Merge adjacent intervals as well as overlapping ones; discard malformed ranges.",
        "reference": """def normalize_intervals(intervals):
    valid = []
    for pair in intervals:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('pair')
        a, b = pair
        if type(a) is not int or type(b) is not int or a > b:
            raise ValueError('bounds')
        if a != b:
            valid.append((a, b))
    result = []
    for a, b in sorted(valid):
        if result and a < result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result
""",
        "tests": """import copy
import unittest
from solution import normalize_intervals as norm
class Checks(unittest.TestCase):
    def test_touching(self):
        self.assertEqual(norm([(3,5),(1,3)]), [(1,3),(3,5)])
    def test_overlap_and_nested(self):
        self.assertEqual(norm([(5,9),(1,7),(2,3),(1,7)]), [(1,9)])
    def test_negative_empty(self):
        self.assertEqual(norm([(0,0),(-5,-2),(-3,1)]), [(-5,1)])
        self.assertEqual(norm([]), [])
    def test_validation(self):
        for pair in [(4,2),(True,3),(1,False),(1.0,3),(1,),None,'ab']:
            with self.assertRaises(ValueError):
                norm([(0,2),pair])
    def test_no_mutation(self):
        source = [[5,9],[1,3]]
        before = copy.deepcopy(source)
        self.assertEqual(norm(source), [(1,3),(5,9)])
        self.assertEqual(source, before)
    def test_chain(self):
        self.assertEqual(norm([(8,10),(1,4),(3,6),(6,9)]), [(1,6),(6,10)])
""",
    },
]
