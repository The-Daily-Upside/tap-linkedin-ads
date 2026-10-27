# tap-linkedin-ads

This is a [Singer](https://singer.io) tap that produces JSON-formatted data
following the [Singer
spec](https://github.com/singer-io/getting-started/blob/master/SPEC.md).

This tap:

- Pulls raw data from the [LinkedIn Marketing API](https://learn.microsoft.com/en-us/linkedin/marketing/) version `202610` (`LinkedIn-Version` header)
- Extracts the following resources:
  - [Ad Accounts](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts#search-for-accounts)
    - [Video Ads](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/advertising-targeting/create-and-manage-video#finders)
  - [Ad Account Users](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-account-users#find-ad-account-users-by-accounts)
  - [Campaign Groups](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaign-groups#search-for-campaign-groups)
  - [Campaigns](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaigns#search-for-campaigns)
    - [Ad Analytics by Campaign](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#analytics-finder)
    - [Creatives](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-creatives#search-for-creatives)
    - [Ad Analytics by Creative](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#analytics-finder)
- Outputs the schema for each resource
- Incrementally pulls data based on the input state

## Streams
[**accounts**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts#search-for-accounts)
- Endpoint: https://api.linkedin.com/rest/adAccounts
- Primary key field: id
- Foreign keys: reference_organization_id (organization), reference_person_id (person)
- Replication strategy: Incremental (query all, filter results)
  - Filter: account id (from config.json)
  - Sort by: account id ascending
  - Bookmark: last_modified_time (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested. String to decimal for total_budget field.
- Children: video_ads

[**video_ads**](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2024-03&tabs=curl#find-posts-by-account)
- Endpoint: https://api.linkedin.com/rest/posts
- Primary key field: content_reference
- Foreign keys: account_id (accounts), owner_organization_id (organizations)
- Required scope - `r_organization_social`
- Replication strategy: Incremental (query all, filter results)
  - Filter: account (from parent account) and owner (from parent account) (see NOTE below)
  - Bookmark: last_modified_time (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested.
- Parent: account
**NOTE**: The parent Account **MUST** reference and **Organization** (not a Person)
- [Campaign Manager User Roles for Video Ads](https://www.linkedin.com/help/lms/answer/90733/campaign-manager-user-roles-for-video-ads?lang=en)

[**account_users**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-account-users#find-ad-account-users-by-accounts)
- Endpoint: https://api.linkedin.com/rest/adAccountUsers
- Primary key fields: account_id, user_person_id
- Foreign keys: account_id (accounts), user_person_id (person)
- Replication strategy: Incremental (query all, filter results)
  - Filter: account (from config.json)
  - Bookmark: last_modified_time (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested.

[**campaign_groups**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaign-groups#search-for-campaign-groups)
- Endpoint: https://api.linkedin.com/rest/adCampaignGroups
- Primary key field: id
- Foreign keys: account_id (accounts)
- Replication strategy: Incremental (query all, filter results)
  - Filter: account (from config.json)
  - Sort by: Campaign Group id ascending
  - Bookmark: last_modified_time (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested.

[**campaigns**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaigns#search-for-campaigns)
- Endpoint: https://api.linkedin.com/rest/adCampaigns
- Primary key field: id
- Foreign keys: account_id (accounts)
- Replication strategy: Incremental (query all, filter results)
  - Filter: account (from config.json)
  - Sort by: Campaign id ascending
  - Bookmark: last_modified_time (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested. String to decimal for daily_budget and unit_cost amount fields. Targeting and Targeting Criteria are transformed to a generalized type with list array structure.
- Children: creatives, ad_analytics_by_campaign, ad_analytics_by_creative

[**creatives**](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-creatives?view=li-lms-2023-01&tabs=http#search-for-creatives)
- Endpoint: https://api.linkedin.com/rest/creatives
- Primary key field: id
- Foreign keys: campaign_id (campaigns)
- Replication strategy: Incremental (query all, filter results)
  - Filter: campaign_id (from parent campaign)
  - Sort by: Creative id ascending
  - Bookmark: last_modified_at (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times.
- Parent: campaign

[**ad_analytics_by_campaign**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#analytics-finder)
- Endpoint: https://api.linkedin.com/rest/adAnalytics
- Primary key fields: campaign_id, start_at
- Foreign keys: campaign_id (campaigns)
- Granulariy: One record per day per campaign_id
- Replication strategy: Incremental (query filtered by bookmark date range)
  - Filter: campaign_id (from parent campaign), start/end date range (bookmark date - 7 days to current date)
  - Bookmark: end_at (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested. Currency and cost fields strings to decimals. Pivot URN to campaign and campaign_id.
- Parent: campaign

[**ad_analytics_by_creative**](https://docs.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting#analytics-finder)
- Endpoint: https://api.linkedin.com/rest/adAnalytics
- Primary key fields: creative_id, start_at
- Foreign keys: creative_id
- Granulariy: One record per day per creative_id
- Replication strategy: Incremental (query filtered by bookmark date range)
  - Filter: campaign_id (from parent campaign), start/end date range (bookmark date - 7 days to current date)
  - Bookmark: end_at (date-time)
- Transformations: Fields camelCase to snake_case. URNs to ids. Unix epoch millisecond integers to date-times. Audit date-times created_at and last_modified_at de-nested. Currency and cost fields strings to decimals. Pivot URN to creative and creative_id.
- Parent: campaign

## Authentication
LinkedIn Marketing APIs have no service-account or client-credentials flow that works for ads. This tap uses 3-legged OAuth for an approved [Marketing Developer Platform](https://www.linkedin.com/developers/apps) app.

- **Access token:** about 60 days. The tap refreshes it with the refresh token when it is inside one day of expiry (or already inactive).
- **Refresh token:** 365 days from the member consent that created it. Refreshing the access token does **not** extend it. The member must re-authorize once a year.
- Programmatic refresh tokens are only returned for approved Marketing Developer Platform apps. See [Refresh tokens](https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens).

Set `client_id`, `client_secret`, `refresh_token`, and the initial `access_token`. Optional `token_file_path` is where the tap writes the latest tokens (mode `0600`). Meltano rebuilds its config from environment variables every run, so without that file the refreshed access token would be discarded and the tap would refresh again on the next run. The file wins over those env values, including when LinkedIn rotates the refresh token. A re-authorization replaces the file when the new `refresh_token` is different and `refresh_token_expires_at` is later than the expiry in the file. Deleting the file also lets the env grant take over.

`scripts/exchange_auth_code.py` prints the authorize URL and exchanges the redirect `code` for both tokens. The exchange is refused unless `state` on the redirect matches the `state` that was sent on the authorize URL.

If the tap receives a 401 invalid token response and no refresh token is configured, the error logs say the access token has expired and the connection must be re-authenticated.
This is described more in [LinkedIn OAuth 2.0 Docs](https://docs.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow?context=linkedin/context).

The API user account should be assigned one of the following roles:
- ACCOUNT_BILLING_ADMIN
- ACCOUNT_MANAGER
- CAMPAIGN_MANAGER
- CREATIVE_MANAGER
- **VIEWER** (Recommended)

The API user account should be assigned the following **permissions** for the API endpoints:
- accounts, account_users, video_ads, campaign_groups, campaigns, creatives:
    - r_ads: read ads (Recommended)
    - rw_ads: read-write ads
- ad_analytics_by_campaign, ad_analytics_by_creative:
    - r_ads_reporting: read ads reporting

**NOTE**: Legacy permissions (r_ad_campaigns) have been migrated to the new permissions (r_ads and r_ads_reporting) based on this [permissions mapping](https://docs.microsoft.com/en-us/linkedin/shared/references/migrations/marketing-permissions-migration?context=linkedin/marketing/context). 

To generate the **access_token**:
1. Login to LinkedIn as the API user.
2. Create an [API App here](https://www.linkedin.com/developers/apps):
    - App Name: tap-linkedin-ads
    - Company: search and find your company LinkedIn page
    - Privacy policy URL: link to company privacy policy
    - Business email: developer/admin email address
    - App logo: Stitch (or Company) logo
    - Products: Select Marketing Developer Platform (checkbox)
    - Review/agree to legal terms and create app
3. Verify App: 
    - Provide the verify URL to your Company's LinkedIn Admin to verify and authorize the app.
    - Once verified, select the [App in the Console here](https://www.linkedin.com/developers/apps). 
    - Review the “Auth” tab:
    - Record **client_id** and **client_secret** (for later steps).
    - Review permissions and ensure app has the permissions (above).
    - Oauth 2.0 settings: Provide a **redirect_uri** (for later steps): https://www.google.com
    - Review the “Products” tab and ensure “Marketing Developer Platform” has been added and approved (listed in the “added products” section).
    - Review the “Usage & limits” tab. This shows the daily application and user/member limits with percent used for each resource endpoint.
4. Authorize App: The access token lasts 60 days. The refresh token lasts 365 days from this consent, then the member must re-authorize. `scripts/exchange_auth_code.py --print-auth-url` builds the URL below.
    - Create an Authorization URL with the following pattern
      - Create a random alphanumeric **state_key** (used to prevent [CRSF](https://en.wikipedia.org/wiki/Cross-site_request_forgery)).
      - URL pattern: Provide the scope from permissions above (with + delimiting each permission) and replace the other highlighted parameters: https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT_URI&scope=YOUR_PERMISSIONS_SCOPE&state=YOUR_STATE_KEY
    - In web browser, navigate to Authorization URL.
    - Once redirected, click “Allow” to authorize app.
    - The browser will be redirected to the redirect_uri. Copy that full URL. It contains `code` and the same `state` you sent.
5. Exchange only after `state` matches. Pass the same `--state` from the authorize URL and the full redirect URL. The script compares them before the token request. The JSON includes `access_token`, `expires_in` (~60 days), `refresh_token`, and `refresh_token_expires_in` (~365 days). Keep the refresh token. Re-authorize when it expires; refreshing does not move that date.
```bash
python scripts/exchange_auth_code.py \
    --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET \
    --redirect-uri YOUR_REDIRECT_URI --state YOUR_STATE_KEY \
    --redirect-url 'THE_FULL_REDIRECT_URL' \
    --out /path/to/linkedin-ads-tokens.json
```
The token endpoint does not check `state`. Use the script above so the redirect `state` is compared locally before the code is spent.
6. Create config.json. `accounts` is one or more numeric ad account ids, comma-separated (URNs are accepted). See [config.json.example](config.json.example).
```json
{
  "start_date": "2024-01-01T00:00:00Z",
  "user_agent": "tap-linkedin-ads <api_user_email@your_company.com>",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "refresh_token": "YOUR_REFRESH_TOKEN",
  "access_token": "YOUR_ACCESS_TOKEN",
  "token_file_path": "/absolute/path/linkedin-ads-tokens.json",
  "accounts": "123456789",
  "request_timeout": 300
}
```

## Quick Start

1. Install

    Clone this repository, and then install using setup.py. We recommend using a virtualenv:

    ```bash
    > virtualenv -p python3 venv
    > source venv/bin/activate
    > python setup.py install
    OR
    > cd .../tap-linkedin-ads
    > pip install .
    ```
2. Dependent libraries
    The following dependent libraries were installed.
    ```bash
    > pip install singer-python
    > pip install singer-tools
    > pip install target-stitch
    > pip install target-json
    
    ```
    - [singer-tools](https://github.com/singer-io/singer-tools)
    - [target-stitch](https://github.com/singer-io/target-stitch)
3. Create your tap's `config.json` file which should look like the following:

    ```json
    {
        "start_date": "2019-01-01T00:00:00Z",
        "user_agent": "tap-linkedin-ads <api_user_email@your_company.com>",
        "access_token": "YOUR_ACCESS_TOKEN",
        "accounts": "id1, id2, id3",
        "request_timeout": 300
    }
    ```
    
    Optionally, also create a `state.json` file. `currently_syncing` is an optional attribute used for identifying the last object to be synced in case the job is interrupted mid-stream. The next run would begin where the last job left off.

    ```json
    {
        "currently_syncing": "creatives",
        "bookmarks": {
            "accounts": "2019-06-11T13:37:55Z",
            "account_users": "2019-06-19T19:48:42Z",
            "video_ads": "2019-06-18T18:23:58Z",
            "campaign_groups": "2019-06-20T00:52:46Z",
            "campaigns": "2019-06-19T19:48:44Z",
            "creatives": "2019-06-11T13:37:55Z",
            "ad_analytics_by_campaign": "2019-06-11T13:37:55Z",
            "ad_analytics_by_creative": "2019-06-11T13:37:55Z"
        }
    }
    ```

4. Run the Tap in Discovery Mode
    This creates a catalog.json for selecting objects/fields to integrate:
    ```bash
    > tap-linkedin-ads --config config.json --discover > catalog.json
    ```
   See the Singer docs on discovery mode
   [here](https://github.com/singer-io/getting-started/blob/master/docs/DISCOVERY_MODE.md#discovery-mode).

5. Run the Tap in Sync Mode (with catalog) and [write out to state file](https://github.com/singer-io/getting-started/blob/master/docs/RUNNING_AND_DEVELOPING.md#running-a-singer-tap-with-a-singer-target)

    For Sync mode:
    ```bash
    > tap-linkedin-ads --config tap_config.json --catalog catalog.json > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    To load to json files to verify outputs:
    ```bash
    > tap-linkedin-ads --config tap_config.json --catalog catalog.json | target-json > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    To pseudo-load to [Stitch Import API](https://github.com/singer-io/target-stitch) with dry run:
    ```bash
    > tap-linkedin-ads --config tap_config.json --catalog catalog.json | target-stitch --config target_config.json --dry-run > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```

6. Test the Tap
    
    While developing the Linkedin Ads tap, the following utilities were run in accordance with Singer.io best practices:
    Pylint to improve [code quality](https://github.com/singer-io/getting-started/blob/master/docs/BEST_PRACTICES.md#code-quality):
    ```bash
    > pylint tap_linkedin_ads -d missing-docstring -d logging-format-interpolation -d too-many-locals -d too-many-arguments
    ```
    Pylint test resulted in the following score:
    ```bash
    Your code has been rated at 9.95/10 (previous run: 9.83/10, +0.12).
    ```

    To [check the tap](https://github.com/singer-io/singer-tools#singer-check-tap) and verify working:
    ```bash
    > tap-linkedin-ads --config tap_config.json --catalog catalog.json | singer-check-tap > state.json
    > tail -1 state.json > state.json.tmp && mv state.json.tmp state.json
    ```
    Check tap resulted in the following:
    ```bash
    The output is valid.
    It contained 833 messages for 8 streams.

        29 schema messages
        765 record messages
        39 state messages

    Details by stream:
    +--------------------------+---------+---------+
    | stream                   | records | schemas |
    +--------------------------+---------+---------+
    | accounts                 | 2       | 1       |
    | video_ads                | 432     | 4       |
    | account_users            | 20      | 1       |
    | campaigns                | 206     | 1       |
    | ad_analytics_by_creative | 47      | 9       |
    | ad_analytics_by_campaign | 51      | 6       |
    | creatives                | 5       | 6       |
    | campaign_groups          | 2       | 1       |
    +--------------------------+---------+---------+
    ```
---

Copyright &copy; 2019 Stitch
