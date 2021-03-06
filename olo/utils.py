from __future__ import absolute_import

import re
import json
import threading
import dateparser
from warnings import warn
from functools import wraps
from ast import literal_eval
from datetime import datetime, date

from .compat import Decimal


def camel2underscore(name):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class Missing(object):

    def __eq__(self, other):
        return isinstance(other, self.__class__)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __nonzero__(self):
        return False

    __bool__ = __nonzero__


missing = Missing()


def deprecation(msg):
    warn(msg, DeprecationWarning, stacklevel=2)


keywords = {
    'select',
    'insert',
    'update',
    'into',
    'values',
    'from',
    'and',
    'or',
    'null',
    'group by',
    'order by',
    'desc',
    'asc',
    'limit',
    'offset',
    'where',
    'in',
    'sum',
    'count',
    'avg',
    'max',
    'min',
    'group_concat',
    'as',
}


# crude implementation
def upper_keywords(sql):
    l = [sql] + list(keywords)
    return reduce(
        lambda x, y: (
            re.sub(
                r'(\s+|[:punct:]+|^){}(\(|\s+|[:punct:]+|$)'.format(y),
                r'\1{}\2'.format(y.upper()),
                x,
                flags=re.IGNORECASE
            )
        ), l)


def type_checker(type_, v):
    if isinstance(type_, type) and isinstance(v, type_):
        return True
    t = type(type_)
    if t != type(v):
        return False
    if t is list:
        if len(type_) == 0:
            return isinstance(v, t)
        _t = type_[0]
        for e in v:
            r = type_checker(_t, e)
            if not r:
                return False
        return True
    elif t is tuple:
        if len(type_) != len(v):
            return False
        for i, e in enumerate(v):
            r = type_checker(type_[i], e)
            if not r:
                return False
        return True
    elif t is dict:
        items = type_.items()
        if len(items) == 0:
            return isinstance(v, t)
        kt, vt = items[0]
        for k, v in v.iteritems():
            if not type_checker(kt, k) or not type_checker(vt, v):
                return False
        return True
    return False


def transform_type(v, type_):
    if isinstance(type_, type) and isinstance(v, type_):
        return v
    if type_ is str:
        if isinstance(v, unicode):
            return v.encode('utf-8')
        elif isinstance(v, (list, dict)):
            return json.dumps(v)
        return type_(v)
    if type_ is unicode:
        if isinstance(v, str):
            return v.decode('utf-8')
        return type_(v)
    if type_ in (list, dict):
        if isinstance(v, basestring):
            v = json.loads(v)
            if isinstance(v, type_):
                return v
        return type_(v)
    if type_ in (datetime, date):
        v = dateparser.parse(v)
        if type_ is date:
            return v.date()
        return v
    if type_ is tuple:
        if isinstance(v, basestring):
            v = literal_eval(v)
            if isinstance(v, type_):
                return v
        return tuple(v)
    if callable(type_):
        if type_ is Decimal:
            return type_(str(v))
        return type_(v)
    t = type(type_)
    if t in (list, dict) and isinstance(v, basestring):
        v = json.loads(v)
    if not isinstance(v, t):
        raise TypeError('{} is not a {} type.'.format(repr(v), t))
    if isinstance(v, list):
        l = []
        for e in v:
            l.append(transform_type(e, type_[0]))
        return l
    elif isinstance(v, dict):
        d = {}
        items = type_.items()
        kt, vt = items[0]
        for k, v in v.iteritems():
            k = transform_type(k, kt)
            v = transform_type(v, vt)
            d[k] = v
        return d
    return v


class ThreadedObject(object):
    def __init__(self, cls, *args, **kw):
        self.local = threading.local()
        self._args = (cls, args, kw)

        def creator():
            return cls(*args, **kw)

        self.creator = creator

    def __getstate__(self):
        return self._args

    def __setstate__(self, state):
        cls, args, kw = state
        self.__init__(cls, *args, **kw)

    def __getattr__(self, name):
        obj = getattr(self.local, 'obj', None)
        if obj is None:
            self.local.obj = obj = self.creator()
        return getattr(obj, name)


class cached_property(object):

    def __init__(self, func, name=None, doc=None):
        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func

    def __set__(self, obj, value):
        obj.__dict__[self.__name__] = value

    def __get__(self, obj, type=None):
        if obj is None:
            return self  # pragma: no cover
        value = obj.__dict__.get(self.__name__, missing)
        if value is missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value


def readonly_cached_property(func):
    attr_name = '_%s' % func.__name__

    @property
    @wraps(func)
    def _(self):
        if attr_name not in self.__dict__:
            setattr(self, attr_name, func(self))
        return self.__dict__[attr_name]

    return _


def override(func):
    setattr(func, '_override', True)
    return func


_OPERATOR_PRECEDENCES = (
    ('*', '/', '%', 'DIV', 'MOD'),
    ('-', '+'),
    ('<<', '>>'),
    ('=', '!=', '>', '<', '>=', '<=', 'IN', 'IS', 'IS NOT', 'NOT IN'),
    ('BETWEEN', 'CASE'),
    ('AND', '&&'),
    ('OR', '||'),
)


OPERATOR_PRECEDENCES = {
    item: idx
    for idx, items in enumerate(reversed(_OPERATOR_PRECEDENCES))
    for item in items
}


UNARY_NEG_OPERATOR = {
    '-': '+'
}


UNARY_NEG_OPERATOR = dict({
    v: k
    for k, v in UNARY_NEG_OPERATOR.iteritems()
}, **UNARY_NEG_OPERATOR)


BINARY_NEG_OPERATOR = {
    'IN': 'NOT IN',
    'IS': 'IS NOT',
    '=': '!=',
    '>': '<=',
    '<': '>='
}


BINARY_NEG_OPERATOR = dict({
    v: k
    for k, v in BINARY_NEG_OPERATOR.iteritems()
}, **BINARY_NEG_OPERATOR)


def get_neg_operator(op, is_unary=False):
    op = op.strip().upper()
    if is_unary:
        return UNARY_NEG_OPERATOR.get(op)  # pragma: no cover
    return BINARY_NEG_OPERATOR.get(op)


def get_operator_precedence(operator):
    return OPERATOR_PRECEDENCES.get(operator, -1)


def compare_operator_precedence(a, b):
    ap = get_operator_precedence(a.upper())
    bp = get_operator_precedence(b.upper())
    if ap == bp:
        return 0
    if ap > bp:
        return 1
    return -1


def sql_and_params(v, coerce=str):
    if hasattr(v, 'get_sql_and_params'):
        return v.get_sql_and_params()
    return coerce(v), []


def get_sql_pieces_and_params(exps, coerce=str):
    pieces = []
    params = []

    for exp in exps:
        piece, _params = sql_and_params(exp)
        pieces.append(piece)
        if _params:
            params.extend(_params)

    return pieces, params


def friendly_repr(v):
    if isinstance(v, unicode):
        return "u'%s'" % v.encode('utf-8')
    if isinstance(v, bytes):
        return "b'%s'" % v
    return repr(v)


def is_under_thread():
    return threading.current_thread().name != 'MainThread'


def make_thread_safe_class(base, method_names=()):
    __class__ = type('', (base,), {})

    def __init__(self, *args, **kwargs):
        super(__class__, self).__init__(*args, **kwargs)
        self.lock = threading.RLock()

    __class__.__init__ = __init__

    def make_method(name):
        def method(self, *args, **kwargs):
            with self.lock:
                return getattr(super(__class__, self), name)(*args, **kwargs)
        method.__name__ = name
        return method

    for name in method_names:
        setattr(__class__, name, make_method(name))

    return __class__


ThreadSafeDict = make_thread_safe_class(dict, method_names=(
    '__getitem__', '__setitem__', '__contains__',
    'get', 'set', 'pop', 'popitem', 'setdefault', 'update'
))


SQL_PATTERNS = {
    'select': re.compile(r'select\s.*?\sfrom\s+`?(?P<table>\w+)`?',
                         re.I | re.S),
    'insert': re.compile(r'insert\s+(ignore\s+)?(into\s+)?`?(?P<table>\w+)`?',
                         re.I),
    'update': re.compile(r'update\s+(ignore\s+)?`?(?P<table>\w+)`?\s+set',
                         re.I),
    'replace': re.compile(r'replace\s+(into\s+)?`?(?P<table>\w+)`?', re.I),
    'delete': re.compile(r'delete\s+from\s+`?(?P<table>\w+)`?', re.I),
}


def parse_execute_sql(sql):
    sql = sql.lstrip()
    cmd = sql.split(' ', 1)[0].lower()

    if cmd not in SQL_PATTERNS:
        raise Exception('SQL command %s is not yet supported' % cmd)

    match = SQL_PATTERNS[cmd].match(sql)
    if not match:
        raise Exception(sql)

    table = match.group('table')

    return cmd, table
