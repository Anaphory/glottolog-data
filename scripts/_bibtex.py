# bibtex.py - basic bibtex file parsing

import io
import re
import mmap
import string
import StringIO
import contextlib
import collections

from pybtex.database.input.bibtex import BibTeXEntryIterator, Parser
from pybtex.scanner import PybtexSyntaxError
from pybtex.exceptions import PybtexError
from pybtex.textutils import whitespace_re
from pybtex.bibtex.utils import split_name_list
from pybtex.database import Person

import latexcodec
assert u'\xe4'.encode('latex') == r'\"a'

__all__ = [
    'load', 'iterentries', 'names',
    'save', 'dump',
    'check',
]

FIELDORDER = [
    'author', 'editor', 'title', 'booktitle', 'journal',
    'school', 'publisher', 'address',
    'series', 'volume', 'number', 'pages', 'year', 'issn', 'url',
]

VERBATIM = {'doi', 'eprint', 'file', 'url', 'pdf', 'fn', 'fnnote'}

# TODO: bracket escapes r'\?\[\\u\d+\]' (possilbly with five digits)
# FIXME: tex-escape/character entity mix in anla.bib titlealt


@contextlib.contextmanager
def memorymapped(filename, access=mmap.ACCESS_READ):
    fd = open(filename)
    try:
        m = mmap.mmap(fd.fileno(), 0,  access=access)
    except:
        fd.close()
        raise
    try:
        yield m
    finally:
        m.close()
        fd.close()


def load(filename, encoding=None, use_pybtex=True, preserve_order=False):
    cls = collections.OrderedDict if preserve_order else dict
    return cls(iterentries(filename, encoding, use_pybtex))


def iterentries(filename, encoding=None, use_pybtex=True):
    if not use_pybtex:
        if encoding not in (None, 'ascii'):
            raise NotImplementedError
        import bib
        with memorymapped(filename) as source:
            for bibkey, entrytype, fields in bib.pitems(source):
                yield bibkey, (entrytype, fields)  
    elif encoding is None:
        with memorymapped(filename) as source:
            try:
                for entrytype, (bibkey, fields) in BibTeXEntryIterator(source):
                    fields = {name.lower():
                        whitespace_re.sub(' ', ''.join(values).strip())
                        for name, values in fields}
                    yield bibkey, (entrytype, fields)
            except PybtexSyntaxError as e:
                debug_pybtex(source, e)
    else:
        with memorymapped(filename) as source:
            try:
                for entrytype, (bibkey, fields) in BibTeXEntryIterator(source):
                    fields = {name.decode(encoding).lower():
                        whitespace_re.sub(' ', ''.join(values).decode(encoding).strip())
                        for name, values in fields}
                    yield bibkey.decode(encoding), (entrytype.decode(encoding), fields)
            except PybtexSyntaxError as e:
                    debug_pybtex(source, e)


def debug_pybtex(source, e):
    start, line, pos = e.error_context_info
    print('BIBTEX ERROR on line %d, last parsed lines:' % line)
    print(source[start:start+500] + '...')
    raise
    

def names(s):
    for name in split_name_list(s):
        try:
            yield Name.from_string(name)
        except PybtexError as e:
            print(e)


class Name(collections.namedtuple('Name', 'prelast last given lineage')):

    __slots__ = ()

    @classmethod
    def from_string(cls, name):
        person = Person(name)
        prelast, last, first, middle, lineage = (' '.join(getattr(person, part))
            for part in ('_prelast', '_last', '_first', '_middle', '_lineage'))
        given = ' '.join(n for n in (first, middle) if n)
        return cls(prelast, last, given, lineage)


def save(entries, filename, sortkey, encoding=None, use_pybtex=False):
    if not use_pybtex:
        if encoding in (None, 'ascii'):
            with open(filename, 'w') as fd:
                dump(entries, fd, sortkey, encoding)
        else:
            with io.open(filename, 'w', encoding=encoding) as fd:
                dump(entries, fd, sortkey, encoding)
    else:
        raise NotImplementedError


def dump(entries, fd, sortkey=None, encoding=None, verbatim=VERBATIM):
    if sortkey is None:
        if isinstance(entries, collections.OrderedDict):
            items = entries.iteritems()
        elif isinstance(entries, dict):
            raise ValueError('dump needs sortkey or ordered entries')
        else:
            items = entries
    else:
        items = sorted(entries.iteritems(), key=sortkeys[sortkey])

    """
    #: \#
    $: \$
    %: \%
    ^: \^{} \textasciicircum
    &: \&
    _: \_
    {: \{
    }: \}
    ~: \~{} \textasciitilde
    \: \textbackslash{}
    <: \textless
    >: \textgreater
    """
    if encoding in (None, 'ascii'):
        for bibkey, (entrytype, fields) in items:
            fd.write('@%s{%s' % (entrytype, bibkey))
            for k, v in fieldorder.sorteddict(fields):
                # FIXME
                if k in verbatim:
                    v = v.strip().encode('ascii')
                else:
                    v = v.strip().encode('latex').replace(r'\_', '_').replace(r'\#', '#').replace(r'\\&', r'\&')
                fd.write(',\n    %s = {%s}' % (k, v))
            fd.write('\n}\n' if fields else ',\n}\n')
    else:
        from latexutf8 import latex_to_utf8
        for bibkey, (entrytype, fields) in items:
            fd.write(u'@%s{%s' % (entrytype, bibkey))
            for k, v in fieldorder.sorteddict(fields):
                # FIXME
                if k in verbatim:
                    v = v.strip().decode('ascii')
                else:
                    v = latex_to_utf8(v.strip(), verbose=False)
                fd.write(u',\n    %s = {%s}' % (k, v))
            fd.write(u'\n}\n' if fields else u',\n}\n')


def authorbibkey_colon(author, bibkey):
    return author + ':'.join(bibkey.split(':', 1)[::-1])
    

def numkey(bibkey, nondigits=re.compile('(\D+)')):
    return tuple(try_int(s) for s in nondigit.split(bibkey))


def try_int(s):
    try:
        return int(s)
    except ValueError:
        return s


sortkeys = {
    'authorbibkey': lambda (k, (typ, fields)): (fields.get('author', '') + k),
    'authorbibkey_colon': lambda (k, (typ, fields)): authorbibkey_colon(fields.get('author', ''), k),
    'bibkey': lambda (k, (typ, fields)): k.lower(),
    'numbibkey': lambda (k, (typ, fields)): numkey(k.lower())
}


class Ordering(dict):

    _missing = float('inf')

    @classmethod
    def fromlist(cls, keys):
        return cls((k, i) for i, k in enumerate(keys))

    def sorteddict(self, dct):
         return sorted(dct.iteritems(), key=self._sorteddictkey)

    def _sorteddictkey(self, (key, value)):
         return self[key], key

    def __missing__(self, key):
        return self._missing


fieldorder = Ordering.fromlist(FIELDORDER)


def check(filename):
    parser = CheckParser()
    parser.parse_file(filename)
    return parser.error_count
    

class CheckParser(Parser):
    def __init__(self, *args, **kwargs):
        super(CheckParser, self).__init__(*args, **kwargs)
        self.error_count = 0
    def process_entry(self, *args, **kwargs):
        try:
            super(CheckParser, self).process_entry(*args, **kwargs)
        except PybtexError as e:
            print(e)
            self.error_count +=1


def _test_dump():
    import bib
    import glob
    from cStringIO import StringIO
    for filename in glob.glob('../references/bibtex/*.bib'):
        print(filename)
        entries = load(filename)
        a = bib.put(entries, srtkey='bibkey')
        s = StringIO()
        dump(entries, s, sortkey='bibkey')
        b = s.getvalue()
        assert a == b


def _test_load():
    import glob
    for filename in glob.glob('../references/bibtex/*.bib'):
        print(filename)
        entries = load(filename)
        print(len(entries))
        print('%d invalid' % check(filename))


def _test_unicode():
    import os
    import glob
    for filename in glob.glob('../references/bibtex/*.bib'):
        if filename.endswith('-utf8.bib'):
            continue
        print(filename)
        dst = os.path.join(os.path.dirname(filename),
            '%s-utf8%s' % os.path.splitext(os.path.basename(filename)))
        try:
            save(iterentries(filename), dst, sortkey=None, encoding='utf-8')
        except ValueError as e:
            print(repr(e))
        os.remove(dst)


if __name__ == '__main__':
    _test_load()
    #_test_dump()
    #_test_unicode()
