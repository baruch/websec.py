#!/usr/bin/env python2.4
import urllib2, StringIO, re, gzip
import random
import model
from model import User, UserPage, WebPage, Page, TG_Visit, SQLObjectNotFound, AND
from datetime import datetime, timedelta
import htmldiff
import urlnorm, urlparse
import javascript
import threading
import md5
import time
import logging
import htmlentitydefs
from turbogears import validators

backendlog = logging.getLogger('noticethat.backend')
userlog = logging.getLogger('noticethat.user')

USER_AGENT = 'NoticeThatBot/1.0 (+http://noticethat.com/bot)'
REFERER = None
MAX_SIZE = 100*1024

short_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
long_weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def format_http_date(date):
    """
    Formats a tuple of 9 integers into an RFC 1123-compliant timestamp as
    required in RFC 2616. We don't use time.strftime() since the %a and %b
    directives can be affected by the current locale (HTTP dates have to be
    in English). The date MUST be in GMT (Greenwich Mean Time).
    """
    if not date:
        return None

    return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (short_weekdays[date[6]], date[2], months[date[1] - 1], date[0], date[3], date[4], date[5])


rfc1123_match = re.compile(r"(?P<weekday>[A-Z][a-z]{2}), (?P<day>\d{2}) (?P<month>[A-Z][a-z]{2}) (?P<year>\d{4}) (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) GMT").match
rfc850_match = re.compile(r"(?P<weekday>[A-Z][a-z]+), (?P<day>\d{2})-(?P<month>[A-Z][a-z]{2})-(?P<year>\d{2}) (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) GMT").match
asctime_match = re.compile(r"(?P<weekday>[A-Z][a-z]{2}) (?P<month>[A-Z][a-z]{2})  ?(?P<day>\d\d?) (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) (?P<year>\d{4})").match

def parse_http_date(date):
    """
    Parses any of the three HTTP date formats into a tuple of 9 integers as
    returned by time.gmtime(). This should not use time.strptime() since
    that function is not available on all platforms and could also be
    affected by the current locale.
    """

    date = str(date)
    year = 0
    weekdays = short_weekdays

    m = rfc1123_match(date)
    if not m:
        m = rfc850_match(date)
        if m:
            year = 1900
            weekdays = long_weekdays
        else:
            m = asctime_match(date)
            if not m:
                return None

    try:
        year = year + int(m.group("year"))
        month = months.index(m.group("month")) + 1
        day = int(m.group("day"))
        hour = int(m.group("hour"))
        minute = int(m.group("minute"))
        second = int(m.group("second"))
        weekday = weekdays.index(m.group("weekday"))
        return datetime(year, month, day, hour, minute, second)
    except:
        # the month or weekday lookup probably failed indicating an invalid timestamp
        return datetime.now()

def get_etag(response):
    return response.info().getheader('ETag')

def get_last_modified(response):
    last_modified = response.info().getheader('Last-Modified')
    return parse_http_date(last_modified)

def fetch_page(url, etag=None, timestamp=None):
    request = urllib2.Request(url)
    if etag:
        request.add_header("If-None-Match", etag)
    if timestamp:
        request.add_header("If-Modified-Since", format_http_date(timestamp.timetuple()))
    request.add_header('User-Agent', USER_AGENT)
    if REFERER:
        request.add_header('Referer', REFERER)
    request.add_header('Accept-Encoding', 'gzip')

    try:
        response = urllib2.urlopen(request)
        etag = get_etag(response)
        timestamp = get_last_modified(response)
        data = response.read(MAX_SIZE)
        if hasattr(response, "headers"):
            if response.headers.get('content-encoding', '') == 'gzip':
                try:
                    data = gzip.GzipFile(fileobj=StringIO.StringIO(data)).read(MAX_SIZE)
                except:
                    # some feeds claim to be gzipped but they're not, so we get garbage
                    data = ''

        return {'etag': etag, 'timestamp': timestamp, 'data': data, 'res': 200}
    except urllib2.HTTPError, e:
        # either the resource is not modified or some other HTTP
        # error occurred so return an empty resource
        if e.code == 304:
            return {'etag': etag, 'timestamp': timestamp, 'data': None, 'res': 304}
        raise
    # The other exceptions mean the page is dead, this is caught upstream to us


def set_first_page_unmodified(webpage):
    for userpage in webpage.users:
        userpage.set(
            lastreadpage=webpage.lastpage,
            prevreadpage=webpage.lastpage,
            lastread=webpage.lastchanged
        )

def _html_decode(s):
    parts = s.split('&')
    out = parts[0:1]
    for part in parts[1:]:
        if part[0] == ' ':
            # This is not a real element since there is no word directly after
            # the ampersand, fix it.
            out.append(u'&')
            out.append(part)
            continue
        code, text = part.split(';', 1)
        codepoint = htmlentitydefs.name2codepoint.get(code, None)
        if codepoint:
            ch = unichr(codepoint)
        elif code[0] == u'#':
            if code[1] in ('x', 'X'): # Hexadecomal char
                ch = unichr(int(code[2:], 16))
            else: # Decimal char
                ch = unichr(int(code[1:], 10))
        else:
            # Unknown character code, put it raw
            ch = u'&' + code + u';'
        out.append(ch)
        out.append(text)
    return u''.join(out)

def html_decode(s):
    # Ensure we have something in s, if s is None we will fail completely in
    # _html_decode.
    if not s:
        return s
    try:
        return _html_decode(s)
    except (ValueError, OverflowError):
        backendlog.exception('cannot html_decode string "%s"' % s)
        return s

# Some encodings are unknown and need to be 'translated' to their known name
encoding_translate = {
    'iso-8859-8-i': 'iso-8859-8'
}

def decode_data(data, encoding):
    encoding = encoding_translate.get(encoding, encoding)
    if encoding:
        try:
            data = data.decode(encoding)
            return (data, encoding)
        except UnicodeDecodeError:
            pass

    # Try to guess the encoding, simple stuff for now
    for encoding in ('utf-8', 'iso-8859-1'):
        try:
            data = data.decode(encoding)
            return (data, encoding)
        except UnicodeDecodeError:
            continue
    raise "Didnt find appropriate encoding for the data"


def update_webpage(webpage):
    modified = False
    try:
        backendlog.info('Updating webpage %d: %s' % (webpage.id, webpage.url))
        webpage.lastvisit = datetime.now()
        res = fetch_page(webpage.url, webpage.etag, webpage.timestamp)
        webpage.set(etag=res['etag'], timestamp=res['timestamp'], dead=False)

        if res['res'] == 200:
            data = res['data']
            (encoding, data) = htmldiff.extract_encoding(data)
            (data, encoding) = decode_data(data, encoding)
            oldpage = webpage.lastpage
            (modified, _, head, change_count) = htmldiff.textDiffPlus(oldpage.data, data, highlight=False)
            if modified:
                title = htmldiff.extract_htmllist_title(head)
                newpage = Page(title='', encoding=encoding)
                newpage.set(title=html_decode(title), data=data)
                webpage.set(lastpage=newpage, lastchanged=webpage.lastvisit)
                if oldpage.id == 1:
                    set_first_page_unmodified(webpage)
    except (urllib2.HTTPError, urllib2.URLError), e:
        webpage.set(dead=True, timestamp=None, etag=None)
        backendlog.warning('WebPage %d (%s) failed to fetch with exception: "%s"' % (webpage.id, webpage.url, str(e)))
    except:
        if 'encoding' in locals():
            encmsg = 'guess encoding was %s' % encoding
        else:
            encmsg = 'encoding not determined'
        backendlog.error('Exception when updating page %s, %s' % (webpage.url, encmsg))
        raise
    return modified


states = (4, 3, 3, 5, 2)
states_min = 0
states_max = sum(states, states_min) - 1
def build_state_deltas():
    state_delta = []
    state_deltas = (timedelta(minutes=30),
                    timedelta(hours=1),
                timedelta(hours=3),
                timedelta(days=1),
                timedelta(days=7))
    i = 0
    for delta in state_deltas:
        for j in range(0, states[i]):
            state_delta.append(delta)
        i += 1

    return state_delta

state_delta = build_state_deltas()

def _next_state(state, modified):
    if modified:
        state -= 1
    else:
        state += 1
    if state < states_min:
        state = states_min
    elif state > states_max:
        state = states_max
    return state

def set_next_check(webpage, modified):
    state = _next_state(webpage.nextvisitState, modified)
    nextvisit = datetime.now() + state_delta[state]
    nextvisit += timedelta(minutes=random.randint(0,10))
    webpage.set(nextvisit=nextvisit, nextvisitState=state)

class InvalidURL(Exception):
    pass
class URLAlreadyTracked(Exception):
    pass

def addpage(userid, url):
    def userurllog(msg):
        userlog.info('%d: Add URL (%s) "%s"' % (userid, msg, url))
    (scheme, authority, path, _, query, _) = urlnorm.norm(urlparse.urlparse(url))
    if scheme not in ['http']:
        userurllog('invalid scheme')
        raise InvalidURL()
    url = urlparse.urlunparse((scheme, authority, path, '', query, ''))

    user = User.get(userid)
    try:
        webpage = WebPage.byUrl(url)
    except:
        webpage = WebPage(url=url, lastpage=model.empty_page())
    num_userpages = UserPage.select(AND(UserPage.q.userID == user.id,
                        UserPage.q.webpageID == webpage.id)).count()
    if num_userpages > 0:
        userurllog('already tracked')
        raise URLAlreadyTracked()

    webpage.ref_inc()
    try:
        lastpage = webpage.lastpage
        userpage = UserPage(user=user, webpage=webpage, mail_notify=None, lastreadpage=lastpage, prevreadpage=lastpage)
    except:
        webpage.ref_dec()
        raise
    userurllog('success')

def delete_user_page(userpage):
    webpage = userpage.webpage
    userpage.destroySelf()
    webpage.ref_dec()

def delete_user_pages(userid, pageids):
    for pageid in pageids:
        userpage = UserPage.get(pageid)
        delete_user_page(userpage)

def set_email_notify(userid, userpages, notify):
    for userpage in userpages:
        userpage.mail_notify = notify

email_validator = validators.Email()
def set_email(user, email_raw):
    # Verify email
    try:
        if email_raw == '':
            email = None
        else:
            email = email_validator.to_python(email_raw)
    except Exception, e:
        return (False, str(e))

    # Set email
    user.email = email
    if email:
        return (True, 'EMail successfully updated.')
    else:
        return (True, 'EMail successfully removed.')

def addjs(msg):
    return javascript.jsmsg % javascript.escape(msg)

def rekey(userid):
    user = User.get(userid)
    md5er = md5.new('mickeymouse')
    md5er.update(user.userId)
    md5er.update(user.password)
    md5er.update(user.key)
    md5er.update(str(user.created))
    md5er.update(str(user.lastlogin))
    md5er.update(time.ctime())
    md5er.update(str(time.clock()))

    user.key = md5er.hexdigest()
    return True

def calc_stats():
    now = datetime.now()
    nowplus12 = now + timedelta(hours=12)
    nowplus24 = now + timedelta(hours=24)

    d = {}
    d['numusers'] = User.select().count()
    # visits that are relatively new, will only expire between 12 and 24
    # hours from now.
    d['numvisits'] = TG_Visit.select(AND(TG_Visit.q.expiry >= nowplus12, TG_Visit.q.expiry <= nowplus24)).count()
    # Visits that are half lifed, will expire between now and 12 hours.
    d['numvisits_halflife'] = TG_Visit.select(AND(TG_Visit.q.expiry >= now, TG_Visit.q.expiry <= nowplus12)).count()
    d['numvisits_dead'] = TG_Visit.select(TG_Visit.q.expiry > nowplus24).count()
    d['numwebpages'] = WebPage.select(WebPage.q.counter > 0).count()
    d['num_dis_webpages'] = WebPage.select(WebPage.q.counter == 0).count()
    d['numuserpages'] = UserPage.select().count()
    return d


if __name__ == '__main__':
    res1 = fetch_page('http://hamilton.ie/')
    print res1

    print
    print

    if res1:
        res2 = fetch_page('http://hamilton.ie/', res1['etag'], res1['timestamp'])
        print res2
    else:
        print 'Got nothing for first attempt, no reason to attempt it again'
