# Methods and validation

The satellite thresholds below are in `backend/src/jalsmriti/config.py`. The newer features keep theirs at the top of
their own module (`heat.py`, `forecast.py`, `waterlog.py`, `actions.py`, `speech.py`). The code that applies each rule
is named in brackets.

## Historic water (`landcover.py`, `lakes.py`)

- **Source:** JRC Global Surface Water v1.3 (Pekel et al. 2016), 30 m, 1984 to 2020: occurrence, maximum extent and
  transition classes.
- **Historic water:** a pixel inside the maximum extent with occurrence of at least 5%.
- **Lost water:** transition classes "lost permanent" and "lost seasonal" inside historic water.
- **Water bodies:** connected patches of historic water after a 3×3 opening, at least 2 ha (0.5 ha in Kathmandu and
  Butwal, 1 ha in Kochi, Sivasagar and Bhadrak, where water bodies are small). A long, thin patch (compactness
  4πA/P² below 0.06 and longer than 3 km) is a river stretch: shown, not graded.
- **Sea:** patches touching the grid edge with elevation of 0.5 m or less and occurrence of 50% or more are removed.

## Water after every monsoon (`water.py`, `handlers/area.py`)

- **Seasons:** each area has a post-monsoon window (for example 15 October to 28 February for Bengaluru; December to
  March for Kochi, after the south-west monsoon; November to February for Sivasagar). Season 2015 means the window
  after the 2015 monsoon.
- **Sensors:** Landsat 4, 5, 7, 8 and 9 Collection 2 Level-2 for 1987 to 2015 (30 m), Sentinel-2 L2A from 2016 (10 to
  20 m). The two clearest scenes per season and sensor with at most 30% scene cloud are read.
- **Water rule:** a clear pixel is water when MNDWI (green and short-wave infrared) is above 0 and SWIR1 reflectance is
  below 0.10, or (Sentinel-2) when the scene classification says water with NDWI (green and near infrared) above
  −0.2 and SWIR1 below 0.12.
  Clear means scene classes vegetation, bare or water for Sentinel-2, and no cloud or shadow bits in Landsat
  QA_PIXEL.
- **A look counts** for a lake only if 90% of the lake has data, 90% is clear and there is no cloud within 150 m.
  A season's spread is the larger of its counted looks.

## What replaced the water (`landcover.py`, `metrics.py`)

Impact Observatory 10 m annual land use and land cover (2017 to 2023) classifies lost water as built-up, bare ground,
crops, trees or grass. Old lake bed counts as built over only where it is built-up in the latest years (persistent).
ESA WorldCover 2021 is computed as a second opinion.

## Terrain (`terrain.py`)

Copernicus DEM GLO-30. Priority-flood depression filling gives the depth of hollows where rain ponds; D8 flow
directions and accumulation give drainage lines; HAND is each pixel's height above the nearest drainage line.

## Radar (`radar.py`)

Sentinel-1 radiometrically terrain-corrected backscatter (VV), 2017 onwards. For a pass on a given date, the baseline
is the median of passes on the same relative orbit in other years within 20 days of the same day of the year (at most
eight). A pixel is unusual standing water when its 5×5 mean VV is below −18 dB and at least 3 dB below that baseline.
Comparing with the same season keeps paddy fields that are flooded every year from looking like floods. For a place,
six or more unusual pixels (0.24 ha) within 300 m is a sighting.

## Rain (`rain.py`)

NASA POWER monthly corrected precipitation (`PRECTOTCORR`) at each lake, summed over the area's monsoon months. Only
complete seasons are used.

## Latest look (`handlers/area.py`, `handlers/lake.py`)

The newest Sentinel-2 scene of the last 120 days that sees 80% of the lake clearly. Floating weeds: vegetation with
NDVI above 0.35 inside the usual water spread (occurrence of 50% or more) where the water rule does not see water. A
high normalised difference chlorophyll index over open water is reported as a sign of an algal bloom.

## Lake grade (`metrics.lake_grade`)

Four parts of 25 points, summed and rescaled when a part is unknown. Bands: A from 80, B from 65, C from 50, D from 35,
E below.

| Part | Full points | Zero points |
|---|---|---|
| Water held now (`metrics.retention`) | holds as much as before | holds nothing |
| Old lake bed still open | nothing built on the historic spread | 30% built over |
| Open water surface | no floating weeds | 60% weed cover |
| Water spread kept since 1984 | nothing lost | 50% lost |

**Retention** compares the median water spread of the four most recent seasons after 2010 with the median spread of
seasons up to 2010 whose monsoon rain was within 25% of the same season's rain (all seasons up to 2010 when fewer than
two match). If the lake was nearly dry in those years too, there is no ratio.

**Storage lost** is the lost spread times 1 to 2 m (1 ha × 1 m = 10 million litres), shown as a range because depth is
not measured.

## Water memory of a place (`placecheck.py`, `metrics.water_memory_index`)

Five signals around the point:

| Signal | Higher means more memory |
|---|---|
| Deepest hollow within 300 m (m) | yes |
| Old water-body beds built over within 2 km (share of the disk) | yes |
| Water lost within 1 km (share) | yes |
| Water ever seen within 1 km (share) | yes |
| Lowest height above a drainage line within 300 m (m) | no |

Each signal is ranked against 240 random built-up places (IO land cover "built area") in Bengaluru, Chennai, Hyderabad
and Delhi (`data/place_reference.json`). The index is the mean percentile, 0 to 100, with equal weights that were not
fitted. Tiers: strong from 70, some from 45, little below. One radar sighting lifts "little" to "some"; two lift
"some" to "strong".

## Validation (`backend/scripts/validate_places.py`, `docs/validation-data/`)

39 localities reported flooded in widely covered events (Bengaluru September 2022 with October 2017 and November 2021
for two localities; Chennai December 2015 and December 2023; Hyderabad October 2020; Delhi Yamuna July 2023 and
Gurugram waterlogging 2023 to 2025), geocoded to locality centres with OpenStreetMap, wrong geocodes removed by hand.
Compared with the 240 random built-up places of the reference set, using the production signal code.

| | All | Bengaluru | Delhi | Hyderabad | Chennai |
|---|---|---|---|---|---|
| AUC of the index | 0.685 | 0.852 | 0.779 | 0.571 | 0.548 |

| Tier | Flooded (39) | Random built-up (240) |
|---|---|---|
| Little water memory | 6 (15%) | 102 (43%) |
| Some water memory | 23 (59%) | 99 (41%) |
| Strong water memory | 10 (26%) | 39 (16%) |

AUC of single signals: deepest hollow 0.66, old beds built over 0.65, water lost 0.59, water ever seen 0.59, height
above drainage 0.58.

**Reading it honestly.** The index is better than chance and much better in a tank city (Bengaluru) and on a
floodplain (Delhi), and weak where floods come from extreme rain over wide areas and breached lakes (Chennai,
Hyderabad). Locality centres are not the exact flooded streets, the reference places are random rather than verified
dry, and the sample is small. The site presents the index as history and terrain, never as a flood forecast.

The features below are rules and measurements built on the place check. None of them was fitted to outcomes, and none
has been validated against flood or heat records the way the index has.

## Summer heat (`heat.py`, `handlers/place.py`)

- **Source:** Landsat 8 and 9 Collection 2 Level-2 surface temperature (band ST_B10, from the TIRS thermal sensor:
  100 m pixels delivered on a 30 m grid), read from Microsoft Planetary Computer. It is the temperature of the surface
  itself (roofs, roads, soil, tree canopy, water), not of the air. Landsat crosses India and Nepal at about 10:30 to
  11:00 local time, so this is mid-morning heat.
- **Summers:** 15 March to 31 May of the last three summers that are over (summer Y counts from 1 June of Y; on
  11 October 2026 that is 2024, 2025 and 2026).
- **Passes:** Landsat 8 and 9 scenes with less than 30% scene cloud. The rows one satellite records on one day are one
  pass and are mosaicked. Passes are ranked by scene cloud in 5% steps; among equally clear passes the summers take
  turns, nearest the middle of the window first, so the sample spans the three summers. The first 10 passes are read
  (the cloud mask first: a pass with less than 40% of the window usable is not read further), and the 8 with the
  largest usable share (in 10% steps) are kept. At least 2 passes are needed.
- **Usable pixel:** QA_PIXEL has data and none of the dilated cloud, cirrus, cloud or cloud shadow bits, and the
  temperature (kelvin = DN × 0.00341802 + 149.0) is between 5 and 75 °C.
- **Composite:** per pixel, the median of its usable observations; a pixel needs at least 2.
- **Grid:** Web Mercator, centred on the place, 6 km × 6 km on the ground at 30 m (200 × 200 pixels).
- **Numbers:**

  | Number | Median of | Pixels needed |
  |---|---|---|
  | Here | the composite within 300 m of the place | 10 |
  | Built-up nearby | Impact Observatory 2023 "built area" in the 6 km window | 50 |
  | Lake water nearby | JRC occurrence of 50% or more (water at least half the time, 1984 to 2020) in the window | 20 |
  | Under trees | Impact Observatory 2023 "trees" in the window | 50 |

  Differences are taken from the rounded medians, so the numbers on the page add up. "Hotter than built-up ground
  nearby" means 2 °C or more.
- **Words:** the page and the PDF say warmer or cooler than built-up ground when the difference is 0.5 °C or more,
  otherwise "about as warm"; the lake-water sentence appears only when the place is warmer than the water.
- **Image:** colour scale 25 to 50 °C, widened in 5 °C steps to cover the window's 2nd to 98th percentile, on the
  ColorBrewer RdYlBu ramp (colour-blind safe), with a ring at 300 m; WebP, 480 px.
- **Example:** in our run for Bellandur, Bengaluru (8 passes, 2024 to 2026), the ground measured 41.1 °C here,
  40.4 °C on built-up ground, 31.8 °C on lake water and 37.4 °C under trees. Nazira in Sivasagar had only one clear
  pass in three summers, so it gets no number.
- **Limits:** a pond narrower than about 100 m mixes with the ground around it and reads warm. Afternoons are hotter
  than the morning pass.

## Rain heads-up (`forecast.py`, `handlers/alerts.py`)

- **Forecast:** Open-Meteo (free, no key), which blends national and global weather models (ECMWF, NCEP GFS, DWD ICON
  and others) at about 10 to 25 km. Hourly precipitation, the daily total and the daily maximum probability for
  3 days, in the place's local time. Up to 50 points go in one request; a failed request is tried once more after
  1 second.
- **Cache:** one forecast per 5-character geohash cell (about 4.9 × 4.9 km), always fetched at the cell's centre and
  kept for an hour. The website and the daily job share it.
- **IMD categories** for rain in 24 hours, compared after rounding to 0.1 mm: no rain below 2.5 mm, light 2.5 to
  15.5, moderate 15.6 to 64.4, heavy 64.5 to 115.5, very heavy 115.6 to 204.4, extremely heavy 204.5 or more.
- **When a place gets a heads-up** (today or tomorrow, at the place's local dates):

  | Water memory of the place | A day's total from | Or one hour from |
  |---|---|---|
  | Strong | 35 mm | 15 mm |
  | Some | 50 mm | 20 mm |
  | Little, or not known | 64.5 mm (IMD heavy) | none |

  64.5 mm in a day is enough everywhere. Places with a water memory get a heads-up earlier because old lake beds,
  hollows and land just above a drain line collect the water from around them, and because bursts above about 15 to
  20 mm in an hour arrive faster than street drains carry them away. These are working thresholds, not fitted to
  flood records. The tier is the one the place had when it was followed.
- **Schedule:** EventBridge Scheduler runs the alerts function every day at 06:15 IST (a 15-minute flexible window, up
  to 2 retries). It reads every follow, fetches each cell once and sends the heads-ups that are due. A rainy day is
  announced once per place, and a place gets at most one heads-up a day, so a re-run or a retry sends nothing new.
- **The email:** in the language the person followed the place in. The amount and its IMD category, the heaviest hour,
  the chance of rain, why this place floods (by tier), the rule for this place, four things to do before the rain,
  links to the place and to report standing water, a line saying that official warnings (IMD and NDMA; DHM and NDRRMA
  in Nepal) come first, and "Weather data by Open-Meteo.com".
- **Delivery:** one Amazon SNS topic per person, named `<project>-user-` plus 20 hex characters of a SHA-256 of their
  account id, so the name says nothing about them. Their verified email is subscribed once (they confirm the
  subscription from the email) and every heads-up for any of their places, up to 10, is published there.
- **Test email:** "Send me a test email" on My activity sends the wettest of the coming days at once, marked "Test:"
  (3 a day per person).
- **On the page:** today, tomorrow and the day after, coloured by IMD category, with a warning when today or tomorrow
  crosses the place's threshold (the same rule as the email).

## Standing water reported by people (`waterlog.py`, `handlers/evidence_ingest.py`)

- **Input:** signed in (Cedar `citizens-report-standing-water`); a JPEG, PNG or WebP photo up to 12 MB, the depth
  (ankle, knee, waist, or above car wheels), an optional note of up to 300 characters and, when allowed, the phone's
  location with its accuracy.
- **Pipeline:** a presigned POST to the private data bucket (`evidence/waterlogging/`), an S3 event, SQS, then the
  evidence function: the SHA-256 of the original (kept private and unchanged) and its EXIF.
- **Where:** the photo's GPS when it lies in India or Nepal, else the phone's location. When both exist and are more
  than 2 km apart, the photo wins and the report is flagged. With neither, the report stays private.
- **When:** the photo's capture time (camera clocks are read as IST, or Nepal time for a place in Nepal) unless it is
  in the future, else the upload time. A photo taken more than 48 hours before it was sent is marked old.
- **Privacy:** Amazon Rekognition moderation blocks explicit content; faces are found and blurred in the public copy,
  which carries no EXIF. The public view rounds positions to 4 decimals (about 11 m) and leaves out the uploader's
  account id, the location exactly as the phone sent it, hashes and EXIF.
- **AI look:** Amazon Nova Lite answers in JSON: whether standing water is visible (a merely wet surface, or water
  within the banks of a lake, river, canal or drain, does not count), the depth (none; ankle, up to about 15 cm; knee,
  up to about 50 cm; waist, up to about 1 m; vehicle, deeper), one plain sentence of at most 30 words and a confidence
  from 0 to 1. When Nova says "no water" with a confidence of 0.6 or more, the report waits for a verifier; every
  other report goes on the map at once. The look is a hint for verifiers, never a verdict.
- **Review:** verifiers (and admins) in the report's area confirm or reject it with a note of at least 10 characters
  (`verifiers-review-water-reports`); nobody reviews their own report (`no-self-review-of-water-reports`).
- **Map:** live and verified reports seen in the last 48 hours or 7 days, at most 500.
- **Place page and place report:** live and verified reports within 1 km in the last 365 days.

## This week's steps (`actions.py`)

Every step follows from the stored place check by fixed rules; no AI is involved. The facts used:

| Fact | Rule |
|---|---|
| Radar dates | the 3 most recent radar sightings |
| Low ground | lowest height above a drainage line within 300 m is 1.0 m or less |
| Bowl | deepest hollow within 300 m is 1.0 m or more |
| Old beds | old water-body beds built over within 2 km of 1 ha or more, or water lost within 300 m of 0.3 ha or more, or water seen on the spot in 5% of looks or more |
| Near water | nearest historic water body within 1,000 m |
| Hot | summer ground of 42 °C or more, or 2 °C or more hotter than built-up ground nearby |
| Country | India or Nepal, from the area or the coordinates |

Someone **renting or buying**, in this order:

1. Ask the owner and two neighbours about water in the last three monsoons (always).
2. Ask about the radar dates in particular (when radar saw water).
3. Prefer the first floor or above; avoid basement flats and parking (strong memory, low ground or a bowl).
4. Check that the ground floor and gate sit above the road; look for water marks (strong or some memory).
5. Check the land's survey number against the village map and the lake's full tank level (old beds; in Nepal, the
   plot's record at the Land Revenue Office and the municipality). In Hyderabad a further step points to HYDRAA's
   lake boundaries and buffer zones.
6. Ask about shade, cross-ventilation and the roof (hot).
7. Check that insurance covers flood and inundation (India: the standard Bharat Griha Raksha policy does; Nepal: flood
   and landslide).
8. Download the signed report and keep it with the agreement (always).
9. Follow the place for rain heads-ups (always).

Someone **living there**:

1. Follow the place (always).
2. Before heavy rain, move vehicles out of basements and low streets and keep documents, medicines and electronics at
   least 1 m above the floor (strong or some memory).
3. Note how deep the water got on the radar dates and which roads stayed open (when radar saw water).
4. Walk the storm drain outside with the residents' association (always).
5. Agree on a way out over higher ground (strong memory).
6. Report standing water with a photo (always).
7. Check on elderly neighbours during heatwaves (hot).
8. Join or start a group for the nearest lake (old beds or near water).
9. Turn on official warnings: NDMA's Sachet app in India; DHM and the municipality in Nepal (always).

A list holds at most 7 steps. When more apply, the middle steps after the first few are left out so that the closing
steps stay at the end (report and follow for renting or buying; report for living here). The place page, the signed
report and the narration (its first three steps) all use these lists, written from the same dictionary keys in the
reader's language. Ticks on the page stay on the device.

## Place report (`placereport.py`, `report_pdf.py`, `handlers/jobs.py`)

- **Request:** from a stored place check, for a reader (renting or buying, or living here) and a language (English,
  Hindi, Kannada, Tamil, Telugu, Malayalam or Nepali). The report id is `rpt` plus 16 hex characters of a SHA-256 of
  the place cell, cache version, check time, language and reader, so the same request returns the same signed PDF.
- **Content:** the water-memory gauge and tier, findings, up to 6 time-lapse frames spread over the seasons, radar
  sightings (the 6 most recent), summer heat with its map and scale, standing water reported within 1 km in the last
  year (up to 6 reports), this week's steps as a checklist, four questions for the owner or seller (renting or buying
  only), four limits, the data sources and a verification block (content fingerprint, signing key fingerprint, the
  verify address and a QR code).
- **Layout:** A4, normally two pages. Three densities are tried and the most comfortable one that does not end on a
  nearly empty page is kept. Indian scripts are set in Noto fonts and shaped with HarfBuzz. In our run the English
  report for Bellandur was two pages, about 120 KB, and rendered in under a second on a laptop.
- **What is signed:** a canonical JSON payload (the place, the check's time and id, science version, memory index and
  tier, finding keys and values, radar sightings, heat numbers, frame seasons, the step keys, language, reader and the
  number of nearby standing-water reports). Its SHA-256 and the PDF's SHA-256 go into an attestation
  (`reportId`, `kind: "place-report"`, `payloadSha256`, `pdfSha256`, `signedAt`, `keyFingerprint`, `issuer`), whose
  SHA-256 is signed by the KMS key (`ECDSA_SHA_256`, ECC P-256), as for dossiers.
- **Check:** `/verify/<report id>` verifies the signature in the browser with Web Crypto and hashes the dropped or
  published PDF to compare it with the signed fingerprint.
- **Kept:** report records for 400 days; place checks for 90 days (a report needs a stored check).

## Listening (`speech.py`, `narration.py`)

- **Voice:** Amazon Polly, neural engine, voice Kajal, which speaks Indian English (`en-IN`) and Hindi (`hi-IN`); MP3.
- **Place text:** the place, its water memory, up to four findings (radar is told once), the radar sentence (passes
  since 2017, sightings within 300 m), one summer-heat sentence, up to three of this week's steps for the chosen
  reader, and "It is not a flood forecast." **Lake text:** the name, the health grade and score, up to four findings,
  and how to help. Units are written out the way a listener hears them ("12 hectares", "40 percent", "41 degrees
  Celsius", "1984 to 2020").
- **Length:** cut at a sentence end to 2,900 characters (SynthesizeSpeech takes at most 3,000 billed characters of
  plain text). In our runs place texts were about 900 to 1,200 characters and lake texts 190 to 690.
- **Cache:** the audio's name is a SHA-256 of voice, engine, language and text; `/pub/speech/<name>.mp3` is written
  once with an immutable cache header and served by CloudFront, so a text is synthesized once however often it is
  played.

## Language and letters

- **Number check** (`dossier.unsupported_numbers`): every number in a draft letter must match a computed fact in one
  of its accepted forms (rounding, thousands separators, dates, percentages); otherwise the draft is redone, and after
  repeated failures a fixed template is used.
- **Translation** (`translate.py`): Amazon Translate for Hindi, Kannada, Tamil, Telugu, Malayalam, Marathi, Bengali,
  Gujarati, Punjabi and Urdu; Amazon Nova for Nepali, Assamese and Odia. Numbers and identifiers are protected from
  translation, and the set of numbers after translation (native digits normalised) must equal the set before.
- **Right to Information request** (`web/src/components/RtiDialog.tsx`, `handlers/api.py`): the draft is assembled in
  the browser, in the page's language, from fixed sentences and the lake's record. In India it is an application to
  the Public Information Officer under Section 6(1) of the RTI Act 2005, with the ₹10 fee, transfer under Section 6(3)
  and a reply within 30 days (Section 7(1)); in Nepal, to the Information Officer under the RTI Act 2064 (2007), with a
  reply within 15 days. Six items can be asked for (survey numbers and the village map with the full tank level
  boundary; encroachment surveys since 2015; action taken on them; permissions and conversions inside the full tank
  level or buffer since 2010; works sanctioned since 2020 with amounts; complaints since 2023), with an optional line
  of satellite facts. Recording a filed request (the office, a filing date within the last 400 days, an optional
  reference and channel) appends an `rti` entry with the record's SHA-256 to the lake's ledger and sets the reply date
  30 days (India) or 15 days (Nepal) after filing.
- **Interface translations** (`web/src/i18n/`): seven languages. `npm run check:i18n` verifies every key and
  placeholder in each dictionary, and that `backend/src/jalsmriti/data/ui_strings.json`, the server's copy of the words
  used in place reports, narration and emails, matches the dictionaries (`npm run export:strings` rewrites it).

## Site-wide daily caps (`config.RATE_LIMIT_PER_DAY`)

Per address (anonymous) or per account (signed in), per day: 25 place checks, 10 lake analyses, 600 searches,
300 forecasts, 20 place reports and 30 new narrations per address; 30 photos, 10 dossiers, 30 watches, 20 follows,
3 test emails, 10 RTI records and 10 standing-water reports per account. For the whole site, set by environment
variables on the API function: `PLACE_CHECKS_PER_DAY` (200), `LAKE_ANALYSES_PER_DAY` (40), `SEARCHES_PER_DAY` (5000),
`REPORTS_PER_DAY` (500), `NARRATIONS_PER_DAY` (200, counted only for audio not already cached),
`WATER_REPORTS_PER_DAY` (1000) and `FORECASTS_PER_DAY` (5000).
