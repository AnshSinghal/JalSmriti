# Methods and validation

The satellite thresholds below are in `backend/src/jalsmriti/config.py`. The newer features keep theirs in their own
module (`heat.py`, `forecast.py`, `waterlog.py`, `actions.py`, `speech.py`, `verdict.py`, `insights.py`, `news.py`,
`evidence.py`, `names.py`). The code that applies each rule is named in brackets.

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

## Why a lake is like this (`insights.py`)

Each lake page lists the likely causes of the lake's state. Fixed rules read them from the stored lake metrics each
time the lake is read (`GET /v1/lakes/<id>` returns them as `insights`); nothing extra is stored and no AI is involved.
Each cause carries its numbers and says what it rests on. These are readings of satellite data, not findings about
anyone: a site visit or the official records settle them.

| Cause | Shown when | High (else medium) when |
|---|---|---|
| Built on its bed | 0.3 ha or more of the old bed is built-up (the larger of the persistent built-over bed and the lost water now classed built-up) | 10% or more of the historic spread, or 5 ha or more |
| Filled in or drying out | 0.5 ha or more lost, of which 0.5 ha or more is now bare ground | 25% or more lost, and bare ground is 30% or more of the loss |
| Covered by plants | 0.5 ha or more lost, of which 0.5 ha or more is now trees, flooded vegetation, rangeland or crops | 25% or more lost |
| Less water reaches it | retention below 0.8 | retention below 0.5 |
| Choked by weeds and algae | floating weeds on 20% or more of the water surface (open water and weeds) in the latest look, or an algal sign (mean NDCI over open water above 0.1) | weeds on 50% or more |
| Holding up | none of the above | always low |

- **Order:** high causes first, then medium.
- **Details:** "Built on its bed" adds the first land-cover year (2017 to 2023) with 0.3 ha or more built-up on the
  bed. "Covered by plants" says the cover is most likely water hidden under floating weeds when weeds cover 40% or more
  of the water surface, because land-cover maps often call a thick mat of water hyacinth crops. "Less water reaches it"
  names the latest compared season and its water spread against that of the comparable years.
- **What residents can do:** photograph what they see, ask for the records (RTI), watch the lake, send a signed dossier
  and join or start a lake group, always; check before renting or buying nearby (built on, or filled in); walk the
  inflow channels after rain (filled in, plants, or less water); report sewage (weeds and algae). Photo, RTI, watch,
  dossier and "Check a home here" have buttons on the page.
- **What to ask the authorities for**, in this order: survey and mark the full boundary and buffer zone (built on,
  filled in or plants); remove buildings on the bed and stop new approvals in the buffer (built on); clear and reconnect
  the inflow channels and desilt the bed (filled in, plants or less water); stop debris dumping (filled in); stop sewage
  entering, and remove the floating weeds regularly (weeds and algae); clear scrub and stop cultivation on the bed
  (plants, without weeds and algae); keep the lake on the record (always). The page names the area's first two
  authorities that are not courts.
- **What protecting it brings back:** when 0.5 ha or more was lost, the storage lost (above) in million litres and in
  Olympic pools of 2.5 million litres.

## Names for unnamed water bodies (`names.py`, `handlers/area.py`)

- **Own names:** an OpenStreetMap name from the Photon geocoder within a reach of 60 m × √(area in ha), at least 250 m
  and at most 1,500 m, for a feature tagged as water or with a water word in its name (lake, kere, tank, cheruvu,
  kunta, talab, sagar, pokhari, pond, kulam, beel, reservoir and others); else a GeoNames name (bundled for India and
  Nepal) within the same reach. An area run looks up lakes only, not river stretches, and a GeoNames name within 400 m
  of a lake also counts as its own.
- **Named after what is near it** (`fallback_name`), first match wins:
  1. the nearest named lake within 2 km: "Water body near Bellandur Lake" within 1 km, else "Water body 1.5 km east of
     Bellandur Lake" (distance to 0.1 km and one of eight compass points, seen from the lake);
  2. the locality (or city) the geocoder gave for the water body's own position: "Water body near Haralur";
  3. the nearest named lake within 6 km, worded as in 1;
  4. the locality the geocoder gave for the nearest other water body within 3 km: "Water body in Yelahanka";
  5. the area: "Water body in Bengaluru".

  Only when none applies is it "Unnamed water body". A river stretch is a "River stretch", not a "Water body".
- **Named lakes** used above: the area's water bodies with names of their own, plus GeoNames water bodies within 0.06°
  (about 6.6 km) of the area's box, unless a named water body lies within 1 km of one or has the same name (often the
  same lake spelt differently: GeoNames "Belandur Tank" is OpenStreetMap's "Bellandur Lake").
- **Repeated names** (`distinct`): when two or more water bodies get the same name, each one with a named lake within
  6 km is told apart by its side of that lake: "Water body north of Bellandur Lake" within 1 km, else "Water body
  4.0 km south-west of Varthur Lake". Names that are still the same stay so.
- **Stored:** the name and its source (`nameSource`: OpenStreetMap, GeoNames, nearby-lake, nearby-place, area or
  none). Only lakes named by OpenStreetMap or GeoNames get a news search.
- **Lakes on request** (`handlers/lake.py`): the same order, with a GeoNames name within 500 m counting as the lake's
  own and GeoNames lakes around the point as the named lakes. There are no neighbours, so step 4 and the repeat check do
  not apply.
- **Re-naming:** the geo function's task `area.rename` names an area's water bodies again with these rules from the
  stored names, without reading imagery, and updates the list rows, the lake records and the public `lakes.geojson`
  in place. `deploy.py` runs it for every loaded area after an update.

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

**Our read on the same places.** The same 39 flooded localities and 240 random built-up places, read for a family
renting a ground-floor flat (rules under "Our read for renters and buyers" below). Radar is left out, so this rests on
satellite history and terrain alone.

| Our read | Flooded (39) | Random built-up (240) |
|---|---|---|
| Look elsewhere | 6 | 12 |
| Think twice | 26 | 114 |
| Fine, with checks | 6 | 52 |
| Good to go | 1 | 62 |
| Warned (Look elsewhere or Think twice) | 32 (82%) | 126 (53%) |

It warns about 1.6 times as often at the flooded places, and "Look elsewhere" is three times as common there (15%
against 5%). It also warns at about half of ordinary built-up places, so a warning means "check before you sign", not
"never live here". The points are fixed rules, not fitted to these places. The 16 recent cases in
[case studies](case-studies.md) read 13 "Think twice", 1 "Look elsewhere" and 2 "Fine, with checks" for a family renting
a ground-floor flat, and 11 "Look elsewhere" and 5 "Think twice" for a buyer of a ground-floor flat with a car in
basement parking.

The features below are rules and measurements built on the place check. None of them was fitted to outcomes. Apart
from our read, checked above, none has been validated against flood or heat records the way the index has.

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
  from 0 to 1. When Amazon Rekognition reads 25 or more printed words in the photo (a screenshot or document, not a
  street: `hiddenReason` "text"), or Nova says "no water" with a confidence of 0.6 or more (`hiddenReason`
  "no-water"), the report waits for a verifier; every other report goes on the map at once. The look is a hint for
  verifiers, never a verdict.
- **Review:** verifiers (and admins) in the report's area confirm or reject it with a note of at least 10 characters
  (`verifiers-review-water-reports`); nobody reviews their own report (`no-self-review-of-water-reports`).
- **Map:** live and verified reports seen in the last 48 hours or 7 days, at most 500.
- **Place page and place report:** live and verified reports within 1 km in the last 365 days.

## Is a photo of the place at all? (`evidence.py`, `handlers/evidence_ingest.py`)

Uploads are not always what they claim to be: some are screenshots, documents, posters or indoor photos. After the
moderation check, and before faces are blurred or anything is published, three independent signals are read for every
lake photo:

- **Printed words:** Amazon Rekognition DetectText, counting the words it reads with 80% confidence or more (it reads
  at most 100). If the call fails, the other two signals decide.
- **Labels:** Rekognition labels (at most 25, asked from 65%) that it is 70% or more sure of, in three sets: made
  images (Text, Document, Poster, Page, Screenshot, Chart, Drawing, Cartoon, Illustration, Screen, Mobile Phone and
  others), outdoor scenes (Outdoors, Nature, Water, Lake, Grass, Tree, Sky, Road, Street, Building, Construction,
  Rubble, Garbage, Bird and others) and water (Water, Lake, Pond, River, Shoreline, Waterfront, Wetland, Swamp, Marsh,
  Puddle, Flood, Canal, Reservoir).
- **Amazon Nova:** the prompt says uploads are not always what they claim and that Nova must never assume a lake is
  there. Besides the categories, the summary and whether water is visible, it asks for `scene` (lake or pond, wetland
  or marsh, dry lake bed, river or canal, drain or outlet, street or buildings, construction site, indoor, screenshot
  or document, poster or graphic, other), `site_photo` (a real photograph taken outdoors at or near a lake, tank, pond
  or wetland, its banks, its channels or the land around it, including building on old lake land) and `confidence`
  (0 to 1, about `site_photo`). When `site_photo` is false, the categories are left empty.

The rule (`relevance`), first match wins:

| Reason | When |
|---|---|
| `text` | 25 or more printed words, and no outdoor-scene label |
| `graphic` | a made-image label, no outdoor-scene label, and Nova did not say it is a site photo |
| from Nova's scene: `indoor`, `text` (screenshot or document), `graphic` (poster or graphic), else `other` | Nova says it is not a site photo with a confidence of 0.6 or more, and Rekognition sees no water |

Any other photo goes on as before: faces blurred, a public copy, a ledger entry and a verifier. Rekognition's signals
come first because they cannot be talked into seeing a lake. Many printed words refuse a photo only when Rekognition
sees no outdoor scene, so a notice board photographed at the lake is not refused for its words. When Nova says no but
Rekognition sees water, a person decides.

- **Unrelated:** the status becomes `unrelated` with the reason; the word count, the labels and Nova's answer are kept,
  and an `EvidenceUnrelated` entry goes to the area's audit log. The photo gets no public copy and no ledger entry,
  never appears on the lake's page or in the verifiers' queue, and cannot be reviewed. The uploader sees "This does not
  look like a photo of the lake" with the reason.
- **Standing-water reports:** 25 or more printed words keep a report hidden until a verifier looks (above).
- **Re-check** (`recheck`): lake photos still awaiting review that were checked before this rule existed (no word
  count stored), up to 300 per area queue, get today's three signals. One that passes keeps its place and gets the
  newer AI description. One that fails is already in its lake's ledger, so it is withdrawn on the record: a review
  entry by "Automatic photo check" (decision `unrelated`, with the reason and Nova's summary) is appended to the ledger,
  the public copy and its thumbnail are deleted, the lake's photo count drops by one, the status becomes `unrelated`
  and an `EvidenceUnrelated` audit entry is written. The evidence function runs it when invoked directly with
  `{"maintenance": "recheck-evidence"}`. `deploy.py` does that after an update (or with `--maintain`) and then
  invalidates `/pub/evidence/*` in CloudFront if any photo was withdrawn.

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

## Our read for renters and buyers (`verdict.py`)

A verdict for someone about to rent or buy a home: "Look elsewhere", "Think twice", "Fine, with checks" or "Good to
go". Fixed points come from the stored place check, the live and verified standing-water reports within 1 km in the
last 365 days, and four answers. No AI is involved.

- **Answers:** renting or buying; the home (a ground-floor flat, a flat on the first or second floor, one on the third
  floor or above, or an independent house); a car in basement parking; elderly people or small children at home. A
  missing or unknown answer counts as renting a ground-floor flat, with no basement car and no one vulnerable.
- **Points from the place:**

  | Fact | Points |
  |---|---|
  | Water memory | strong 4, some 3, little 0, not known 1 |
  | This very spot was water in 5% or more of satellite looks, 1984 to 2020 | 3 (4 from 20%) |
  | Low ground (1.0 m or less above a drainage line within 300 m) or a hollow 1 m or more deep within 300 m | 1, both 2; a hollow of 3 m or more adds 1 |
  | Old water-body beds built over within 2 km | 1 from 5 ha |
  | Radar sightings | 2 (3 from three sightings) |
  | Standing water reported by people within 1 km in the last year | 1 (2 from three reports) |

- **Then the answers:** a first or second floor takes off 2 points, the third floor or above 3, and an independent
  house adds 1 (the total never goes below 0). Where the place alone scores 3 or more, a car in basement parking adds 2
  and elderly people or small children add 1. Buying adds 1 where an old lake bed is at or near the spot (water on the
  spot in 5% of looks or more, 0.3 ha or more of water lost within 300 m, or 5 ha or more of old beds built over within
  2 km): the legal risk, and a long commitment.
- **Levels:** "Look elsewhere" from 8 points, "Think twice" 5 to 7, "Fine, with checks" 2 to 4, "Good to go" 1 or
  less. A place that scores 3 or more on its own is never "Good to go", whatever the floor, because the street, the
  basement, the power and the water supply still go under: it reads "Fine, with checks". A flat on the third floor or
  above is never "Look elsewhere", because the family can be stranded but not flooded: it reads "Think twice".
- **Why:** what the water memory means against the validation set, then the two weightiest lines against the place
  (for "Good to go", in its favour). The other lines follow under "In its favour" (up to 5) and "Against it" (up to 6),
  heaviest first; nothing is said twice.

  | Against it | When | Weight |
  |---|---|---|
  | The spot was water | 5% or more of looks | 5 (6 from 20%) |
  | Radar dates (the 3 most recent) | any radar sighting | 5 |
  | Low ground | 1.0 m or less above a drainage line | 4 |
  | Legal risk of an old lake bed (in Nepal, also a river bank) | buying, old bed at or near the spot | 4 |
  | Water lost within 300 m | 0.3 ha or more | 3 |
  | A hollow | 1 m or more deep | 2 (3 from 3 m) |
  | Old beds built over within 2 km | 1 ha or more | 2 (3 from 10 ha) |
  | People's reports within 1 km | one or more | 2 (3 from three) |
  | Water gets into ground-floor homes first | ground floor or house, place scores 3 or more | 3 |
  | Basement parking | a basement car, place scores 3 or more | 3 |
  | Hard to move at night | elderly people or small children, place scores 3 or more | 2 |
  | Summer heat | ground of 42 °C or more, or 2 °C or more hotter than built-up ground nearby | 1 |

  | In its favour | When | Weight |
  |---|---|---|
  | Never water | under 1% of looks on the spot, under 0.3 ha lost within 300 m, and little water memory | 4 |
  | High ground | 3 m or more above a drainage line | 3 |
  | Upstairs | first floor or above | 3 where the place scores 3 or more, else 1 |
  | No hollow | deepest hollow under 0.5 m | 2 |
  | Renting keeps you free to move | renting, place scores 3 or more | 2 |
  | Cooler | 1.5 °C or more cooler than built-up ground nearby | 1 |
  | Few signs | only one of seven warning signs (spot, radar, low ground, hollow, water lost, beds built over, reports), and not strong water memory | 1 |

- **If you still like it** (not for "Good to go"), in this order: take the first floor or above (ground floor or house,
  place scores 3 or more); avoid basement parking, or move the car before heavy rain (a basement car, place scores 3 or
  more); ask about the radar dates, else ask the owner and two neighbours about the flood the area remembers
  (4 December 2023 in Chennai, 13 October 2020 in Hyderabad, otherwise the area's latest mapped flood) or, outside the
  nine areas, the last three monsoons; when buying on an old bed, check the survey number against the lake's full tank
  level and buffer in the revenue records (in Nepal, ownership and the distance from rivers and ponds with the
  municipality); check that the entrance and plinth are at least three steps above the road (ground floor or house,
  strong or some memory); visit once after heavy rain; plan how to move elderly people or children (when they live
  there and the place scores 3 or more); take flood insurance and keep documents and electronics off the floor (place
  scores 3 or more).
  At most five, then always "Follow this place to get a heads-up before heavy rain."
- **Where it shows:** on the place page (`web/src/components/place/VerdictCard.tsx`) for someone renting or buying,
  read again as the answers change (the answers stay on the device); through `GET /v1/places/verdict`, which answers
  409 before the place is checked; and in the signed place report when the answers are sent. Every line is a dictionary
  key with variables, worded in the reader's language. A note under it says it is a reading of open satellite records
  and the family's answers, not a survey, a legal opinion or financial advice.

## Place report (`placereport.py`, `report_pdf.py`, `handlers/jobs.py`)

- **Request:** from a stored place check, for a reader (renting or buying, or living here) and a language (English,
  Hindi, Kannada, Tamil, Telugu, Malayalam or Nepali); for renting or buying, optionally with the four answers of our
  read. The report id is `rpt` plus 16 hex characters of a SHA-256 of the place cell, cache version, check time,
  language and reader (and the answers, when sent), so the same request returns the same signed PDF.
- **Content:** the water-memory gauge and tier, our read when the answers were sent (the level and headline on a panel
  edged in the level's colour, then why, in its favour, against it and the note), findings, up to 6 time-lapse frames
  spread over the seasons, radar sightings (the 6 most recent), summer heat with its map and scale, standing water
  reported within 1 km in the last year (up to 6 reports), this week's steps as a checklist, four questions for the
  owner or seller (renting or buying only), four limits, the data sources and a verification block (content
  fingerprint, signing key fingerprint, the verify address and a QR code).
- **Layout:** A4, normally two pages. Three densities are tried and the most comfortable one that does not end on a
  nearly empty page is kept. Indian scripts are set in Noto fonts and shaped with HarfBuzz. In our run the English
  report for Bellandur was two pages, about 120 KB, and rendered in under a second on a laptop.
- **What is signed:** a canonical JSON payload (the place, the check's time and id, science version, memory index and
  tier, finding keys and values, radar sightings, heat numbers, frame seasons, the step keys, language, reader, the
  number of nearby standing-water reports and, with answers, the answers and our read's level, points and the keys of
  its why, in-favour and against lines). Its SHA-256 and the PDF's SHA-256 go into an attestation
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

## Recent news (`news.py`)

- **Sources, in order:** Google News search (its public RSS feed, `hl=en-IN`, `gl=IN`), over the past 365 days
  (`when:365d`); then, only when Google News does not answer, the GDELT Project's DOC 2.0 API (free, no key), which
  searches the last 3 months (its longest window), 50 asked for per query. GDELT answers in 10 seconds or more and
  often refuses shared cloud addresses, which is why it is the fallback.
- **Lake** (`GET /v1/lakes/<id>/news`): the lake's name as a phrase with its city's names, for example
  `"Bellandur Lake" (Bengaluru OR Bangalore)`. Only lakes with a name of their own (OpenStreetMap or GeoNames) of at
  least 4 characters are searched; a water body named after what is near it gets the answer "none".
- **Locality** (`GET /v1/news/floods?locality=`): a name of at least 4 characters, cut to 60, searched as a phrase
  with flood, flooded, flooding, floods, waterlogging, waterlogged, inundated or submerged; only headlines that name
  the locality are kept.
- **Headlines:** only http and https links, within the past 365 days. The outlet's name is taken off the end of a
  Google News headline. The same headline (compared in lower case without spaces or punctuation, first 80 characters)
  is kept once, newest first, at most 12, each with the headline, link, outlet, date and which source found it. The
  articles stay on their publishers' sites. A headline is tagged when it contains one of these word parts, in any case;
  **a headline with no tag is left out**, so a crime story that happens to name the lake is not shown:

  | Tag | Word parts |
  |---|---|
  | Flooding | flood, inundat, waterlog, submerg, deluge, cloudburst, downpour, heavy rain, rain fury, overflow, breach |
  | Encroachment | encroach, land grab, illegal(ly) or unauthorised construction, building, structure, layout (and illegally occupied or filled), demoli, bulldoz, razed, evict, squatter, buffer zone, notice(s) to a developer or builder, built on a lake or tank |
  | Pollution | sewage, sewer, foam, froth, dead fish, fish kill, fish death, pollut, hyacinth, weed, toxic, effluent, garbage, dumping, debris, fire and blaze (whole words), stink, contaminat, algae, algal |
  | Restoration | rejuvenat, restor, desilt, revival, revive, clean-up (cleanup, clean up), cleaning, conserv, wetland, makeover, inflow, treatment plant, STP, plantation, bund repair, strengthening or work, beautif |

  The encroachment words are narrow on purpose: they say that land or water is being taken. Building near a lake is
  not tagged as encroachment (a headline about a company completing a flyover near Bellandur Lake gets no tag and is
  left out), because the tag must not suggest that anyone named in a headline took the lake's land.

- **GDELT's turn:** GDELT asks for at most one request every 5 seconds. A conditional write on one DynamoDB item (PK
  `NEWS`, SK `THROTTLE`; it succeeds when there was no call yet or the last one was more than 5.5 s ago) gives one
  Lambda the turn; a request tries once a second for up to 3 s. Each call to either source times out after 8 s.
- **Cache:** each answer is kept in an item with PK `NEWS` and SK `<kind>#<query>` (kind `lake` or `floods`, the
  query in lower case), served for 12 hours and removed by TTL after 14 days. When both sources fail, the last answer
  is served marked "stale", or "unavailable" when there is none.
- **On the page:** "In the news" on a lake page shows up to 8 headlines with their tags and the number of headlines per
  tag.

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
300 forecasts, 120 news requests, 20 place reports and 30 new narrations per address; 30 photos, 10 dossiers,
30 watches, 20 follows, 3 test emails, 10 RTI records and 10 standing-water reports per account. For the whole site,
set by environment variables on the API function: `PLACE_CHECKS_PER_DAY` (200), `LAKE_ANALYSES_PER_DAY` (40),
`SEARCHES_PER_DAY` (5000), `REPORTS_PER_DAY` (500), `NARRATIONS_PER_DAY` (200, counted only for audio not already
cached), `WATER_REPORTS_PER_DAY` (1000) and `FORECASTS_PER_DAY` (5000).
