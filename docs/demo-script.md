# Demo video script (under 3 minutes)

One person, one week: **Priya is about to rent a ground-floor flat near Bellandur, Bengaluru.** The video follows her
from the first search to the lake's records, then shows where AWS runs it. It runs to 2:55.

Cues in *italics* are what is on screen; the quoted lines are the voice-over. The numbers come from our run on
11 October 2026. Read them off the screen when you record and change the voice-over if they differ.

---

**0:00 to 0:11. The problem**

*Home page. Bengaluru's water memory fades in over the satellite image; drag the year gauge from 1991 to 2025. Blue
is water still there, amber is water that has gone, red is old lake bed now built over.*

> Bengaluru floods where its lakes used to be. Priya is about to rent a ground-floor flat near Bellandur. Before she
> signs, she asks JalSmriti what the place remembers.

**0:11 to 0:33. What the place remembers**

*Under "What brings you here?" click "I'm renting or buying a home", then the chip "Bellandur, Bengaluru". The place
page: the gauge "Strong water memory, 79 of 100", the three findings (6.3 ha of old water-body beds built over within
2 km, a bowl up to 2.2 m deep, ground less than 1 m above a drainage line), scrub the time-lapse from 1990 to 2025,
then the radar line.*

> JalSmriti reads forty years of Landsat and Sentinel images, the terrain and every monsoon radar pass for this spot.
> Strong water memory: old lake beds built over nearby, a bowl in the ground, land less than a metre above a drain.
> Radar saw no unusual standing water here since 2017, but radar cannot see between tall buildings, and the page says
> so.

**0:33 to 0:53. What to do this week**

*Scroll to "What to do this week", "Renting or buying" selected. Point at the first, second and fourth steps; tick the
first. Then a four-second cut: the chip "Yamuna Bazar, Delhi", its step "Radar saw standing water near here on
25 Sep 2026, 17 Sep 2026, 20 Aug 2026. Ask about those days in particular." Back to Bellandur.*

> Then the record becomes this week's steps for a renter: ask the owner and two neighbours about the last three
> monsoons, take the first floor, check the survey number against the lake's full tank level. Where radar did see
> water, as in Delhi's Yamuna Bazar, the dates become questions.

**0:53 to 1:11. A signed report, checked in the browser**

*Switch the language to ಕನ್ನಡ (the buttons below are now in Kannada). Click "Signed report (PDF)", then "Download
PDF": show the two pages for a second.
Click "Check the signature": "The signature is valid." Drop the PDF on the page: "This PDF is the signed original."
Drop the copy with one byte changed: "This PDF is not the signed original: its fingerprint is different."*

> She downloads the report in Kannada for the owner. It is signed with a key that never leaves AWS KMS, and anyone can
> check it in their own browser. Change one byte, and the check fails.

**1:11 to 1:21. Share and listen**

*Back on the place page, in English, in the second tab that shows it at phone size (Chrome's device toolbar, 390 ×
844): the same page, one column, large buttons. Tap "Share on WhatsApp" and show the prepared message for a second.
Then "Listen", "हिन्दी": let three seconds of the Hindi narration play.*

> On her phone, she shares it with her family on WhatsApp. Her mother would rather listen: Amazon Polly reads it in
> Hindi.

**1:21 to 1:40. A heads-up before heavy rain**

*The panel "Rain in the next three days" with its three bars. Click "Follow this place", sign in as Priya (the
account made before recording): "Heads-ups on". Open My activity, "Send me a test email". Cut to the inbox: the email "Test: Rain heads-up for
Bellandur, Bengaluru ...", scroll through the amount, the rule for this place, "Before the rain" and the line about
official warnings.*

> Then she follows the place. Every morning, EventBridge Scheduler runs a Lambda function that checks the forecast for
> every followed place, with lower thresholds where the ground remembers water, and emails a heads-up through her own
> SNS topic. Here is the test email.

**1:40 to 1:52. Lost lakes, hotter streets**

*Scroll to "Summer heat": the heat map with the 300 m ring, then the numbers: here 41.1 °C, built-up nearby 40.4 °C,
lake water nearby 31.8 °C, under trees 37.4 °C.*

> Lost lakes also make streets hotter. On summer mornings, Landsat measures the ground here at 41 degrees, 9 degrees
> hotter than the lake water nearby.

**1:52 to 2:15. The lake itself**

*Explore lakes, Bengaluru, open Bellandur Lake: "D", 42 of 100; the findings (a third of its water spread lost since
1984, 89.4% of the surface under floating weeds on 4 October 2026). Click "Ask for the records (RTI)": the draft
letter to the Public Information Officer, "Copy the text". Under "Already filed it?" pick the date and "Record it":
"Recorded in the lake's ledger. A reply is due by ...". Scroll to "Record of changes": the new entry "rti" at the
top and "The chain is intact."*

> The lake itself, Bellandur: grade D. A third of its water spread is gone since 1984, and in October most of its
> surface was under weeds. JalSmriti drafts a Right to Information request for its records. Once it is filed and
> recorded, the date a reply is due sits in the lake's tamper-evident ledger.

**2:15 to 2:25. Officials answer on the record**

*Sign in as the officer. Review console, Bengaluru, Dossiers: respond "Acknowledged" with a note. Open the Audit log:
the allowed and denied decisions with the Cedar rule for each.*

> Officers answer on the record. Who may verify or respond is written in Cedar, and every decision, denials included,
> is logged with its rule.

**2:25 to 2:45. Where AWS runs it**

*AWS console, about three seconds each:*

1. *Step Functions, `jalsmriti-place`: the graph, with the parallel state "Look" and its four branches Static,
   Optical, Radar and Heat, then Score (open a finished execution so the branches are green).*
2. *Step Functions, `jalsmriti-area`: a finished Bengaluru execution, its Distributed Map run "Scenes" with the item
   counts.*
3. *Lambda, Functions: `jalsmriti-api`, `jalsmriti-geo`, `jalsmriti-evidence`, `jalsmriti-jobs`,
   `jalsmriti-alerts`.*
4. *EventBridge Scheduler, Schedules: `jalsmriti-daily-rain`, `cron(15 6 * * ? *)` in Asia/Kolkata, next to
   `jalsmriti-weekly-watch`.*
5. *KMS, Customer managed keys: `alias/jalsmriti-signing`, key spec ECC_NIST_P256, usage Sign and verify.*
6. *CloudWatch, Dashboards: `jalsmriti`.*

> All of it runs on AWS: Step Functions, with four parallel branches for each place and a Distributed Map for whole
> cities; five Lambda functions; EventBridge Scheduler for the daily rain check; a KMS key that signs every report;
> and a CloudWatch dashboard over it all.

**2:45 to 2:55. One command**

*The terminal at the end of `python3 deploy.py`: the PASS lines of the smoke tests and "JalSmriti is live." Then the
home page in the dark theme.*

> One command deploys it into a new AWS account, for about one to two dollars a month at demo traffic. Water
> remembers. Now Priya does too.

---

## Before you record

- Deploy with `python3 deploy.py` and wait until Bengaluru has loaded (`python3 deploy.py --status`). Open the
  Bellandur place page and the Yamuna Bazar one once before recording (each takes two to four minutes the first time;
  the smoke tests may already have checked Bellandur), so both open at once on camera.
- Create an account on the site with an email address you can open (the demo accounts use `example.com` addresses,
  which cannot receive mail). Confirm the sign-up code, follow Bellandur once and click the link in the
  "Subscription Confirmation" email from AWS, so the test email arrives. Unfollow again if you want to film the
  follow.
- As that account, add a photo to Bellandur Lake, prepare a dossier and record its submission, so the officer has a
  submitted dossier to answer. Have the officer password ready (`python3 deploy.py --show-passwords`).
- Recording a photo, a dossier or an RTI filing writes permanent entries to the lake's ledger. Do it on your own demo
  deployment only.
- Download the Kannada report once and make a copy with one byte changed, for example
  `cp report.pdf changed.pdf && printf 'X' | dd of=changed.pdf bs=1 seek=4000 conv=notrunc`.
- Run `npm run check:i18n` in `web/`: Kannada and Hindi should show 0 missing keys, or the report and the narration
  fall back to English words. If Kannada is not complete, record the report in Hindi.
- Open the six AWS console pages in tabs in a second Chrome profile, signed in, so the cuts are quick.
- In the site's window, open a second tab with the Bellandur place page and switch on Chrome's device toolbar at
  390 × 844 with touch, for the phone beat at 1:11.

## Recording checklist

- [ ] Chrome at 1440×900, zoom 100%, bookmarks bar and extensions hidden, signed out of the site at the start.
- [ ] Notifications off; a quiet room for the voice-over (recording it separately and laying it over is fine).
- [ ] The AWS console is on screen for at least 15 seconds, with service names readable: the rules say the video has
      to show AWS, not only name it.
- [ ] Keep it under 3:00 (this script runs to 2:55). Trim the waiting while the report renders.
- [ ] Captions on: upload an `.srt` made from the voice-over above, or correct YouTube's automatic captions.
- [ ] Upload to YouTube as **Unlisted**, then open the link in a private window to check that it plays signed out.
- [ ] Put the video link and the live site address in the README and the submission form.
