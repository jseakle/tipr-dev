import collections, sys
from itertools import chain

from box import Box as oBox
CREATED = 0
ACTIVE = 1
PAUSED = 2
FINISHED = 3

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
def apply_numeric_modifiers(value, mods):
    final_mod = 0
    for mod in mods:
        final_mod = mod_table[mod[0]](final_mod, mod[1])
    return value + final_mod

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
def update(d, u, update_numbers=False):
    if not u:
        return d
    for k, v in u.items():
        if v == 'del':
            del d[k]
        elif type(v) is tuple:
            if update_numbers:
                if k in d:
                    d[k] = apply_numeric_modifiers(d[k], v)
                else:
                    d[k] = apply_numeric_modifiers(0, v)
            else:
                if k not in d:
                    d[k] = v
                else:
                    match d[k]:
                        case (str(), _) as t:
                            d[k] = (t, v)
                        case (tuple(), _) as t:
                            d[k] = tuple(chain(t, (v,)))
                        case _:
                            raise RuntimeError(f"Don't put tuples on {type(d[k])}s")
        elif k in d and type(d[k]) is tuple:
            raise RuntimeError(f"Don't put {type(v)} on tuples")
        elif isinstance(d[k], list):
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
            d[k] = v
    return d

def mzip(*lists):
    max_len = max(map(len, lists))
    return zip(*(l + [None] * (max_len - len(l)) for l in lists))

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


empty_delta = Box({'meta': {'message': ''}})


class inject(object):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*args, **kwargs):
            old_trace = sys.gettrace()
            def tracefn(frame, event, arg):
                # define a new tracefn each time, since it needs to
                # call the *current* tracefn if they're in debug mode
                frame.f_locals.update(self.kwargs)
                if old_trace:
                    return old_trace(frame, event, arg)
                else:
                    return None

            sys.settrace(tracefn)
            try:
                retval = fn(*args, **kwargs)
            finally:
                sys.settrace(old_trace)
            return retval

        return wrapped

    def into(self, fn, *args, **kwargs):
        return self(fn)(*args, **kwargs)

# no debugging allowed
class prod_inject(object):
    def __init__(self, **kwargs):
        self.kwargs = kwargs

        def _tracefn(frame, event, arg):
            frame.f_locals.update(self.kwargs)
            return None
        self.tracefn = _tracefn

    def __call__(self, fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*args, **kwargs):

            old_trace = sys.gettrace()
            sys.settrace(self.tracefn)
            try:
                retval = fn(*args, **kwargs)
            finally:
                sys.settrace(old_trace)
            return retval

        return wrapped

    def into(self, fn, *args, **kwargs):
        return self(fn)(*args, **kwargs)
