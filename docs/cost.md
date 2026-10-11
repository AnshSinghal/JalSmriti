# What JalSmriti costs to run

Estimates for `us-west-2` at list prices checked in October 2026; prices change, so check the AWS pricing pages before
relying on them. "Free" means inside an always-free monthly allowance. New AWS accounts on the free plan also get
100 to 200 USD of credits for six months.

## Fixed

| Item | Monthly |
|---|---|
| KMS signing key (asymmetric, ECC P-256) | 1.00 USD, plus 0.15 USD per 10,000 signatures (one per dossier and one per place report) |
| Daily rain check and weekly lake check (EventBridge Scheduler) | free: about 35 scheduled runs a month; the daily run is a few seconds of a 512 MB function when few places are followed |
| Everything else when nobody uses the site | about 0 (S3 storage of a few hundred MB, idle DynamoDB, alarms and dashboard within the free allowance) |

## One-time: reading the nine areas after a deploy

Each area is 57 to 77 post-monsoon scenes from 1987 on, read by the geo worker (3,008 MB), plus static layers,
radar and names. Measured locally at 5 to 15 minutes per area; in Lambda that is roughly 5,000 to 9,000 GB-seconds
per area, **about 50,000 to 80,000 GB-seconds for all nine**. Lambda's free allowance is 400,000 GB-seconds and one
million requests a month, so the preload is free. Step Functions uses about 4,000 to 5,000 state transitions for it
(4,000 a month are free; the rest cost 0.025 USD per 1,000).

## Per use

| Action | What runs | Cost |
|---|---|---|
| Place check (first time for a spot) | 5 geo-worker steps at 3 GB: static, optical, radar and summer heat in parallel, then the score. The heat branch read 10 Landsat passes in 2 to 3 minutes per place in local runs (116 to 188 seconds) | about 400 GB-s without heat plus about 350 to 550 GB-s for heat: roughly 450 checks a month fit in the free Lambda allowance, then about 0.015 USD each |
| Place check (repeat within the same 150 m) | one DynamoDB read | free |
| Lake analysed on request | find, looks, static, latest, grade | similar to a place check without the heat branch |
| Photo of a lake | Rekognition moderation, faces and labels (3 calls), Amazon Nova Lite description, Lambda | about 0.003 USD (Rekognition) plus a few hundredths of a cent |
| Standing-water report | Rekognition moderation and faces (2 calls), Amazon Nova Lite look, Lambda | about 0.002 USD (Rekognition) plus a few hundredths of a cent |
| Dossier | Strands agent on Nova Lite (a few thousand tokens), Amazon Translate (about 3,000 characters), PDF, one KMS signature | Nova well under 0.001 USD; Translate about 0.045 USD (15 USD per million characters); Nepali, Assamese and Odia go through Nova instead |
| Signed place report | the jobs function (2 GB) reads the stored check and images, renders the PDF (under a second on a laptop, about 120 KB) and makes one KMS signature | one signature is 0.000015 USD; a few seconds of Lambda, free within the allowance |
| Narration (Listen) | Amazon Polly neural voice, once per text; replays come from S3 through CloudFront | 16 USD per million characters: a place text of about 900 to 1,200 characters is up to about 0.02 USD, a lake text (190 to 690 characters) about 0.01 USD or less. AWS lists 1 million neural characters a month free for the first 12 months |
| Rain forecast on a place page | the API reads the cached forecast for the 5 km cell, or asks Open-Meteo once an hour per cell | Open-Meteo's free API: non-commercial use, under 10,000 calls a day (also 5,000 an hour, 600 a minute and 300,000 a month in its pricing table); a commercial deployment needs a paid Open-Meteo plan |
| Rain heads-up email | SNS publish to the person's own topic | email: 1,000 a month free, then 2 USD per 100,000; publishes: 1 million requests a month free, then 0.50 USD per million |
| Lake-watch emails | SNS email | as above |
| Page views | CloudFront, S3, API Gateway, Lambda, DynamoDB | free up to CloudFront's 1 TB and 10 million requests a month; API Gateway HTTP API 1 USD per million requests after any free allowance |
| Search and base map | Amazon Location Service geocoding and map tiles | free for three months (20,000 geocodes and 500,000 tiles a month), then priced per 1,000 requests |
| Weekly check | 9 latest looks plus one check per watched lake | a few thousand GB-seconds a week: free |

Amazon Nova Lite is 0.06 USD per million input tokens and 0.24 USD per million output tokens. Cognito is free up to
10,000 monthly active users; its built-in email has a small daily quota (use Amazon SES for a public launch). SNS
charges for requests and deliveries, not for keeping topics, so one topic per person who follows places costs nothing
while it is idle.

The daily rain check asks Open-Meteo for up to 50 forecast cells in one request and stores each for an hour, so the
website reuses them. Open-Meteo's terms count one HTTP request as one call and do not say how a request for several
locations is counted; at demo scale both readings stay far below the free limits.

## Guard rails

Anonymous visitors can start satellite work, reports and narrations, so the API limits them:

- per address per day: 25 place checks, 10 lake analyses, 600 searches, 300 forecasts, 20 place reports and 30 new
  narrations; per account per day: 30 photos, 10 dossiers, 30 watches, 20 follows, 3 test emails, 10 RTI records and
  10 standing-water reports;
- for the whole site per day, set by Lambda environment variables on the API function (the defaults below apply when
  they are not set):

  | Variable | Default | What it bounds |
  |---|---|---|
  | `PLACE_CHECKS_PER_DAY` | 200 | first-time place checks |
  | `LAKE_ANALYSES_PER_DAY` | 40 | lakes analysed on request |
  | `SEARCHES_PER_DAY` | 5000 | place searches |
  | `REPORTS_PER_DAY` | 500 | signed place reports (an existing report is returned without counting) |
  | `NARRATIONS_PER_DAY` | 200 | new narrations (audio already made is served without counting) |
  | `WATER_REPORTS_PER_DAY` | 1000 | standing-water photos |
  | `FORECASTS_PER_DAY` | 5000 | forecast requests from the website; with the hourly cache per cell, the website makes at most this many Open-Meteo calls a day, half of Open-Meteo's free limit |

- only CloudFront can call the API, so the address used for limits is the one CloudFront saw.

Worst cases, if a cap were reached every single day of a 30-day month (none of this is expected at demo traffic):

| Cap | Worst case a month |
|---|---|
| 200 place checks | about 5 million GB-seconds, about 80 USD beyond the free Lambda allowance |
| 200 narrations of up to 1,200 characters | about 7.2 million characters, about 115 USD in Polly (about 16 USD less where the free allowance applies) |
| 1,000 standing-water reports | about 60 USD in Rekognition, plus Nova and Lambda |
| 500 place reports | 15,000 KMS signatures, about 0.23 USD, plus Lambda and about 2 GB of new PDFs in S3 |

Lower the caps if that matters, and consider an AWS Budgets alert on the account.
