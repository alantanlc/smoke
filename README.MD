# GXP Smoke Test

GXP Automated Smoke Test

## Features

1. Run smoke test for multiple flows concurrently
1. Run smoke test on different environments
1. Re-run smoke test for failed/incomplete transactions
1. View statuses of all transactions
1. Mock sanctions/fundcontrol/clearing/posting for all transactions
1. Toggle business live flag
1. Toggle source system for incoming transactions (RRCT, RDDT, RRTN)
1. NFT: Continuously trigger transactions at a given TPS (transactions per second) and duration in minutes
1. NFT: Soak test (Trigger transactions at given intervals, e.g. 2 transactions every 15 minutes)

## Dependencies

- python3+
- pip3
- virtualenv (optional)

## Setup virtualenv (optional)

First, create a virtualenv directory:
```
$ virtualenv env
```

Once env directory has been created, activate the virtualenv:

__macOS/Linux__
```
$ source env/bin/activate
```

__Windows__
```
$ .\env\Scripts\activate
```

## Install packages

Install python packages using pip:
```
$ pip install -r requirements.txt
```

## How to run

Using python:
```
python smoke.py
```
Note: By default, this loads configuration from `./config/ua1/config.yaml` which points to `UA1`.

To run on a specific environment, e.g. `dev`:
```
python smoke.py --env dev
```
Note: Possible environments are `dev`, `qa1`, `qa2`, `ua1`, `ua2`, `ua3`, `ua4`, `perf`
