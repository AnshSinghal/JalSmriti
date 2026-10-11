# Demo video script (under 3 minutes)

The video has to cover four things: what the project is, the tech stack and architecture, how it uses AWS, and
(optionally) what was learned. It does them in that order, and runs to 2:55. One family carries the first half:
**Priya is about to rent a ground-floor flat near Bellandur, Bengaluru.**

Cues in *italics* are what is on screen; the quoted lines are the voice-over. The numbers come from the live site on
11 October 2026. Read them off the screen when you record and change the voice-over if they differ.

| Part the form asks for | Where it is |
|---|---|
| About the project | 0:00 to 1:35 |
| Tech stack and architecture | 1:35 to 2:00 |
| How AWS is used | 2:00 to 2:32 |
| Learning and growth | 2:32 to 2:48 |
| End card ("Made by Ansh Singhal") | 2:48 to 2:55 |

---

## About the project

**0:00 to 0:14. The hook**

*Past floods page (`/proof`), scrolled to the Kendriya Vihar row: "22 Nov 2021; 6, 16 and 21-22 Oct 2024", and on
the right "Strong water memory, 75 of 100" with the verdict "Think twice". Then scroll up to the three bars.*

> In October 2024, 600 families were evacuated from Kendriya Vihar in Bengaluru, its third flood in a month. It had
> flooded in 2021 too. The satellite record already said that this ground remembers water. JalSmriti puts that record
> in front of people before they sign.

**0:14 to 0:42. What the place remembers, and our read**

*Home page: "What brings you here?" → "I'm renting or buying a home" → chip "Bellandur, Bengaluru". The place page:
the gauge "Strong water memory, 79 of 100" and the three findings. Then "Our read": the answers start at Renting,
Ground, No, No and the verdict shows "Think twice". Tap "3rd or above": it changes to "Fine, with checks". Tap
"Ground" again and then "Buying": it changes to "Look elsewhere". Hover over Why, In its favour, Against it and "If
you still like it".*

> Priya checks the street. JalSmriti reads forty years of Landsat and Sentinel images, the terrain and every monsoon
> radar pass: strong water memory, old lake beds built over nearby, ground less than a metre above a drain. Then four
> taps: renting or buying, which floor, a car in the basement, elderly people or children at home. For a ground-floor
> flat our read is: think twice. On the third floor: fine, with checks. Buying on the ground floor: look elsewhere.
> Every verdict says why, what is for and against it, and what to do if she still likes the flat.

**0:42 to 0:54. Signed, shared, heard**

*"Signed report (PDF)" → "Download PDF": page one with the "Our read" panel. "Check the signature": "The signature is
valid." Then "Share on WhatsApp" for a second, and two seconds of "Listen" in Hindi.*

> The verdict goes into a PDF signed with a key that never leaves AWS KMS, so anyone can check it. She shares it on
> WhatsApp, and her mother listens to it in Hindi.

**0:54 to 1:16. The lake behind the flooding**

*Explore lakes → Bengaluru → Bellandur Lake: grade D. Scroll to "Why it is like this": the cause list (covered by
plants, less water reaches it, choked by weeds and algae, built on its bed), each with "Rests on". Then "What would
help": the residents' buttons and the asks for the authorities. Then "In the news" with its tags.*

> Bellandur Lake itself: grade D. The page reads why it is like this, from its own record: floating weeds over most of
> the water, a sign of sewage; less water reaching it than in years of similar rain. Each cause says what it rests on.
> Then what would help: what residents can do, and what to ask the authorities for, with recent news naming the lake.

**1:16 to 1:26. A random photo is refused**

*"Add a photo" → choose a screenshot of a news article. After a few seconds: "This does not look like a photo of the
lake. We read many printed words in it, so it looks like a screenshot, a document or a poster." and "Amazon Nova saw:
...".*

> Evidence has to be evidence. A screenshot is refused: Rekognition reads its printed words, and Amazon Nova is asked
> whether this is a real photo taken at the lake. Real photos go to a verifier and into the lake's tamper-evident
> record.

**1:26 to 1:35. Would it have helped?**

*Back on the Past floods page: the three bars. Point at "88% warned", "82% warned" and "53% warned".*

> We ran sixteen places that flooded between 2020 and 2026. For a ground-floor renter, our read says think twice or
> look elsewhere at fourteen of them. And honestly: it also warns at about half of ordinary places. It is a prompt to
> check, not a ban.

## Tech stack and architecture

**1:35 to 2:00**

*The architecture diagram (docs/images/architecture.png, or the Eraser canvas) full screen; slowly move from the
browser on the left to CloudFront and the API, the photo pipeline, the Step Functions workflows, the jobs box and the
open data on the right. Then two seconds of the tech-stack diagram.*

> The website is React and TypeScript in seven languages. Behind it is one AWS SAM stack: CloudFront, API Gateway with
> Cognito, five Lambda functions in Python, Step Functions for the satellite work, DynamoDB, and the open archives
> read in place from the Registry of Open Data on AWS and Planetary Computer, never copied. Access rules are written in
> Cedar, the letter agent runs on Strands Agents, and the API on Powertools.

## How AWS is used

**2:00 to 2:32**

*AWS console, Region Asia Pacific (Sydney), about four seconds each:*

1. *Step Functions, `jalsmriti-place`: a finished execution with the parallel state "Look" and its four green
   branches Static, Optical, Radar and Heat, then Score.*
2. *Step Functions, `jalsmriti-area`: a Bengaluru execution, its Distributed Map "Scenes" with the item counts.*
3. *Lambda, Functions: `jalsmriti-api`, `jalsmriti-geo`, `jalsmriti-evidence`, `jalsmriti-jobs`,
   `jalsmriti-alerts`.*
4. *CloudWatch Logs for `jalsmriti-evidence`: the line with `EvidenceUnrelated` (or DynamoDB, the evidence item with
   `status: unrelated`, `textWords` and `ai.scene`).*
5. *KMS, Customer managed keys: `alias/jalsmriti-signing`, ECC_NIST_P256, Sign and verify.*
6. *EventBridge Scheduler: `jalsmriti-daily-rain` at `cron(15 6 * * ? *)`, Asia/Kolkata.*
7. *CloudWatch, Dashboards: `jalsmriti`.*

> Each place check is a Step Functions workflow with four parallel branches, and a whole city is a Distributed Map
> over decades of scenes. Photos go through Rekognition and Amazon Nova on Bedrock before anyone sees them. Reports and
> dossiers are signed with KMS, Polly reads them aloud, EventBridge Scheduler runs the daily rain check that emails
> through SNS, and CloudWatch watches it all. One command, deploy.py, builds it in a new account.

## Learning and growth

**2:32 to 2:48**

*The terminal at the end of `python3 deploy.py`: the PASS lines and "JalSmriti is live." Then the "Is it the lake at
all?" paragraph on the How it works page.*

> What I learned: AWS's new sign-up allows one Region, so the deploy now finds it. Lambda's Python 3.12 runtime lacks
> a library GDAL needs, so the layer carries it. And an AI asked to describe a lake photo will find a lake in an
> infographic. So JalSmriti asks three independent questions, and states its own error rates.

## End card

**2:48 to 2:55**

*Home page in the dark theme, then the end card: "JalSmriti: water remembers", the site address
https://d2av4xxvyq12ej.cloudfront.net and "Made by Ansh Singhal".*

> Water remembers. Now Priya does too. JalSmriti, made by Ansh Singhal.

---

## Before you record

- Deploy with `python3 deploy.py` and check `python3 deploy.py --status`: all areas ready. Open the Bellandur place
  page, the Kendriya Vihar row of Past floods and Bellandur Lake once, so they open at once on camera.
- Clear the site data for the site in the recording browser so "Our read" starts at Renting, Ground, No, No.
- Have a screenshot of a news article (a PNG or JPEG) ready for the photo beat, and a signed-in account (the demo
  citizen account works; `python3 deploy.py --show-passwords` prints the password). Uploading a refused photo writes no
  ledger entry, so it is safe to film on the live site.
- Download the Bellandur report once beforehand, so the PDF opens quickly on camera.
- Open the seven AWS console pages in tabs of a second Chrome profile, signed in, in Asia Pacific (Sydney).
- Open docs/images/architecture.png and docs/images/tech-stack.png in an image viewer at full screen.

## Recording checklist

- [ ] Chrome at 1440×900, zoom 100%, bookmarks bar and extensions hidden, signed out of the site at the start.
- [ ] Notifications off; a quiet room for the voice-over (recording it separately and laying it over is fine).
- [ ] The AWS console is on screen for at least 25 seconds with the service names readable: the rules say the video
      has to show AWS, not only name it.
- [ ] Keep it under 3:00 (this script runs to 2:55). Trim waits while pages load or the PDF renders.
- [ ] Captions on: upload an `.srt` made from the voice-over above, or correct YouTube's automatic captions.
- [ ] Upload to YouTube as **Unlisted** (or Public), then open the link in a private window to check that it plays
      signed out.
- [ ] Put the video link in the README ("Demo video") and in the submission form, with the live site address.
