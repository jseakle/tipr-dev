import collections, sys

from box import Box as oBox
CREATED = 0
ACTIVE = 1
PAUSED = 2
FINISHED = 3

ROCK = 0
PAPER = 1
SCISSORS = 2

def opp(p):
    return ('p1', 'p2')[p=='p1']

import collections.abc

def update(d, u):
    if not u:
        return d
    for k, v in u.items():
        if v == 'del':
            del d[k]
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


class Box(oBox):
    def __getattr__(self, item):

        if item in ['del_values']:
            setattr(self, item, [])

        return super(Box, self).__getattr__(item)

    def ga(self, item):
        try:
            return self.__getattr__(item)
        except KeyError:
            return None


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
