"""
A class to interact with AMO's api, using OAuth.
Ripped off from Daves test_oauth.py and some notes from python-oauth2
"""
import commonware
# Wherein import almost every http or urllib in Python
import urllib
import urllib2
import httplib2
import oauth2 as oauth
import os
import re
import time
import json
import mimetools

from django.http import Http404
from urlparse import urlparse, urlunparse, parse_qsl

from helpers import encode_multipart, data_keys

log = commonware.log.getLogger('f.amooauth')

# AMO Specific end points
urls = {
    'login': '/users/login',
    'request_token': '/oauth/request_token/',
    'access_token': '/oauth/access_token/',
    'authorize': '/oauth/authorize/',
    'user': '/api/2/user/',
    'addon': '/api/2/addons/',
    'version': '/api/2/addon/%s/versions',
    'update': '/api/2/update/',
    'perf': '/api/2/performance/',
}

storage_file = os.path.join(os.path.expanduser('~'), '.amo-oauth')
boundary = mimetools.choose_boundary()

old = httplib2.Http.__init__


# Ouch, I'll go to hell for this.
def hack(self, **kw):
    kw['disable_ssl_certificate_validation'] = True
    return old(self, **kw)

httplib2.Http.__init__ = hack


class AMOOAuth:
    """
    A base class to authenticate and work with AMO OAuth.
    """
    signature_method = oauth.SignatureMethod_HMAC_SHA1()
    should_save_storage = False

    def __init__(self, domain='addons.mozilla.org', protocol='https',
                 port=443, prefix='', three_legged=False):
        self.data = self.read_storage()
        self.domain = domain
        self.protocol = protocol
        self.port = port
        self.prefix = prefix
        self.three_legged = three_legged

    def set_consumer(self, consumer_key, consumer_secret, save_storage=False):
        self.should_save_storage = save_storage
        self.data['consumer_key'] = consumer_key
        self.data['consumer_secret'] = consumer_secret
        if self.should_save_storage:
            self.save_storage()

    def get_consumer(self):
        return oauth.Consumer(self.data['consumer_key'],
                              self.data['consumer_secret'])

    def get_access(self):
        return oauth.Token(self.data['access_token']['oauth_token'],
                           self.data['access_token']['oauth_token_secret'])

    def has_access_token(self):
        return not self.three_legged or 'access_token' in self.data

    def read_storage(self):
        if self.should_save_storage and os.path.exists(storage_file):
            try:
                return json.load(open(storage_file, 'r'))
            except ValueError:
                pass
        return {}

    def url(self, key):
        return urlunparse((self.protocol, '%s:%s' % (self.domain, self.port),
                           '%s/en-US/firefox%s' % (self.prefix, urls[key]),
                           '', '', ''))

    def shorten(self, url):
        return urlunparse(['', ''] + list(urlparse(url)[2:]))

    def save_storage(self):
        json.dump(self.data, open(storage_file, 'w'))

    def get_csrf(self, content):
        return re.search("name='csrfmiddlewaretoken' value='(.*?)'",
                         content).groups()[0]

    def _request(self, token, method, url, data={}, headers={}, **kw):
        parameters = data_keys(data)
        parameters.update(kw)
        request = (oauth.Request
                        .from_consumer_and_token(self.get_consumer(), token,
                                                 method, url, parameters))
        log.debug('request created')
        request.sign_request(self.signature_method, self.get_consumer(), token)
        log.debug('request signed')
        client = httplib2.Http()
        log.debug('client is instantiated')
        if data and method == 'POST':
            log.debug('this is a POST request')
            data = encode_multipart(boundary, data)
            headers.update({'Content-Type':
                            'multipart/form-data; boundary=%s' % boundary})
        else:
            log.debug('this is not a POST request')
            data = urllib.urlencode(data)
        log.debug('request url: %s a' % request.to_url())
        log.debug(("AMOOAUTH: Sending  request url: %s, data: %s, method: %s"
            ) % (request.to_url(), json.dumps(data), method))
        return client.request(request.to_url(), method=method,
                              headers=headers, body=data)

    def authenticate(self, username=None, password=None):
        """
        This is only for the more convoluted three legged approach.
        1. Login into AMO.
        2. Get a request token for the consumer.
        3. Approve the consumer.
        4. Get an access token.
        """
        # First we need to login to AMO, this takes a few steps.
        # If this was being done in a browser, this wouldn't matter.
        #
        # This callback is pretty academic, but required so we can get
        # verification token.
        callback = 'http://foo.com/'

        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor())
        urllib2.install_opener(opener)
        res = opener.open(self.url('login'))
        assert res.code == 200

        # get the CSRF middleware token
        if password is None:
            password = raw_input('Enter password: ')

        csrf = self.get_csrf(res.read())
        data = urllib.urlencode({'username': username,
                                 'password': password,
                                 'csrfmiddlewaretoken': csrf})
        res = opener.open(self.url('login'), data)
        assert res.code == 200

        # We need these headers to be able to post to the authorize method
        cookies = {}
        # Need to find a better way to find the handler, -2 is fragile.
        for cookie in opener.handlers[-2].cookiejar:
            if cookie.name == 'sessionid':
                cookies = {'Cookie': '%s=%s' % (cookie.name, cookie.value)}
        # Step 1 completed, we can now be logged in for any future requests

        # Step 2, get a request token.
        resp, content = self._request(None, 'GET', self.url('request_token'),
                                      oauth_callback=callback)
        assert resp['status'] == '200', 'Status was: %s' % resp.status

        request_token = dict(parse_qsl(content))
        assert request_token
        token = oauth.Token(request_token['oauth_token'],
                            request_token['oauth_token_secret'])

        # Step 3, authorize the access of this consumer for this user account.
        resp, content = self._request(token, 'GET', self.url('authorize'),
                                      headers=cookies)
        csrf = self.get_csrf(content)
        data = {'authorize_access': True,
                'csrfmiddlewaretoken': csrf,
                'oauth_token': token.key}
        resp, content = self._request(token, 'POST', self.url('authorize'),
                                      headers=cookies, data=data,
                                      oauth_callback=callback)

        assert resp.status == 302, 'Status was: %s' % resp.status
        qsl = parse_qsl(resp['location'][len(callback) + 1:])
        verifier = dict(qsl)['oauth_verifier']
        token.set_verifier(verifier)

        # We have now authorized the app for this user.
        resp, content = self._request(token, 'GET', self.url('access_token'))
        access_token = dict(parse_qsl(content))
        self.data['access_token'] = access_token
        self.save_storage()
        # Done. Wasn't that fun?

    def get_params(self):
        return dict(oauth_consumer_key=self.data['consumer_key'],
                    oauth_nonce=oauth.generate_nonce(),
                    oauth_signature_method='HMAC-SHA1',
                    oauth_timestamp=int(time.time()),
                    oauth_version='1.0')

    def _send(self, url, method, data):
        log.debug('starting request: (%s, %s, %s)' % (method, url, json.dumps(data)))
        resp, content = self._request(None, method, url,
                                      data=data)
        log.debug('response received: %d, %s' % (resp.status, content))
        if resp.status == 404:
            raise Http404
        if resp.status != 200:
            log.debug('failed request')
            raise ValueError('%s: %s' % (resp.status, content))
        try:
            return json.loads(content)
        except ValueError:
            return content

    def get_user(self):
        return self._send(self.url('user'), 'GET', {})

    def get_user_by_email(self, email):
        log.debug("Accessing API %s with %s" % (self.url('user'), email))
        return self._send(self.url('user'), 'GET', {'email': email})

    def create_addon(self, data):
        return self._send(self.url('addon'), 'POST', data)

    def update_addon(self, data):
        return self._send(self.url('addon'), 'PUT', data)

    def create_perf(self, data):
        return self._send(self.url('perf'), 'POST', data)

    def create_version(self, data, id):
        return self._send(self.url('version') % id, 'POST', data)
