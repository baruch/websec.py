#!/usr/bin/python2.2
"""HTML Diff: http://www.aaronsw.com/2002/diff
Rough code, badly documented. Send me comments and patches."""

__author__ = 'Aaron Swartz <me@aaronsw.com>'
__copyright__ = '(C) 2003 Aaron Swartz. GNU GPL 2.'
__version__ = '0.22'

import difflib, string, re

def isWhitespace(x):
    """Is the token a whitespace?
       We know that tokens which start with a whitespace will be completely whitespace.
    """
    return x[0] in string.whitespace

def isComment(x):
    """Is the token an HTML comment?"""
    return x[0:4] == '<!--' and x[-3:] == '-->'

def isTag(x):
    return x[0] == '<' and x[-1] == '>'

def isIgnore(x):
    return isWhitespace(x) or isTag(x)

def calcIgnore(before, after):
    for token in before + after:
        if not isIgnore(token):
            return False
    return True

def textDiffPlus(a, b, baseurl=None, highlight=True):
    """Takes in strings a and b and returns a human-readable HTML diff."""

    a_head, a_body, a_tail = split_html_list(html2list(a))
    b_head, b_body, b_tail = split_html_list(html2list(b))

    if baseurl:
        base = '<base href="%s"/>' % baseurl
        head = []
        for e in b_head:
            if e[0:5].lower() == '<base':
                continue
            elif e[0:5].lower() == '<head':
                head.append(e)
                head.append(base)
            elif e[0:6].lower() == '</head':
                head.append(base)
                head.append(e)
            else:
                head.append(e)
        b_head = head

    (modified, body, change_count) = html_list_diff(a_body, b_body, highlight)

    if highlight:
        diff_head = ''.join(b_head)
        diff_tail = ''.join(b_tail)
        diff = diff_head + body + diff_tail
    else:
        diff = None
    return (modified, diff, b_head, change_count)

def textDiff(a, b):
    (modified, diff, head, change_count) = textDiffPlus(a, b)
    return (modified, diff, change_count)

delcolor = '#E8292A'
inscolor = '#ACEF48'
diffstyle = '''
<style type="text/css">
    .deldiff { background-color: %(delcolor)s; text-decoration: line-through;}
    .insdiff { background-color: %(inscolor)s;}
</style>''' % dict(inscolor=inscolor, delcolor=delcolor)

simple_tags = set(['a', 'b', 'strong', 'span', 'big', 'br', 'em', 'hr', 'img',
    'i', 'small', 'strike'])

ignorable_tags = set(['!', '/'])

def html_transform(elements, insert=False, delete=False):
    simple = {'simple': True}
    if insert:
        theclass = 'insdiff'
    elif delete:
        theclass = 'deldiff'

    def transform_tag(elem):
        return ''.join([elem[0:-1], ' class="', theclass, '">'])

    def transform_tags(elem):
        if elem[0] == '<' and elem[-1] == '>' and elem[1] not in ignorable_tags:
            if not simple['simple']:
                return transform_tag(elem)
            tagparts = elem[1:-1].split(' ') # TODO: account for splitting by tabs
            for tagpart in tagparts:
                name = tagpart
                if name != '':
                    break
            if name not in simple_tags:
                simple['simple'] = False
                return transform_tag(elem)

        return elem

    elements = map(transform_tags, elements)

    if not simple['simple']:
        # everything was transformed already
        return elements

    pre = ['<span class="', theclass, '">']
    post = ['</span>']
    return pre + elements + post


def html_list_diff(a_body, b_body, highlight=True):
    modified = False
    out = []
    change_count = 0

    s = difflib.SequenceMatcher(None, a_body, b_body)
    for e in s.get_opcodes():
        before = a_body[e[1]:e[2]]
        after = b_body[e[3]:e[4]]

        if e[0] == "equal":
            out += after
            continue

        if calcIgnore(before, after):
            if e[0] != "delete":
                out += after
            continue

        if not modified:
            modified = True
            if not highlight:
                return (True, None, -1)

        change_count += 1
        if e[0] == "replace":
            # @@ need to do something more complicated here
            # call textDiff but not for html, but for some html... ugh
            # gonna cop-out for now
            out += html_transform(before, delete=True)
            out += html_transform(after, insert=True)
        elif e[0] == "delete":
            out += html_transform(before, delete=True)
        elif e[0] == "insert":
            out += html_transform(after, insert=True)
        else:
            raise "Um, something's broken. I didn't expect a '" + `e[0]` + "'."

    if modified:
        out = [diffstyle] + out
    return (modified, ''.join(out), change_count)

meta_re = re.compile('<\s*meta\s+')
charset_re_str = r''.join([
    r'\s+(?P<key>[-a-zA-Z]+)',
    r'\s*=\s*',
    r'(',
    r'(?P<bracket>["\'])(?P<value1>.+?)(?P=bracket)',
    r'|',
    r'(?P<value2>\S+)',
    r')',
])
charset_re = re.compile(charset_re_str)
head_end_re = re.compile(r'(</head>|<body>)')

def extract_encoding(html):
    """Return the value for the encoding meta (if any), removes the meta header."""
    #  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    htmllist = html2list(html)

    charset = None
    i = 0
    for elem in htmllist:
        i += 1
        elem = elem.lower()
        if head_end_re.match(elem):
            break
        if not meta_re.match(elem):
            continue
        groups = charset_re.finditer(elem)
        attr = {}
        for group in groups:
            d = group.groupdict()
            value = d['value1'] or d['value2']
            attr[d['key']] = value
        if attr.get('http-equiv', None) != 'content-type':
            continue
        if not 'content' in attr:
            continue
        content = attr['content'].split(';')
        try:
            charset = content[1].split('=')[1]
        except IndexError:
            pass
        break

    return (charset, ''.join(htmllist[0:i-1] + htmllist[i:]))

def extract_htmllist_title(head):
    i = 0
    t_start = None
    t_end = None
    title = None
    for elem in head:
        low_elem = elem.lower()
        if low_elem == '<title>':
            t_start = i+1
        elif low_elem == '</title>':
            t_end = i
        elif low_elem == '</head>' or low_elem == '<body':
            break
        i += 1

    if t_start and t_end:
        title = ''.join(head[t_start:t_end])
    return title


_S_CHAR = 1
_S_TAG = 2
_S_TAG_STRING = 3
_S_TAG_OR_COMMENT = 4
_S_COMMENT = 5
_S_COMMENT_OR_DOCTYPE = 8
_S_COMMENT_END = 6
_S_WHITESPACE = 7

def _html2list_state(mode, out, cur, c):
    if mode == _S_TAG:
        cur += c
        if c == '>':
            out.append(cur); cur = ''; mode = _S_CHAR
        elif c == '"':
            mode = _S_TAG_STRING
    elif mode == _S_TAG_STRING:
        cur += c
        if c == '"':
            mode = _S_TAG
    elif mode == _S_COMMENT_OR_DOCTYPE:
        if c != '-':
            return _html2list_state(_S_TAG, out, cur, c)
        else:
            cur += c
            mode = _S_COMMENT
    elif mode == _S_COMMENT:
        cur += c
        if c == '-':
            mode = _S_COMMENT_END
    elif mode == _S_COMMENT_END:
        cur += c
        if c == '>':
            out.append(cur); cur = ''; mode = _S_CHAR
        elif c != '-':
            mode = _S_COMMENT
    elif mode == _S_TAG_OR_COMMENT:
        if c == '!':
            cur += c
            mode = _S_COMMENT_OR_DOCTYPE
        else:
            return _html2list_state(_S_TAG, out, cur, c)
    elif mode == _S_WHITESPACE:
        if c in string.whitespace:
            cur += c
        else:
            out.append(cur)
            cur = ''
            return _html2list_state(_S_CHAR, out, cur, c)
    elif mode == _S_CHAR:
        if c == '<':
            out.append(cur)
            cur = c
            mode = _S_TAG_OR_COMMENT
        elif c in string.whitespace:
            out.append(cur)
            cur = c
            mode = _S_WHITESPACE
        else:
            cur += c
    else:
        raise Exception()
    return (mode, cur)

def html2list(x):
    if x == None:
        return []

    mode = _S_CHAR
    cur = ''
    out = []
    for c in x:
        (mode, cur) = _html2list_state(mode, out, cur, c)
    out.append(cur)
    return filter(lambda x: x is not '', out)

def split_html_list(html):
    i = 0

    for x in html:
        i += 1
        if x[0:5].lower() == '<body':
            break

    j = i
    for x in html[i:]:
        if x[0:6].lower() == '</body':
            break
        j += 1

    if j == len(html):
        # There is no body, return an empty head and tail
        return ([], html, [])

    # We have found a body, seperate it out
    return (html[0:i], html[i:j], html[j:])

if __name__ == '__main__':
    import sys
    try:
        a, b = sys.argv[1:3]
    except ValueError:
        print "htmldiff: highlight the differences between two html files"
        print "usage: " + sys.argv[0] + " a b"
        sys.exit(1)
    print textDiff(open(a).read(), open(b).read())

