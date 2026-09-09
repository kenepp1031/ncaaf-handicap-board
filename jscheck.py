"""Prove the dashboard's inline script is balanced without depending on Node.

A single unterminated string inside a template literal stops the browser from
parsing the whole `<script>`, so the page renders nothing at all and no Python
test notices. This scans string, template, comment and regex boundaries — not a
full parse, but enough to catch that failure before it ships.

Limits worth knowing: a stray quote can be swallowed by the next quote on a
densely packed line and still leave the file balanced, so this proves structure,
not correctness. Run the page once in a browser after editing the script.
"""
import re

SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script>', re.S | re.I)
# A '/' after one of these ends an expression, so the next '/' opens a regex
# rather than dividing. Everything else in IDENT_END means division.
IDENT_END = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$)]}')
KEYWORDS_BEFORE_REGEX = {'return', 'typeof', 'case', 'in', 'of', 'new', 'delete',
                         'void', 'do', 'else', 'yield', 'await', 'instanceof'}


class JsSyntaxError(ValueError):
    pass


def scripts(html):
    return [m.group(1) for m in SCRIPT.finditer(html)]


def _regex_allowed(source, i):
    j = i-1
    while j >= 0 and source[j] in ' \t\r\n':
        j -= 1
    if j < 0 or source[j] not in IDENT_END:
        return True
    k = j
    while k >= 0 and (source[k].isalnum() or source[k] in '_$'):
        k -= 1
    return source[k+1:j+1] in KEYWORDS_BEFORE_REGEX


def _skip_string(source, i, line, fail):
    quote, j = source[i], i+1
    while j < len(source):
        c = source[j]
        if c == '\\':
            j += 2
            continue
        if c == quote:
            return j+1
        if c == '\n':
            break
        j += 1
    fail(f'unterminated {quote} string', line)


def _skip_regex(source, i, line, fail):
    j, in_class = i+1, False
    while j < len(source):
        c = source[j]
        if c == '\\':
            j += 2
            continue
        if c == '\n':
            break
        if c == '[':
            in_class = True
        elif c == ']':
            in_class = False
        elif c == '/' and not in_class:
            j += 1
            while j < len(source) and source[j].isalpha():
                j += 1
            return j
        j += 1
    fail('unterminated regular expression', line)


def check(source, label='script'):
    """Raise JsSyntaxError when a string, comment, template or ${...} is left open."""
    def fail(message, at):
        raise JsSyntaxError(f'{label}, line {at}: {message}')

    stack = [{'kind': 'code', 'braces': 0, 'line': 1}]
    i, n, line = 0, len(source), 1
    while i < n:
        c = source[i]
        if c == '\n':
            line, i = line+1, i+1
            continue
        top = stack[-1]
        if top['kind'] == 'template':
            if c == '\\':
                i += 2
            elif c == '`':
                stack.pop()
                i += 1
            elif c == '$' and source[i+1:i+2] == '{':
                stack.append({'kind': 'expression', 'braces': 0, 'line': line})
                i += 2
            else:
                i += 1
            continue
        if c in '\'"':
            i = _skip_string(source, i, line, fail)
        elif c == '`':
            stack.append({'kind': 'template', 'braces': 0, 'line': line})
            i += 1
        elif source.startswith('//', i):
            found = source.find('\n', i)
            i = n if found < 0 else found
        elif source.startswith('/*', i):
            found = source.find('*/', i+2)
            if found < 0:
                fail('unterminated /* comment', line)
            line += source.count('\n', i, found)
            i = found+2
        elif c == '/' and _regex_allowed(source, i):
            i = _skip_regex(source, i, line, fail)
        else:
            if c == '{':
                top['braces'] += 1
            elif c == '}':
                if top['braces']:
                    top['braces'] -= 1
                elif top['kind'] == 'expression':
                    stack.pop()
                else:
                    fail('unmatched }', line)
            i += 1
    top = stack[-1]
    if top['kind'] == 'template':
        fail('unterminated template literal', top['line'])
    if top['kind'] == 'expression':
        fail('unterminated ${...} inside a template literal', top['line'])
    if top['braces']:
        fail('unbalanced { }', line)
    return True


def check_html(html, label='dashboard.html'):
    blocks = scripts(html)
    if not blocks:
        raise JsSyntaxError(f'{label}: no <script> block found')
    for index, block in enumerate(blocks, 1):
        offset = html[:html.index(block)].count('\n')
        try:
            check(block, label)
        except JsSyntaxError as e:
            raise JsSyntaxError(re.sub(r'line (\d+)', lambda m: f'line {int(m.group(1))+offset}', str(e))) from None
    return len(blocks)
