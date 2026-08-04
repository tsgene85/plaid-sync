# Overview

`plaid-sync` is a Python based command-line interface to the [Plaid API](https://plaid.com/docs/api/) that synchronizes your bank/credit card transactions to a local SQLite database.

## Table of Contents

- [Overview](#overview)
  - [Use-Cases](#use-cases)
  - [Plaid](#plaid)
  - [Plaid Link](#plaid-link)
  - [Limitations](#limitations)
- [Usage](#usage)
  - [Installation](#installation)
    - [uv (recommended)](#uv-recommended)
    - [pip / venv](#pip--venv)
  - [Configuration](#configuration)
  - [Linking a Real Account (Production)](#linking-a-real-account-production)
  - [Updating an Expired Account](#updating-an-expired-account)
- [WARNINGS](#warnings)
- [TODO](#todo)

## Use-Cases

The data can be easily queried using SQLite JSON query syntax, so this could be used as part of a standard personal finance workflow. Determine how often you eat out, how
much you spend on groceries, when was the last time you shopped at a particular store.

My particular use-case is to process the resulting trasansactions into a 
[beancount](http://furius.ca/beancount/) journal file for use with [Fava](https://beancount.github.io/fava/) as well as the beancount Python API for custom reporting/charting.

## Plaid

Plaid's API provides a way to connect to your bank accounts to obtain transactions
and balance data from a large variety of banks in a standardized way. Plaid offers a "free forever" developer program with 100 accounts supported, and a pay as you go "Launch" program with no publicly stated pricing, but once you're signed up you have access to the pricing details. API keys (beyond the fake data sandbox mode) are gated behind a customer service agent approving your use-case.

For more details, see [Plaid's website](https://dashboard.plaid.com/signup).

## Plaid Link

Plaid no longer supports an API-based method for establishing new accounts or updating
existing accounts with credentials (username, password). This helps prevent third party
programs from getting access to user's credentials, but also makes programs like this
have to go through some more hoops to set up. 

Specifically, you have to use the [Plaid Link API](https://plaid.com/docs/link/), and run that in a web browser. That the uses iframes to isolate the credentials updates to
just Plaid's servers/code. 

This program incorporates a very simple webserver to handle the Plaid Link portion. This is only needed when setting up a new account, or when an existing account needs a credentials refresh. In my experience, the credentials refresh is going to happen periodically - one bank has a 90 day policy, another needed it after I was locked out of my account due to invalid login attempts. 

## Limitations

Plaid's lower tiers do not provide investment or libabilities details, so this cannot
sync mortgage or brokerage transactions. It does work fine with all of the credit card and bank accounts I need it to.

# Usage

## Installation

Requires Python 3.9+ (see `pyproject.toml`). The main dependency is the Plaid API (`plaid-python>=30.0.0`). This version is required for personal finance categories and other modern Plaid features.

There is one optional dependency, [`tqdm`](https://github.com/tqdm/tqdm), if you want fancy progress bars during syncing. If you don't install it, you just get unfancy print
messages. My current account load takes about 4 seconds to sync.

This is not set up to be run/installed as a command line program, but could be easily done so.

### uv (recommended)

Install [uv](https://docs.astral.sh/uv/), then from the repository root:

```
uv sync
uv sync --extra progress   # optional: tqdm progress bars
```

This creates `.venv` and installs locked dependencies from `uv.lock`. Run commands with:

```
uv run python plaid-sync.py -c config/sandbox
```

### pip / venv

Clone the repository, create a virtual environment, and install dependencies:

```
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -r requirements.txt
pip install tqdm          # optional
```

## Configuration

Establish a configuration file with your Plaid credentials. This is in standard INI format. There is an example file `config/sandbox`;

```
[PLAID]
client_id = XXXXXXXXXXXXX
secret = XXXXXXXXXXXXXX
public_key = xXXXXXXXXXXXXXXX
environment = sandbox

[plaid-sync]
dbfile = /tmp/sandbox.db

; account definitions will be added by plaid-sync
; when --link-account step is run
;
; but if you already have Plaid access tokens, you
; can add them as such:
;
; [Friendly Account Name]
; access_token = XXXXXXXXXXXX
; disabled=false/true
```

Once you've set up the basic credentials, run through linking a new account:

```
$ ./plaid-sync.py -c config/sandbox --link-account 'Test Chase'

Open the following page in your browser to continue:
    http://127.0.0.1:4583/link.html
```

Open the above link, follow the instructions (click the button, find your bank, enter credentials).

The console will then update with confirmation:

```
Public token obtained [public-sandbox-XXXX]. Exchanging for access token.
Access token received: access-sandbox-XXXX

Saving new link to configuration file
Backing up existing configuration to: config/sandbox.1605537592.bkp
Overwriting existing config file: config/sandbox

Test Chase is linked and is ready to sync.
```

Your config file will have updated to have a line for this new account:

```
[Test Chase]
access_token = access-sandbox-XXXX
```

And you can now run the sync process:

```
$ ./plaid-sync.py -c config/sandbox
                                                                                       
Finished syncing 2 Plaid accounts using cursor-based sync

Test Chase : 16 new transactions (0 pending),  0 archived transactions over 5 accounts
```

The sync process now uses Plaid's cursor-based `/sync` endpoint by default. If you want to use this project's original
date-range based sync you can supply the argument `--date-range-sync`

```
$ ./plaid-sync.py -c config/sandbox --date-range-sync -s "2025-08-21" -e "2025-09-21"
```

Included is a script `./show_recent.sh` to quickly check the recent transactions saved in the database file.

```
$ ./show_recent.sh sandbox.db

2025-09-21T14:34:26Z|Uber 063015 SF**POOL**|5.4
2025-09-21T14:34:26Z|United Airlines|-500.0
2025-09-21T14:34:26Z|McDonald's|12.0
```

## Linking a Real Account (Production)

Sandbox only creates fake test Items. To sync a real bank or credit card, you must use Plaid's **Production** environment. See the [Plaid docs overview](https://plaid.com/docs/), [API environments](https://plaid.com/docs/api/#api-host), [Link](https://plaid.com/docs/link/), and [Sandbox vs Production](https://plaid.com/docs/sandbox/).

Plaid has two environments with separate API hosts and secrets:

| Environment | API host | Purpose |
|-------------|----------|---------|
| Sandbox | `https://sandbox.plaid.com` | Fake institutions and test credentials |
| Production | `https://production.plaid.com` | Real institutions and live account data |

**Items and access tokens cannot move between environments.** A Sandbox-linked account cannot be reused in Production; you must complete Link again with Production credentials.

### 1. Get Production access and keys

1. Sign up / log in at the [Plaid Dashboard](https://dashboard.plaid.com/).
2. Open [API Keys](https://dashboard.plaid.com/developers/keys). You get one `client_id` and a **separate `secret` per environment**. Copy the **Production** secret (not Sandbox).
3. Request Production (or Trial) access from the Dashboard ([Production access](https://dashboard.plaid.com/overview/production)). New teams may be able to test live data on a [Trial plan](https://plaid.com/docs/sandbox/#testing-with-live-data-using-a-trial-plan) before full billing approval.
4. In [Link customization](https://dashboard.plaid.com/link), complete any required use-case / Data Transparency settings. Accounts created after late 2024 often need this before Production Link will work with real banks.
5. For many US banks that use OAuth (Chase, Bank of America, Wells Fargo, etc.), complete [OAuth institution registration](https://plaid.com/docs/link/oauth/) in the Dashboard. On a Trial plan this may be deferred until you move to a paid plan; without registration, some major institutions will not appear or will fail to link.

### 2. Create a Production config

Use a **separate** config file and database from Sandbox so you never mix tokens or environments:

```
[PLAID]
client_id = YOUR_CLIENT_ID
secret = YOUR_PRODUCTION_SECRET
environment = production

[plaid-sync]
dbfile = ./production.db
```

Notes:

- `environment` must be `production` (this project maps that to `https://production.plaid.com`).
- Do not put a Sandbox `secret` in a Production config (or the reverse).
- Keep this file private; the Production `secret` and later `access_token` values grant access to real financial data.

### 3. Link the real account with Plaid Link

In Production, [Link is required](https://plaid.com/docs/link/) — you cannot create Items by API alone (that Sandbox-only shortcut does not exist here).

```
$ ./plaid-sync.py -c config/production --link-account 'My Chase Checking'

Open the following page in your browser to continue:
    http://127.0.0.1:4583/link.html
```

Open the page, click the button, pick your real institution, and complete login / MFA / OAuth in the browser. On success, plaid-sync exchanges the temporary `public_token` for a permanent Production `access_token` and writes it into your config:

```
[My Chase Checking]
access_token = access-production-XXXX
```

Then sync as usual:

```
$ ./plaid-sync.py -c config/production -v
```

Optional: flatten `plaid_json` into columns while syncing with `-tj`, or run `plaid-transform.py -d production.db` afterward.

### Production caveats

- **Desktop Link / OAuth:** For desktop web, Plaid typically opens the bank OAuth flow in a pop-up. Stay on the local Link page until the console confirms the token exchange. See the [OAuth guide](https://plaid.com/docs/link/oauth/) if a bank fails mid-redirect.
- **Credentials refresh:** Real Items still expire into `ITEM_LOGIN_REQUIRED`; use `--update-account` the same way as in Sandbox (see below).
- **Billing / limits:** Production usage may count against Trial Item limits or paid plan quotas. Do not discard Production access tokens carelessly.
- **Scope of this tool:** plaid-sync initializes Link for the **Transactions** product only. Investment and liabilities data still require higher Plaid product access and are not fully supported here.

## Updating an Expired Account

Occasionally you'll get an error like this while syncing:

```
./plaid-sync.py -c config/sandbox                       

Finished syncing 2 Plaid accounts

Test Chase :  0 new transactions (0 pending),  0 archived transactions over 0 accounts
           : *** Plaid Error ***
           : ITEM_LOGIN_REQUIRED: the login details
           : of this item have changed (credentials,
           : MFA, or required user action) and a user
           : login is required to update this
           : information. use Link's update mode to
           : restore the item to a good state
           : *** re-run with: ***
           : --update 'Test Chase'
           : to fix
```

This just means your bank either isn't accepting the old credentials, or has a setup/arrangement where the login needs to be refreshed periodically. 

This process requires the Plaid Link (web browser) process again, but it's fairly painless. 

Just run the update process:

```
$ ./plaid-sync.py -c config/sandbox --update 'Test Chase'
Starting account update process for [Test Chase]

Open the following page in your browser to continue:
    http://127.0.0.1:4583/link.html
```

Open the page in your browser, click the button, enter new credentials, return to the console, confirm the process completed:

```
Public token obtained [public-sandbox-be30eb9a-8bcb-4dd0-9cf5-048ca7dfa5a3].

There is nothing else to do, the account should sync properly now with the existing credentials.
```

The sync process should run normally again.

# WARNINGS

When linking/setting up a new account, your public token (temporary) and access token (permanent) cannot be recovered if lost. I've taken care to show them to you during this process in both the browser and the command line so you can recover the flow if 
something goes wrong. Once you've saved the access token, you don't need the public token anymore.

This is important for accounts in the "test" level, as there is a 100 lifetime account limit.

# TODO

* Request and store balance amounts in a new table in the SQLite database.
* Formalize setup process, add `setup.py`, ensure support for installation through [pipx](https://github.com/pipxproject/pipx).