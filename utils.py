import collections, sys
import logging
import pdb
from datetime import datetime, timezone
from itertools import chain
import traceback

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

seats = ('p1', 'p2')

def opp(p):
    return seats[p=='p1']

import collections.abc


# apply all ops to the base modifier, then apply the final modifier
# e.g. starting hp 15, -2 base dmg, -1, x2 = -6 -> 9hp
mod_table = {
    'add': lambda x, y: x + y,
    'mul': lambda x, y: x * y,
}
def combine_numeric_modifiers(mods):
    final_mod = 0
    for mod in mods:
        final_mod = mod_table[mod[0]](final_mod, mod[1])
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
    if not u:
        return d
    for k, v in u.items():
        if v == 'del':
            del d[k]
        elif k == 'dins':  # 'delta insert'
            if 'ins' in d:
                d['ins'].append(v)
            else:
                d['ins'] = [v]
        elif type(v) is tuple:
            if k not in d:
                d[k] = v
            else:
                if type(d[k]) is tuple:
                    d[k] = tuple(list(d[k]) + list(v))
                elif type(d[k]) is int:
                    base = d[k] if k in d else 0
                    d[k] = base + combine_numeric_modifiers(v)
                else:
                    raise RuntimeError(f"Don't put tuples ({v}) on {d[k]}")
        elif k in d and type(d[k]) is tuple:
            raise RuntimeError(f"Don't put {v} on tuples ({d[k]})")
        elif k in d and isinstance(d[k], list):
            if isinstance(v, list):
                d[k] = v
                continue
            if 'deletes' in v:
                d[k] = filter(lambda i, x: i not in v['deletes'], enumerate(d[k]))
            if 'del_values' in v:
                for del_val in v['del_values']:
                    d[k].remove(del_val)
            if 'ins' in v:
                d[k].extend(v['ins'])

        elif isinstance(v, collections.abc.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            try:
                d[k] = v
            except:
                s()
    return d

def add_message(delta, message):
    update(delta, {'meta': {'message': {'ins': [message]}}})

def damage(delta, who, amt, mul=False):
    if mul:
        update(delta, {who: {'hp': (('mul', amt),)}})
    else:
        update(delta, {who: {'hp': (('add', -amt),)}})

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


def empty_delta():
    return Box({'meta': {'message': []}})