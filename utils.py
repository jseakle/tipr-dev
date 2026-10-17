import collections, sys
import itertools
import logging
import pdb
from datetime import datetime, timezone
from itertools import chain
import traceback
from copy import deepcopy
from numbers import Real

from box import Box as oBox
from pdb import set_trace as s

def nothing():
    pass
#s = nothing

def b(e):
    logging.warning(traceback.format_exc(e))


CREATED = 0
ACTIVE = 1  # one at a time, others are paused
PAUSED = 2
FINISHED = 3

DEFAULT = -1
ROCK = 0
PAPER = 1
SCISSORS = 2
TYPES = {-1: '???', 0: 'Rock', 1: 'Paper', 2: 'Scissors'}
TYPELIST = ['Rock', 'Paper', 'Scissors']

TRUCE = 9
INCOME = 10

seats = ('p1', 'p2')

YELLOW = '#ffdb0d'
BLUE = '#008CBA'
RED = '#f44336'
GREEN = '#4CAF50'
WHITE = '#FFF'

def opp(p):
    if isinstance(p, str):
        return seats[p=='p1']
    return seats[not p]

import collections.abc


# apply all ops to the base modifier, then apply the final modifier
# e.g. starting hp 15, -2 base dmg, -1, x2 = -6 -> 9hp
mod_table = {
    'add': lambda x, y: x + y,
    'mul': lambda x, y: x * y,
}
def combine_numeric_modifiers(mods):
    final_mod = 0
    for operation, amount in mods:
        if operation not in mod_table or not isinstance(amount, Real) or isinstance(amount, bool):
            raise ValueError(f"Invalid numeric modifier: {(operation, amount)!r}")
        final_mod = mod_table[operation](final_mod, amount)
    return final_mod

# handling numbers:
# update = False, ie, we're working on a delta
# existing, new:
#   nothing, number or tuple -> new value
#   number, number -> new number
#   number, tuple -> error. the idea is that numbers are for meta stuff and tuples are for gamestate vals
#   tuple, number -> error
#   (str, num), tuple -> (old tuple, new tuple)
#   (tup, tup), tuple -> (tup, tup, new tuple)
# update = True
#   nothing, number -> number
#   nothing, tuple -> tupleops(0). maybe. the idea is that this could handle "counters" in the future
#   number, number -> new number
#   number, tuple -> tupleops(number)
def update(d, u):
    """Apply a delta in place, without retaining references to it.

    Numeric operations describe a change from zero, added to the existing
    number. JSON arrays of operations are accepted when replaying saved deltas.
    """
    if not isinstance(d, collections.abc.MutableMapping):
        raise TypeError("The update target must be a mutable mapping")
    if u is None:
        return d
    if not isinstance(u, collections.abc.Mapping):
        raise TypeError("An update must be a mapping")
    for k, v in u.items():
        if isinstance(v, str) and v == 'del':
            del d[k]
        elif k == 'dins':
            d.setdefault('ins', []).append(deepcopy(v))
        elif k == 'ins' and k in d and isinstance(d[k], list) and isinstance(v, (list, tuple)):
            d[k].extend(deepcopy(v))
        else:
            d[k] = _updated_value(d.get(k), v, missing=k not in d)
    return d


def _numeric_operations(value):
    return (isinstance(value, (tuple, list)) and bool(value)
            and all(isinstance(op, (tuple, list)) and len(op) == 2
                    and isinstance(op[0], str) and op[0] in mod_table
                    for op in value))


def _updated_value(current, patch, missing=False):
    if isinstance(patch, collections.abc.Mapping) and 'replace' in patch:
        if len(patch) != 1:
            raise ValueError("A replacement cannot contain other patch operations")
        return deepcopy(patch['replace'])
    if patch is None:
        return None
    if isinstance(patch, tuple) and isinstance(current, Real) and not _numeric_operations(patch):
        raise ValueError(f"Invalid numeric operations: {patch!r}")
    if _numeric_operations(patch) and (isinstance(patch, tuple)
                                      or isinstance(current, Real)
                                      or isinstance(current, tuple)):
        operations = tuple(tuple(op) for op in patch)
        combine_numeric_modifiers(operations)
        if missing:
            return operations
        if isinstance(current, (tuple, list)) and _numeric_operations(current):
            return tuple(tuple(op) for op in current) + operations
        if isinstance(current, Real) and not isinstance(current, bool):
            return current + combine_numeric_modifiers(operations)
        raise TypeError(f"Cannot apply numeric operations to {current!r}")
    if isinstance(current, tuple) and _numeric_operations(current):
        raise TypeError(f"Cannot replace numeric operations with {patch!r}")
    if isinstance(patch, collections.abc.Mapping):
        if isinstance(current, list):
            return _updated_list(current, patch)
        if missing:
            current = {}
        if not isinstance(current, collections.abc.MutableMapping):
            raise TypeError(f"Cannot apply a mapping patch to {current!r}; use replace")
        return update(current, patch)
    return deepcopy(patch)


def _list_index(value, length):
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Invalid list index: {value!r}")
    if not 0 <= value < length:
        raise IndexError(f"List index out of range: {value}")
    return value


def _updated_list(current, patch):
    operations = {'deletes', 'del_values', 'ins', 'dins', 'set', 'rep', 'upd'}
    if unknown := set(patch) - operations:
        raise ValueError(f"Unknown list patch operations: {sorted(unknown)}")
    result = deepcopy(current)
    deleted = {_list_index(index, len(result)) for index in patch.get('deletes', [])}
    result = [value for index, value in enumerate(result) if index not in deleted]
    for value in patch.get('del_values', []):
        result.remove(value)
    if 'ins' in patch:
        if not isinstance(patch['ins'], (list, tuple)):
            raise TypeError("List inserts must be a sequence")
        result.extend(deepcopy(patch['ins']))
    if 'dins' in patch:
        result.append(deepcopy(patch['dins']))
    if 'set' in patch:
        index, value = patch['set']
        result[_list_index(index, len(result))] = deepcopy(value)
    if 'rep' in patch:
        if not isinstance(patch['rep'], list):
            raise TypeError("A list replacement must be a list")
        result = deepcopy(patch['rep'])
    for index, delta in patch.get('upd', {}).items():
        index = _list_index(index, len(result))
        result[index] = _updated_value(result[index], delta)
    return result


class NoChange(object):
    pass

def gen_patch(state1, state2, rec=False):
    """Produce a JSON-replayable patch for nested game state values."""
    if isinstance(state1, collections.abc.Mapping) and isinstance(state2, collections.abc.Mapping):
        if rec and ('replace' in state1 or 'replace' in state2):
            return {'replace': deepcopy(state2)}
        result = {}
        for key in dict.fromkeys(chain(state1, state2)):
            if key not in state2:
                result[key] = 'del'
            elif key not in state1:
                result[key] = {'replace': deepcopy(state2[key])}
            else:
                change = gen_patch(state1[key], state2[key], True)
                if change is not NoChange:
                    result[key] = change
        return result if result or not rec else NoChange
    if isinstance(state1, list) and isinstance(state2, list):
        if len(state1) == len(state2):
            changes = {}
            for index, (before, after) in enumerate(zip(state1, state2)):
                change = gen_patch(before, after, True)
                if change is not NoChange:
                    changes[index] = change
            return {'upd': changes} if changes else (NoChange if rec else {})
        if len(state2) > len(state1) and all(
                gen_patch(before, after, True) is NoChange
                for before, after in zip(state1, state2)):
            return {'ins': deepcopy(state2[len(state1):])}
        return {'rep': deepcopy(state2)}
    if type(state1) is type(state2) and state1 == state2:
        return NoChange if rec else {}
    if isinstance(state2, (collections.abc.Mapping, list)) or state2 == 'del':
        return {'replace': deepcopy(state2)}
    return deepcopy(state2)
    
def add_message(delta, message):
    update(delta, {'meta': {'message': {'ins': [message]}}})

def damage(delta, who, amt, mul=False):
    if mul:
        update(delta, {who: {'hp': (('mul', amt),)}})
    else:
        update(delta, {who: {'hp': (('add', -amt),)}})

def shields(delta, who, count):
    update(delta, {who: {'shields': {'n': (('add', count),), 'this_turn': (('add', count),)}}})

def mzip(*lists):
    if not lists:
        return [[]]
    max_len = max(map(len, lists))
    return zip(*(l + [None] * (max_len - len(l)) for l in lists))

def luple(l):
    return set(map(tuple, l))

def unluple(s):
    return list(map(list, s))

def tznow():
    return datetime.now(timezone.utc)

class Box(oBox):

    def __new__(self, *args, **kwargs):
        kwargs['box_class'] = self.__class__
        return oBox.__new__(self, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        kwargs['box_class'] = self.__class__
        super(Box, self).__init__(*args, **kwargs)
        
    def __getattr__(self, name):
        if name in ['del_values']:
            setattr(self, name, [])
        return super(Box, self).__getattr__(name)

    # enable assignment to possibly new fields even when a key on the path is a variable
    # box.get(var).foo = 5 doesn't work
    def ga(self, name):
        try:
            return self.__getattr__(name)
        except KeyError:
            setattr(self, name, {})
            return self.__getattr__(name)

def descendants(cls):
    subclasses = cls.__subclasses__()
    if subclasses:
        return itertools.chain(subclasses, itertools.chain.from_iterable(map(descendants, subclasses)))
    return []

def empty_delta():
    return Box({'meta': {'message': []}})
