from datetime import datetime, timedelta
import os
import tempfile
import time
import json
import backoff
import requests

from singer import metrics
import singer

LOGGER = singer.get_logger()
BASE_URL = 'https://api.linkedin.com/rest'
LINKEDIN_TOKEN_URI = 'https://www.linkedin.com/oauth/v2/accessToken'
INTROSPECTION_URI = 'https://www.linkedin.com/oauth/v2/introspectToken'
# October 2026 Marketing API (LinkedIn-Version: 202610). Sunsets 2027-10-15.
# https://learn.microsoft.com/en-us/linkedin/marketing/versioning
LINKEDIN_VERSION = '202610'

# set default timeout of 300 seconds
REQUEST_TIMEOUT = 300

class LinkedInError(Exception):
    pass

class Server5xxError(LinkedInError):
    pass

class Server429Error(LinkedInError):
    pass

class LinkedInBadRequestError(LinkedInError):
    pass


class LinkedInUnauthorizedError(LinkedInError):
    pass


class LinkedInMethodNotAllowedError(LinkedInError):
    pass

class LinkedInNotFoundError(LinkedInError):
    pass

class LinkedInForbiddenError(LinkedInError):
    pass

class LinkedInLengthRequiredError(LinkedInError):
    pass

class LinkedInRateLimitExceeededError(Server429Error):
    pass

class LinkedInInternalServiceError(Server5xxError):
    pass

class LinkedInGatewayTimeoutError(Server5xxError):
    pass


ERROR_CODE_EXCEPTION_MAPPING = {
    400: {
        "raise_exception": LinkedInBadRequestError,
        "message": "The request is missing or has a bad parameter."
    },
    401: {
        "raise_exception": LinkedInUnauthorizedError,
        "message": "Invalid authorization credentials."
    },
    403: {
        "raise_exception": LinkedInForbiddenError,
        "message": "User does not have permission to access the resource."
    },
    404: {
        "raise_exception": LinkedInNotFoundError,
        "message": "The resource you have specified cannot be found. Either the accounts provided are invalid or you do not have access to the Ad Account."
    },
    405: {
        "raise_exception": LinkedInMethodNotAllowedError,
        "message": "The provided HTTP method is not supported by the URL."
    },
    411: {
        "raise_exception": LinkedInLengthRequiredError,
        "message": "The server refuses to accept the request without a defined Content-Length header."
    },
    429: {
        "raise_exception": LinkedInRateLimitExceeededError,
        "message": "API rate limit exceeded, please retry after some time."
    },
    500: {
        "raise_exception": LinkedInInternalServiceError,
        "message": "An error has occurred at LinkedIn's end."
    },
    504: {
        "raise_exception": LinkedInGatewayTimeoutError,
        "message": "A gateway timeout occurred. There is a problem at LinkedIn's end."
    }
}

def raise_for_error(response):
    error_code = response.status_code
    try:
        response_json = response.json()
    except Exception:
        response_json = {}

    if error_code == 404:
        # 404 returns "Not Found" so getting custom message
        error_description = ERROR_CODE_EXCEPTION_MAPPING.get(error_code).get("message")
    else:
        # get message from the reponse if present or get custom message if not present
        error_description = response_json.get("error_description", response_json.get("message", ERROR_CODE_EXCEPTION_MAPPING.get(error_code, {}).get("message", "Unknown Error")))

    if response.status_code == 401 and 'Expired access token' in error_description:
        LOGGER.error("Your access_token has expired as per LinkedIn’s security policy. Please re-authenticate your connection to generate a new token and resume extraction.")

    message = "HTTP-error-code: {}, Error: {}".format(
                error_code, error_description)

    if error_code not in ERROR_CODE_EXCEPTION_MAPPING and error_code >= 500:
        # Raise `Server5xxError` for all 5xx unknown error
        exc = Server5xxError
    else:
        exc = ERROR_CODE_EXCEPTION_MAPPING.get(error_code, {}).get("raise_exception", LinkedInError)
    raise exc(message) from None

class LinkedinClient: # pylint: disable=too-many-instance-attributes
    def __init__(self, # pylint: disable=too-many-arguments
                 client_id,
                 client_secret,
                 refresh_token,
                 access_token,
                 config_path,
                 request_timeout=REQUEST_TIMEOUT,
                 user_agent=None,
                 token_file_path=None,
                 refresh_token_expires_at=None):
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__refresh_token = refresh_token
        self.__config_path = config_path
        self.__user_agent = user_agent
        self.__access_token = access_token
        self.__token_file_path = token_file_path or None
        self.__refresh_token_expires_at = None
        if refresh_token_expires_at:
            try:
                self.__refresh_token_expires_at = self._parse_token_expiry(refresh_token_expires_at)
            except ValueError:
                LOGGER.warning('Ignoring invalid refresh_token_expires_at: %s', refresh_token_expires_at)
        self.__expires = None
        self.__session = requests.Session()
        self.__base_url = None
        # if request_timeout is other than 0,"0" or "" then use request_timeout
        if request_timeout and float(request_timeout):
            request_timeout = float(request_timeout)
        else: # If value is 0,"0" or "" then set default to 300 seconds.
            request_timeout = REQUEST_TIMEOUT
        self.request_timeout = request_timeout


    @property
    def access_token(self):
        return self.__access_token

    # during 'Timeout' error there is also possibility of 'ConnectionError',
    # hence added backoff for 'ConnectionError' too.
    # as 'check_access_token' is also called in 'request' hence added backoff here
    # instead of 'check_access_token' to avoid backoff 25 times
    @backoff.on_exception(backoff.expo,
                          (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
                          max_tries=5,
                          factor=2)
    def __enter__(self):
        self.fetch_and_set_access_token()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.__session.close()

    # The following two functions are used solely by unittests and are not utilized by the tap

    def get_expires_time_for_test(self):
        return self.__expires

    def set_mock_expires_for_test(self, mock_expire):
        self.__expires = mock_expire
        return self.__expires


    @staticmethod
    def _parse_token_expiry(value):
        text = str(value).strip().replace('Z', '')
        if len(text) >= 19 and text[10] in ('T', ' '):
            text = text[:19].replace(' ', 'T')
            return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S')
        return datetime.strptime(text[:10], '%Y-%m-%d')

    def _config_grant_is_newer(self, stored_refresh, stored_expiry):
        """A re-auth has a different refresh token and a later expiry than the file.

        LinkedIn can also rotate the refresh token on an ordinary refresh. That
        rotation does not move the expiry, so a different string alone is not a
        new grant. Treating it as one would throw away the durable file and
        keep using the original env token.
        """
        if not stored_refresh or not self.__refresh_token:
            return False
        if stored_refresh == self.__refresh_token:
            return False
        if not self.__refresh_token_expires_at or not stored_expiry:
            return False
        return self.__refresh_token_expires_at > stored_expiry

    def _load_persisted_tokens(self):
        """Prefer the durable token file over Meltano's env-built config.

        Meltano rebuilds config from environment variables on every run, so the
        file holds the latest access token and any rotated refresh token. A
        re-authorization replaces the file only when its refresh token differs
        and its expiry is later than the one stored in the file.
        """
        path = self.__token_file_path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, encoding='utf-8') as file:
                stored = json.load(file)
        except (OSError, ValueError) as exc:
            LOGGER.warning('Could not read LinkedIn token file %s: %s', path, exc)
            return
        if not isinstance(stored, dict):
            return

        stored_refresh = stored.get('refresh_token')
        stored_expiry = None
        expires_at = stored.get('refresh_token_expires_at')
        if expires_at:
            try:
                stored_expiry = self._parse_token_expiry(expires_at)
            except ValueError:
                LOGGER.warning('Ignoring invalid refresh_token_expires_at in %s', path)
        if self._config_grant_is_newer(stored_refresh, stored_expiry):
            LOGGER.info(
                'Config refresh token expires after %s; using the config grant.',
                path,
            )
            # The new access token may still be valid, so no refresh runs.
            # Replace the file now or the next run loads the old grant again.
            self._write_token_file()
            return
        if stored.get('access_token'):
            self.__access_token = stored['access_token']
        if stored_refresh:
            self.__refresh_token = stored_refresh
        if stored_expiry:
            self.__refresh_token_expires_at = stored_expiry

    def _warn_if_refresh_token_expiring(self):
        expires_at = self.__refresh_token_expires_at
        if not expires_at:
            return
        # Refreshing the access token does not extend the refresh token (365 days
        # from the original member consent).
        if expires_at - timedelta(days=31) < datetime.utcnow():
            LOGGER.warning(
                'LinkedIn refresh token expires %s. Re-authorize before then. '
                'Refreshing the access token does not extend the refresh token.',
                expires_at.strftime('%Y-%m-%d'),
            )

    def _token_payload(self):
        payload = {
            'access_token': self.__access_token,
            'refresh_token': self.__refresh_token,
        }
        if self.__refresh_token_expires_at:
            payload['refresh_token_expires_at'] = (
                self.__refresh_token_expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            )
        return payload

    def _write_token_file(self):
        path = self.__token_file_path
        if not path:
            return
        directory = os.path.dirname(path) or "."
        tmp_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            # Unique 0600 file from the start. A predictable "*.tmp" name can be
            # swapped for a symlink before chmod, and open() would follow it.
            fd, tmp_path = tempfile.mkstemp(prefix=".linkedin-ads-", suffix=".json", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self._token_payload(), file, indent=2)
                file.write("\n")
            os.replace(tmp_path, path)
            tmp_path = None
            LOGGER.info('Wrote LinkedIn tokens to %s', path)
        except OSError as exc:
            LOGGER.warning('Could not persist LinkedIn tokens to %s: %s', path, exc)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def write_access_token_to_config(self):
        """
        Write an updated access token in the config to reuse in the next sync.
        If we generate access_token today, then it would be valid for 2 months.
        But after 2 months whenever we do an introspection call, access_token would
        always be found as expired because the config still contains the same access_token.
        So, whenever we generate a new access_token, it would be updated in the config.

        Meltano passes a throwaway config file, so also write token_file_path when set.
        A read-only config must not fail the sync; the in-memory token is already set.
        """
        self._write_token_file()
        if not self.__config_path:
            return
        try:
            with open(self.__config_path, encoding='utf-8') as file:
                config = json.load(file)
            config.update(self._token_payload())
            with open(self.__config_path, 'w', encoding='utf-8') as file:
                json.dump(config, file, indent=2)
        except (OSError, ValueError) as exc:
            LOGGER.warning(
                'Could not persist LinkedIn tokens to config %s: %s',
                self.__config_path,
                exc,
            )

    @backoff.on_exception(backoff.expo,
                          (Server5xxError, LinkedInUnauthorizedError),
                          max_tries=5,
                          factor=2)
    def get_token_expires(self):
        """
        Function to get expiry time of access token.
        """
        if not self.__expires:
            headers = {}
            if self.__user_agent:
                headers['User-Agent'] = self.__user_agent

            response = self.__session.post(
                url=INTROSPECTION_URI,
                headers=headers,
                data={
                    'client_id': self.__client_id,
                    'client_secret': self.__client_secret,
                    'token': self.__access_token
                },
                timeout=self.request_timeout)

            if response.status_code != 200:
                raise_for_error(response)

            data = response.json()
            # Introspection of an expired token returns active=false. Treat that as
            # already expired so fetch_and_set_access_token refreshes instead of looping.
            if data.get('active') is False or not data.get('expires_at'):
                self.__expires = datetime.utcnow() - timedelta(seconds=1)
            else:
                self.__expires = datetime.fromtimestamp(data['expires_at'])

            # Display a warning message to inform the customer about the upcoming refresh token expiry in advance, helping to prevent sync failures.
            # Inactive tokens often omit created_at; a missing field must not block refresh.
            created_at = data.get('created_at')
            if created_at and datetime.fromtimestamp(created_at) + timedelta(days=334) < datetime.utcnow():
                LOGGER.warning('The refresh token is going to expire soon. '
                               'Please re-authenticate your connection to generate a new token and resume extraction.')

        return self.__expires


    @backoff.on_exception(backoff.expo,
                          (Server5xxError, LinkedInUnauthorizedError),
                          max_tries=5,
                          factor=2)
    def refresh_access_token(self):
        headers = {}
        if self.__user_agent:
            headers['User-Agent'] = self.__user_agent

        response = self.__session.post(
            url=LINKEDIN_TOKEN_URI,
            headers=headers,
            data={
                'grant_type': 'refresh_token',
                'client_id': self.__client_id,
                'client_secret': self.__client_secret,
                'refresh_token': self.__refresh_token,
            },
            timeout=self.request_timeout)

        if response.status_code != 200:
            raise_for_error(response)

        data = response.json()
        self.__access_token = data['access_token']
        # data['expires_in'] is an integer of seconds until the access_token expires.
        # Technically this self.__expires is inaccurate because it was true when LinkedIn generated the token, but
        # we receive and process that response some (very) small amount of time after it was true.
        self.__expires = datetime.utcnow() + timedelta(seconds=data['expires_in'])
        if data.get('refresh_token'):
            self.__refresh_token = data['refresh_token']
        if data.get('refresh_token_expires_in'):
            self.__refresh_token_expires_at = datetime.utcnow() + timedelta(
                seconds=int(data['refresh_token_expires_in'])
            )

        self.write_access_token_to_config()
        self._warn_if_refresh_token_expiring()

    def fetch_and_set_access_token(self):
        """
        This method generates a new access token if the refresh token is provided.

        Note: Linkedin-ads access token expires in 60 days, whereas the refresh token expires in 365 days.
        """
        # If the refresh token is not provided then we are assuming that it is an old connection
        # and client has provided the valid access_token already
        # Checking if the token is expired, It will be refreshed
        self._load_persisted_tokens()
        self._warn_if_refresh_token_expiring()
        if not self.__refresh_token:
            return

        if self.__access_token:
            # Subtracting 1 day from the expiration date to avoid the failure of the token in case of a longer sync run.
            if self.get_token_expires() - timedelta(seconds=86400) > datetime.utcnow():
                LOGGER.info('Existing token still valid; token expires %s', self.__expires.strftime("%Y-%m-%d %H:%M:%S"))
                return

        self.refresh_access_token()
        LOGGER.info('Retrieved new access token; token expires %s', self.__expires.strftime("%Y-%m-%d %H:%M:%S"))


        # Waiting 30 seconds after generating a new token
        # as it works after several seconds.
        time.sleep(30)

    # during 'Timeout' error there is also possibility of 'ConnectionError',
    # hence added backoff for 'ConnectionError' too.
    @backoff.on_exception(backoff.expo,
                          (Server5xxError, requests.exceptions.ConnectionError, requests.exceptions.Timeout),
                          max_tries=5,
                          factor=2)
    def check_accounts(self, config):
        if config.get('accounts'):
            account_list = config['accounts'].replace(" ", "").split(",")
            # Normalize to numeric IDs — accept both '12345' and 'urn:li:sponsoredAccount:12345'
            account_list = [
                a.rsplit(':', 1)[-1] if ':' in a else a
                for a in account_list if a
            ]
            if not account_list:
                return

            urn_list = ["urn%3Ali%3AsponsoredAccount%3A{}".format(a) for a in account_list]
            search_param = "(id:(values:List({})))".format(','.join(urn_list))
            accounts_check_url = 'https://api.linkedin.com/rest/adAccounts?pageSize={}&q=search&search={}'.format(
                len(account_list), search_param
            )
            response = self.get(
                url=accounts_check_url,
                endpoint='accounts',
                headers={'X-Restli-Protocol-Version': '2.0.0'}
            )
            # LinkedIn may return element IDs as URNs (e.g. "urn:li:sponsoredAccount:12345");
            # extract the trailing numeric portion so comparison works regardless of format.
            visible_ids = {
                str(e.get('id')).rsplit(':', 1)[-1]
                for e in response.get('elements', [])
            }
            invalid_account = [a for a in account_list if a not in visible_ids]
            if invalid_account:
                error_message = 'Invalid Linked Ads accounts provided during the configuration:{}'.format(invalid_account)
                raise Exception(error_message) from None

    @backoff.on_exception(
        backoff.expo,
        (Server5xxError, requests.exceptions.ConnectionError, Server429Error),
        # Choosing a max time of 10 minutes since documentation for the
        # [ads reporting api](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#data-throttling) says
        # "Data limit for all queries over a 5 min interval: 45 million metric values(where metric value is the value for a metric specified in the fields parameter)."
        max_time=600, # seconds
        jitter=backoff.full_jitter,
    )
    # backoff for 'Timeout' error
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.Timeout,
        max_tries=5,
        factor=2
    )
    def request(self, method, url=None, path=None, **kwargs):

        if not url and self.__base_url is None:
            self.__base_url = 'https://api.linkedin.com/rest'

        if not url and path:
            url = '{}/{}'.format(self.__base_url, path)

        if 'endpoint' in kwargs:
            endpoint = kwargs['endpoint']
            del kwargs['endpoint']
        else:
            endpoint = None

        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        kwargs['headers']['Authorization'] = 'Bearer {}'.format(self.__access_token)
        kwargs['headers']['Accept'] = 'application/json'
        kwargs['headers']['LinkedIn-Version'] = LINKEDIN_VERSION
        kwargs['headers']['Cache-Control'] = "no-cache"

        if self.__user_agent:
            kwargs['headers']['User-Agent'] = self.__user_agent

        if method == 'POST':
            kwargs['headers']['Content-Type'] = 'application/json'

        # Use query tunneling to allow large URIs
        # https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/query-tunneling?context=linkedin/context
        if method == 'GET':
            if url:
                url, query = url.split('?', 1)
                kwargs['data'] = query
            kwargs['headers']['Content-Type'] = 'application/x-www-form-urlencoded'
            kwargs['headers']['X-HTTP-Method-Override'] = 'GET'

        with metrics.http_request_timer(endpoint) as timer:
            response = self.__session.request('POST', url, timeout=self.request_timeout, **kwargs)
            timer.tags[metrics.Tag.http_status_code] = response.status_code

        if response.status_code != 200:
            raise_for_error(response)
        return response.json()

    def get(self, url=None, path=None, **kwargs):
        return self.request('GET', url=url, path=path, **kwargs)

    def post(self, url=None, path=None, **kwargs):
        return self.request('POST', url=url, path=path, **kwargs)
