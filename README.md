# JalSmriti: water remembers

Made by **Ansh Singhal**.

![JalSmriti: Bengaluru's water memory over a Sentinel-2 image of December 2025](docs/images/landing.jpg)

Indian cities flood where their lakes used to be. JalSmriti reads forty years of open satellite data and tells anyone in
India or Nepal, in plain words and in their own language, what a place remembers about water: whether the street was
once a tank bed, how the ground drains, whether monsoon radar has seen water standing there, and how hot the ground
gets in summer. It then turns that record into steps for this week: what to ask before renting, when heavy rain is
coming, where to report standing water and whom to ask for a lake's records. For lake groups it turns satellite
history and citizens' photos into a signed complaint that any office can verify, and that officials answer on the
record.

It is built to run as a public website on AWS, deployed into a new AWS account with one command.

## For the judges

**Track:** Heat and Water.

**Demo video:** `https://youtu.be/<video id>` (under 3 minutes; the script is in
[docs/demo-script.md](docs/demo-script.md)).

**The problem.** Indian cities flood, and heat up, where their lakes and tanks used to be, but the record of where
water lived sits in satellite archives that only specialists read. So a family choosing a flat, a resident before the
monsoon and a lake group facing encroachment get no plain answer, and nothing they can act on this week.

**Who it is for:** someone about to rent or buy a home, a resident who wants to be ready for the monsoon, a lake group,
and the officers who have to answer them.

**Before the flood.** We checked 16 places that flooded, or where families lost homes on old lake land, between 2020
and 2026 (Velachery, the Budameru colonies of Vijayawada, Kendriya Vihar, Yamuna Bazar, the Kathmandu Valley and
others). All 16 show warning signs in their satellite record. For a family renting a ground-floor flat, JalSmriti's
read is "think twice" or "look elsewhere" at 14 of them. On the validation set it warns at 82% of 39 flooded
localities, against 53% of 240 ordinary built-up places. See [docs/case-studies.md](docs/case-studies.md) and the
site's **Past floods** page.

**Try it in 2 minutes.** The website is live at **https://d2av4xxvyq12ej.cloudfront.net** (deployed in AWS Asia
Pacific (Sydney); `python3 deploy.py` prints the address of your own deployment and `python3 deploy.py --status`
prints it again). Checking places, downloading reports and listening need no account. To follow a place or report standing water, sign in with a demo account (`citizen@example.com`;
`verifier@example.com`, `officer@example.com` and `admin@example.com` open the review console) or create your own with
any email address you can read. Demo passwords are generated at deploy time and printed by
`python3 deploy.py --show-passwords`.

1. **Check Bellandur.** On the home page choose "I'm renting or buying a home", then the chip "Bellandur, Bengaluru".
   The place page shows strong water memory (79 of 100 in our run): old lake beds built over nearby, a bowl in the
   ground, low land by a drain line. The same page has monsoon radar, summer heat and rain for the next three days.
2. **Get our read.** Under "Our read", tap renting or buying, the floor, a car in basement parking, and elderly people
   or small children at home. The verdict changes as you tap ("Look elsewhere", "Think twice", "Fine, with checks" or
   "Good to go"), with why, what is in its favour and against it, and what to do if you still like the place.
   "What to do this week" lists what to ask the owner and neighbours; switch to "Living here" for the resident's list.
3. **Download the signed report and verify it.** "Signed report (PDF)", then "Download PDF" and "Check the signature":
   your browser checks the AWS KMS signature itself. Drop the PDF on that page; change one byte and the check fails.
4. **Listen in Hindi.** "Listen", then "हिन्दी": Amazon Polly reads the report and the first three steps aloud.
5. **Open Bellandur Lake** (Explore lakes, Bengaluru). "Why it is like this" lists the likely causes with the numbers
   behind each (here weeds and sewage, less water reaching it, a bed overgrown from space); "What would help" says what
   residents can do and what to ask the authorities for; "In the news" shows recent headlines naming the lake.
   "Ask for the records (RTI)" drafts a Right to Information request.
6. **Try a random photo.** "Add a photo" with a screenshot or a poster: it comes back as "This does not look like a
   photo of the lake", is kept private and never enters the lake's record.

## What it does

- **Check a place.** Type a locality or point at the map. In two to four minutes you get its water memory (strong,
  some or little), what the records show, a time-lapse of the same spot since 1990, every monsoon radar pass since
  2017 that saw unusual standing water, how hot the ground gets on summer mornings next to built-up ground, lake water
  and trees nearby, the rain forecast for the next three days, and how often people reported standing water within
  1 km in the last year.
- **What to do this week.** Up to seven concrete steps for the place, in two lists: for someone about to rent or buy
  (what to ask, which floor to prefer, which land records to check, insurance) and for someone who lives there
  (drains, a way out over higher ground, heat, official warnings). Radar dates become questions about those days. The
  home page asks "What brings you here?" and opens the matching list.
- **Our read, for renting or buying.** Four quick taps (renting or buying, which floor, a car in basement parking,
  elderly people or small children at home) turn the record into a clear verdict: "Look elsewhere", "Think twice",
  "Fine, with checks" or "Good to go", with why (what the water memory means, against the flooded places we tested),
  what is in its favour, what is against it, and what to do if the family still likes the place: take the first floor,
  skip basement parking, ask about the floods the area remembers, check the land against the lake's full tank level.
  Buying adds the legal risk of old lake land. The answers stay on the device and go into the signed report.
- **Signed place report.** A PDF of one or two pages in the reader's language, for the chosen reader, with our read
  (for someone renting or buying), this week's steps and four questions for the owner or seller, signed with a key
  held in AWS KMS. Anyone can check it at `/verify/<report id>` in their own browser.
- **Listen.** Place and lake reports read aloud in Hindi or English by Amazon Polly (neural voice Kajal).
- **Rain heads-up.** Follow a place and get an email when heavy rain is forecast there for today or tomorrow. A job
  every morning compares the forecast with the India Meteorological Department's rain categories, with lower
  thresholds where the place has a water memory. A test email shows what one looks like.
- **Report standing water.** A photo, the location and the depth go through the same privacy checks as lake photos,
  Amazon Nova checks that standing water is visible, and the report appears on a live map of the last 48 hours or
  7 days. NGO verifiers confirm or reject reports.
- **Explore lakes.** Nine areas are read in full: Bengaluru, Chennai, Hyderabad, Delhi-NCR, Kochi, Sivasagar (Assam),
  Bhadrak (Odisha), Kathmandu Valley and Butwal (Nepal). That is 1,138 water bodies, each graded A to E, with water
  spread after every monsoon since 1987, what replaced lost water, floating weeds and radar maps of recent floods
  (2026 floods in Kerala, Assam, Odisha and Butwal). Any other water body in India or Nepal is analysed on request.
  A water body that no map names is named after what is near it ("Water body near Bellandur Lake", "Water body 1.9 km
  south of Agara Lake"), never just "unnamed".
- **Why a lake is like this.** Each lake page reads the likely causes from its record, most serious first, each with
  its numbers and the data it rests on: built on its bed, filled in or drying out, covered by plants, less water
  reaching it, choked by weeds and algae, or holding up. Then what would help: what residents can do (each with a
  button on the page) and what to ask the authorities for; how much monsoon water the lost spread would hold again if
  restored; recent news naming the lake about floods, encroachment, pollution or restoration (Google News search, with
  the GDELT Project's open index as a fallback, cached 12 hours); and how the lake is being protected on JalSmriti
  (photos, verifications, dossiers, RTI requests, watchers, ledger entries).
- **Defend a lake.** Add photos (GPS checked against the lake outline, faces blurred, and refused when they are not
  photos of the place at all: Rekognition counts the printed words and reads the labels, and Amazon Nova is asked
  whether it is a real photo taken at the lake), have an NGO verifier confirm them, and prepare a dossier: a letter drafted by an AI agent from computed facts only, translated into one of 13
  languages of India and Nepal, rendered as a PDF and signed with a key held in AWS KMS. Anyone can verify the
  signature in the browser. Every step goes into the lake's tamper-evident ledger.
- **Ask for the records.** A Right to Information request for a lake's survey records, encroachments, permits and
  works, under India's RTI Act 2005 or Nepal's RTI Act 2007, to copy, download or print. Record that you filed it and
  the lake's ledger shows when a reply is due: 30 days in India, 15 in Nepal.
- **Watch a lake.** Get an email when the weekly satellite check sees a change.
- **Share.** WhatsApp buttons on place, lake and dossier pages, where neighbourhood groups already talk.
- **Review console.** Verifiers and officers work in their own areas under 16 written access rules (Cedar). Every
  allowed and denied action is logged with the rule that decided it.
- **Past floods.** Sixteen places that flooded between 2020 and 2026, what happened and what the records say (with
  sources), JalSmriti's read of each and the verdict for a family renting there, next to the same verdict on the
  validation set.

The interface speaks English, Hindi, Kannada, Tamil, Telugu, Malayalam and Nepali, in a light and a dark theme. The
same site works on phones, tablets and laptops: every page was checked from 320 to 1440 px wide with no sideways
scrolling, and on touch screens every control is at least 44 px, the size of a fingertip.

| | |
|---|---|
| ![Our read for a family renting a ground-floor flat at Bellandur: think twice, with why, for, against and what to do](docs/images/our-read.jpg) | ![Why Bellandur Lake is like this, and what would help](docs/images/lake-why.jpg) |
| ![Before the flood: what our read would have said at 16 places that flooded](docs/images/past-floods.jpg) | ![A screenshot uploaded as lake evidence is refused](docs/images/photo-refused.jpg) |
| ![Place check, Bellandur: water memory, report, share and listen](docs/images/place-check.jpg) | ![Rain in the next three days, this week's steps and summer heat](docs/images/this-week.jpg) |
| ![Signed place report in Kannada, both pages](docs/images/place-report.jpg) | ![The same report checked in the browser](docs/images/verify.jpg) |
| ![Standing water reported by people, last 48 hours](docs/images/standing-water.jpg) | ![Right to Information request for Bellandur Lake](docs/images/rti.jpg) |
| ![Lake page, Bellandur](docs/images/lake.jpg) | ![Radar flood map, Sivasagar, August 2026](docs/images/radar-sivasagar.jpg) |
| ![Signed dossier](docs/images/dossier.jpg) | ![Audit log with Cedar decisions](docs/images/audit-log.jpg) |
| ![Dark theme](docs/images/landing-dark.jpg) | ![Hindi interface](docs/images/landing-hindi.jpg) |

![The place page on a laptop, a tablet and a phone](docs/images/devices.jpg)

![Phone layouts: home, this week's steps and standing water](docs/images/phones.jpg)

## Where AWS fits

| AWS service | What it does in JalSmriti |
|---|---|
| Amazon CloudFront | Serves the website, map layers, PDFs and audio; the only way to reach the API (it adds a stack-unique header that the API checks). While AWS has not yet verified a brand-new account for CloudFront, API Gateway serves the site instead |
| Amazon S3 | Site bucket for the web app and everything public under `/pub/`; private data bucket for original photos and rasters, uploaded by presigned POST |
| Amazon API Gateway (HTTP API) | Public `/v1` routes, and `/v1/secure` routes behind a Cognito JWT authorizer |
| AWS Lambda | Five functions: `api` (Powertools router, Cedar decisions), `geo` (GDAL and rasterio, reads the satellite archives), `evidence` (photo pipeline), `jobs` (dossiers and place reports), `alerts` (daily rain heads-up) |
| AWS Step Functions | A place check runs four parallel branches (Static, Optical, Radar, Heat), then scores; an area run reads 57 to 77 post-monsoon scenes since 1987 with a Distributed Map; lake on request, the weekly check and the deploy-time preload are workflows too |
| Amazon DynamoDB | One table: areas, lakes, place checks, jobs, evidence, dossiers, place reports, follows, standing-water reports, RTI records, ledgers, audit log, rate limits and the forecast cache |
| Amazon Cognito | Accounts, email confirmation, and the verifier, officer and admin groups |
| Amazon Bedrock (Amazon Nova Lite) | The letter-drafting agent (Strands Agents); whether an upload is a real photo of the lake at all, and what it shows; whether a standing-water photo shows water and how deep; Nepali, Assamese and Odia translation |
| Amazon Translate | Letters in 10 Indian languages, with numbers checked after translation (on accounts without Translate, such as AWS's new Free Tier, Amazon Nova translates them with the same checks) |
| Amazon Rekognition | Blocks unsafe photos, finds faces to blur, reads printed words (DetectText) and labels so screenshots, documents and posters are refused, for lake photos and standing-water reports |
| Amazon Polly | Reads place and lake reports aloud in Hindi or Indian English (neural voice Kajal, or the standard voice Aditi where Kajal is not offered); each text is synthesized once and cached |
| AWS KMS | An ECC P-256 key signs dossiers and place reports (`ECDSA_SHA_256`); the private key never leaves KMS, and browsers verify with the public key |
| Amazon SQS | Evidence queue (S3 upload events) and jobs queue (dossiers and place reports), each with a dead-letter queue |
| Amazon SNS | Email: one topic per watched lake for weekly change alerts, one topic per person (`<project>-user-*`) for rain heads-ups |
| Amazon EventBridge Scheduler | The daily rain check at 06:15 IST and the weekly lake check on Mondays at 02:30 IST |
| Amazon Location Service | Place search (geocoding) and the base map, with an API key limited to map tiles and to the site |
| Amazon CloudWatch and AWS X-Ray | A dashboard, alarms on API errors and on both dead-letter queues, logs kept 30 days, tracing on every function |
| AWS CloudFormation (AWS SAM), IAM, Systems Manager | One SAM template deployed as one stack, a least-privilege role per function, the site address and demo passwords in Parameter Store |

## AWS open source

- **Strands Agents** runs the letter-drafting agent on Amazon Nova, with three read-only tools that return the
  computed facts.
- **Cedar** (through the cedarpy bindings) holds the 16 access rules in
  [`policies/jalsmriti.cedar`](backend/src/jalsmriti/policies/jalsmriti.cedar). Every write, and every look at a
  review queue or audit log, is decided by them, and the decision and its rule go to the audit log.
- **Powertools for AWS Lambda (Python)** routes the API and structures its logs.
- **AWS SAM** describes the whole stack in [`infra/template.yaml`](infra/template.yaml).

## Registry of Open Data on AWS

Read in place from [Earth Search](https://earth-search.aws.element84.com/v1) by Element 84, never copied:

- **Sentinel-2 Level-2A cloud-optimised GeoTIFFs** (`sentinel-2-l2a`): water spread after every monsoon from 2016,
  the time-lapse frames and the latest look at each lake.
- **Copernicus DEM GLO-30** (`cop-dem-glo-30`): hollows where rain ponds, drainage lines and height above drainage.

Landsat Collection 2 Level-2 (water spread from 1987 to 2015, and the surface temperature for summer heat), Sentinel-1
radar, JRC Global Surface Water and the land cover maps come from Microsoft Planetary Computer. Monsoon rain history
comes from NASA POWER and rain forecasts from Open-Meteo.

## Deploy to AWS (macOS, one command)

You need an AWS account and Python 3.9 or newer (the `python3` that comes with the Xcode command-line tools, from
python.org or from Homebrew all work). No Docker, Node, AWS CLI or SAM CLI.

1. **Make an access key.** In the AWS console open IAM, create a user (for example `jalsmriti-deploy`), attach the
   `AdministratorAccess` policy, then under *Security credentials* create an access key for "Command Line Interface".
   Keep the key ID and secret at hand.
2. **Deploy.**

   ```bash
   cd jalsmriti
   python3 deploy.py
   ```

   Paste the key ID and the secret when asked (the secret is not shown as you type). You can instead export
   `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or put them in a `.env` file next to `deploy.py`
   (see `.env.example`). The keys stay in memory: they are never written to disk, uploaded or logged.

What happens, in about 25 to 40 minutes:

1. The script checks your keys and the services the app uses (Bedrock with Amazon Nova, Translate, Rekognition,
   Polly with the Kajal voice, Location Service), your Lambda limits and, on the AWS free plan, your remaining credits.
2. It makes a private Python environment in `.build/venv` (first run only), then builds the two Lambda layers on your
   Mac by downloading pinned Linux wheels for Python 3.12.
3. It uploads code, layers and workflow definitions to an artifacts bucket and deploys one CloudFormation stack
   (an AWS SAM template) in `us-west-2`, next to the Sentinel-2 and Landsat archives, or in the one Region a new
   account is allowed (see below).
4. It uploads the website, creates four demo accounts and starts reading the satellite archive: Bengaluru first
   (15 to 25 minutes), then the other eight areas, which continue in AWS after the script finishes. On an update it
   brings stored data up to today's rules instead: water bodies without a name of their own get one, and photos still
   awaiting review get today's photo checks.
5. It runs smoke tests against the live site (sign-in, a Cedar allow and a deny, a dossier signed with KMS, a place
   check, the rain forecast, a narration in Hindi and a signed place report in Kannada) and prints the website address
   and the demo passwords.

| Command | What it does |
|---|---|
| `python3 deploy.py` | Deploy, or update an existing deployment (safe to re-run) |
| `python3 deploy.py --status` | Website address and how far the area preload has got |
| `python3 deploy.py --show-passwords` | Print the demo account passwords again |
| `python3 deploy.py --preload` | Start the preload of all areas again and follow it |
| `python3 deploy.py --web-only` | Upload only the website |
| `python3 deploy.py --maintain` | Only re-name water bodies and re-check photos awaiting review with today's rules |
| `python3 deploy.py --region ap-south-1` | Deploy somewhere else (us-west-2 is fastest for imagery) |
| `python3 deploy.py --website cloudfront` | Put CloudFront in front once AWS has verified a new account (`--website api` serves the site through API Gateway) |
| `python3 deploy.py --destroy` | Delete everything the script created, including the SNS topics the app made (one per watched lake, one per person who follows places) |

Demo accounts: `citizen@example.com`, `verifier@example.com` (all areas), `officer@example.com` (Bengaluru, Chennai,
Kochi) and `admin@example.com`. Anyone can also create their own account on the site.

**Brand-new accounts.** Accounts opened with AWS's new sign-up (the AWS Settings and projects experience) may
create resources in one Region only, chosen from the contact address: `ap-southeast-2` (Sydney) for India. An
organisation policy (SCP) blocks every other Region, and no IAM permission can lift it, so when you do not pass
`--region` the script finds the allowed Region and deploys there (imagery reads from us-west-2 are then a little
slower). On those accounts Amazon Translate comes with the Paid Plan (AWS Settings > Billing > Upgrade); without it,
Amazon Nova translates the letters. Brand-new accounts also sometimes cannot create a CloudFront distribution until
AWS has verified them: the script then serves the site through API Gateway straight from the site bucket (over HTTPS,
no CloudFront) and says so; once AWS Support has verified the account, `python3 deploy.py --website cloudfront` puts
CloudFront back in front. New accounts also start with low
Lambda limits (10 concurrent runs, 3008 MB of memory); the template and the preload are sized to work within them,
only more slowly. Re-running `python3 deploy.py` is always safe.

## Run it on your computer (no AWS account)

The local stack runs the real API, workflows and satellite reads, with AWS mocked by [moto](https://github.com/getmoto/moto).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements/dev.txt
python backend/scripts/run_area_local.py bengaluru   # reads 40 years of imagery for one area (~15 minutes)
python backend/scripts/local_stack.py                # http://127.0.0.1:8787
```

Local accounts use the password `Demo-pass-2026`; new sign-ups confirm with the code `123456`. Letters use the
template, translations and AI photo descriptions are labelled stand-ins, and dossiers and place reports are signed with
a local key. "Listen" plays a short two-note sound instead of Amazon Polly, and rain heads-ups are logged instead of
emailed (`POST /local-run/rain-check` runs the daily check at once). Forecasts come from Open-Meteo, so they need the
internet.

To work on the website: `cd web && npm ci && npm run dev` (port 5173, proxied to the local stack). The built site
ships in `web/dist`, so deploying does not need Node.

Checks: `pytest backend/tests` (API, access rules, ledger, dossiers, signatures, metrics, this week's steps, our
read for renters and buyers, lake causes and news, photo relevance checks, names for unnamed water bodies, summer heat,
rain heads-up and narration, standing-water reports, the place report PDF, deploy script and template, cfn-lint), `npm run typecheck` and `npm run check:i18n` in `web/`. The i18n check compares every dictionary with
English (keys and placeholders) and confirms that the server's copy of the words used in reports, narration and emails
(`backend/src/jalsmriti/data/ui_strings.json`, written by `npm run export:strings`) is up to date.

## How it works

![JalSmriti on AWS: architecture](docs/images/architecture.png)

**A place check, end to end.** The API answers at once from the stored check, or starts the place workflow: four
parallel branches read the open archives (Static, Optical, Radar, Heat), then Score stores the result, and the page,
our read, the signed PDF, the narration and the rain heads-up all build on that one stored check.

![A place check, end to end](docs/images/place-check-flow.png)

**From a citizen photo to a signed complaint.** Every upload is fingerprinted and checked (GPS against the lake
outline, unsafe content, faces, printed words, and Nova's look at whether it is the lake at all) before a verifier sees
it; Cedar decides who may verify, every step is chained into the lake's ledger, and the dossier is signed in KMS.

![From a citizen photo to a signed complaint](docs/images/photo-to-dossier-flow.png)

![Tech stack](docs/images/tech-stack.png)

Each job uses the AWS service built for it (the table above lists them). A place check fans out into four parallel
Step Functions branches and an area run into a Distributed Map over its scenes; the results are stored once, and the
page, the signed PDF and the narration all build their steps from that stored check, so they never disagree. The rain
warning on the page uses the same rule as the email. Three AWS open-source projects do the core logic:
**Strands Agents** (the letter-drafting agent), **Cedar** (access rules) and **Powertools for AWS Lambda** (the API).

More: [architecture](docs/architecture.md), [methods and validation](docs/methods.md), [cost](docs/cost.md),
[demo script](docs/demo-script.md). The site's own [How it works](web/src/pages/About.tsx) page explains the methods
for a general reader.

## Does it work?

A place's **water memory** compares five terrain and history signals with 240 ordinary built-up places in four
cities. Against 39 localities reported flooded in widely covered events (Bengaluru 2022, Chennai 2015 and 2023,
Hyderabad 2020, Delhi and Gurugram 2023), a flooded locality scores higher than a random built-up place 68.5% of the
time (AUC 0.685). Only 15% of the flooded localities had "little water memory", against 43% of random built-up places.
It works best in Bengaluru (AUC 0.85) and Delhi (0.78) and is weak in Chennai and Hyderabad (0.55 and 0.57), where
floods came from extreme rain and breached lakes. It describes history and terrain; it is not a flood forecast. The
data and script are in [docs/validation-data](docs/validation-data) and
[backend/scripts/validate_places.py](backend/scripts/validate_places.py).

**Our read** is a fixed set of points from the stored check and the family's answers, not a fitted model (the rules
are written out in [verdict.py](backend/src/jalsmriti/verdict.py)). For a family renting a ground-floor flat it says
"think twice" or "look elsewhere" at 82% of the 39 flooded localities and at 53% of the 240 random built-up places;
"look elsewhere" is three times as common at the flooded ones (15% against 5%). So a warning means "check before you
sign", not "never live here". The 16 recent cases are in [docs/case-studies.md](docs/case-studies.md).

The other newer parts are rules and measurements too: the steps and a lake's likely causes follow fixed rules from
the stored record, the rain thresholds are working values (IMD's heavy-rain line, and lower lines for places with a
water memory), and summer heat is measured from Landsat, not predicted.

## What it costs

At demo traffic about 1 to 2 USD a month, almost all of it the KMS signing key (1 USD a month). The satellite
preload of all nine areas fits in Lambda's monthly free allowance; a dossier costs well under a cent in Bedrock and
about 5 cents in Translate; a narration up to about 2 cents in Polly, once per text; a signed place report one KMS
signature and a few seconds of Lambda; rain emails are free up to 1,000 a month. Site-wide daily caps bound what
anonymous visitors can start. Details in [docs/cost.md](docs/cost.md).

## Limits

Pixels are 10 to 30 m, so ponds smaller than about half a hectare are missed. Outlines are approximate and are not a
land survey. The historic record ends in 2020; later change comes from seasonal and latest looks. Radar cannot see
water between tall buildings. The letter is drafted by AI: its numbers are checked against the computed facts, its
tone and legal reading should be checked by the person who submits it.

Summer heat is the temperature of the ground surface at about 10:30 to 11:00 in the morning, when Landsat passes, not
the air temperature; afternoons are hotter, and the 100 m thermal pixels make small ponds read warm. Rain forecasts
come from Open-Meteo's weather models at about 10 to 25 km; they are not official warnings, which come from IMD and
NDMA (DHM and NDRRMA in Nepal), and the email says so. Standing-water reports are citizen data: Amazon Nova and NGO
verifiers check them, and a report can still be wrong. Open-Meteo's free API is for non-commercial use; a commercial
deployment needs a paid Open-Meteo plan. Cognito's built-in email sends a limited number of messages a day; switch the
user pool to Amazon SES before a public launch.

## Built with AI coding tools

The team used Claude (Anthropic) as an AI coding assistant for code, documentation and the interface translations.
The translations into Hindi, Kannada, Tamil, Telugu, Malayalam and Nepali were machine-drafted and should be reviewed
by native speakers before a public launch. Separately, the running app uses Amazon Nova on Amazon Bedrock to draft
letters and look at photos; that is part of the product and is described above.

## Repository

```
deploy.py                   one-command deploy, status, preload and destroy
infra/template.yaml         the AWS SAM template; infra/statemachines/*.asl.json are the workflows
backend/src/jalsmriti/      science and app library (water detection, terrain, radar, summer heat, metrics, this
                            week's steps, forecast, standing-water reports, ledger, Cedar, PDFs, speech)
backend/src/handlers/       Lambda handlers: api, geo_worker (area, place, lake, watch), evidence_ingest, jobs, alerts
backend/scripts/            local area runner, local stack, place validation
backend/tests/              pytest suite (moto)
web/                        React + TypeScript + Tailwind + MapLibre; web/dist is the built site
docs/                       architecture, methods, cost, demo script, blog draft, case studies, validation data,
                            diagrams and screenshots
```

## Credits

Satellite and map data: JRC Global Surface Water (European Commission, CC BY 4.0); Landsat (USGS); Copernicus
Sentinel-1 and Sentinel-2 data processed by ESA, read from Earth Search by Element 84 on the Registry of Open Data on
AWS and from Microsoft Planetary Computer; Copernicus DEM GLO-30 (© DLR e.V. and © Airbus Defence and Space GmbH,
provided under COPERNICUS by the European Union and ESA); Impact Observatory, Esri and Microsoft 10 m land cover
(CC BY 4.0); ESA WorldCover 2021 (CC BY 4.0); NASA POWER; names © OpenStreetMap contributors (ODbL) via Photon, and
GeoNames (CC BY 4.0). News headlines found through Google News search and the [GDELT Project](https://www.gdeltproject.org)
(each article stays on its publisher's site; only headlines, outlets and dates are shown). Weather data by [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0; free API for non-commercial
use). Rain categories: India Meteorological Department. Heat colour ramp: ColorBrewer RdYlBu by Cynthia A. Brewer
(Apache License 2.0). Fonts: Anek by Ek Type and Noto by Google (SIL Open Font License). Open-source libraries (GDAL
and rasterio, NumPy, Pillow, fpdf2, HarfBuzz through uharfbuzz, segno, React, MapLibre GL JS, Tailwind CSS and others)
are listed with their versions in `backend/requirements/` and `web/package.json`, each under its own licence.

Made by Ansh Singhal. Code: MIT licence, see [LICENSE](LICENSE).
