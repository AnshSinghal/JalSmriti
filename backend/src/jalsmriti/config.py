"""Every setting and every science threshold JalSmriti depends on, in one place.

Thresholds come from the validation work in docs/validation.md. Change them there first, then here.
Deployment-specific names (tables, buckets, keys) are injected as environment variables by the
CloudFormation template; the defaults below are only used by tests and the local stack.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------------- deployment
REGION = os.environ.get("AWS_REGION", "us-west-2")
PROJECT = os.environ.get("PROJECT", "jalsmriti")
TABLE_NAME = os.environ.get("TABLE_NAME", "jalsmriti")
DATA_BUCKET = os.environ.get("DATA_BUCKET", "")          # private: originals, rasters, scratch
SITE_BUCKET = os.environ.get("SITE_BUCKET", "")          # served by CloudFront: web app + pub/ data
PUBLIC_PREFIX = "pub/"                                    # everything under SITE_BUCKET/pub/ is public
SITE_URL_PARAM = os.environ.get("SITE_URL_PARAM", f"/{PROJECT}/site-url")
SITE_URL = os.environ.get("SITE_URL", "")                # set in tests/local; Lambdas read SITE_URL_PARAM
KMS_KEY_ID = os.environ.get("KMS_KEY_ID", "")            # asymmetric ECC_NIST_P256 signing key (alias or ARN)
JOBS_QUEUE_URL = os.environ.get("JOBS_QUEUE_URL", "")    # dossier rendering and other async jobs
PLACE_SFN_ARN = os.environ.get("PLACE_SFN_ARN", "")
LAKE_SFN_ARN = os.environ.get("LAKE_SFN_ARN", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
ORIGIN_SECRET = os.environ.get("ORIGIN_SECRET", "")      # CloudFront adds it to API requests (X-JalSmriti-Origin)
LOCAL = os.environ.get("JALSMRITI_LOCAL", "") == "1"     # local stack: no Bedrock / Translate / KMS


def lake_topic_name(lake_id: str) -> str:
    """One SNS topic per watched lake (SNS allows only 200 filter policies per topic, so no shared topic)."""
    return f"{PROJECT}-lake-{lake_id}"


def user_topic_name(user_id: str) -> str:
    """One SNS topic per person who follows places: their verified email is subscribed once, and every rain
    heads-up for any of their places is published there (the id is hashed so the name says nothing about them)."""
    import hashlib
    return f"{PROJECT}-user-{hashlib.sha256(f'jalsmriti:{user_id}'.encode()).hexdigest()[:20]}"

# Amazon Bedrock models, tried in order (the first that answers is used). Amazon Nova is enabled by default.
TEXT_MODEL_IDS = [m.strip() for m in os.environ.get(
    "TEXT_MODEL_IDS", "us.amazon.nova-lite-v1:0,amazon.nova-lite-v1:0,us.amazon.nova-pro-v1:0").split(",") if m.strip()]
VISION_MODEL_IDS = [m.strip() for m in os.environ.get(
    "VISION_MODEL_IDS", "us.amazon.nova-lite-v1:0,amazon.nova-lite-v1:0").split(",") if m.strip()]

USER_AGENT = f"{PROJECT}/1.0 (+https://github.com/; environmental public-interest tool)"

# ---------------------------------------------------------------------------------- data sources
EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"            # Sentinel-2 L2A and Copernicus DEM on AWS
PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/stac/v1"
PC_SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token"  # anonymous read tokens (per account/container)
S2_COLLECTION = "sentinel-2-l2a"
DEM_COLLECTION = "cop-dem-glo-30"
PHOTON = "https://photon.komoot.io"                                   # OpenStreetMap names (lakes, localities)

# ---------------------------------------------------------------------------------- grids
AREA_RES_M = 30.0            # area analysis grid (Landsat / JRC native)
FRAME_RES_LANDSAT_M = 30.0   # time-machine frames
FRAME_RES_S2_M = 10.0
PLACE_RADIUS_M = 300.0       # "this place" for the place check
PLACE_CONTEXT_M = 2000.0     # neighbourhood used for terrain and water context
PLACE_CHIP_HALF_M = 1200.0   # half-width of place time-lapse crops

# ---------------------------------------------------------------------------------- lakes
JRC_OCCURRENCE_MIN = 5.0     # % of 1984-2020 observations; below this a pixel is not "historic water"
LAKE_MIN_HA = 2.0
RIVER_MAX_COMPACTNESS = 0.06 # 4*pi*A/P^2 below this, and long, means a river stretch rather than a lake
RIVER_MIN_LENGTH_M = 3000.0
OPEN_RADIUS_PX = 1           # morphological opening (3x3) before splitting water bodies

# ---------------------------------------------------------------------------------- water detection
# Sentinel-2 L2A: MNDWI and SWIR1 rule, plus the scene classifier's water class with a looser check
S2_MNDWI_MIN = 0.0
S2_SWIR1_MAX = 0.10
S2_SCL_WATER_NDWI_MIN = -0.20
S2_SCL_WATER_SWIR1_MAX = 0.12
S2_CLEAR_CLASSES = (4, 5, 6)          # vegetation, bare soil, water
S2_CLOUD_CLASSES = (3, 8, 9, 10)      # cloud shadow, cloud medium/high, cirrus
# Landsat 4-9 Collection 2 surface reflectance: same spectral rule, QA_PIXEL cloud bits
LS_MNDWI_MIN = 0.0
LS_SWIR1_MAX = 0.10
LOOK_MIN_VALID_FRAC = 0.90            # a look counts for a lake only if >= 90 % of it has data ...
LOOK_MIN_CLEAR_FRAC = 0.90            # ... and >= 90 % of it is cloud-free ...
LOOK_CLOUD_BUFFER_M = 150.0           # ... and no cloud or shadow within this distance
FLOATING_VEG_NDVI = 0.35              # inside the usual water spread, vegetation this green is weed cover

# ---------------------------------------------------------------------------------- seasons and epochs
FIRST_SEASON = 1987
CURRENT_SEASON = int(os.environ.get("CURRENT_SEASON", "2026"))   # monsoon season being watched now
SCENES_PER_SEASON = 2         # clearest looks kept per season per sensor
MAX_SCENE_CLOUD = 30.0        # % scene cloud cover considered at all
S2_FIRST_SEASON = 2016        # Sentinel-2 L2A over India from late 2016; Landsat before that
FRAME_SEASONS = (1990, 1995, 2000, 2005, 2010, 2015, 2019, 2022, 2025)   # time-machine frames (nearest available)

# ---------------------------------------------------------------------------------- land cover
IO_LULC_YEARS = tuple(range(2017, 2024))     # Impact Observatory 10 m annual land cover (Planetary Computer)
IO_BUILT, IO_WATER, IO_TREES, IO_FLOODED_VEG, IO_CROPS, IO_BARE, IO_RANGE = 7, 1, 2, 4, 5, 8, 11
JRC_LOST = (3, 6)            # transitions: lost permanent, lost seasonal
JRC_PERMANENT = (1, 7, 8)
JRC_SEASONAL = (4, 9, 10)
JRC_NEW = (2, 5)

# ---------------------------------------------------------------------------------- radar (Sentinel-1 RTC)
S1_WATER_DB = -18.0          # VV backscatter below this (after a 5x5 mean) is open water
S1_DROP_DB = 3.0             # and at least this much darker than the usual for that season and orbit
S1_FIRST_YEAR = 2017
S1_MIN_SIGHTING_PX = 6       # 6 px of 20 m = 0.24 ha of unusual water near the place counts as a sighting
S1_BASELINE_DAYS = 20        # same orbit, other years, within +-20 days of the same date

# ---------------------------------------------------------------------------------- lake health grade
# Each part scores 0-25; grade from the total (100 = healthy). See metrics.lake_grade.
GRADE_BANDS = ((80, "A"), (65, "B"), (50, "C"), (35, "D"), (0, "E"))

# ---------------------------------------------------------------------------------- evidence and dossiers
EVIDENCE_MAX_BYTES = 12 * 1024 * 1024
EVIDENCE_TYPES = ("image/jpeg", "image/png", "image/webp")
EVIDENCE_GEOFENCE_M = 400.0  # photo GPS must be within this distance of the lake's historic outline
EVIDENCE_CATEGORIES = ("dumping", "sewage", "construction", "fencing", "weeds", "dead_fish", "foam", "dry_bed",
                       "healthy", "other")
DOSSIER_LANGUAGES = ("hi", "kn", "ta", "te", "ml", "mr", "bn", "gu", "pa", "ur", "ne", "as", "or")
TRANSLATE_SUPPORTED = ("hi", "kn", "ta", "te", "ml", "mr", "bn", "gu", "pa", "ur")   # Amazon Translate
BEDROCK_TRANSLATED = ("ne", "as", "or")      # not in Amazon Translate: Nova translates, numbers checked, labelled
# per person (signed in) or per client address (anonymous), per day ...
RATE_LIMIT_PER_DAY = {"evidence": 30, "dossier": 10, "place": 25, "lake": 10, "watch": 30, "geocode": 600,
                      "follow": 20, "heads-up-test": 3, "report": 20, "speech": 30, "rti": 10, "waterlog": 10,
                      "forecast": 300,
                      # ... and for the whole site per day: these bound the satellite work anyone can start
                      "place-all": int(os.environ.get("PLACE_CHECKS_PER_DAY", "200")),
                      "lake-all": int(os.environ.get("LAKE_ANALYSES_PER_DAY", "40")),
                      "geocode-all": int(os.environ.get("SEARCHES_PER_DAY", "5000")),
                      "report-all": int(os.environ.get("REPORTS_PER_DAY", "500")),
                      "speech-all": int(os.environ.get("NARRATIONS_PER_DAY", "200")),
                      "waterlog-all": int(os.environ.get("WATER_REPORTS_PER_DAY", "1000")),
                      "forecast-all": int(os.environ.get("FORECASTS_PER_DAY", "5000"))}
MAX_FOLLOWS = 10              # places one person can follow for rain heads-ups

# ---------------------------------------------------------------------------------- versions
SCIENCE_VERSION = "2026.10-a"
PLACE_CACHE_VERSION = "2026.10-b"   # place checks now carry summer heat; older cached checks are read again
